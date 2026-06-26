"""
VoiceChangerV2向け
"""
import math
import json
import time
import torch
from data.ModelSlot import RVCModelSlot, saveSlotInfo
from const import EnumInferenceTypes
import logging
import os
from voice_changer.embedder.EmbedderManager import EmbedderManager
from voice_changer.utils.VoiceChangerModel import (
    AudioInOutFloat,
    VoiceChangerModel,
)
from voice_changer.RVC.consts import HUBERT_SAMPLE_RATE, WINDOW_SIZE
from voice_changer.RVC.onnx_exporter.export2onnx import export2onnx
from voice_changer.pitch_extractor.PitchExtractorManager import PitchExtractorManager
from voice_changer.RVC.pipeline.PipelineGenerator import createPipeline
from voice_changer.common.TorchUtils import circular_write
from voice_changer.common.deviceManager.DeviceManager import DeviceManager
from voice_changer.RVC.pipeline.Pipeline import Pipeline
from torchaudio import transforms as tat
from voice_changer.VoiceChangerSettings import VoiceChangerSettings
from settings import get_settings
from Exceptions import (
    PipelineNotInitializedException,
)

logger = logging.getLogger(__name__)

# --- Auto Pitch (experimental) tuning constants ---
# Max automatic transpose correction, in semitones, in either direction.
# Kept modest: large transposes sound squeaky/robotic.
AUTO_PITCH_MAX_SEMITONES = 5.0
# Dead zone (semitones): ignore small drifts so natural intonation is not
# fought and the output does not wobble.
AUTO_PITCH_DEADZONE = 1.0
# EMA factor for tracking the speaker's input register (lower = slower/steadier).
AUTO_PITCH_INPUT_SMOOTH = 0.15
# Number of voiced frames used to establish the "home" register after enabling.
AUTO_PITCH_WARMUP_FRAMES = 20
# Minimum number of voiced pitch samples in a frame for it to be trusted.
AUTO_PITCH_MIN_VOICED = 6
# --- Robustness: reject sounds that aren't the speaker's voice ---
# (chair squeaks, keyboard clacks, taps, etc.)
# Plausible human speaking fundamental range, in Hz. Pitch readings outside
# this are almost certainly not the speaker, so they are ignored.
AUTO_PITCH_MIN_HZ = 70.0
AUTO_PITCH_MAX_HZ = 380.0
# Require at least this fraction of the frame to be voiced. Sustained speech is
# mostly voiced; brief transient noises are not.
AUTO_PITCH_MIN_VOICED_FRAC = 0.30
# Ignore a frame whose measured pitch leaps more than this (semitones) from the
# tracked register -- a sudden large jump is a transient noise, not the voice.
AUTO_PITCH_OUTLIER_SEMITONES = 4.0
# How strongly an "outlier" frame is still allowed to nudge the tracked
# register. Tiny, so a brief squeak barely moves it, but a *sustained* shift in
# the real voice still adapts over a few seconds (prevents the tracker getting
# stuck when anchored far from the current register).
AUTO_PITCH_OUTLIER_LEAK = 0.03

# --- Voice calibration ---
# How long (seconds) to listen while the user talks normally. A longer window
# captures more of the speaker's natural range for a more accurate profile.
CALIBRATION_DURATION = 45.0
# Minimum voiced pitch samples needed to trust the calibration.
CALIBRATION_MIN_SAMPLES = 20


class RVCr2(VoiceChangerModel):
    def __init__(self, slotInfo: RVCModelSlot, settings: VoiceChangerSettings):
        self.voiceChangerType = "RVC"

        self.device_manager = DeviceManager.get_instance()
        EmbedderManager.initialize()
        PitchExtractorManager.initialize()
        self.settings = settings
        self.params = get_settings()

        self.pipeline: Pipeline | None = None

        self.convert_buffer: torch.Tensor | None = None
        self.pitch_buffer: torch.Tensor | None = None
        self.pitchf_buffer: torch.Tensor | None = None
        self.return_length = 0
        self.skip_head = 0
        self.silence_front = 0
        self.slotInfo = slotInfo

        self.resampler_in: tat.Resample | None = None
        self.resampler_out: tat.Resample | None = None

        self.input_sample_rate = self.settings.inputSampleRate
        self.output_sample_rate = self.settings.outputSampleRate

        # Convert dB to RMS
        self.inputSensitivity = 10 ** (self.settings.silentThreshold / 20)

        # --- Silence-gate release ("Word tail") state ---
        # Keep converting for a short tail after volume drops, so the quiet end
        # of words (e.g. "...yeah") is not chopped off by the silence gate.
        self._block_frame = 0
        self._release_chunks = 0
        self._silence_count = 0

        self.is_half = self.device_manager.use_fp16()
        self.dtype = torch.float16 if self.is_half else torch.float32

        # --- Auto Pitch (experimental) state ---
        self._ap_prev_enabled = False
        self._ap_baseline: float | None = None   # "home" input register, semitones
        self._ap_smooth_in: float | None = None  # smoothed input register, semitones
        self._ap_offset: float = 0.0             # currently applied correction, semitones
        self._ap_warmup = 0
        self._ap_last_effective_tran: float = 0.0  # last transpose actually used

        # --- Voice calibration state ---
        # A saved profile is just a few numbers describing the speaker's pitch:
        # { homeHz, lowHz, highHz, homeSemi }. No audio is stored.
        self._voice_profile: dict | None = None
        self._cal_active = False
        self._cal_t_end = 0.0
        self._cal_samples: list[float] = []
        self._cal_ready = False
        self._cal_error: str | None = None
        self._load_voice_profile()

    # --- Voice profile / calibration -----------------------------------
    def _load_voice_profile(self):
        raw = getattr(self.settings, "voiceProfile", "") or ""
        if not raw:
            self._voice_profile = None
            return
        try:
            p = json.loads(raw)
            self._voice_profile = p if (isinstance(p, dict) and "homeSemi" in p) else None
        except Exception:
            self._voice_profile = None

    def _plausible_range_hz(self) -> tuple[float, float]:
        """Pitch range to accept as 'the voice'. Personalised when a profile
        exists (with a margin so going a bit high/low still counts), otherwise
        a generic human speaking range."""
        p = self._voice_profile
        if p:
            lo = max(50.0, float(p.get("lowHz", AUTO_PITCH_MIN_HZ)) * 0.75)
            hi = min(500.0, float(p.get("highHz", AUTO_PITCH_MAX_HZ)) * 1.33)
            return lo, hi
        return AUTO_PITCH_MIN_HZ, AUTO_PITCH_MAX_HZ

    def _measure_input_pitch(self, eff_tran: float, use_profile: bool = True) -> float | None:
        """Robustly measure the speaker's input pitch (Hz) for this frame, or
        None if the frame isn't trustworthy voice."""
        pitchf = self.pitchf_buffer.float()
        voiced = pitchf[pitchf > 0]
        total = pitchf.numel()
        if voiced.numel() < AUTO_PITCH_MIN_VOICED or (total > 0 and voiced.numel() / total < AUTO_PITCH_MIN_VOICED_FRAC):
            return None
        # pitchf holds the transposed f0 that was used this frame; undo the
        # transpose to recover the speaker's actual input pitch.
        factor = 2 ** ((eff_tran - self.settings.formantShift) / 12)
        raw_median = (voiced / factor).median().item()
        if raw_median <= 0:
            return None
        lo, hi = self._plausible_range_hz() if use_profile else (AUTO_PITCH_MIN_HZ, AUTO_PITCH_MAX_HZ)
        if raw_median < lo or raw_median > hi:
            return None
        return raw_median

    def start_calibration(self, duration: float = CALIBRATION_DURATION):
        self._cal_samples = []
        self._cal_active = True
        self._cal_ready = False
        self._cal_error = None
        self._cal_t_end = time.time() + duration

    def _calibration_step(self, eff_tran: float):
        # Use the generic range during calibration so we capture the speaker's
        # true range rather than filtering against a stale profile.
        hz = self._measure_input_pitch(eff_tran, use_profile=False)
        if hz is not None:
            self._cal_samples.append(hz)
        if time.time() >= self._cal_t_end:
            self._finalize_calibration()

    def _finalize_calibration(self):
        self._cal_active = False
        samples = sorted(self._cal_samples)
        n = len(samples)
        if n < CALIBRATION_MIN_SAMPLES:
            self._cal_ready = False
            self._cal_error = "not_enough_voice"
            return

        def pct(p):
            return samples[min(n - 1, max(0, int(p * (n - 1))))]

        home_hz = pct(0.50)
        low_hz = pct(0.10)
        high_hz = pct(0.90)
        home_semi = 12.0 * math.log2(home_hz)
        self._voice_profile = {
            "homeHz": round(home_hz, 1),
            "lowHz": round(low_hz, 1),
            "highHz": round(high_hz, 1),
            "homeSemi": round(home_semi, 3),
        }
        # Persist via settings (written to disk by the manager).
        try:
            self.settings.voiceProfile = json.dumps(self._voice_profile)
        except Exception as e:
            logger.exception(e)
        self._cal_ready = True
        self._cal_error = None
        # Apply immediately so auto-pitch anchors to the new profile.
        self._ap_baseline = home_semi
        self._ap_smooth_in = home_semi
        self._ap_offset = 0.0
        self._ap_warmup = 0

    def get_calibration_status(self) -> dict:
        # Finalise on poll too, so it still completes if audio frames stop.
        if self._cal_active and time.time() >= self._cal_t_end:
            self._finalize_calibration()
        remaining = max(0.0, self._cal_t_end - time.time()) if self._cal_active else 0.0
        return {
            "active": self._cal_active,
            "remaining": round(remaining, 1),
            "count": len(self._cal_samples),
            "ready": self._cal_ready,
            "error": self._cal_error,
            "profile": self._voice_profile,
            "hasProfile": self._voice_profile is not None,
        }

    def _auto_pitch_reset(self):
        self._ap_offset = 0.0
        self._ap_warmup = 0
        # If the user has calibrated, anchor straight to their saved home pitch
        # (no warm-up needed); otherwise learn it live as before.
        if self._voice_profile and "homeSemi" in self._voice_profile:
            self._ap_baseline = float(self._voice_profile["homeSemi"])
            self._ap_smooth_in = float(self._voice_profile["homeSemi"])
        else:
            self._ap_baseline = None
            self._ap_smooth_in = None

    def get_auto_pitch_status(self) -> dict:
        return {
            "enabled": self._auto_pitch_enabled(),
            "baseTran": self.settings.tran,
            "offset": round(self._ap_offset, 1),
            "effectiveTran": round(self._ap_last_effective_tran, 1),
            "baselineReady": self._ap_baseline is not None,
        }

    def _auto_pitch_enabled(self) -> bool:
        # Only meaningful for pitch-aware (f0) models.
        return bool(self.settings.autoPitch) and bool(getattr(self.slotInfo, "f0", False))

    def _effective_tran(self) -> float:
        if not self._auto_pitch_enabled():
            return self.settings.tran
        eff = self.settings.tran + self._ap_offset
        lo, hi = self.settings.autoPitchMin, self.settings.autoPitchMax
        if lo <= hi:
            eff = max(lo, min(hi, eff))
        return eff

    def _auto_pitch_update(self, eff_tran: float):
        """After a voiced inference, measure the speaker's true input pitch and
        slowly steer the correction so the output stays at the home register."""
        if not self._auto_pitch_enabled():
            return
        # Robust, gated measurement (sustained voicing + plausible range,
        # personalised when a profile exists).
        raw_median = self._measure_input_pitch(eff_tran, use_profile=True)
        if raw_median is None:
            return
        input_semi = 12.0 * math.log2(raw_median)

        # Track the speaker's register slowly.
        if self._ap_smooth_in is None:
            self._ap_smooth_in = input_semi
        else:
            diff = input_semi - self._ap_smooth_in
            # Outlier gate: a sudden large jump from the tracked register is
            # probably a transient noise, not the voice. Let it nudge the
            # tracker only a hair and don't react to it this frame -- but a
            # sustained shift still adapts (no permanent deadlock).
            if abs(diff) > AUTO_PITCH_OUTLIER_SEMITONES:
                self._ap_smooth_in += AUTO_PITCH_OUTLIER_LEAK * diff
                return
            self._ap_smooth_in += AUTO_PITCH_INPUT_SMOOTH * diff

        # Establish the home register once, shortly after enabling.
        if self._ap_baseline is None:
            self._ap_warmup += 1
            if self._ap_warmup >= AUTO_PITCH_WARMUP_FRAMES:
                self._ap_baseline = self._ap_smooth_in
            return

        # Desired correction keeps the output register near the home baseline:
        # if the speaker drops lower, raise the transpose, and vice versa.
        desired = self._ap_baseline - self._ap_smooth_in
        # Dead zone: don't react to small, natural pitch drift.
        if abs(desired) <= AUTO_PITCH_DEADZONE:
            desired = 0.0
        else:
            desired -= math.copysign(AUTO_PITCH_DEADZONE, desired)
        desired = max(-AUTO_PITCH_MAX_SEMITONES, min(AUTO_PITCH_MAX_SEMITONES, desired))

        # Move slowly toward the target; responsiveness slider scales the speed.
        response = max(1, int(self.settings.autoPitchResponse)) / 200.0  # 1..20 -> 0.005..0.1
        self._ap_offset += response * (desired - self._ap_offset)

        # Respect the user's pitch limits, and keep the offset from winding up
        # past them so it reacts immediately when the voice comes back in range.
        lo = self.settings.autoPitchMin - self.settings.tran
        hi = self.settings.autoPitchMax - self.settings.tran
        if lo <= hi:
            self._ap_offset = max(lo, min(hi, self._ap_offset))

    def initialize(self, force_reload: bool = False):
        logger.info("Initializing...")

        if self.settings.useONNX and not self.slotInfo.modelFileOnnx:
            self.export2onnx()

        # pipelineの生成
        try:
            self.pipeline = createPipeline(
                self.slotInfo, self.settings.f0Detector, self.settings.useONNX, force_reload
            )
        except Exception as e:  # NOQA
            logger.error("Failed to create pipeline.")
            logger.exception(e)
            return

        # 処理は16Kで実施(Pitch, embed, (infer))
        self.resampler_in = tat.Resample(
            orig_freq=self.input_sample_rate,
            new_freq=HUBERT_SAMPLE_RATE,
            dtype=torch.float32
        ).to(self.device_manager.device)

        self.resampler_out = tat.Resample(
            orig_freq=self.slotInfo.samplingRate,
            new_freq=self.output_sample_rate,
            dtype=torch.float32
        ).to(self.device_manager.device)

        # Apply the configured RMVPE voiced threshold to the fresh pipeline.
        self.pipeline.set_f0_threshold(self.settings.f0Threshold)

        logger.info("Initialized.")

    def set_sampling_rate(self, input_sample_rate: int, output_sample_rate: int):
        if self.input_sample_rate != input_sample_rate:
            self.input_sample_rate = input_sample_rate
            self.resampler_in = tat.Resample(
                orig_freq=self.input_sample_rate,
                new_freq=HUBERT_SAMPLE_RATE,
                dtype=torch.float32
            ).to(self.device_manager.device)
        if self.output_sample_rate != output_sample_rate:
            self.output_sample_rate = output_sample_rate
            self.resampler_out = tat.Resample(
                orig_freq=self.slotInfo.samplingRate,
                new_freq=self.output_sample_rate,
                dtype=torch.float32
            ).to(self.device_manager.device)

    def change_pitch_extractor(self):
        pitchExtractor = PitchExtractorManager.getPitchExtractor(
            self.settings.f0Detector, self.settings.gpu
        )
        self.pipeline.setPitchExtractor(pitchExtractor)
        # A freshly-loaded extractor defaults to 0.05; restore the user's value.
        self.pipeline.set_f0_threshold(self.settings.f0Threshold)

    def update_settings(self, key: str, val, old_val):
        if key in {"gpu", "forceFp32", "disableJit"}:
            self.is_half = self.device_manager.use_fp16()
            self.dtype = torch.float16 if self.is_half else torch.float32
            self.initialize(True)
        elif key == 'useONNX':
            self.initialize()
        elif key == "f0Detector" and self.pipeline is not None:
            self.change_pitch_extractor()
        elif key == 'f0Fp32':
            # The detector's compute precision is fixed at construction, so it
            # must be rebuilt. The device flag is updated by the manager first.
            self.initialize(True)
        elif key == 'f0Threshold' and self.pipeline is not None:
            self.pipeline.set_f0_threshold(self.settings.f0Threshold)
        elif key == 'silentThreshold':
            # Convert dB to RMS
            self.inputSensitivity = 10 ** (self.settings.silentThreshold / 20)
        elif key == 'silenceReleaseMs':
            self._compute_release_chunks()
        elif key == 'voiceProfile':
            # Profile was set/cleared externally (e.g. cleared by the user);
            # reload and re-anchor auto-pitch.
            self._load_voice_profile()
            self._auto_pitch_reset()

    def _compute_release_chunks(self):
        # How many audio chunks to keep converting after the volume drops.
        if self._block_frame > 0 and self.settings.silenceReleaseMs > 0:
            # Always at least one chunk when enabled, so a large chunk size
            # can't silently round the word-tail down to nothing.
            self._release_chunks = max(1, math.ceil(
                self.settings.silenceReleaseMs / 1000 * self.input_sample_rate / self._block_frame
            ))
        else:
            self._release_chunks = 0

    def set_slot_info(self, slotInfo: RVCModelSlot):
        self.slotInfo = slotInfo

    def get_info(self):
        data = {}
        if self.pipeline is not None:
            pipelineInfo = self.pipeline.getPipelineInfo()
            data["pipelineInfo"] = pipelineInfo
        else:
            data["pipelineInfo"] = "None"
        return data

    def get_processing_sampling_rate(self):
        return self.slotInfo.samplingRate

    def realloc(self, block_frame: int, extra_frame: int, crossfade_frame: int, sola_search_frame: int):
        # Remember the chunk size and (re)compute the silence-gate release window.
        self._block_frame = block_frame
        self._compute_release_chunks()
        # Calculate frame sizes based on DEVICE sample rate (f.e., 48000Hz) and convert to 16000Hz
        block_frame_16k = int(block_frame / self.input_sample_rate * HUBERT_SAMPLE_RATE)
        crossfade_frame_16k = int(crossfade_frame / self.input_sample_rate * HUBERT_SAMPLE_RATE)
        sola_search_frame_16k = int(sola_search_frame / self.input_sample_rate * HUBERT_SAMPLE_RATE)
        extra_frame_16k = int(extra_frame / self.input_sample_rate * HUBERT_SAMPLE_RATE)

        convert_size_16k = block_frame_16k + sola_search_frame_16k + extra_frame_16k + crossfade_frame_16k
        if (modulo := convert_size_16k % WINDOW_SIZE) != 0:  # モデルの出力のホップサイズで切り捨てが発生するので補う。
            convert_size_16k = convert_size_16k + (WINDOW_SIZE - modulo)
        self.convert_feature_size_16k = convert_size_16k // WINDOW_SIZE

        self.skip_head = extra_frame_16k // WINDOW_SIZE
        self.return_length = self.convert_feature_size_16k - self.skip_head
        self.silence_front = extra_frame_16k - (WINDOW_SIZE * 5) if self.settings.silenceFront else 0

        # Buffer dtype: stock build uses the model dtype. With hqBuffers (opt-in)
        # we keep them in fp32 so the volume/silence-gate measurement is accurate
        # and quiet-speech detail is preserved; they're cast to the model dtype
        # downstream (the pitch detector and embedder handle that).
        buf_dtype = torch.float32 if self.settings.hqBuffers else self.dtype
        # Audio buffer to measure volume between chunks
        audio_buffer_size = block_frame_16k + crossfade_frame_16k
        self.audio_buffer = torch.zeros(audio_buffer_size, dtype=buf_dtype, device=self.device_manager.device)

        # Audio buffer for conversion without silence
        self.convert_buffer = torch.zeros(convert_size_16k, dtype=buf_dtype, device=self.device_manager.device)
        # Additional +1 is to compensate for pitch extraction algorithm
        # that can output additional feature.
        self.pitch_buffer = torch.zeros(self.convert_feature_size_16k + 1, dtype=torch.int64, device=self.device_manager.device)
        self.pitchf_buffer = torch.zeros(self.convert_feature_size_16k + 1, dtype=self.dtype, device=self.device_manager.device)
        logger.info(f'Allocated audio buffer size: {audio_buffer_size}')
        logger.info(f'Allocated convert buffer size: {convert_size_16k}')
        logger.info(f'Allocated pitchf buffer size: {self.convert_feature_size_16k + 1}')

    def convert(self, audio_in: AudioInOutFloat, sample_rate: int) -> torch.Tensor:
        if self.pipeline is None:
            raise PipelineNotInitializedException()

        # Input audio is always float32
        audio_in_t = torch.as_tensor(audio_in, dtype=torch.float32, device=self.device_manager.device)
        if self.is_half:
            audio_in_t = audio_in_t.half()

        audio_in_16k = tat.Resample(
            orig_freq=sample_rate,
            new_freq=HUBERT_SAMPLE_RATE,
            dtype=self.dtype
        ).to(self.device_manager.device)(audio_in_t)

        # Feature size must be derived from the 16kHz audio actually fed to the
        # pipeline, not the pre-resample input (those differ when sample_rate
        # != 16000).
        convert_feature_size_16k = audio_in_16k.shape[0] // WINDOW_SIZE

        vol_t = torch.sqrt(
            torch.square(audio_in_16k).mean()
        )

        audio_model = self.pipeline.exec(
            self.settings.dstId,
            audio_in_16k,
            None,
            None,
            self.settings.tran,
            self.settings.formantShift,
            self.settings.indexRatio,
            convert_feature_size_16k,
            0,
            self.slotInfo.embOutputLayer,
            self.slotInfo.useFinalProj,
            0,
            convert_feature_size_16k,
            self.settings.protect,
            self.settings.maxPitch,
            bool(self.settings.f0Smoothing),
        )

        # TODO: Need to handle resampling for individual files
        # FIXME: Why the heck does it require another sqrt to amplify the volume?
        audio_out: torch.Tensor = self.resampler_out(audio_model * torch.sqrt(vol_t))

        return audio_out

    def inference(self, audio_in: AudioInOutFloat):
        if self.pipeline is None:
            raise PipelineNotInitializedException()

        # Input audio is always float32; match it to the buffer dtype (half on
        # the stock path, fp32 when hqBuffers is on). The pitch detector and
        # embedder cast to their own compute dtype downstream.
        audio_in_t = torch.as_tensor(audio_in, dtype=torch.float32, device=self.device_manager.device)
        audio_in_16k = self.resampler_in(audio_in_t).to(self.audio_buffer.dtype)

        circular_write(audio_in_16k, self.audio_buffer)

        vol_t = torch.sqrt(
            torch.square(self.audio_buffer).mean()
        )
        vol = max(vol_t.item(), 0)

        # Auto Pitch: reset the controller when it is freshly enabled, then use
        # the auto-corrected transpose. When disabled, eff_tran == settings.tran.
        enabled = self._auto_pitch_enabled()
        if enabled and not self._ap_prev_enabled:
            self._auto_pitch_reset()
        self._ap_prev_enabled = enabled
        eff_tran = self._effective_tran()
        self._ap_last_effective_tran = eff_tran

        # Silence-gate release ("Word tail"): keep converting for a short tail
        # after the volume drops, so quiet word-endings are not chopped off.
        loud = vol >= self.inputSensitivity
        if loud:
            self._silence_count = 0
        else:
            self._silence_count += 1

        if not loud and self._silence_count > self._release_chunks:
            # Busy wait to keep power manager happy and clocks stable. Running pipeline on-demand seems to lag when the delay between
            # voice changer activation is too high.
            # https://forums.developer.nvidia.com/t/why-kernel-calculate-speed-got-slower-after-waiting-for-a-while/221059/9
            self.pipeline.exec(
                self.settings.dstId,
                self.convert_buffer,
                self.pitch_buffer,
                self.pitchf_buffer,
                eff_tran,
                self.settings.formantShift,
                self.settings.indexRatio,
                self.convert_feature_size_16k,
                self.silence_front,
                self.slotInfo.embOutputLayer,
                self.slotInfo.useFinalProj,
                self.skip_head,
                self.return_length,
                self.settings.protect,
                self.settings.maxPitch,
                bool(self.settings.f0Smoothing),
            )
            return None, vol

        circular_write(audio_in_16k, self.convert_buffer)

        audio_model = self.pipeline.exec(
            self.settings.dstId,
            self.convert_buffer,
            self.pitch_buffer,
            self.pitchf_buffer,
            eff_tran,
            self.settings.formantShift,
            self.settings.indexRatio,
            self.convert_feature_size_16k,
            self.silence_front,
            self.slotInfo.embOutputLayer,
            self.slotInfo.useFinalProj,
            self.skip_head,
            self.return_length,
            self.settings.protect,
            self.settings.maxPitch,
            bool(self.settings.f0Smoothing),
        )

        # Update the auto-pitch controller from this (voiced) frame.
        self._auto_pitch_update(eff_tran)

        # Collect pitch for voice calibration, if a calibration is running.
        if self._cal_active:
            self._calibration_step(eff_tran)

        # FIXME: Why the heck does it require another sqrt to amplify the volume?
        audio_out: torch.Tensor = self.resampler_out(audio_model * torch.sqrt(vol_t))

        return audio_out, vol

    def __del__(self):
        del self.pipeline

    def export2onnx(self):
        modelSlot = self.slotInfo

        if modelSlot.isONNX:
            logger.error(f"{modelSlot.modelFile} is already in ONNX format.")
            return

        output_path = export2onnx(modelSlot)

        self.slotInfo.modelFileOnnx = os.path.basename(output_path)
        self.slotInfo.modelTypeOnnx = EnumInferenceTypes.onnxRVC.value if self.slotInfo.f0 else EnumInferenceTypes.onnxRVCNono.value
        saveSlotInfo(self.params.model_dir, self.slotInfo.slotIndex, self.slotInfo)

    def get_model_current(self) -> dict:
        return [
            {
                "key": "defaultTune",
                "val": self.settings.tran,
            },
            {
                "key": "defaultIndexRatio",
                "val": self.settings.indexRatio,
            },
            {
                "key": "defaultProtect",
                "val": self.settings.protect,
            },
            {
                "key": "defaultFormantShift",
                "val": self.settings.formantShift,
            },
        ]
