/*
 * Extra Controls (beta) -- 3-column grid tray.
 *
 * Talks to the server's REST endpoints, so it works without rebuilding the
 * main bundle:
 *   POST /update_settings        key/val pairs
 *   GET  /auto_pitch             live auto-pitch status
 *   GET  /auto_smooth            live auto-smooth status
 *   POST /calibrate_start        begin voice calibration
 *   GET  /calibrate_status       calibration progress / saved profile
 *   GET  /info                   current settings
 *
 * Background noise cleanup is client-side: it forces the browser's built-in
 * noise suppression on via a getUserMedia wrapper (applies on next Start).
 */
(function () {
  var NS_KEY = 'vc_noise_cleanup'; // '1' = on (default), '0' = off
  function nsEnabled() { return localStorage.getItem(NS_KEY) !== '0'; }

  // --- Force browser noise suppression via a getUserMedia wrapper ---------
  (function patchGetUserMedia() {
    var md = navigator.mediaDevices;
    if (!md || !md.getUserMedia || md.__vcNoisePatched) return;
    var orig = md.getUserMedia.bind(md);
    md.__vcNoisePatched = true;
    md.getUserMedia = function (constraints) {
      try {
        if (nsEnabled() && constraints && constraints.audio) {
          if (constraints.audio === true) constraints.audio = {};
          if (typeof constraints.audio === 'object') constraints.audio.noiseSuppression = true;
        }
      } catch (e) { /* never block capture */ }
      return orig(constraints);
    };
  })();

  // --- Auto-dismiss the startup "Welcome" dialog --------------------------
  function trySkipWelcome() {
    var titles = document.getElementsByClassName('dialog-title');
    for (var i = 0; i < titles.length; i++) {
      if ((titles[i].textContent || '').indexOf('Welcome to Realtime Voice Changer') < 0) continue;
      var frame = titles[i].closest && titles[i].closest('.dialog-frame');
      if (!frame) continue;
      var btns = frame.getElementsByClassName('body-button');
      for (var j = 0; j < btns.length; j++) {
        if ((btns[j].textContent || '').trim() === 'Start') { btns[j].click(); return true; }
      }
    }
    return false;
  }
  (function watchWelcome() {
    trySkipWelcome();
    if (typeof MutationObserver === 'undefined') return;
    var obs = new MutationObserver(function () { trySkipWelcome(); });
    obs.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(function () { obs.disconnect(); }, 20000);
  })();

  function post(key, val) {
    return fetch('/update_settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ key: key, val: String(val) }),
    }).catch(function (e) { console.error('[extras] update failed', key, e); });
  }

  // --- Shared hover tooltip ----------------------------------------------
  var tipEl = null;
  function ensureTip() {
    if (tipEl) return;
    tipEl = document.createElement('div');
    tipEl.style.cssText = [
      'position:fixed', 'z-index:100000', 'pointer-events:none', 'display:none',
      'max-width:260px', 'background:rgba(10,10,16,0.97)', 'color:#fff',
      'font:14px/1.4 system-ui,sans-serif', 'padding:8px 10px', 'border-radius:8px',
      'box-shadow:0 3px 12px rgba(0,0,0,0.55)', 'border:1px solid rgba(255,255,255,0.12)'
    ].join(';');
    document.body.appendChild(tipEl);
  }
  function placeTip(el) {
    var r = el.getBoundingClientRect();
    var left = Math.max(8, Math.min(window.innerWidth - tipEl.offsetWidth - 8, r.left));
    var top = r.top - tipEl.offsetHeight - 8;
    if (top < 8) top = r.bottom + 8;
    tipEl.style.left = left + 'px';
    tipEl.style.top = top + 'px';
  }
  function attachTip(el, text) {
    el.addEventListener('mouseenter', function () { tipEl.textContent = text; tipEl.style.display = 'block'; placeTip(el); });
    el.addEventListener('mouseleave', function () { tipEl.style.display = 'none'; });
  }

  // --- Cell + control helpers --------------------------------------------
  function cell(labelText, tip) {
    var wrap = document.createElement('div');
    wrap.style.cssText = 'display:flex;flex-direction:column;gap:5px;align-items:stretch';
    var label = document.createElement('div');
    label.textContent = labelText;
    label.style.cssText = 'font-size:17px;font-weight:600;opacity:0.92;white-space:nowrap';
    wrap.appendChild(label);
    if (tip) attachTip(wrap, tip);
    return { wrap: wrap, label: label };
  }

  function makeToggle(on) {
    var b = document.createElement('button');
    b._on = !!on;
    b.style.cssText = 'padding:8px 10px;border:0;border-radius:7px;cursor:pointer;color:#fff;font-weight:bold;font-size:15px';
    function paint() { b.textContent = b._on ? 'ON' : 'OFF'; b.style.background = b._on ? '#2e9e5b' : '#555'; }
    paint();
    b.setOn = function (v) { b._on = !!v; paint(); };
    return b;
  }

  function makeSlider(min, max, step, val, fmt, oninput) {
    var holder = document.createElement('div');
    holder.style.cssText = 'display:flex;flex-direction:column;gap:2px';
    var v = document.createElement('div');
    v.style.cssText = 'font-size:14px;opacity:0.9;text-align:center;min-height:16px';
    var s = document.createElement('input');
    s.type = 'range'; s.min = min; s.max = max; s.step = step; s.value = val;
    s.style.cssText = 'width:100%;margin:0';
    function show() { v.textContent = fmt(s.value); }
    show();
    s.oninput = function () { show(); oninput(s.value); };
    holder.appendChild(v); holder.appendChild(s);
    return { el: holder, slider: s, show: show };
  }

  function build() {
    if (document.getElementById('vc-extras-bar')) return;
    ensureTip();

    var panel = document.createElement('div');
    panel.id = 'vc-extras-bar';
    panel.style.cssText = [
      'position:fixed', 'right:12px', 'bottom:12px', 'z-index:99999',
      'background:rgba(28,28,38,0.96)', 'color:#fff', 'font:15px/1.4 system-ui,sans-serif',
      'padding:12px 16px', 'border-radius:12px', 'box-shadow:0 4px 18px rgba(0,0,0,0.55)',
      'display:flex', 'flex-direction:column', 'gap:10px', 'user-select:none', 'max-width:calc(100vw - 24px)'
    ].join(';');

    var header = document.createElement('div');
    header.style.cssText = 'display:flex;align-items:center;gap:8px;font-weight:bold;font-size:18px;cursor:pointer';
    var caret = document.createElement('span');
    var hText = document.createElement('span');
    hText.textContent = 'Extra Controls';
    header.appendChild(caret); header.appendChild(hText);
    panel.appendChild(header);

    var grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(3, minmax(150px, 1fr));gap:16px 22px';
    panel.appendChild(grid);
    function add(c) { grid.appendChild(c); }

    // === Row 1: Auto Pitch, Calibrate, Responsiveness ====================
    var apC = cell('Auto Pitch', 'Automatically keeps your converted voice in the model’s comfortable pitch range, so it doesn’t go squeaky or too deep.');
    var apBtn = makeToggle(false);
    apBtn.onclick = function () { apBtn.setOn(!apBtn._on); post('autoPitch', apBtn._on ? 1 : 0); };
    var apRead = document.createElement('div');
    apRead.style.cssText = 'font-size:13px;opacity:0.85;min-height:15px';
    apRead.textContent = '--';
    apC.wrap.appendChild(apBtn); apC.wrap.appendChild(apRead);
    add(apC.wrap);

    var calC = cell('Calibrate', 'Talk normally ~45s; it measures your pitch and saves a tiny profile (no audio). Auto Pitch then anchors to your voice and rejects noises outside your range.');
    var calBtn = document.createElement('button');
    calBtn.textContent = '🎤 Calibrate';
    calBtn.style.cssText = 'padding:8px 10px;border:0;border-radius:7px;cursor:pointer;background:#3a6ea5;color:#fff;font-weight:bold;font-size:15px';
    var calStatus = document.createElement('div');
    calStatus.style.cssText = 'font-size:13px;opacity:0.85;min-height:15px';
    calC.wrap.appendChild(calBtn); calC.wrap.appendChild(calStatus);
    add(calC.wrap);
    var calPoll = null;
    function calLabel(s) {
      if (s && s.hasProfile && s.profile) {
        calStatus.innerHTML = 'Saved ~' + Math.round(s.profile.homeHz) + ' Hz · <a href="#" id="ap-cal-clear" style="color:#ff9bb0">clear</a>';
        var clr = document.getElementById('ap-cal-clear');
        if (clr) clr.onclick = function (e) { e.preventDefault(); post('voiceProfile', ''); calStatus.textContent = 'Cleared.'; };
      } else { calStatus.textContent = 'Start, click, talk ~45s.'; }
    }
    calBtn.onclick = function () {
      fetch('/calibrate_start', { method: 'POST' }).then(function (r) { return r.json(); }).then(function () {
        calBtn.disabled = true;
        if (calPoll) clearInterval(calPoll);
        calPoll = setInterval(function () {
          fetch('/calibrate_status').then(function (r) { return r.json(); }).then(function (s) {
            if (!s || !s.available) { calStatus.textContent = 'N/A for this model.'; clearInterval(calPoll); calBtn.disabled = false; return; }
            if (s.active) { calStatus.textContent = 'Listening… ' + Math.ceil(s.remaining) + 's (' + s.count + ')'; return; }
            clearInterval(calPoll); calBtn.disabled = false;
            if (s.ready && s.profile) calStatus.textContent = '✓ Saved ~' + Math.round(s.profile.homeHz) + ' Hz.';
            else calStatus.textContent = '✗ Not enough voice. Retry.';
          }).catch(function () { clearInterval(calPoll); calBtn.disabled = false; });
        }, 500);
      }).catch(function () { calStatus.textContent = 'Could not start.'; });
    };

    var respSc = (function () {
      var c = cell('Responsiveness', 'How fast Auto Pitch reacts. Low = slow & steady, high = snappy.');
      var sc = makeSlider(1, 20, 1, 5, function (v) { return v; }, function (v) { post('autoPitchResponse', v); });
      c.wrap.appendChild(sc.el); add(c.wrap); return sc;
    })();

    // === Row 2: Lowest pitch, Highest pitch, Max pitch ===================
    function numCell(label, tip, key) {
      var c = cell(label, tip);
      var inp = document.createElement('input');
      inp.type = 'number'; inp.step = '1';
      inp.style.cssText = 'width:70px;background:#1c1c26;color:#fff;border:1px solid #555;border-radius:5px;padding:6px 6px;font-size:15px';
      inp.onchange = function () { post(key, inp.value); };
      c.wrap.appendChild(inp); add(c.wrap);
      return inp;
    }
    var lowInp = numCell('Lowest pitch', 'Auto Pitch will never go below this (e.g. 11).', 'autoPitchMin');
    var highInp = numCell('Highest pitch', 'Auto Pitch will never go above this (e.g. 13).', 'autoPitchMax');

    function sliderCell(label, tip, min, max, step, val, fmt, key, mapOut) {
      var c = cell(label, tip);
      var sc = makeSlider(min, max, step, val, fmt, function (v) { post(key, mapOut ? mapOut(v) : v); });
      c.wrap.appendChild(sc.el); add(c.wrap);
      return sc;
    }
    var capSc = sliderCell('Max pitch', 'Caps how high the voice can go, to stop squeals from loud non-speech.', 0, 800, 25, 0,
      function (v) { return Number(v) <= 0 ? 'Off' : v + ' Hz'; }, 'maxPitch');

    // === Row 3: Breath detail, Input sensitivity, Word tail ==============
    var protSc = sliderCell('Breath detail', 'More breath/consonant detail (right) vs cleaner (left).', 0, 50, 1, 0,
      function (v) { return ((50 - Number(v)) / 100).toFixed(2); }, 'protect', function (v) { return ((50 - Number(v)) / 100).toFixed(2); });
    var sensSc = sliderCell('Input sensitivity', 'Mic gate: how loud before it converts. Lower = picks up quieter sound.', -90, -20, 1, -90,
      function (v) { return v + ' dB'; }, 'silentThreshold');
    var tailSc = sliderCell('Word tail', 'Keep converting briefly after you stop, so quiet word-endings aren’t cut off.', 0, 400, 10, 150,
      function (v) { return v + ' ms'; }, 'silenceReleaseMs');

    // === Row 4: De-ess, Leveling, Formant ===============================
    var dzSc = sliderCell('De-ess', 'Tames harsh sss/shh sibilance.', 0, 100, 5, 0, function (v) { return v; }, 'deEss');
    var lvSc = sliderCell('Leveling', 'Evens out and boosts loudness (compressor).', 0, 100, 5, 0, function (v) { return v; }, 'outputComp');
    var fmSc = sliderCell('Formant', 'Voice character / timbre shift.', -8, 8, 0.5, 0, function (v) { return v; }, 'formantShift');

    // === Row 5: Noise cleanup, Auto-smooth ==============================
    var nsC = cell('Noise cleanup', 'Removes steady background noise (fan/hum) from your mic. Applies on the next Start.');
    var nsBtn = makeToggle(nsEnabled());
    nsBtn.onclick = function () { nsBtn.setOn(!nsBtn._on); localStorage.setItem(NS_KEY, nsBtn._on ? '1' : '0'); };
    nsC.wrap.appendChild(nsBtn); add(nsC.wrap);

    var asC = cell('Auto-smooth', 'Auto-adjusts the audio buffer based on how hard PC2 is working, to stop stutter.');
    var asBtn = makeToggle(false);
    asBtn.onclick = function () { asBtn.setOn(!asBtn._on); post('autoSmooth', asBtn._on ? 1 : 0); };
    var asRead = document.createElement('div');
    asRead.style.cssText = 'font-size:13px;opacity:0.85;min-height:15px';
    asRead.textContent = '--';
    asC.wrap.appendChild(asBtn); asC.wrap.appendChild(asRead);
    add(asC.wrap);

    // === Row 6: Pitch quality controls (EXPERIMENTAL, default OFF) =======
    // Each is independent so a problem can be isolated to one switch. If audio
    // ever goes silent after enabling one, turn it back off.
    var hqC = cell('Pitch HQ (beta)', 'EXPERIMENTAL, default OFF. Runs pitch detection in full precision (fp32) even in fast/half mode. May steady pitch — but on some GPUs it can cause silence; turn back off if so.');
    var hqBtn = makeToggle(false);
    hqBtn.onclick = function () { hqBtn.setOn(!hqBtn._on); post('f0Fp32', hqBtn._on ? 1 : 0); };
    hqC.wrap.appendChild(hqBtn); add(hqC.wrap);

    var smC = cell('Pitch smooth (beta)', 'EXPERIMENTAL, default OFF. Removes single-frame pitch spikes / octave cracks while keeping natural intonation.');
    var smBtn = makeToggle(false);
    smBtn.onclick = function () { smBtn.setOn(!smBtn._on); post('f0Smoothing', smBtn._on ? 1 : 0); };
    smC.wrap.appendChild(smBtn); add(smC.wrap);

    var hbC = cell('HQ buffers (beta)', 'EXPERIMENTAL, default OFF. Keeps the internal audio buffers in full precision for a more accurate mic gate and quieter-detail capture.');
    var hbBtn = makeToggle(false);
    hbBtn.onclick = function () { hbBtn.setOn(!hbBtn._on); post('hqBuffers', hbBtn._on ? 1 : 0); };
    hbC.wrap.appendChild(hbBtn); add(hbC.wrap);

    var thSc = sliderCell('Voice gate', 'How sure the detector must be that a sound is your voice (RMVPE). Higher = rejects more noise on noisy mics; lower = catches softer voicing. 0.05 = stock.', 0.01, 0.30, 0.01, 0.05,
      function (v) { return Number(v).toFixed(2); }, 'f0Threshold');

    document.body.appendChild(panel);

    // --- Collapse / expand ---
    var collapsed = false;
    function setCollapsed(c) {
      collapsed = c;
      caret.textContent = c ? '▲' : '▼';
      grid.style.display = c ? 'none' : 'grid';
    }
    header.addEventListener('click', function () { setCollapsed(!collapsed); });

    // --- Initialise from current settings ---
    fetch('/info').then(function (r) { return r.json(); }).then(function (info) {
      if (!info) return;
      if (typeof info.autoPitch !== 'undefined') apBtn.setOn(Number(info.autoPitch) === 1);
      if (typeof info.autoSmooth !== 'undefined') asBtn.setOn(Number(info.autoSmooth) === 1);
      if (typeof info.autoPitchResponse !== 'undefined') { respSc.slider.value = info.autoPitchResponse; respSc.show(); }
      if (typeof info.autoPitchMin !== 'undefined') lowInp.value = Math.round(info.autoPitchMin);
      if (typeof info.autoPitchMax !== 'undefined') highInp.value = Math.round(info.autoPitchMax);
      if (typeof info.maxPitch !== 'undefined') { capSc.slider.value = info.maxPitch; capSc.show(); }
      if (typeof info.protect !== 'undefined') { protSc.slider.value = String(50 - Math.round(Number(info.protect) * 100)); protSc.show(); }
      if (typeof info.silentThreshold !== 'undefined') { sensSc.slider.value = info.silentThreshold; sensSc.show(); }
      if (typeof info.silenceReleaseMs !== 'undefined') { tailSc.slider.value = info.silenceReleaseMs; tailSc.show(); }
      if (typeof info.deEss !== 'undefined') { dzSc.slider.value = info.deEss; dzSc.show(); }
      if (typeof info.outputComp !== 'undefined') { lvSc.slider.value = info.outputComp; lvSc.show(); }
      if (typeof info.formantShift !== 'undefined') { fmSc.slider.value = info.formantShift; fmSc.show(); }
      if (typeof info.f0Fp32 !== 'undefined') hqBtn.setOn(Number(info.f0Fp32) === 1);
      if (typeof info.f0Smoothing !== 'undefined') smBtn.setOn(Number(info.f0Smoothing) === 1);
      if (typeof info.hqBuffers !== 'undefined') hbBtn.setOn(Number(info.hqBuffers) === 1);
      if (typeof info.f0Threshold !== 'undefined') { thSc.slider.value = info.f0Threshold; thSc.show(); }
    }).catch(function () {});
    fetch('/calibrate_status').then(function (r) { return r.json(); }).then(calLabel).catch(function () {});

    // --- Live readouts (only while expanded) ---
    setInterval(function () {
      if (collapsed) return;
      fetch('/auto_pitch').then(function (r) { return r.json(); }).then(function (s) {
        if (!s || !s.available) { apRead.textContent = '--'; return; }
        if (!s.enabled) { apRead.textContent = 'off (' + s.baseTran + ')'; return; }
        if (!s.baselineReady) { apRead.textContent = 'learning…'; return; }
        apRead.textContent = 'pitch ' + s.effectiveTran;
      }).catch(function () {});
      fetch('/auto_smooth').then(function (r) { return r.json(); }).then(function (s) {
        if (!s || !s.available || !s.enabled) { asRead.textContent = s && s.available ? 'off' : '--'; return; }
        var pct = Math.round((s.load || 0) * 100);
        asRead.textContent = 'PC2 load ' + pct + '%';
        asRead.style.color = (s.load || 0) > 0.85 ? '#ffd27a' : '#fff';
      }).catch(function () {});
    }, 800);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
