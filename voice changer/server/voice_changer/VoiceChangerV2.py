from typing import Any, Union

import time
from torch.functional import F
import torch
import numpy as np
import logging
from const import VoiceChangerType
from data.ModelSlot import ModelSlots

from voice_changer.IORecorder import IORecorder
from voice_changer.VoiceChangerSettings import VoiceChangerSettings
from voice_changer.utils.Timer import Timer2
from voice_changer.utils.VoiceChangerModel import AudioInOutFloat, VoiceChangerModel
from Exceptions import (
    VoiceChangerIsNotSelectedException,
)
from voice_changer.common.deviceManager.DeviceManager import DeviceManager
from voice_changer.common.OutputFX import OutputFX

logger = logging.getLogger(__name__)

# --- Auto Smooth (experimental) tuning constants ---
# How much of the real-time budget the processing may use before we add buffer.
AUTO_SMOOTH_HIGH = 0.85
# Below this, there is spare headroom, so we can trim buffer back toward the
# user's configured value (lower latency).
AUTO_SMOOTH_LOW = 0.45
# Don't adjust more often than this (seconds) -- avoids thrashing/reallocs.
AUTO_SMOOTH_INTERVAL = 2.0
# Step and bounds for extraConvertSize (seconds).
AUTO_SMOOTH_STEP = 0.05
AUTO_SMOOTH_MIN_EXTRA = 0.10
AUTO_SMOOTH_MAX_EXTRA = 1.50


class VoiceChangerV2:
    def __init__(self, settings: VoiceChangerSettings):
        # 初期化
        self.settings = settings

        self.block_frame = self.settings.serverReadChunkSize * 128
        self.crossfade_frame = int(self.settings.crossFadeOverlapSize * self.settings.inputSampleRate)
        self.extra_frame = int(self.settings.extraConvertSize * self.settings.inputSampleRate)
        self.sola_search_frame = self.settings.inputSampleRate // 100

        self.vcmodel: VoiceChangerModel | None = None
        self.output_fx = OutputFX()
        self.device_manager = DeviceManager.get_instance()
        self.sola_buffer: torch.Tensor | None = None
        self.io_recorder = IORecorder(
            self.settings.inputSampleRate,
            self.settings.outputSampleRate,
        )
        self._generate_strength()

        # --- Auto Smooth (experimental) state ---
        self._as_ema = None            # smoothed processing/budget ratio (1.0 = exactly real-time)
        self._as_baseline = None       # user's configured extraConvertSize, restored when idle/off
        self._as_last_adjust = 0.0
        self._as_prev_enabled = False

    def initialize(self, vcmodel: VoiceChangerModel):
        self.vcmodel = vcmodel
        self.vcmodel.realloc(self.block_frame, self.extra_frame, self.crossfade_frame, self.sola_search_frame)
        self.vcmodel.initialize()

    def set_slot_info(self, slot_info: ModelSlots):
        self.vcmodel.set_slot_info(slot_info)
        self.vcmodel.initialize()

    def get_type(self) -> VoiceChangerType:
        if self.vcmodel is None:
            return "None"
        return self.vcmodel.voiceChangerType

    def set_input_sample_rate(self):
        self.io_recorder.open(self.settings.inputSampleRate, self.settings.outputSampleRate)

        self.extra_frame = int(self.settings.extraConvertSize * self.settings.inputSampleRate)
        self.crossfade_frame = int(self.settings.crossFadeOverlapSize * self.settings.inputSampleRate)
        self.sola_search_frame = self.settings.inputSampleRate // 100
        self._generate_strength()

        self.vcmodel.set_sampling_rate(self.settings.inputSampleRate, self.settings.outputSampleRate)
        self.vcmodel.realloc(self.block_frame, self.extra_frame, self.crossfade_frame, self.sola_search_frame)

    def set_output_sample_rate(self):
        self.io_recorder.open(self.settings.inputSampleRate, self.settings.outputSampleRate)

        self.vcmodel.set_sampling_rate(self.settings.inputSampleRate, self.settings.outputSampleRate)

    def get_info(self):
        if self.vcmodel is not None:
            return self.vcmodel.get_info()
        return {}

    def update_settings(self, key: str, val: Any, old_val: Any):
        if key == "serverReadChunkSize":
            self.block_frame = self.settings.serverReadChunkSize * 128
        elif key == 'gpu':
            # When changing GPU, need to re-allocate fade-in/fade-out buffers on different device
            self._generate_strength()
        elif key == "inputSampleRate":
            self.set_input_sample_rate()
        elif key == "outputSampleRate":
            self.set_output_sample_rate()
        elif key == 'extraConvertSize':
            self.extra_frame = int(val * self.settings.inputSampleRate)
        elif key == 'crossFadeOverlapSize':
            self.crossfade_frame = int(val * self.settings.inputSampleRate)
            self._generate_strength()
        elif key == 'autoSmooth':
            if val:
                # (Re)arm; baseline is captured on the first processed chunk.
                self._as_prev_enabled = False
            else:
                # Restore the user's configured buffer and reset the controller.
                if self._as_baseline is not None:
                    self._apply_extra(self._as_baseline)
                self._as_prev_enabled = False
                self._as_ema = None

        if self.vcmodel is not None:
            self.vcmodel.update_settings(key, val, old_val)
            if key in {'gpu', 'serverReadChunkSize', 'extraConvertSize', 'crossFadeOverlapSize', 'silenceFront', 'forceFp32'}:
                self.vcmodel.realloc(self.block_frame, self.extra_frame, self.crossfade_frame, self.sola_search_frame)


    def _generate_strength(self):
        self.fade_in_window: torch.Tensor = (
            torch.sin(
                0.5
                * np.pi
                * torch.linspace(
                    0.0,
                    1.0,
                    steps=self.crossfade_frame,
                    device=self.device_manager.device,
                    dtype=torch.float32,
                )
            )
            ** 2
        )
        self.fade_out_window: torch.Tensor = 1 - self.fade_in_window

        # ひとつ前の結果とサイズが変わるため、記録は消去する。
        self.sola_buffer = torch.zeros(self.crossfade_frame, device=self.device_manager.device, dtype=torch.float32)
        logger.info(f'Allocated SOLA buffer size: {self.crossfade_frame}')

    def get_processing_sampling_rate(self) -> int:
        if self.vcmodel is None:
            return 0
        return self.vcmodel.get_processing_sampling_rate()

    def process_audio(self, audio_in: AudioInOutFloat) -> tuple[AudioInOutFloat, float]:
        block_size = audio_in.shape[0]

        audio, vol = self.vcmodel.inference(audio_in)

        if audio is None:
            # In case there's an actual silence - send full block with zeros
            return np.zeros(block_size, dtype=np.float32), vol

        # SOLA algorithm from https://github.com/yxlllc/DDSP-SVC, https://github.com/liujing04/Retrieval-based-Voice-Conversion-WebUI
        conv_input = audio[
            None, None, : self.crossfade_frame + self.sola_search_frame
        ]
        cor_nom = F.conv1d(conv_input, self.sola_buffer[None, None, :])
        cor_den = torch.sqrt(
            F.conv1d(
                conv_input ** 2,
                torch.ones(1, 1, self.crossfade_frame, device=self.device_manager.device),
            )
            + 1e-8
        )
        sola_offset = torch.argmax(cor_nom[0, 0] / cor_den[0, 0])

        audio = audio[sola_offset:]
        audio[: self.crossfade_frame] *= self.fade_in_window
        audio[: self.crossfade_frame] += (
            self.sola_buffer * self.fade_out_window
        )

        self.sola_buffer[:] = audio[block_size : block_size + self.crossfade_frame]

        out = audio[: block_size].detach().cpu().numpy()

        # Optional output DSP (de-esser + equalizer + compressor). Isolated:
        # passes through unchanged on any error. All off by default.
        out = self.output_fx.process(out, self.settings.outputSampleRate, self.settings.deEss, self.settings.outputComp, self.settings.eqProfile)

        return out, vol

    @torch.no_grad()
    def on_request(self, audio_in: AudioInOutFloat) -> tuple[AudioInOutFloat, list[Union[int, float]]]:
        if self.vcmodel is None:
            raise VoiceChangerIsNotSelectedException("Voice Changer is not selected.")

        with Timer2("main-process", True) as t:
            result, vol = self.process_audio(audio_in)

        mainprocess_time = t.secs

        # Auto Smooth: adapt the conversion buffer to keep up with PC2's load.
        if self.settings.autoSmooth:
            self._auto_smooth_update(audio_in.shape[0], mainprocess_time)

        # 後処理
        if self.settings.recordIO:
            self.io_recorder.write_input((audio_in * 32767).astype(np.int16).tobytes())
            self.io_recorder.write_output((result * 32767).astype(np.int16).tobytes())

        return result, vol, [0, mainprocess_time, 0]

    # --- Auto Smooth (experimental) -------------------------------------
    def _apply_extra(self, val: float):
        """Set extraConvertSize and re-allocate the model buffers (same path a
        manual slider change takes, so it's no riskier than that)."""
        self.settings.extraConvertSize = val
        self.extra_frame = int(val * self.settings.inputSampleRate)
        if self.vcmodel is not None:
            self.vcmodel.realloc(self.block_frame, self.extra_frame, self.crossfade_frame, self.sola_search_frame)

    def _auto_smooth_update(self, n_samples: int, proc_secs: float):
        # Reset the controller when freshly enabled, remembering the user's value.
        if not self._as_prev_enabled:
            self._as_prev_enabled = True
            self._as_baseline = self.settings.extraConvertSize
            self._as_ema = None
            self._as_last_adjust = time.time()

        sr = self.settings.inputSampleRate
        chunk_secs = (n_samples / sr) if sr else 0.0
        if chunk_secs <= 0:
            return

        # ratio > 1.0 means we processed slower than real time (will stutter).
        ratio = proc_secs / chunk_secs
        self._as_ema = ratio if self._as_ema is None else (self._as_ema * 0.8 + ratio * 0.2)

        now = time.time()
        if now - self._as_last_adjust < AUTO_SMOOTH_INTERVAL:
            return

        cur = self.settings.extraConvertSize
        if self._as_ema > AUTO_SMOOTH_HIGH:
            target = min(AUTO_SMOOTH_MAX_EXTRA, round(cur + AUTO_SMOOTH_STEP, 3))
        elif self._as_ema < AUTO_SMOOTH_LOW:
            # Trim back toward (but never below) the user's configured value.
            floor = max(AUTO_SMOOTH_MIN_EXTRA, self._as_baseline if self._as_baseline is not None else AUTO_SMOOTH_MIN_EXTRA)
            target = max(floor, round(cur - AUTO_SMOOTH_STEP, 3))
        else:
            target = cur

        if target != cur:
            self._apply_extra(target)
        self._as_last_adjust = now

    def get_auto_smooth_status(self) -> dict:
        return {
            "enabled": bool(self.settings.autoSmooth),
            "load": round(self._as_ema, 2) if self._as_ema is not None else 0.0,
            "extra": round(self.settings.extraConvertSize, 3),
            "baseline": self._as_baseline,
        }

    @torch.no_grad()
    def export2onnx(self):
        return self.vcmodel.export2onnx()

    def get_current_model_settings(self) -> dict:
        return self.vcmodel.get_model_current()
