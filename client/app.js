/* ─── Config ─────────────────────────────────────────────────────── */
const WS_URL     = `ws://${location.host}/ws`;
const STT_URL    = `${location.protocol}//${location.host}/transcribe`;
const WAKE_WORDS = ['jarvis','jarvi','harvis','harvi','jarbis','yarvis','yarbis','yarbiss','jarviz','harvey'];
const ACTIVE_MS  = 8000;

/* ─── DOM ────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const orb          = $('orb');
const orbLabel     = $('orb-label');
const statusEl     = $('status');
const transcriptEl = $('transcript');
const responseEllet ws          = null;
let wsDelay     = 1000;
let recognition = null;
let isActive    = false;
let isSpeaking  = false;   // TTS is playing — block new activations
let activeTimer = null;
let analyser    = null;
let micStream   = null;   // shared mic stream
let recorder    = null;   // MediaRecorder for Whisper
let recChunks   = [];
let micSource   = localStorage.getItem('jarvis_mic_source') || 'auto';

window.saveMicSource = function () {
  const select = document.getElementById('mic-source-select');
  if (select) {
    micSource = select.value;
    localStorage.setItem('jarvis_mic_source', micSource);
    addLog('Micrófono configurado: ' + micSource, 'reply');
  }
};

function initMicSourceUI() {
  const select = document.getElementById('mic-source-select');
  if (select) {
    select.value = micSource;
  }
}

function shouldRecordOnPC() {
  if (micSource === 'pc') return true;
  if (micSource === 'tablet') return false;
  // 'auto': pc on desktop, tablet on mobile
  return !/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
}

/* ─── Bridge Android ─────────────────────────────────────────────── */
window.onNativeResult = function (text, isFinal) {
  if (recognition) { try { recognition.abort(); } catch (_) {} recognition = null; }
  handleTranscript(text, Boolean(isFinal));
};

/* ══════════════════════════════════════════════════════════════════
   WEBSOCKET
   ══════════════════════════════════════════════════════════════════ */
function connectWS() {
  ws = new WebSocket(WS_URL);
  ws.onopen  = () => { connDot.className = 'conn-dot on'; wsDelay = 1000; setStatus('En espera...'); initMicSourceUI(); };
  ws.onmessage = ({ data }) => {
    if (data === '__tablet_mic__') {
      startRecording();
      activeTimer = setTimeout(() => stopRecording(), ACTIVE_MS);
      return;
    }
    let reply = data;
    try {
      const parsed = JSON.parse(data);
      if (parsed.reply !== undefined) {
        reply = parsed.reply;
        if (parsed.shape && window._setShape) window._setShape(parsed.shape);
      }
    } catch (_) {}
    showResponse(reply);
    addLog('← ' + reply, reply.toLowerCase().startsWith('error') ? 'error' : 'reply');
  };
  ws.onclose = () => {
    connDot.className = 'conn-dot off';
    setStatus('Reconectando...');
    setTimeout(connectWS, wsDelay);
    wsDelay = Math.min(wsDelay * 2, 30000);
  };
  ws.onerror = () => ws.close();
}

/* ══════════════════════════════════════════════════════════════════
   STT — Whisper (servidor) + Web Speech (wake word)
   ══════════════════════════════════════════════════════════════════ */
function initSpeech() {
  if (window.ANDROID_NATIVE) { setStatus('En espera...'); return; }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { setStatus('❌ STT no disponible'); return; }

  recognition = new SR();
  recognition.lang            = 'es-ES';
  recognition.continuous      = true;
  recognition.interimResults  = true;
  recognition.maxAlternatives = 1;

  recognition.onaudiostart = () => { if (!isActive) setStatus('🎙 Escuchando... di "jarvis"'); };

  recognition.onresult = (event) => {
    const last = event.results[event.results.length - 1];
    const text = last[0].transcript.trim();
    const lower = text.toLowerCase();

    // Wake word detection — blocked while speaking to avoid self-activation
    if (!isActive && !isSpeaking && WAKE_WORDS.some(w => lower.includes(w))) {
      activate();
      return;
    }

    // If active: show interim + stop/dispatch on final
    if (isActive) {
      transcriptEl.textContent = '🎤 ' + text;
      if (last.isFinal) {
        if (typeof MediaRecorder !== 'undefined' && !shouldRecordOnPC()) {
          stopRecording();  // let Whisper handle it
        } else if (typeof MediaRecorder === 'undefined' && !shouldRecordOnPC()) {
          // Fallback: Dispatch Web Speech API result directly
          let cleanText = text;
          WAKE_WORDS.forEach(w => {
            if (cleanText.toLowerCase().startsWith(w)) {
              cleanText = cleanText.substring(w.length).trim();
            }
          });
          if (cleanText) {
            dispatch(cleanText);
          } else {
            deactivate();
          }
        }
      }
    }
  };

  recognition.onend   = () => { setTimeout(() => { try { recognition.start(); } catch(_){} }, 300); };
  recognition.onerror = ({ error }) => {
    const d = error === 'network' ? 3000 : 500;
    setTimeout(() => { try { recognition.start(); } catch(_){} }, d);
  };

  recognition.start();
}

/* ─── MediaRecorder (Whisper) ────────────────────────────────────── */
function startRecording() {
  if (!micStream) return;
  if (typeof MediaRecorder === 'undefined') return;
  recChunks = [];
  let mimeType = 'audio/webm';
  try {
    mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';
  } catch (e) {}
  try {
    recorder = new MediaRecorder(micStream, { mimeType });
    recorder.ondataavailable = e => { if (e.data.size > 0) recChunks.push(e.data); };
    recorder.onstop = sendToWhisper;
    recorder.start(250);  // collect chunks every 250ms
  } catch (e) {
    addLog('MediaRecorder error: ' + e.message, 'error');
  }
}

function stopRecording() {
  if (recorder && recorder.state === 'recording') {
    try {
      recorder.stop();
    } catch (e) {}
  }
}

async function sendToWhisper() {
  if (recChunks.length === 0) { deactivate(); return; }

  setStatus('Transcribiendo...');
  const blob = new Blob(recChunks, { type: 'audio/webm' });
  const form = new FormData();
  form.append('audio', blob, 'cmd.webm');

  try {
    const res  = await fetch(STT_URL, { method: 'POST', body: form });
    const data = await res.json();
    const text = (data.text || '').trim();

    if (text) {
      transcriptEl.textContent = '🎤 ' + text;
      addLog('→ ' + text, 'cmd');
      dispatch(text);
    } else {
      setStatus('No entendí — di "jarvis [comando]"');
      deactivate();
    }
  } catch (e) {
    addLog('Error Whisper: ' + e.message, 'error');
    deactivate();
  }
}

/* ── Lógica de activación ────────────────────────────────────────── */
function handleTranscript(text, isFinal) {
  const lower = text.toLowerCase();
  if (!isActive && WAKE_WORDS.some(w => lower.includes(w))) activate();
  if (isActive && isFinal) {
    if (typeof MediaRecorder !== 'undefined' && !shouldRecordOnPC()) {
      stopRecording();
    } else if (typeof MediaRecorder === 'undefined' && !shouldRecordOnPC()) {
      let cleanText = text;
      WAKE_WORDS.forEach(w => {
        if (cleanText.toLowerCase().startsWith(w)) {
          cleanText = cleanText.substring(w.length).trim();
        }
      });
      if (cleanText) dispatch(cleanText);
      else deactivate();
    }
  }
}

function activate() {
  if (isSpeaking) return;  // never interrupt speaking
  isActive = true;
  clearTimeout(activeTimer);
  setOrbState('active');
  orbLabel.textContent = '●';
  setStatus('Escuchando comando...');
  document.getElementById('mic-btn')?.classList.add('recording');

  // Tell server to record from PC mic if configured
  if (shouldRecordOnPC() && ws && ws.readyState === WebSocket.OPEN) {
    ws.send('__activate__');
    // Safety timeout in case server doesn't respond
    activeTimer = setTimeout(() => deactivate(), ACTIVE_MS + 3000);
  } else {
    // Fallback: use tablet mic
    startRecording();
    activeTimer = setTimeout(() => {
      if (typeof MediaRecorder !== 'undefined') {
        stopRecording();
      } else {
        deactivate();
      }
    }, ACTIVE_MS);
  }
}

function deactivate() {
  isActive = false;
  isSpeaking = false;
  clearTimeout(activeTimer);
  setOrbState('');
  orbLabel.textContent = 'JARVIS';
  setStatus('En espera...');
  document.getElementById('mic-btn')?.classList.remove('recording');
}

function dispatch(text) {��──────── */
function handleTranscript(text, isFinal) {
  const lower = text.toLowerCase();
  if (!isActive && WAKE_WORDS.some(w => lower.includes(w))) activate();
  if (isActive && isFinal) stopRecording();
}

function activate() {
  if (isSpeaking) return;  // never interrupt speaking
  isActive = true;
  clearTimeout(activeTimer);
  setOrbState('active');
  orbLabel.textContent = '●';
  setStatus('Escuchando comando...');
  document.getElementById('mic-btn')?.classList.add('recording');

  // Tell server to record from PC mic (better quality)
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send('__activate__');
    // Safety timeout in case server doesn't respond
    activeTimer = setTimeout(() => deactivate(), ACTIVE_MS + 3000);
  } else {
    // Fallback: use tablet mic
    startRecording();
    activeTimer = setTimeout(() => stopRecording(), ACTIVE_MS);
  }
}

function deactivate() {
  isActive = false;
  isSpeaking = false;
  clearTimeout(activeTimer);
  setOrbState('');
  orbLabel.textContent = 'JARVIS';
  setStatus('En espera...');
  document.getElementById('mic-btn')?.classList.remove('recording');
}

function dispatch(text) {
  clearTimeout(activeTimer);
  isActive = false;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(text);
    setOrbState('processing');
    orbLabel.textContent = '...';
    setStatus('Procesando...');
  } else {
    deactivate();
  }
}

/* ── Typewriter effect ───────────────────────────────────────── */
function typewrite(el, text, done) {
  el.classList.add('typing');
  el.textContent = '';
  let i = 0;
  const spd = Math.max(18, Math.min(55, 1800 / Math.max(text.length, 1)));
  (function step() {
    if (i < text.length) {
      el.textContent += text[i++];
      setTimeout(step, spd);
    } else {
      el.classList.remove('typing');
      if (done) done();
    }
  })();
}

function showResponse(text) {
  isSpeaking = true;
  setOrbState('speaking');
  orbLabel.textContent = 'JARVIS';
  statusEl.className = 'status speaking-status';
  setStatus('Respondiendo...');
  typewrite(responseEl, text, () => {
    statusEl.className = 'status';
    // Keep speaking state long enough for TTS to finish (estimate)
    const ttsMs = Math.max(2000, text.split(' ').length * 420);
    setTimeout(deactivate, ttsMs);
  });
}

/* ─── Helpers UI ─────────────────────────────────────────────────── */
function setOrbState(state) {
  orb.className = state ? `orb ${state}` : 'orb';
  if (window._setParticleIntensity) {
    if      (state === 'active')     window._setParticleIntensity(0.75);
    else if (state === 'processing') window._setParticleIntensity(0.45);
    else if (state === 'speaking')   window._setParticleIntensity(1.0);
    else                             window._setParticleIntensity(0.05);
  }
}
function setStatus(text) { statusEl.textContent = text; }

function addLog(text, type = 'cmd') {
  const el = Object.assign(document.createElement('span'), {
    className: `log-entry log-${type}`,
    textContent: `› ${text}`,
  });
  logEl.prepend(el);
  while (logEl.children.length > 6) logEl.lastChild.remove();

  // push to panel history
  const ts = new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  cmdHistory.unshift({ text, type, ts });
  if (cmdHistory.length > 120) cmdHistory.pop();
}

/* ══════════════════════════════════════════════════════════════════
   AUDIO VISUALIZER
══════════════════════════════════════════════════════════════════ */
async function initVisualizer() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 128;
    audioCtx.createMediaStreamSource(micStream).connect(analyser);
    window._audioAnalyser = analyser;
  } catch (_) {
    // No mic — sphere runs in ambient mode
  }
}

/* ── Prueba manual ───────────────────────────────────────────────── */
function testCommand() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const text = 'jarvis qué hora es';
  ws.send(text);
  addLog('→ ' + text + ' [manual]', 'cmd');
  setOrbState('processing');
  orbLabel.textContent = '...';
  setStatus('Procesando...');
}

/* ── Orb / mic button / text input handlers ──────────────────── */
function handleOrbClick() {
  if (isSpeaking) return;
  if (isActive) {
    if (recorder && recorder.state === 'recording') stopRecording();
    deactivate();
  } else {
    activate();
  }
}

function handleMicBtn() { handleOrbClick(); }


/* ══════════════════════════════════════════════════════════════════
   JARVIS NEURAL MORPHING v2 — AI Consciousness + Shape Library
   Backup esfera en: visual_sphere.js
   Estados: IDLE · THINKING · LISTENING · SPEAKING · MORPHING
   Formas: galaxy · brain · dna · wave · ring · star · tree
══════════════════════════════════════════════════════════════════ */
(function () {
  const pc  = document.getElementById('particles');
  const ctx = pc.getContext('2d');

  /* ── Config ─────────────────────────────────────────────────── */
  const N_NODES = 92;
  const N_DUST  = 72;
  const FOCAL   = 920;

  /* ── State ──────────────────────────────────────────────────── */
  let W, H, CX, CY, SR, activeSR;
  let nodes   = [];
  let dust    = [];
  let pulses  = [];
  let sparks  = [];
  let rotX    = 0.32, rotY = 0;
  let t       = 0, breatheT = 0;
  let energy  = 0.05, target = 0.05, prevEnergy = 0.05;
  let morphTarget = 0, morphResetTimer = null;

  window._setParticleIntensity = v => { target = Math.max(0, Math.min(1, v)); };

  /* ═══════════════════════════════════════════════════════════════
     SHAPE LIBRARY — coords normalizadas a [-1, 1], escaladas por SR
  ════════════════════════════════════════════════════════════════ */

  function genGalaxy(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const arm = i % 3;
      const t2  = Math.pow(Math.random(), 0.72);
      const ang = (arm / 3) * Math.PI * 2 + t2 * Math.PI * 3.6;
      const r   = 0.06 + t2 * 0.94;
      const sp  = 0.13 * (1 - t2 * 0.55);
      pts.push([
        r * Math.cos(ang) + (Math.random() - 0.5) * sp,
        (Math.random() - 0.5) * 0.08,
        r * Math.sin(ang) + (Math.random() - 0.5) * sp,
      ]);
    }
    return pts;
  }

  function genBrain(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const side = i < n / 2 ? -0.52 : 0.52;
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(1 - 2 * Math.random());
      const fold = Math.sin(th * 5 + ph * 4) * 0.09;
      const r = 0.36 + Math.random() * 0.26 + fold;
      pts.push([
        side + r * Math.sin(ph) * Math.cos(th) * 0.68,
        r * Math.sin(ph) * Math.sin(th) * 0.80,
        r * Math.cos(ph) * 0.72,
      ]);
    }
    return pts;
  }

  function genDNA(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const t2  = (i / n) * 2 - 1;
      const ang = t2 * Math.PI * 6;
      const s   = i % 2 === 0 ? 0 : Math.PI;
      pts.push([Math.cos(ang + s) * 0.52, t2, Math.sin(ang + s) * 0.52]);
    }
    return pts;
  }

  function genWave(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const u = (Math.random() - 0.5) * 2;
      const v = (Math.random() - 0.5) * 2;
      pts.push([u * 0.92, Math.sin(u * Math.PI * 2.5) * Math.cos(v * Math.PI * 1.5) * 0.52, v * 0.92]);
    }
    return pts;
  }

  function genRing(n) {
    const pts = [], R = 0.65, r = 0.22;
    for (let i = 0; i < n; i++) {
      const th = Math.random() * Math.PI * 2;
      const ph = Math.random() * Math.PI * 2;
      pts.push([
        (R + r * Math.cos(ph)) * Math.cos(th),
        r * Math.sin(ph),
        (R + r * Math.cos(ph)) * Math.sin(th),
      ]);
    }
    return pts;
  }

  function genStar(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const th    = Math.random() * Math.PI * 2;
      const ph    = Math.acos(1 - 2 * Math.random());
      const spike = Math.pow(Math.abs(Math.sin(th * 4)), 1.8);
      const r     = 0.18 + spike * 0.82;
      pts.push([
        r * Math.sin(ph) * Math.cos(th),
        r * Math.sin(ph) * Math.sin(th) * 0.35,
        r * Math.cos(ph),
      ]);
    }
    return pts;
  }

  function genTree(n) {
    const pts = [], tn = Math.floor(n * 0.18);
    for (let i = 0; i < tn; i++) {
      const t2 = i / tn;
      pts.push([(Math.random() - 0.5) * 0.08, -1 + t2 * 1.1, (Math.random() - 0.5) * 0.08]);
    }
    for (let i = tn; i < n; i++) {
      const t2 = Math.random();
      const th = Math.random() * Math.PI * 2;
      const r  = Math.random() * (0.15 + t2 * 0.85) * (1 - t2 * 0.4);
      pts.push([r * Math.cos(th), -0.15 + t2 * 1.15, r * Math.sin(th)]);
    }
    return pts;
  }

  function genSphere(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(1 - 2 * Math.random());
      const r  = 0.5 + Math.random() * 0.5;
      pts.push([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), r * Math.cos(ph)]);
    }
    return pts;
  }

  const SHAPES = {
    galaxy: genGalaxy, brain: genBrain, dna: genDNA,
    wave: genWave, ring: genRing, star: genStar,
    tree: genTree, sphere: genSphere,
  };

  /* ── Shape morph API (llamada desde WebSocket) ───────────────── */
  window._setShape = (name) => {
    const gen = SHAPES[name] || genSphere;
    const pts = gen(nodes.length);
    nodes.forEach((n, i) => {
      const p = pts[i] || [0, 0, 0];
      n.tx = p[0] * SR * 0.88;
      n.ty = p[1] * SR * 0.88;
      n.tz = p[2] * SR * 0.88;
    });
    morphTarget = 1;
    clearTimeout(morphResetTimer);
    // Vuelve a esfera después de 10s
    morphResetTimer = setTimeout(() => { morphTarget = 0; }, 10000);
  };

  /* ── Resize ─────────────────────────────────────────────────── */
  function resize() {
    W  = pc.width  = window.innerWidth;
    H  = pc.height = window.innerHeight;
    CX = W / 2;
    CY = H * 0.46;
    SR = Math.min(W, H) * 0.36;
    dust = Array.from({ length: N_DUST }, makeDust);
  }

  /* ── Ambient dust (scattered across whole canvas) ───────────── */
  function makeDust() {
    return {
      x    : Math.random() * (W || 600),
      y    : Math.random() * (H || 900),
      vx   : (Math.random() - 0.5) * 0.16,
      vy   : (Math.random() - 0.5) * 0.16,
      r    : 0.3 + Math.random() * 0.9,
      alpha: 0.035 + Math.random() * 0.10,
    };
  }

  /* ── Node factory ───────────────────────────────────────────── */
  function makeNode() {
    const theta = Math.random() * Math.PI * 2;
    const phi   = Math.acos(1 - 2 * Math.random());
    const rFrac = Math.random() < 0.62
      ? 0.68 + Math.random() * 0.32
      : 0.16 + Math.random() * 0.52;
    return {
      theta, phi, rFrac,
      dTheta : (Math.random() - 0.5) * 0.00044,
      dPhi   : (Math.random() - 0.5) * 0.00025,
      jitter : (Math.random() - 0.5) * 0.00010,
      size   : 1.2 + Math.random() * 2.6,
      bright : 0.38 + Math.random() * 0.62,
      trail  : [],
      morph  : 0,    // interpolación actual 0→1
      tx: 0, ty: 0, tz: 0,  // posición target de la forma
      x: 0, y: 0, z: 0,
    };
  }

  /* ── Update node — órbita + morph LERP staggered ────────────── */
  function updateNode(n) {
    const spd   = 1 + energy * 3.4;
    const chaos = energy * 0.00085;
    n.theta += (n.dTheta + n.jitter * Math.sin(t * 0.028)) * spd
               + (Math.random() - 0.5) * chaos;
    n.phi    = Math.max(0.03, Math.min(Math.PI - 0.03,
               n.phi + (n.dPhi + n.jitter * Math.cos(t * 0.021)) * spd
               + (Math.random() - 0.5) * chaos * 0.5));

    const r  = n.rFrac * activeSR * (1 + Math.sin(breatheT + n.theta * 0.6) * 0.018);
    const sp = Math.sin(n.phi);
    // Posición esfera
    const sX = r * sp * Math.cos(n.theta);
    const sY = r * sp * Math.sin(n.theta);
    const sZ = r * Math.cos(n.phi);

    // Cada nodo llega a su destino a diferente velocidad → efecto orgánico
    n.morph += (morphTarget - n.morph) * (0.010 + Math.random() * 0.010);

    // Blend: 0 = esfera pura, 1 = forma target
    n.x = sX + (n.tx - sX) * n.morph;
    n.y = sY + (n.ty - sY) * n.morph;
    n.z = sZ + (n.tz - sZ) * n.morph;
  }

  /* ── Perspective projection with rotated axes ───────────────── */
  function project(n) {
    const cy = Math.cos(rotY), sy = Math.sin(rotY);
    const x1 = n.x * cy + n.z * sy;
    const z1 = -n.x * sy + n.z * cy;
    const cx_ = Math.cos(rotX), sx = Math.sin(rotX);
    const y2 = n.y * cx_ - z1 * sx;
    const z2 = n.y * sx  + z1 * cx_;
    const sc = FOCAL / Math.max(0.1, FOCAL + z2);
    return { sx: CX + x1 * sc, sy: CY + y2 * sc, z: z2, sc };
  }

  /* ── Pulse ring from center ─────────────────────────────────── */
  function emitPulse(e) {
    pulses.push({ r: 6, o: 0.55 + e * 0.40, spd: 2.2 + e * 2.8 });
  }

  /* ── Electric spark (white hot flash) ──────────────────────── */
  function addSpark(proj) {
    if (sparks.length >= 14) return;
    const a = Math.floor(Math.random() * proj.length);
    const b = Math.floor(Math.random() * proj.length);
    if (a !== b) sparks.push({ a, b, life: 1.0 });
  }

  /* ═══════════════════════════════════════════════════════════════
     MAIN LOOP
  ════════════════════════════════════════════════════════════════ */
  function loop() {
    requestAnimationFrame(loop);
    t++;
    breatheT += 0.017;

    /* Smooth energy toward target */
    energy += (target - energy) * (energy < target ? 0.09 : 0.04);

    /* Emit pulse on state-change spike */
    if (energy - prevEnergy > 0.022 && pulses.length < 10) emitPulse(energy);
    prevEnergy = energy;

    /* Global rotation — much faster when active */
    const rotSpd = 0.00048 + energy * 0.0035;
    rotY += rotSpd;
    rotX += rotSpd * 0.30;

    /* Sphere breathing: radius pulses like a heartbeat */
    const breatheAmp = 0.028 + energy * 0.14;
    activeSR = SR * (1 + Math.sin(breatheT * 1.35) * breatheAmp);

    ctx.clearRect(0, 0, W, H);

    /* ── LAYER 1 · Background blue aura ──────────────────────── */
    const aura = ctx.createRadialGradient(CX, CY, 0, CX, CY, activeSR * 1.55);
    aura.addColorStop(0,    `rgba(0,16,52,${0.22 + energy * 0.22})`);
    aura.addColorStop(0.45, `rgba(0,6,22,${0.12 + energy * 0.10})`);
    aura.addColorStop(1,    'rgba(0,0,0,0)');
    ctx.fillStyle = aura;
    ctx.fillRect(0, 0, W, H);

    /* ── LAYER 2 · Ambient neural dust (full canvas) ─────────── */
    ctx.save();
    ctx.shadowColor = '#00d4ff';
    ctx.shadowBlur  = 5;
    for (const d of dust) {
      d.x += d.vx * (1 + energy * 0.9);
      d.y += d.vy * (1 + energy * 0.9);
      if (d.x < -8) d.x = W + 8;
      else if (d.x > W + 8) d.x = -8;
      if (d.y < -8) d.y = H + 8;
      else if (d.y > H + 8) d.y = -8;
      ctx.fillStyle = `rgba(0,210,255,${Math.min(0.22, d.alpha + energy * 0.14)})`;
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r * (1 + energy * 0.5), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    /* ── LAYER 3 · Pulse rings ───────────────────────────────── */
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i];
      p.r  += p.spd;
      p.o  -= 0.009;
      if (p.o <= 0) { pulses.splice(i, 1); continue; }
      ctx.save();
      ctx.shadowColor = '#00b0ff';
      ctx.shadowBlur  = 18;
      ctx.globalAlpha = p.o * 0.6;
      ctx.strokeStyle = 'rgba(0,192,255,0.95)';
      ctx.lineWidth   = 1.4;
      ctx.beginPath(); ctx.arc(CX, CY, p.r, 0, Math.PI * 2); ctx.stroke();
      ctx.strokeStyle = 'rgba(0,80,200,0.35)';
      ctx.lineWidth   = 4;
      ctx.beginPath(); ctx.arc(CX, CY, Math.max(1, p.r - 5), 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    }

    /* ── IRON MAN SCANNING ARC ───────────────────────────────── */
    {
      const sa = (t * 0.013) % (Math.PI * 2);
      const sR = activeSR * 1.42;
      ctx.save();
      ctx.shadowColor = '#00d4ff';

      // Tick marks on outer targeting ring
      ctx.globalAlpha = 0.06 + energy * 0.05;
      ctx.strokeStyle = '#00c8ff';
      for (let d = 0; d < 360; d += 15) {
        const ang = (d * Math.PI / 180) + rotY * 0.05;
        const tl  = d % 90 === 0 ? 11 : d % 45 === 0 ? 7 : 4;
        ctx.lineWidth = d % 90 === 0 ? 1.4 : 0.7;
        ctx.beginPath();
        ctx.moveTo(CX + Math.cos(ang) * (sR - tl), CY + Math.sin(ang) * (sR - tl));
        ctx.lineTo(CX + Math.cos(ang) * sR,        CY + Math.sin(ang) * sR);
        ctx.stroke();
      }

      // Static dashed outer ring
      ctx.globalAlpha = 0.055 + energy * 0.035;
      ctx.strokeStyle = '#00c8ff';
      ctx.lineWidth   = 0.8;
      ctx.setLineDash([3, 10]);
      ctx.beginPath(); ctx.arc(CX, CY, sR, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);

      // Crosshair lines
      ctx.globalAlpha = 0.05 + energy * 0.04;
      ctx.strokeStyle = '#00d4ff';
      ctx.lineWidth   = 0.7;
      const ch = sR * 0.82;
      ctx.beginPath(); ctx.moveTo(CX - ch, CY); ctx.lineTo(CX + ch, CY); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(CX, CY - ch); ctx.lineTo(CX, CY + ch); ctx.stroke();

      // Sweeping radar arc (fading trail)
      ctx.shadowBlur = 14;
      for (let i = 20; i >= 0; i--) {
        const a     = sa - (i / 20) * 1.4;
        const alpha = ((20 - i) / 20) * (0.055 + energy * 0.14);
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = '#00d4ff';
        ctx.lineWidth   = 0.5 + ((20 - i) / 20) * 2;
        ctx.shadowBlur  = i > 15 ? 16 : 5;
        ctx.beginPath(); ctx.arc(CX, CY, sR, a - 0.07, a); ctx.stroke();
      }

      // Bright tip
      ctx.globalAlpha = 0.92;
      ctx.strokeStyle = 'rgba(210,248,255,0.95)';
      ctx.lineWidth   = 2.5;
      ctx.shadowBlur  = 22;
      ctx.beginPath(); ctx.arc(CX, CY, sR, sa - 0.06, sa); ctx.stroke();
      ctx.restore();
    }

    /* ── Update + Project all nodes ──────────────────────────── */
    nodes.forEach(updateNode);
    const proj = nodes.map((n, i) => {
      const p = project(n);
      // Store screen trail for motion blur
      n.trail.unshift({ sx: p.sx, sy: p.sy, sc: p.sc });
      if (n.trail.length > 7) n.trail.pop();
      return { ...p, i };
    });
    proj.sort((a, b) => b.z - a.z); // back-to-front

    /* ── LAYER 4 · Motion trails (visible above thinking state) ─ */
    if (energy > 0.25) {
      const trailStrength = (energy - 0.25) / 0.75;
      for (const p of proj) {
        const n = nodes[p.i];
        for (let ti = 1; ti < n.trail.length; ti++) {
          const tp = n.trail[ti];
          const ta = (1 - ti / n.trail.length) * 0.32 * trailStrength;
          if (ta < 0.01) continue;
          ctx.fillStyle = `rgba(0,195,255,${ta.toFixed(3)})`;
          ctx.beginPath();
          ctx.arc(tp.sx, tp.sy, n.size * tp.sc * 0.65, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    /* ── LAYER 5 · Neural connections (3D distance) ──────────── */
    const connMax      = SR * (0.37 + energy * 0.20);
    const connAlphaMax = 0.18 + energy * 0.62;
    ctx.save();
    ctx.lineWidth = 0.6;
    for (let a = 0; a < proj.length; a++) {
      for (let b = a + 1; b < proj.length; b++) {
        const ni = proj[a].i, nj = proj[b].i;
        const dx = nodes[ni].x - nodes[nj].x;
        const dy = nodes[ni].y - nodes[nj].y;
        const dz = nodes[ni].z - nodes[nj].z;
        const d  = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (d >= connMax) continue;
        const norm  = 1 - d / connMax;
        const avgSc = (proj[a].sc + proj[b].sc) * 0.5;
        const alpha = norm * norm * avgSc * connAlphaMax;
        ctx.strokeStyle = `rgba(0,204,255,${alpha.toFixed(3)})`;
        ctx.beginPath();
        ctx.moveTo(proj[a].sx, proj[a].sy);
        ctx.lineTo(proj[b].sx, proj[b].sy);
        ctx.stroke();
      }
    }
    ctx.restore();

    /* ── LAYER 6 · Electric sparks (listening + speaking states) */
    if (energy > 0.48 && Math.random() < energy * 0.09) addSpark(proj);
    for (let i = sparks.length - 1; i >= 0; i--) {
      const sp = sparks[i];
      sp.life -= 0.055 + energy * 0.045;
      if (sp.life <= 0 || !proj[sp.a] || !proj[sp.b]) { sparks.splice(i, 1); continue; }
      const pa = proj[sp.a], pb = proj[sp.b];
      ctx.save();
      ctx.globalAlpha = sp.life;
      ctx.shadowColor = '#ffffff';
      ctx.shadowBlur  = 12;
      ctx.strokeStyle = `rgba(210,245,255,${sp.life * 0.85})`;
      ctx.lineWidth   = 0.85;
      ctx.beginPath(); ctx.moveTo(pa.sx, pa.sy); ctx.lineTo(pb.sx, pb.sy); ctx.stroke();
      ctx.restore();
    }

    /* ── LAYER 6.5 · Audio neural arcs (replaces bar visualizer) ── */
    if (window._audioAnalyser && energy > 0.06) {
      const freqData = new Uint8Array(window._audioAnalyser.frequencyBinCount);
      window._audioAnalyser.getByteFrequencyData(freqData);
      const N   = freqData.length;
      const avg = freqData.reduce((s, v) => s + v, 0) / (N * 255);
      if (avg > 0.015) {
        ctx.save();
        ctx.shadowColor = '#00d4ff';
        ctx.shadowBlur  = 10;
        for (let i = 0; i < N; i++) {
          const amp   = freqData[i] / 255;
          if (amp < 0.06) continue;
          const angle = (i / N) * Math.PI * 2 + rotY * 0.25;
          const r0    = activeSR * (1.04 + Math.sin(breatheT + i) * 0.012);
          const r1    = r0 + amp * activeSR * 0.30;
          const g     = Math.floor(160 + amp * 95);
          ctx.strokeStyle = `rgba(0,${g},255,${(amp * 0.65).toFixed(2)})`;
          ctx.lineWidth   = 0.7 + amp * 1.6;
          ctx.beginPath();
          ctx.moveTo(CX + Math.cos(angle) * r0, CY + Math.sin(angle) * r0);
          ctx.lineTo(CX + Math.cos(angle) * r1, CY + Math.sin(angle) * r1);
          ctx.stroke();
        }
        ctx.restore();
      }
    }

    /* ── LAYER 7 · Nodes (front-to-back) ────────────────────── */
    for (let k = proj.length - 1; k >= 0; k--) {
      const p = proj[k];
      const n = nodes[p.i];
      const alpha = Math.min(0.93, (0.28 + n.bright * 0.47 + energy * 0.36) * Math.max(0.33, p.sc));
      const sz    = n.size * p.sc * (1 + energy * 0.88);
      const glow  = (5 + energy * 17) * p.sc;

      ctx.save();
      ctx.shadowColor = '#00d4ff';
      ctx.shadowBlur  = glow;

      // Outer soft glow disc
      const gr = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, sz * 2.8);
      gr.addColorStop(0, `rgba(0,210,255,${alpha})`);
      gr.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gr;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, sz * 2.8, 0, Math.PI * 2); ctx.fill();

      // Crisp bright core dot
      ctx.shadowBlur = 3;
      ctx.fillStyle  = `rgba(198,248,255,${alpha * 0.90})`;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, sz, 0, Math.PI * 2); ctx.fill();

      ctx.restore();
    }
  }

  /* ── Init ───────────────────────────────────────────────────── */
  function init() {
    resize();
    activeSR = SR;
    nodes  = Array.from({ length: N_NODES }, makeNode);
    window.addEventListener('resize', resize);
    // Boot pulse
    setTimeout(() => emitPulse(0.4), 300);
    setTimeout(() => emitPulse(0.2), 800);
    loop();
  }

  init();
})();

/* ══════════════════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════════════════ */
connectWS();
initVisualizer().then(() => initSpeech());


/* ══════════════════════════════════════════════════════════════════
   CONTROL PANEL
══════════════════════════════════════════════════════════════════ */
const cmdHistory = [];
let   panelOpen  = false;
let   panelTab   = 'home';
let   refreshTimer = null;

function togglePanel() { panelOpen ? closePanel() : openPanel(); }

function openPanel() {
  panelOpen = true;
  document.getElementById('ctrl-panel').classList.add('open');
  document.getElementById('panel-overlay').classList.add('open');
  loadTab(panelTab);
  refreshTimer = setInterval(() => loadTab(panelTab), 10000);
}

function closePanel() {
  panelOpen = false;
  document.getElementById('ctrl-panel').classList.remove('open');
  document.getElementById('panel-overlay').classList.remove('open');
  clearInterval(refreshTimer);
}

function switchTab(tab) {
  panelTab = tab;
  document.querySelectorAll('.cptab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab)
  );
  document.querySelectorAll('.cptab-pane').forEach(p =>
    p.classList.toggle('active', p.id === `cptab-${tab}`)
  );
  loadTab(tab);
}

function loadTab(tab) {
  if (tab === 'home')    loadDevices();
  if (tab === 'battery') loadBattery();
  if (tab === 'system')  loadSystem();
  if (tab === 'hist')    renderHistory();
}

/* ─── Smart Home ─────────────────────────────────────────────── */
const DEV_ICONS = { bombillo: '💡', aire: '❄️', control: '🎛️', enchufe: '🔌' };
function devIcon(name) {
  const n = name.toLowerCase();
  for (const [k, v] of Object.entries(DEV_ICONS)) if (n.includes(k)) return v;
  return '🔧';
}

async function loadDevices() {
  const list = document.getElementById('devices-list');
  list.innerHTML = '<p class="cp-loading">◌ Conectando con Tuya...</p>';
  try {
    const res  = await fetch('/api/devices');
    const data = await res.json();
    if (!data.devices?.length) {
      list.innerHTML = '<p class="cp-loading">Sin dispositivos vinculados</p>';
      return;
    }
    list.innerHTML = data.devices.map(d => `
      <div class="dev-card">
        <div class="dev-info">
          <span class="dev-icon">${devIcon(d.name)}</span>
          <div>
            <div class="dev-name">${d.name.toUpperCase()}</div>
            <div class="dev-status ${d.online ? 'online' : 'offline'}">${d.online ? '● En línea' : '○ Sin conexión'}</div>
          </div>
        </div>
        <button class="toggle-btn ${d.switch === true ? 'on' : 'off'}"
                id="tog-${d.id}"
                onclick="toggleDevice('${d.id}', ${!d.switch})">
          ${d.switch === null ? '?' : d.switch ? 'ON' : 'OFF'}
        </button>
      </div>`).join('');
  } catch {
    list.innerHTML = '<p class="cp-loading cp-err">❌ Error de conexión</p>';
  }
}

async function toggleDevice(id, turnOn) {
  const btn = document.getElementById(`tog-${id}`);
  if (btn) { btn.textContent = '···'; btn.className = 'toggle-btn'; }
  try {
    const res  = await fetch(`/api/devices/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ on: turnOn }),
    });
    const data = await res.json();
    if (btn) {
      btn.textContent = data.ok ? (turnOn ? 'ON' : 'OFF') : 'ERR';
      btn.className   = `toggle-btn ${data.ok ? (turnOn ? 'on' : 'off') : 'err'}`;
    }
    addLog(`Dispositivo ${turnOn ? 'encendido' : 'apagado'}`, 'reply');
  } catch {
    if (btn) { btn.textContent = 'ERR'; btn.className = 'toggle-btn err'; }
  }
}

/* ─── Battery ────────────────────────────────────────────────── */
const BAT_CIRC = 2 * Math.PI * 55;

async function loadBattery() {
  try {
    const res = await fetch('/api/battery');
    const d   = await res.json();
    const arc = document.getElementById('bat-arc');

    if (!d.available) {
      document.getElementById('bat-pct').textContent = 'N/A';
      document.getElementById('bat-st').textContent  = 'Sin batería detectada';
      arc.style.strokeDasharray  = BAT_CIRC;
      arc.style.strokeDashoffset = BAT_CIRC;
      return;
    }

    const pct = d.percent;
    arc.style.strokeDasharray  = BAT_CIRC;
    arc.style.strokeDashoffset = BAT_CIRC * (1 - pct / 100);
    arc.style.stroke = pct > 60 ? '#00d4ff' : pct > 25 ? '#ffaa00' : '#ff3355';

    document.getElementById('bat-pct').textContent  = `${pct}%`;
    document.getElementById('bat-st').textContent   = d.plugged ? '⚡ Cargando' : 'En batería';
    document.getElementById('bat-auto').textContent = d.auto !== null ? (d.auto ? 'ACTIVO' : 'INACTIVO') : 'N/A';
    document.getElementById('bat-plug').textContent = d.plugged ? 'Conectado' : 'Desconectado';
    document.getElementById('bat-lo').textContent   = `${d.low}%`;
    document.getElementById('bat-hi').textContent   = `${d.high}%`;
  } catch {
    document.getElementById('bat-pct').textContent = 'Error';
  }
}

/* ─── System ─────────────────────────────────────────────────── */
async function loadSystem() {
  try {
    const res = await fetch('/api/system');
    const d   = await res.json();
    setBar('cpu',  d.cpu,  `${d.cpu}%`);
    setBar('ram',  d.ram,  `${d.ram_used} / ${d.ram_total} GB`);
    setBar('disk', d.disk, `${d.disk}%`);
  } catch { /* silent */ }
}

function setBar(name, pct, label) {
  const fill = document.getElementById(`${name}-bar`);
  document.getElementById(`${name}-v`).textContent = label;
  fill.style.width      = `${Math.min(pct, 100)}%`;
  fill.style.background = pct > 85 ? '#ff3355' : pct > 65 ? '#ffaa00' : 'var(--cyan)';
  fill.style.boxShadow  = pct > 85
    ? '0 0 6px rgba(255,51,85,0.5)'
    : pct > 65 ? '0 0 6px rgba(255,170,0,0.4)' : '0 0 6px rgba(0,212,255,0.4)';
}

/* ─── Quick Commands ─────────────────────────────────────────── */
function sendQuick(cmd) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(cmd);
  addLog('→ ' + cmd, 'cmd');
  setOrbState('processing');
  orbLabel.textContent = '...';
  setStatus('Procesando...');
  closePanel();
}

/* ─── History ────────────────────────────────────────────────── */
function renderHistory() {
  const list = document.getElementById('hist-list');
  if (!cmdHistory.length) {
    list.innerHTML = '<p class="cp-loading">Sin actividad en esta sesión</p>';
    return;
  }
  list.innerHTML = cmdHistory.map(e => `
    <div class="hist-entry hist-${e.type}">
      <span class="hist-ts">${e.ts}</span>
      <span class="hist-text">${e.text.replace(/</g, '&lt;')}</span>
    </div>`).join('');
}

function clearHistory() {
  cmdHistory.length = 0;
  renderHistory();
}
