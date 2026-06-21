# from const import PitchExtractorType
from typing import NamedTuple

import logging
logger = logging.getLogger(__name__)

IGNORED_KEYS = { 'version' }
STATEFUL_KEYS = [ 'serverAudioStated', 'passThrough', 'recordIO' ]

def _js_bool_to_bool(value: str) -> bool:
    return value == 'true'

class SetPropertyResult(NamedTuple):
    error: bool
    old_value: str | int | float | bool | None

class VoiceChangerSettings:

    def to_dict(self) -> dict:
        return self.get_properties()

    # TODO: This is a temporary kostyl.
    # Stateful keys must not be part of the settings. Need to rework audio handling logic
    def to_dict_stateless(self) -> dict:
        data = self.to_dict()
        for key in STATEFUL_KEYS:
            del data[key]
        return data

    def get_properties(self) -> dict:
        return {
            key: value.fget(self)
            for key, value in self.__class__.__dict__.items()
            if isinstance(value, property)
        }

    def set_properties(self, data: dict) -> list[SetPropertyResult]:
        return [
            self.set_property(key, value)
            for key, value in data.items()
        ]

    def set_property(self, key, value) -> SetPropertyResult:
        cls = self.__class__
        if key in IGNORED_KEYS:
            return SetPropertyResult(error=False, old_value=None)
        if key not in cls.__dict__:
            logger.error(f'Failed to set setting: {key} does not exist')
            return SetPropertyResult(error=True, old_value=None)
        p = cls.__dict__[key]
        if not isinstance(p, property):
            return SetPropertyResult(error=True, old_value=None)
        if p.fset is None:
            logger.error(f'Failed to set setting: {key} is immutable.')
            return SetPropertyResult(error=True, old_value=None)
        old_value = p.fget(self)
        p.fset(self, value)
        return SetPropertyResult(error=False, old_value=old_value)

    def get_property(self, key):
        return getattr(self, key)

    # Immutable
    _version: str = 'v1'

    @property
    def version(self):
        return self._version

    # General settings
    _modelSlotIndex: int = -1

    _outputSampleRate: int = 48000
    _inputSampleRate: int = 48000

    _crossFadeOverlapSize: float = 0.1
    _serverReadChunkSize: int = 192
    _extraConvertSize: float = 0.5
    _gpu: int = -1
    _forceFp32: int = 0
    _disableJit: int = 0

    _passThrough: bool = False
    _recordIO: int = 0

    @property
    def modelSlotIndex(self):
        return self._modelSlotIndex

    @modelSlotIndex.setter
    def modelSlotIndex(self, idx: str):
        self._modelSlotIndex = int(idx)

    @property
    def inputSampleRate(self):
        return self._inputSampleRate

    @inputSampleRate.setter
    def inputSampleRate(self, sample_rate: str):
        self._inputSampleRate = int(sample_rate)

    @property
    def outputSampleRate(self):
        return self._outputSampleRate

    @outputSampleRate.setter
    def outputSampleRate(self, sample_rate: str):
        self._outputSampleRate = int(sample_rate)

    @property
    def passThrough(self):
        return self._passThrough

    @passThrough.setter
    def passThrough(self, enable: str):
        self._passThrough = _js_bool_to_bool(enable)

    @property
    def recordIO(self):
        return self._recordIO

    @recordIO.setter
    def recordIO(self, enable: str):
        self._recordIO = int(enable)

    @property
    def gpu(self):
        return self._gpu

    @gpu.setter
    def gpu(self, gpu: str):
        self._gpu = int(gpu)

    @property
    def extraConvertSize(self):
        return self._extraConvertSize

    @extraConvertSize.setter
    def extraConvertSize(self, size: str):
        self._extraConvertSize = float(size)

    @property
    def serverReadChunkSize(self):
        return self._serverReadChunkSize

    @serverReadChunkSize.setter
    def serverReadChunkSize(self, size: str):
        self._serverReadChunkSize = int(size)

    @property
    def crossFadeOverlapSize(self):
        return self._crossFadeOverlapSize

    @crossFadeOverlapSize.setter
    def crossFadeOverlapSize(self, size: str):
        self._crossFadeOverlapSize = float(size)

    @property
    def forceFp32(self):
        return self._forceFp32

    @forceFp32.setter
    def forceFp32(self, enable: str):
        self._forceFp32 = int(enable)

    @property
    def disableJit(self):
        return self._disableJit

    @disableJit.setter
    def disableJit(self, enable: str):
        self._disableJit = int(enable)

    # Server Audio settings
    _serverAudioStated: int = 0
    _enableServerAudio: int = 0
    _serverInputAudioSampleRate: int = 44100
    _serverOutputAudioSampleRate: int = 44100
    _serverMonitorAudioSampleRate: int = 44100

    _serverAudioSampleRate: int = 44100

    _serverInputDeviceId: int = -1
    _serverOutputDeviceId: int = -1
    _serverMonitorDeviceId: int = -1  # -1 でモニター無効
    _serverInputAudioGain: float = 1.0
    _serverOutputAudioGain: float = 1.0
    _serverMonitorAudioGain: float = 1.0

    _exclusiveMode: int = 0
    _asioInputChannel: int = -1
    _asioOutputChannel: int = -1

    @property
    def serverAudioStated(self):
        return self._serverAudioStated

    @serverAudioStated.setter
    def serverAudioStated(self, enabled: str):
        self._serverAudioStated = int(enabled)

    @property
    def enableServerAudio(self):
        return self._enableServerAudio

    @enableServerAudio.setter
    def enableServerAudio(self, enabled: str):
        self._enableServerAudio = int(enabled)

    @property
    def serverInputAudioSampleRate(self):
        return self._serverInputAudioSampleRate

    @serverInputAudioSampleRate.setter
    def serverInputAudioSampleRate(self, rate: str):
        self._serverInputAudioSampleRate = int(rate)

    @property
    def serverOutputAudioSampleRate(self):
        return self._serverOutputAudioSampleRate

    @serverOutputAudioSampleRate.setter
    def serverOutputAudioSampleRate(self, rate: str):
        self._serverOutputAudioSampleRate = int(rate)

    @property
    def serverMonitorAudioSampleRate(self):
        return self._serverMonitorAudioSampleRate

    @serverMonitorAudioSampleRate.setter
    def serverMonitorAudioSampleRate(self, rate: str):
        self._serverMonitorAudioSampleRate = int(rate)

    @property
    def serverAudioSampleRate(self):
        return self._serverAudioSampleRate

    @serverAudioSampleRate.setter
    def serverAudioSampleRate(self, rate: str):
        self._serverAudioSampleRate = int(rate)

    @property
    def serverInputDeviceId(self):
        return self._serverInputDeviceId

    @serverInputDeviceId.setter
    def serverInputDeviceId(self, id: str):
        self._serverInputDeviceId = int(id)

    @property
    def serverOutputDeviceId(self):
        return self._serverOutputDeviceId

    @serverOutputDeviceId.setter
    def serverOutputDeviceId(self, id: str):
        self._serverOutputDeviceId = int(id)

    @property
    def serverMonitorDeviceId(self):
        return self._serverMonitorDeviceId

    @serverMonitorDeviceId.setter
    def serverMonitorDeviceId(self, id: str):
        self._serverMonitorDeviceId = int(id)

    @property
    def serverInputAudioGain(self):
        return self._serverInputAudioGain

    @serverInputAudioGain.setter
    def serverInputAudioGain(self, gain: str):
        self._serverInputAudioGain = float(gain)

    @property
    def serverOutputAudioGain(self):
        return self._serverOutputAudioGain

    @serverOutputAudioGain.setter
    def serverOutputAudioGain(self, gain: str):
        self._serverOutputAudioGain = float(gain)

    @property
    def serverMonitorAudioGain(self):
        return self._serverMonitorAudioGain

    @serverMonitorAudioGain.setter
    def serverMonitorAudioGain(self, gain: str):
        self._serverMonitorAudioGain = float(gain)

    @property
    def exclusiveMode(self):
        return self._exclusiveMode

    @exclusiveMode.setter
    def exclusiveMode(self, enabled: str):
        self._exclusiveMode = int(enabled)

    @property
    def asioInputChannel(self):
        return self._asioInputChannel

    @asioInputChannel.setter
    def asioInputChannel(self, id: str):
        self._asioInputChannel = int(id)

    @property
    def asioOutputChannel(self):
        return self._asioOutputChannel

    @asioOutputChannel.setter
    def asioOutputChannel(self, id: str):
        self._asioOutputChannel = int(id)

    # RVCv2 settings
    _dstId: int = 0

    _f0Detector: str = "rmvpe_onnx"
    _tran: int = 0
    _formantShift: float = 0
    _useONNX: int = 0

    _silentThreshold: int = -90

    _indexRatio: float = 0
    _protect: float = 0.5
    _silenceFront: int = 1

    # Auto Pitch (experimental): when enabled, the transpose ("tran") is
    # automatically nudged so the speaker's voice stays in the target model's
    # comfortable pitch range, instead of being stuck at a fixed value.
    # autoPitchResponse (1=very slow .. 20=fast) controls how quickly it adapts.
    _autoPitch: int = 0
    _autoPitchResponse: int = 5
    # Hard limits on the pitch Auto Pitch may output (effective transpose, in
    # semitones). Wide defaults = effectively no limit; narrow them to stop it
    # swinging too low/high.
    _autoPitchMin: float = -36.0
    _autoPitchMax: float = 36.0

    # Auto Smooth (experimental): when enabled, the conversion buffer
    # ("extraConvertSize") is automatically tuned based on how hard PC2 is
    # working, to keep the audio stable (no stutter) while staying as low
    # latency as the machine allows. 0 = off.
    _autoSmooth: int = 0

    # Voice calibration profile: a small JSON string of pitch numbers (or '').
    # Lets auto-pitch anchor to the speaker's measured home pitch. No audio.
    _voiceProfile: str = ''

    # Silence-gate release ("Word tail"), in milliseconds: keep converting for
    # this long after the volume drops so quiet word-endings are not cut off.
    _silenceReleaseMs: int = 150

    # Scream/cough guard: maximum output pitch in Hz (0 = off). Caps how high
    # the voice can go so loud non-speech transients don't produce squeals.
    _maxPitch: int = 0

    # Optional AI speech enhancement (DeepFilterNet) on the output (0 = off).
    _postEnhance: int = 0

    # Output DSP amounts, 0..100 (0 = off).
    _deEss: int = 0         # tames harsh sss/shh sibilance
    _outputComp: int = 0    # evens out loudness + makeup gain + safety limiter

    # Equalizer profile: a small JSON string describing the 5-band graphic EQ
    # plus the bass/vocal boost knobs, e.g.
    #   {"bands": [0, 0, 0, 0, 0], "bass": 0, "vocal": 0}
    # Empty string ('') means a flat EQ (off). No audio is stored.
    _eqProfile: str = ''

    @property
    def dstId(self):
        return self._dstId

    @dstId.setter
    def dstId(self, id: str):
        self._dstId = int(id)

    @property
    def f0Detector(self):
        return self._f0Detector

    @f0Detector.setter
    def f0Detector(self, pitch_extractor_type: str):
        self._f0Detector = pitch_extractor_type

    @property
    def tran(self):
        return self._tran

    @tran.setter
    def tran(self, tone: str):
        self._tran = int(tone)

    @property
    def formantShift(self):
        return self._formantShift

    @formantShift.setter
    def formantShift(self, shift_size: str):
        self._formantShift = float(shift_size)

    @property
    def useONNX(self):
        return self._useONNX

    @useONNX.setter
    def useONNX(self, enabled: str):
        self._useONNX = int(enabled)

    @property
    def silentThreshold(self):
        return self._silentThreshold

    @silentThreshold.setter
    def silentThreshold(self, threshold: str):
        self._silentThreshold = int(threshold)

    @property
    def indexRatio(self):
        return self._indexRatio

    @indexRatio.setter
    def indexRatio(self, ratio: str):
        self._indexRatio = float(ratio)

    @property
    def protect(self):
        return self._protect

    @protect.setter
    def protect(self, protect: str):
        self._protect = float(protect)

    @property
    def silenceFront(self):
        return self._silenceFront

    @silenceFront.setter
    def silenceFront(self, enable: str):
        self._silenceFront = int(enable)

    @property
    def autoPitch(self):
        return self._autoPitch

    @autoPitch.setter
    def autoPitch(self, enable: str):
        self._autoPitch = int(enable)

    @property
    def autoPitchResponse(self):
        return self._autoPitchResponse

    @autoPitchResponse.setter
    def autoPitchResponse(self, val: str):
        self._autoPitchResponse = int(val)

    @property
    def autoPitchMin(self):
        return self._autoPitchMin

    @autoPitchMin.setter
    def autoPitchMin(self, val: str):
        self._autoPitchMin = float(val)

    @property
    def autoPitchMax(self):
        return self._autoPitchMax

    @autoPitchMax.setter
    def autoPitchMax(self, val: str):
        self._autoPitchMax = float(val)

    @property
    def autoSmooth(self):
        return self._autoSmooth

    @autoSmooth.setter
    def autoSmooth(self, enable: str):
        self._autoSmooth = int(enable)

    @property
    def voiceProfile(self):
        return self._voiceProfile

    @voiceProfile.setter
    def voiceProfile(self, val: str):
        self._voiceProfile = str(val) if val is not None else ''

    @property
    def silenceReleaseMs(self):
        return self._silenceReleaseMs

    @silenceReleaseMs.setter
    def silenceReleaseMs(self, val: str):
        self._silenceReleaseMs = int(val)

    @property
    def maxPitch(self):
        return self._maxPitch

    @maxPitch.setter
    def maxPitch(self, val: str):
        self._maxPitch = int(val)

    @property
    def postEnhance(self):
        return self._postEnhance

    @postEnhance.setter
    def postEnhance(self, val: str):
        self._postEnhance = int(val)

    @property
    def deEss(self):
        return self._deEss

    @deEss.setter
    def deEss(self, val: str):
        self._deEss = int(val)

    @property
    def outputComp(self):
        return self._outputComp

    @outputComp.setter
    def outputComp(self, val: str):
        self._outputComp = int(val)

    @property
    def eqProfile(self):
        return self._eqProfile

    @eqProfile.setter
    def eqProfile(self, val: str):
        self._eqProfile = str(val) if val is not None else ''
