"""
Lightweight output audio effects (DSP) applied to the converted voice:
  * De-esser    - tames harsh sss/shh sibilance.
  * Equalizer   - 5-band graphic EQ plus dedicated bass-boost and vocal-boost
                  controls (a cascade of biquad peaking/shelf filters).
  * Compressor  - evens out loudness (quiet parts louder, peaks tamed) with a
                  makeup gain and a safety limiter.

All effects are fully isolated: any error returns the audio unchanged, and
filter/envelope state is carried across chunks so there are no boundary clicks.
Amounts are 0..100 (0 = off); EQ band gains are in dB.
"""
import json
import logging
import math
import numpy as np

logger = logging.getLogger(__name__)

# Center frequencies (Hz) of the 5 graphic-EQ band sliders, low -> high.
EQ_BAND_FREQS = [80.0, 250.0, 1000.0, 4000.0, 12000.0]
# Dedicated boost knobs (0..100 in the UI) map onto these biquads.
BASS_BOOST_FREQ = 110.0      # low-shelf
BASS_BOOST_MAX_DB = 12.0
VOCAL_BOOST_FREQ = 2800.0    # presence peak for vocal clarity
VOCAL_BOOST_MAX_DB = 9.0
VOCAL_BOOST_Q = 1.0
EQ_BAND_Q = 1.0


class OutputFX:
    def __init__(self):
        self._sr = None
        self._comp_a = 0.0
        self._comp_zi = None
        self._deess_a = 0.0
        self._deess_zi = None
        self._hp_b = None
        self._hp_a = None
        self._hp_zi = None
        # Equalizer: a list of (b, a) biquad coefficients designed from the
        # current profile, plus per-filter lfilter state. Cached by profile
        # string + sample rate so coefficients are only recomputed on change.
        self._eq_key = None
        self._eq_biquads = []
        self._eq_zi = []

    def _setup(self, sr: int):
        from scipy.signal import butter
        self._sr = sr
        self._comp_a = math.exp(-1.0 / (sr * 0.030))   # ~30 ms envelope
        self._deess_a = math.exp(-1.0 / (sr * 0.010))  # ~10 ms envelope
        wc = min(5000.0 / (sr / 2.0), 0.99)            # highpass ~5 kHz (sibilance)
        self._hp_b, self._hp_a = butter(2, wc, btype="high")
        self._comp_zi = None
        self._deess_zi = None
        self._hp_zi = None

    def _ensure_setup(self, sr: int):
        if self._sr != sr or self._hp_b is None:
            self._setup(sr)

    def _envelope(self, absx: np.ndarray, a: float, zi):
        from scipy.signal import lfilter
        if zi is None:
            zi = np.array([absx[0] * a], dtype=np.float64)
        env, zi = lfilter([1 - a], [1.0, -a], absx, zi=zi)
        return np.maximum(env, 1e-6), zi

    def _deess(self, x: np.ndarray, amount: float) -> np.ndarray:
        from scipy.signal import lfilter, lfilter_zi
        if self._hp_zi is None:
            self._hp_zi = lfilter_zi(self._hp_b, self._hp_a) * float(x[0])
        hb, self._hp_zi = lfilter(self._hp_b, self._hp_a, x, zi=self._hp_zi)
        env, self._deess_zi = self._envelope(np.abs(hb).astype(np.float64), self._deess_a, self._deess_zi)
        thresh = 0.05
        over = np.maximum(env - thresh, 0.0) / (thresh + 1e-6)
        red = np.minimum(over * (amount / 100.0), amount / 100.0)
        return (x - hb * red.astype(np.float32)).astype(np.float32)

    # ---- Equalizer ------------------------------------------------------
    # RBJ Audio-EQ-Cookbook biquad designs (returned normalised by a0).
    def _peaking(self, f0: float, gain_db: float, q: float, sr: int):
        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * math.pi * f0 / sr
        cw = math.cos(w0)
        alpha = math.sin(w0) / (2.0 * q)
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
        return np.array(b) / a[0], np.array(a) / a[0]

    def _low_shelf(self, f0: float, gain_db: float, sr: int, q: float = 0.707):
        A = 10.0 ** (gain_db / 40.0)
        w0 = 2.0 * math.pi * f0 / sr
        cw = math.cos(w0)
        alpha = math.sin(w0) / (2.0 * q)
        tsa = 2.0 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + tsa),
             2 * A * ((A - 1) - (A + 1) * cw),
             A * ((A + 1) - (A - 1) * cw - tsa)]
        a = [(A + 1) + (A - 1) * cw + tsa,
             -2 * ((A - 1) + (A + 1) * cw),
             (A + 1) + (A - 1) * cw - tsa]
        return np.array(b) / a[0], np.array(a) / a[0]

    def _design_eq(self, profile: str, sr: int):
        """Parse the EQ profile JSON and build the active biquad cascade.

        Profile shape: {"bands": [g0..g4] in dB, "bass": 0..100, "vocal": 0..100}.
        Filters whose gain rounds to ~0 dB are skipped so a flat EQ is free.
        """
        try:
            prof = json.loads(profile) if profile else {}
        except Exception:
            prof = {}
        bands = prof.get("bands") or []
        bass = float(prof.get("bass") or 0.0)
        vocal = float(prof.get("vocal") or 0.0)

        filters = []
        for i, f0 in enumerate(EQ_BAND_FREQS):
            try:
                g = float(bands[i])
            except (IndexError, TypeError, ValueError):
                g = 0.0
            if abs(g) >= 0.05:
                filters.append(self._peaking(f0, g, EQ_BAND_Q, sr))
        if bass > 0.05:
            g = min(max(bass, 0.0), 100.0) / 100.0 * BASS_BOOST_MAX_DB
            filters.append(self._low_shelf(BASS_BOOST_FREQ, g, sr))
        if vocal > 0.05:
            g = min(max(vocal, 0.0), 100.0) / 100.0 * VOCAL_BOOST_MAX_DB
            filters.append(self._peaking(VOCAL_BOOST_FREQ, g, VOCAL_BOOST_Q, sr))
        return filters

    def _ensure_eq(self, profile: str, sr: int):
        key = (profile, sr)
        if key == self._eq_key:
            return
        self._eq_key = key
        self._eq_biquads = self._design_eq(profile, sr)
        self._eq_zi = [None] * len(self._eq_biquads)

    def _apply_eq(self, x: np.ndarray) -> np.ndarray:
        from scipy.signal import lfilter, lfilter_zi
        y = x.astype(np.float64)
        for idx, (b, a) in enumerate(self._eq_biquads):
            zi = self._eq_zi[idx]
            if zi is None:
                zi = lfilter_zi(b, a) * y[0]
            y, zi = lfilter(b, a, y, zi=zi)
            self._eq_zi[idx] = zi
        # Boosting bands can push peaks past full scale; clip so the downstream
        # int conversion can't wrap around into harsh distortion.
        np.clip(y, -0.99, 0.99, out=y)
        return y.astype(np.float32)

    def _compress(self, x: np.ndarray, amount: float) -> np.ndarray:
        env, self._comp_zi = self._envelope(np.abs(x).astype(np.float64), self._comp_a, self._comp_zi)
        env_db = 20.0 * np.log10(env)
        threshold_db = -24.0
        ratio = 3.0
        makeup_db = amount / 100.0 * 12.0
        over = np.maximum(env_db - threshold_db, 0.0)
        gain_db = -over * (1.0 - 1.0 / ratio) + makeup_db
        gain = np.power(10.0, gain_db / 20.0)
        y = (x * gain.astype(np.float32)).astype(np.float32)
        np.clip(y, -0.99, 0.99, out=y)
        return y

    def process(self, x: np.ndarray, sr: int, deess_amount: float, comp_amount: float, eq_profile: str = "") -> np.ndarray:
        if (deess_amount <= 0 and comp_amount <= 0 and not eq_profile) or x is None or len(x) == 0:
            return x
        try:
            self._ensure_setup(sr)
            self._ensure_eq(eq_profile or "", sr)
            if deess_amount > 0:
                x = self._deess(x, deess_amount)
            if self._eq_biquads:
                x = self._apply_eq(x)
            if comp_amount > 0:
                x = self._compress(x, comp_amount)
            return x
        except Exception as e:
            logger.error("OutputFX error, passing audio through: %s", e)
            return x
