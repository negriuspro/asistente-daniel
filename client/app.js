/* ─── Config ─────────────────────────────────────────────────────── */
const WS_URL     = `ws://${location.host}/ws`;
const STT_URL    = `${location.protocol}//${location.host}/transcribe`;
// Wake words: "daniel" + common mishearings
const WAKE_WORDS = ['daniel','danial','danie','danielle','danil','daniyel','dani'];
const ACTIVE_MS  = 8000;

/* ─── DOM ────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const orb          = $('orb');
const orbLabel     = $('orb-label');
const statusEl     = $('status');
const transcriptEl = $('transcript');
const responseEl   = $('response');
const logEl        = $('log');
const connDot      = $('conn-dot');

let ws          = null;
let wsDelay     = 1000;
let recognition = null;
let isActive    = false;
let isSpeaking  = false;
let activeTimer = null;
let analyser    = null;
let micStream   = null;
let recorder    = null;
let recChunks   = [];
let micSource   = localStorage.getItem('daniel_mic_source') || 'auto';

window.saveMicSource = function () {
  const select = document.getElementById('mic-source-select');
  if (select) {
    micSource = select.value;
    localStorage.setItem('daniel_mic_source', micSource);
    addLog('Micrófono: ' + micSource, 'reply');
  }
};

function initMicSourceUI() {
  const select = document.getElementById('mic-source-select');
  if (select) select.value = micSource;
}

function shouldRecordOnPC() {
  if (micSource === 'pc') return true;
  if (micSource === 'tablet') return false;
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
  ws.onopen = () => {
    connDot.className = 'conn-dot on';
    wsDelay = 1000;
    setStatus('Di "Daniel" para activar');
    initMicSourceUI();
  };
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
        if (parsed.open_url) {
          try { window.open(parsed.open_url, '_blank', 'noopener,noreferrer'); } catch (_) {}
        }
      }
    } catch (_) {}
    if (reply) showResponse(reply);
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
   STT — Web Speech API (siempre escuchando) + Whisper para comando
   ══════════════════════════════════════════════════════════════════ */
function initSpeech() {
  if (window.ANDROID_NATIVE) { setStatus('Di "Daniel" para activar'); return; }

  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { setStatus('❌ STT no disponible en este navegador'); return; }

  recognition = new SR();
  recognition.lang            = 'es-ES';
  recognition.continuous      = true;
  recognition.interimResults  = true;
  recognition.maxAlternatives = 1;

  recognition.onaudiostart = () => {
    if (!isActive) setStatus('Di "Daniel" para activar');
  };

  recognition.onresult = (event) => {
    const last  = event.results[event.results.length - 1];
    const text  = last[0].transcript.trim();
    const lower = text.toLowerCase();

    // Always-listening: detect wake word in the speech stream
    if (!isActive && !isSpeaking && WAKE_WORDS.some(w => lower.includes(w))) {
      activate();
      return;
    }

    // When active: update transcript and dispatch on final result
    if (isActive) {
      transcriptEl.textContent = '🎤 ' + text;
      if (last.isFinal) {
        if (shouldRecordOnPC()) {
          // PC path handled via __activate__ / server mic
        } else if (typeof MediaRecorder !== 'undefined') {
          stopRecording();
        } else {
          // Fallback: use Web Speech text directly
          const cmd = stripWake(text);
          if (cmd) dispatch(cmd);
          else deactivate();
        }
      }
    }
  };

  recognition.onend = () => {
    setTimeout(() => { try { recognition.start(); } catch (_) {} }, 300);
  };
  recognition.onerror = ({ error }) => {
    const d = error === 'network' ? 3000 : 500;
    setTimeout(() => { try { recognition.start(); } catch (_) {} }, d);
  };

  recognition.start();
  setStatus('Di "Daniel" para activar');
}

function stripWake(text) {
  let out = text;
  for (const w of WAKE_WORDS) {
    const re = new RegExp(`(?i)^\\s*${w}\\s*[,.]?\\s*`, 'i');
    out = out.replace(re, '');
  }
  return out.trim();
}

/* ─── MediaRecorder (Whisper) ────────────────────────────────────── */
function startRecording() {
  if (!micStream || typeof MediaRecorder === 'undefined') return;
  recChunks = [];
  let mimeType = 'audio/webm';
  try {
    if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus'))
      mimeType = 'audio/webm;codecs=opus';
  } catch (_) {}
  try {
    recorder = new MediaRecorder(micStream, { mimeType });
    recorder.ondataavailable = e => { if (e.data.size > 0) recChunks.push(e.data); };
    recorder.onstop = sendToWhisper;
    recorder.start(250);
  } catch (e) {
    addLog('MediaRecorder: ' + e.message, 'error');
  }
}

function stopRecording() {
  if (recorder && recorder.state === 'recording') {
    try { recorder.stop(); } catch (_) {}
  }
}

async function sendToWhisper() {
  if (!recChunks.length) { deactivate(); return; }
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
      dispatch(stripWake(text) || text);
    } else {
      setStatus('No entendí — di "Daniel [comando]"');
      deactivate();
    }
  } catch (e) {
    addLog('Error Whisper: ' + e.message, 'error');
    deactivate();
  }
}

/* ── Activate / Deactivate / Dispatch ────────────────────────────── */
function activate() {
  if (isSpeaking) return;
  isActive = true;
  clearTimeout(activeTimer);
  setOrbState('active');
  orbLabel.textContent = '●';
  setStatus('Escuchando...');
  document.getElementById('mic-btn')?.classList.add('recording');

  if (shouldRecordOnPC() && ws && ws.readyState === WebSocket.OPEN) {
    ws.send('__activate__');
    activeTimer = setTimeout(() => deactivate(), ACTIVE_MS + 3000);
  } else {
    startRecording();
    activeTimer = setTimeout(() => stopRecording(), ACTIVE_MS);
  }
}

function deactivate() {
  isActive  = false;
  isSpeaking = false;
  clearTimeout(activeTimer);
  setOrbState('');
  orbLabel.textContent = 'DANIEL';
  setStatus('Di "Daniel" para activar');
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

function handleTranscript(text, isFinal) {
  const lower = text.toLowerCase();
  if (!isActive && !isSpeaking && WAKE_WORDS.some(w => lower.includes(w))) activate();
  if (isActive && isFinal) {
    if (typeof MediaRecorder !== 'undefined' && !shouldRecordOnPC()) stopRecording();
    else if (!shouldRecordOnPC()) {
      const cmd = stripWake(text);
      if (cmd) dispatch(cmd);
      else deactivate();
    }
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
  orbLabel.textContent = 'DANIEL';
  statusEl.className = 'status speaking-status';
  setStatus('Respondiendo...');
  typewrite(responseEl, text, () => {
    statusEl.className = 'status';
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
  const ts = new Date().toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  cmdHistory.unshift({ text, type, ts });
  if (cmdHistory.length > 120) cmdHistory.pop();
}

/* ── Orb / mic button handlers ───────────────────────────────────── */
function handleOrbClick() {
  if (!micStream) {
    // First click: request mic permission and start always-listening
    requestMicAndListen();
    return;
  }
  if (isSpeaking) return;
  if (isActive) {
    stopRecording();
    deactivate();
  } else {
    activate();
  }
}
function handleMicBtn() { handleOrbClick(); }

function testCommand() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const text = 'qué hora es';
  ws.send(text);
  addLog('→ ' + text + ' [test]', 'cmd');
  setOrbState('processing');
  orbLabel.textContent = '...';
  setStatus('Procesando...');
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
    return true;
  } catch (e) {
    return false;
  }
}

async function requestMicAndListen() {
  setStatus('Activando micrófono...');
  const ok = await initVisualizer();
  if (ok) {
    initSpeech();
    setStatus('Di "Daniel" para activar');
    // Hide the mic button hint since wake-word is active
    const btn = document.getElementById('mic-btn');
    if (btn) btn.title = 'Di "Daniel" o pulsa para activar';
  } else {
    setStatus('🎤 Permite el micrófono en el navegador');
    // Show permission hint on the mic button
    const btn = document.getElementById('mic-btn');
    if (btn) { btn.style.animation = 'pulse-warn 1s ease-in-out infinite'; btn.title = 'Clic para activar micrófono'; }
    addLog('Micrófono bloqueado — clic en el orbe para activar', 'error');
  }
}

/* ══════════════════════════════════════════════════════════════════
   DANIEL NEURAL MORPHING v2 — AI Consciousness + Shape Library
   Estados: IDLE · THINKING · LISTENING · SPEAKING · MORPHING
   Formas: galaxy · brain · dna · wave · ring · star · tree
══════════════════════════════════════════════════════════════════ */
(function () {
  const pc  = document.getElementById('particles');
  const ctx = pc.getContext('2d');

  const N_NODES = 92;
  const N_DUST  = 72;
  const FOCAL   = 920;

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

  function genGalaxy(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const arm = i % 3;
      const t2  = Math.pow(Math.random(), 0.72);
      const ang = (arm / 3) * Math.PI * 2 + t2 * Math.PI * 3.6;
      const r   = 0.06 + t2 * 0.94;
      const sp  = 0.13 * (1 - t2 * 0.55);
      pts.push([r * Math.cos(ang) + (Math.random() - 0.5) * sp, (Math.random() - 0.5) * 0.08, r * Math.sin(ang) + (Math.random() - 0.5) * sp]);
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
      pts.push([side + r * Math.sin(ph) * Math.cos(th) * 0.68, r * Math.sin(ph) * Math.sin(th) * 0.80, r * Math.cos(ph) * 0.72]);
    }
    return pts;
  }
  function genDNA(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const t2 = (i / n) * 2 - 1;
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
      pts.push([(R + r * Math.cos(ph)) * Math.cos(th), r * Math.sin(ph), (R + r * Math.cos(ph)) * Math.sin(th)]);
    }
    return pts;
  }
  function genStar(n) {
    const pts = [];
    for (let i = 0; i < n; i++) {
      const th = Math.random() * Math.PI * 2;
      const ph = Math.acos(1 - 2 * Math.random());
      const spike = Math.pow(Math.abs(Math.sin(th * 4)), 1.8);
      const r = 0.18 + spike * 0.82;
      pts.push([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th) * 0.35, r * Math.cos(ph)]);
    }
    return pts;
  }
  function genTree(n) {
    const pts = [], tn = Math.floor(n * 0.18);
    for (let i = 0; i < tn; i++) {
      pts.push([(Math.random() - 0.5) * 0.08, -1 + (i / tn) * 1.1, (Math.random() - 0.5) * 0.08]);
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

  const SHAPES = { galaxy: genGalaxy, brain: genBrain, dna: genDNA, wave: genWave, ring: genRing, star: genStar, tree: genTree, sphere: genSphere };

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
    morphResetTimer = setTimeout(() => { morphTarget = 0; }, 10000);
  };

  function resize() {
    W  = pc.width  = window.innerWidth;
    H  = pc.height = window.innerHeight;
    CX = W / 2;
    CY = H * 0.46;
    SR = Math.min(W, H) * 0.36;
    dust = Array.from({ length: N_DUST }, makeDust);
  }
  function makeDust() {
    return { x: Math.random() * (W || 600), y: Math.random() * (H || 900), vx: (Math.random() - 0.5) * 0.16, vy: (Math.random() - 0.5) * 0.16, r: 0.3 + Math.random() * 0.9, alpha: 0.035 + Math.random() * 0.10 };
  }
  function makeNode() {
    const theta = Math.random() * Math.PI * 2;
    const phi   = Math.acos(1 - 2 * Math.random());
    const rFrac = Math.random() < 0.62 ? 0.68 + Math.random() * 0.32 : 0.16 + Math.random() * 0.52;
    return { theta, phi, rFrac, dTheta: (Math.random() - 0.5) * 0.00044, dPhi: (Math.random() - 0.5) * 0.00025, jitter: (Math.random() - 0.5) * 0.00010, size: 1.2 + Math.random() * 2.6, bright: 0.38 + Math.random() * 0.62, trail: [], morph: 0, tx: 0, ty: 0, tz: 0, x: 0, y: 0, z: 0 };
  }
  function updateNode(n) {
    const spd   = 1 + energy * 3.4;
    const chaos = energy * 0.00085;
    n.theta += (n.dTheta + n.jitter * Math.sin(t * 0.028)) * spd + (Math.random() - 0.5) * chaos;
    n.phi    = Math.max(0.03, Math.min(Math.PI - 0.03, n.phi + (n.dPhi + n.jitter * Math.cos(t * 0.021)) * spd + (Math.random() - 0.5) * chaos * 0.5));
    const r  = n.rFrac * activeSR * (1 + Math.sin(breatheT + n.theta * 0.6) * 0.018);
    const sp = Math.sin(n.phi);
    const sX = r * sp * Math.cos(n.theta);
    const sY = r * sp * Math.sin(n.theta);
    const sZ = r * Math.cos(n.phi);
    n.morph += (morphTarget - n.morph) * (0.010 + Math.random() * 0.010);
    n.x = sX + (n.tx - sX) * n.morph;
    n.y = sY + (n.ty - sY) * n.morph;
    n.z = sZ + (n.tz - sZ) * n.morph;
  }
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
  function emitPulse(e) { pulses.push({ r: 6, o: 0.55 + e * 0.40, spd: 2.2 + e * 2.8 }); }
  function addSpark(proj) {
    if (sparks.length >= 14) return;
    const a = Math.floor(Math.random() * proj.length);
    const b = Math.floor(Math.random() * proj.length);
    if (a !== b) sparks.push({ a, b, life: 1.0 });
  }

  function loop() {
    requestAnimationFrame(loop);
    t++;
    breatheT += 0.017;
    energy += (target - energy) * (energy < target ? 0.09 : 0.04);
    if (energy - prevEnergy > 0.022 && pulses.length < 10) emitPulse(energy);
    prevEnergy = energy;
    const rotSpd = 0.00048 + energy * 0.0035;
    rotY += rotSpd;
    rotX += rotSpd * 0.30;
    const breatheAmp = 0.028 + energy * 0.14;
    activeSR = SR * (1 + Math.sin(breatheT * 1.35) * breatheAmp);
    ctx.clearRect(0, 0, W, H);

    // Background aura
    const aura = ctx.createRadialGradient(CX, CY, 0, CX, CY, activeSR * 1.55);
    aura.addColorStop(0,    `rgba(0,16,52,${0.22 + energy * 0.22})`);
    aura.addColorStop(0.45, `rgba(0,6,22,${0.12 + energy * 0.10})`);
    aura.addColorStop(1,    'rgba(0,0,0,0)');
    ctx.fillStyle = aura;
    ctx.fillRect(0, 0, W, H);

    // Ambient dust
    ctx.save();
    ctx.shadowColor = '#00d4ff';
    ctx.shadowBlur  = 5;
    for (const d of dust) {
      d.x += d.vx * (1 + energy * 0.9);
      d.y += d.vy * (1 + energy * 0.9);
      if (d.x < -8) d.x = W + 8; else if (d.x > W + 8) d.x = -8;
      if (d.y < -8) d.y = H + 8; else if (d.y > H + 8) d.y = -8;
      ctx.fillStyle = `rgba(0,210,255,${Math.min(0.22, d.alpha + energy * 0.14)})`;
      ctx.beginPath();
      ctx.arc(d.x, d.y, d.r * (1 + energy * 0.5), 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();

    // Pulse rings
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i];
      p.r += p.spd; p.o -= 0.009;
      if (p.o <= 0) { pulses.splice(i, 1); continue; }
      ctx.save();
      ctx.shadowColor = '#00b0ff'; ctx.shadowBlur = 18;
      ctx.globalAlpha = p.o * 0.6;
      ctx.strokeStyle = 'rgba(0,192,255,0.95)'; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.arc(CX, CY, p.r, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    }

    // Scanning arc
    {
      const sa = (t * 0.013) % (Math.PI * 2);
      const sR = activeSR * 1.42;
      ctx.save();
      ctx.shadowColor = '#00d4ff';
      ctx.globalAlpha = 0.06 + energy * 0.05;
      ctx.strokeStyle = '#00c8ff';
      for (let d = 0; d < 360; d += 15) {
        const ang = (d * Math.PI / 180) + rotY * 0.05;
        const tl  = d % 90 === 0 ? 11 : d % 45 === 0 ? 7 : 4;
        ctx.lineWidth = d % 90 === 0 ? 1.4 : 0.7;
        ctx.beginPath();
        ctx.moveTo(CX + Math.cos(ang) * (sR - tl), CY + Math.sin(ang) * (sR - tl));
        ctx.lineTo(CX + Math.cos(ang) * sR, CY + Math.sin(ang) * sR);
        ctx.stroke();
      }
      ctx.globalAlpha = 0.055 + energy * 0.035;
      ctx.strokeStyle = '#00c8ff'; ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 10]);
      ctx.beginPath(); ctx.arc(CX, CY, sR, 0, Math.PI * 2); ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 0.05 + energy * 0.04;
      ctx.strokeStyle = '#00d4ff'; ctx.lineWidth = 0.7;
      const ch = sR * 0.82;
      ctx.beginPath(); ctx.moveTo(CX - ch, CY); ctx.lineTo(CX + ch, CY); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(CX, CY - ch); ctx.lineTo(CX, CY + ch); ctx.stroke();
      ctx.shadowBlur = 14;
      for (let i = 20; i >= 0; i--) {
        const a = sa - (i / 20) * 1.4;
        const alpha = ((20 - i) / 20) * (0.055 + energy * 0.14);
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = '#00d4ff'; ctx.lineWidth = 0.5 + ((20 - i) / 20) * 2;
        ctx.shadowBlur = i > 15 ? 16 : 5;
        ctx.beginPath(); ctx.arc(CX, CY, sR, a - 0.07, a); ctx.stroke();
      }
      ctx.globalAlpha = 0.92;
      ctx.strokeStyle = 'rgba(210,248,255,0.95)'; ctx.lineWidth = 2.5; ctx.shadowBlur = 22;
      ctx.beginPath(); ctx.arc(CX, CY, sR, sa - 0.06, sa); ctx.stroke();
      ctx.restore();
    }

    // Update + project nodes
    nodes.forEach(updateNode);
    const proj = nodes.map((n, i) => {
      const p = project(n);
      n.trail.unshift({ sx: p.sx, sy: p.sy, sc: p.sc });
      if (n.trail.length > 7) n.trail.pop();
      return { ...p, i };
    });
    proj.sort((a, b) => b.z - a.z);

    // Motion trails
    if (energy > 0.25) {
      const ts = (energy - 0.25) / 0.75;
      for (const p of proj) {
        const n = nodes[p.i];
        for (let ti = 1; ti < n.trail.length; ti++) {
          const tp = n.trail[ti];
          const ta = (1 - ti / n.trail.length) * 0.32 * ts;
          if (ta < 0.01) continue;
          ctx.fillStyle = `rgba(0,195,255,${ta.toFixed(3)})`;
          ctx.beginPath(); ctx.arc(tp.sx, tp.sy, n.size * tp.sc * 0.65, 0, Math.PI * 2); ctx.fill();
        }
      }
    }

    // Neural connections
    const connMax = SR * (0.37 + energy * 0.20);
    const connAlphaMax = 0.18 + energy * 0.62;
    ctx.save(); ctx.lineWidth = 0.6;
    for (let a = 0; a < proj.length; a++) {
      for (let b = a + 1; b < proj.length; b++) {
        const ni = proj[a].i, nj = proj[b].i;
        const dx = nodes[ni].x - nodes[nj].x;
        const dy = nodes[ni].y - nodes[nj].y;
        const dz = nodes[ni].z - nodes[nj].z;
        const d  = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (d >= connMax) continue;
        const norm = 1 - d / connMax;
        const alpha = norm * norm * ((proj[a].sc + proj[b].sc) * 0.5) * connAlphaMax;
        ctx.strokeStyle = `rgba(0,204,255,${alpha.toFixed(3)})`;
        ctx.beginPath(); ctx.moveTo(proj[a].sx, proj[a].sy); ctx.lineTo(proj[b].sx, proj[b].sy); ctx.stroke();
      }
    }
    ctx.restore();

    // Electric sparks
    if (energy > 0.48 && Math.random() < energy * 0.09) addSpark(proj);
    for (let i = sparks.length - 1; i >= 0; i--) {
      const sp = sparks[i];
      sp.life -= 0.055 + energy * 0.045;
      if (sp.life <= 0 || !proj[sp.a] || !proj[sp.b]) { sparks.splice(i, 1); continue; }
      const pa = proj[sp.a], pb = proj[sp.b];
      ctx.save(); ctx.globalAlpha = sp.life;
      ctx.shadowColor = '#ffffff'; ctx.shadowBlur = 12;
      ctx.strokeStyle = `rgba(210,245,255,${sp.life * 0.85})`; ctx.lineWidth = 0.85;
      ctx.beginPath(); ctx.moveTo(pa.sx, pa.sy); ctx.lineTo(pb.sx, pb.sy); ctx.stroke();
      ctx.restore();
    }

    // Audio arcs
    if (window._audioAnalyser && energy > 0.06) {
      const freqData = new Uint8Array(window._audioAnalyser.frequencyBinCount);
      window._audioAnalyser.getByteFrequencyData(freqData);
      const N = freqData.length;
      const avg = freqData.reduce((s, v) => s + v, 0) / (N * 255);
      if (avg > 0.015) {
        ctx.save(); ctx.shadowColor = '#00d4ff'; ctx.shadowBlur = 10;
        for (let i = 0; i < N; i++) {
          const amp = freqData[i] / 255;
          if (amp < 0.06) continue;
          const angle = (i / N) * Math.PI * 2 + rotY * 0.25;
          const r0 = activeSR * (1.04 + Math.sin(breatheT + i) * 0.012);
          const r1 = r0 + amp * activeSR * 0.30;
          const g  = Math.floor(160 + amp * 95);
          ctx.strokeStyle = `rgba(0,${g},255,${(amp * 0.65).toFixed(2)})`; ctx.lineWidth = 0.7 + amp * 1.6;
          ctx.beginPath(); ctx.moveTo(CX + Math.cos(angle) * r0, CY + Math.sin(angle) * r0); ctx.lineTo(CX + Math.cos(angle) * r1, CY + Math.sin(angle) * r1); ctx.stroke();
        }
        ctx.restore();
      }
    }

    // Nodes
    for (let k = proj.length - 1; k >= 0; k--) {
      const p = proj[k];
      const n = nodes[p.i];
      const alpha = Math.min(0.93, (0.28 + n.bright * 0.47 + energy * 0.36) * Math.max(0.33, p.sc));
      const sz    = n.size * p.sc * (1 + energy * 0.88);
      const glow  = (5 + energy * 17) * p.sc;
      ctx.save(); ctx.shadowColor = '#00d4ff'; ctx.shadowBlur = glow;
      const gr = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, sz * 2.8);
      gr.addColorStop(0, `rgba(0,210,255,${alpha})`);
      gr.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gr;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, sz * 2.8, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 3;
      ctx.fillStyle  = `rgba(198,248,255,${alpha * 0.90})`;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, sz, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    }
  }

  function init() {
    resize();
    activeSR = SR;
    nodes = Array.from({ length: N_NODES }, makeNode);
    window.addEventListener('resize', resize);
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
// Try to get mic permission automatically — works if browser already allowed it.
// If denied, user taps orb/mic button to request permission.
(async () => {
  const ok = await initVisualizer();
  if (ok) {
    initSpeech();
  } else {
    setStatus('🎤 Toca el orbe para activar el micrófono');
  }
})();

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
  document.querySelectorAll('.cptab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.cptab-pane').forEach(p => p.classList.toggle('active', p.id === `cptab-${tab}`));
  loadTab(tab);
}

function loadTab(tab) {
  if (tab === 'home')    loadDevices();
  if (tab === 'battery') loadBattery();
  if (tab === 'system')  loadSystem();
  if (tab === 'hist')    renderHistory();
  if (tab === 'monitor') loadMonitor();
  if (tab === 'smart')   smartInit();
}

const DEV_ICONS = { bombillo: '💡', aire: '❄️', control: '🎛️', enchufe: '🔌' };
function devIcon(name) {
  const n = name.toLowerCase();
  for (const [k, v] of Object.entries(DEV_ICONS)) if (n.includes(k)) return v;
  return '🔧';
}

async function loadDevices() {
  const list = document.getElementById('devices-list');
  list.innerHTML = '<p class="cp-loading">◌ Conectando con Home Assistant...</p>';
  try {
    const res  = await fetch('/api/devices');
    const data = await res.json();
    if (!data.devices?.length) { list.innerHTML = '<p class="cp-loading">Sin dispositivos vinculados</p>'; return; }
    list.innerHTML = data.devices.map(d => `
      <div class="dev-card">
        <div class="dev-info"><span class="dev-icon">${devIcon(d.name)}</span><div><div class="dev-name">${d.name.toUpperCase()}</div><div class="dev-status ${d.online ? 'online' : 'offline'}">${d.online ? '● En línea' : '○ Sin conexión'}</div></div></div>
        <button class="toggle-btn ${d.switch === true ? 'on' : 'off'}" id="tog-${d.id}" onclick="toggleDevice('${d.id}', ${!d.switch})">${d.switch === null ? '?' : d.switch ? 'ON' : 'OFF'}</button>
      </div>`).join('');
  } catch { list.innerHTML = '<p class="cp-loading cp-err">❌ Error de conexión</p>'; }
}

async function toggleDevice(id, turnOn) {
  const btn = document.getElementById(`tog-${id}`);
  if (btn) { btn.textContent = '···'; btn.className = 'toggle-btn'; }
  try {
    const res  = await fetch(`/api/devices/${id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: turnOn }) });
    const data = await res.json();
    if (btn) { btn.textContent = data.ok ? (turnOn ? 'ON' : 'OFF') : 'ERR'; btn.className = `toggle-btn ${data.ok ? (turnOn ? 'on' : 'off') : 'err'}`; }
    addLog(`Dispositivo ${turnOn ? 'encendido' : 'apagado'}`, 'reply');
  } catch { if (btn) { btn.textContent = 'ERR'; btn.className = 'toggle-btn err'; } }
}

const BAT_CIRC = 2 * Math.PI * 55;
async function loadBattery() {
  try {
    const res = await fetch('/api/battery');
    const d   = await res.json();
    const arc = document.getElementById('bat-arc');
    if (!d.available) { document.getElementById('bat-pct').textContent = 'N/A'; arc.style.strokeDashoffset = BAT_CIRC; return; }
    const pct = d.percent;
    arc.style.strokeDasharray  = BAT_CIRC;
    arc.style.strokeDashoffset = BAT_CIRC * (1 - pct / 100);
    arc.style.stroke = pct > 60 ? '#00d4ff' : pct > 25 ? '#ffaa00' : '#ff3355';
    document.getElementById('bat-pct').textContent = `${pct}%`;
    document.getElementById('bat-st').textContent  = d.plugged ? '⚡ Cargando' : 'En batería';
    document.getElementById('bat-auto').textContent = d.auto !== null ? (d.auto ? 'ACTIVO' : 'INACTIVO') : 'N/A';
    document.getElementById('bat-plug').textContent = d.plugged ? 'Conectado' : 'Desconectado';
    document.getElementById('bat-lo').textContent   = `${d.low}%`;
    document.getElementById('bat-hi').textContent   = `${d.high}%`;
  } catch { document.getElementById('bat-pct').textContent = 'Error'; }
}

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
  fill.style.boxShadow  = pct > 85 ? '0 0 6px rgba(255,51,85,0.5)' : pct > 65 ? '0 0 6px rgba(255,170,0,0.4)' : '0 0 6px rgba(0,212,255,0.4)';
}


/* ── System Monitor ─────────────────────────────────────── */
function _fmtUptime(secs) {
  if (!secs && secs !== 0) return '--';
  const d = Math.floor(secs / 86400);
  const h = Math.floor((secs % 86400) / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return d > 0 ? `${d}d ${h}h ${m}m` : h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function _fmtTs(iso) {
  if (!iso) return '--';
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return '--'; }
}

function _setMonBar(prefix, id, pct, label) {
  const fill = document.getElementById(`mon-${prefix}-${id}-bar`);
  const val  = document.getElementById(`mon-${prefix}-${id}-v`);
  if (!fill || !val) return;
  val.textContent  = label;
  fill.style.width = `${Math.min(pct || 0, 100)}%`;
  const color = (pct > 85) ? '#ff3355' : (pct > 65) ? '#ffaa00' : 'var(--cyan)';
  fill.style.background = color;
  fill.style.boxShadow  = (pct > 85) ? '0 0 6px rgba(255,51,85,0.5)' : (pct > 65) ? '0 0 6px rgba(255,170,0,0.4)' : '0 0 6px rgba(0,212,255,0.4)';
}

function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text ?? '--';
}

async function loadMonitor() {
  try {
    const res  = await fetch('/api/system/status');
    const data = await res.json();
    const pc   = data.main_pc  || {};
    const sv   = data.server   || {};

    // ── PC Principal ─────────────────────────────
    _setText('mon-pc-hostname', pc.hostname || 'Computadora Principal');

    const onlineBadge = document.getElementById('mon-pc-online');
    if (onlineBadge) {
      onlineBadge.textContent = pc.online ? 'ONLINE' : 'OFFLINE';
      onlineBadge.className   = `mon-badge ${pc.online ? 'mon-online' : 'mon-offline'}`;
    }

    _setMonBar('pc', 'cpu',  pc.cpu_percent,  `${pc.cpu_percent ?? '--'}%`);
    _setMonBar('pc', 'ram',  pc.ram_percent,  `${pc.ram_percent ?? '--'}%`);
    _setMonBar('pc', 'disk', pc.disk_percent, `${pc.disk_percent ?? '--'}%`);

    const bat = pc.battery_percent;
    _setMonBar('pc', 'bat', bat, bat != null ? `${bat}%` : 'N/A');

    _setText('mon-pc-plugged', pc.power_plugged != null ? (pc.power_plugged ? '⚡ Conectado' : 'Desconectado') : '--');
    _setText('mon-pc-temp',   pc.temperature   != null ? `${pc.temperature}°C` : 'N/A');
    _setText('mon-pc-uptime', _fmtUptime(pc.uptime));
    _setText('mon-pc-ts',     _fmtTs(pc.timestamp));

    // ── Servidor ──────────────────────────────────
    _setText('mon-sv-hostname', sv.hostname || 'angel-HP-Notebook');
    _setMonBar('sv', 'cpu',  sv.cpu_percent,  `${sv.cpu_percent ?? '--'}%`);
    _setMonBar('sv', 'ram',  sv.ram_percent,  `${sv.ram_percent ?? '--'}%`);
    _setMonBar('sv', 'disk', sv.disk_percent, `${sv.disk_percent ?? '--'}%`);

    _setText('mon-sv-temp',   sv.temperature   != null ? `${sv.temperature}°C` : 'N/A');
    _setText('mon-sv-docker', sv.docker_containers_running ?? '--');
    _setText('mon-sv-ip',     sv.ip_address    || '--');
    _setText('mon-sv-uptime', _fmtUptime(sv.uptime));

  } catch { /* silent — panel puede estar cerrado */ }
}

function sendQuick(cmd) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(cmd);
  addLog('→ ' + cmd, 'cmd');
  setOrbState('processing');
  orbLabel.textContent = '...';
  setStatus('Procesando...');
  closePanel();
}

function renderHistory() {
  const list = document.getElementById('hist-list');
  if (!cmdHistory.length) { list.innerHTML = '<p class="cp-loading">Sin actividad en esta sesión</p>'; return; }
  list.innerHTML = cmdHistory.map(e => `<div class="hist-entry hist-${e.type}"><span class="hist-ts">${e.ts}</span><span class="hist-text">${e.text.replace(/</g, '&lt;')}</span></div>`).join('');
}

function clearHistory() {
  cmdHistory.length = 0;
  renderHistory();
}

/* ─── Dispositivos Inteligentes ──────────────────────────────────────── */

let _smartTab = 'cameras';
let _scanPollInterval = null;

function smartInit() {
  switchSmartTab(_smartTab);
}

function switchSmartTab(tab) {
  _smartTab = tab;
  document.querySelectorAll('.stab').forEach(b => b.classList.toggle('active', b.dataset.stab === tab));
  document.querySelectorAll('.stab-pane').forEach(p => p.classList.toggle('active', p.id === `stab-${tab}`));
  if (tab === 'cameras')   smartLoadCameras();
  if (tab === 'tvs')       smartLoadTvs();
  if (tab === 'plugs')     smartLoadPlugs();
  if (tab === 'ir')        smartLoadIr();
  if (tab === 'discovery') smartLoadScanStatus();
  if (tab === 'config')    smartLoadAll();
}

/* ── Helpers ── */
const _typeIcons = { camera:'📷', tv:'📺', plug:'🔌', ir_controller:'🔴',
                     computer:'💻', phone:'📱', router:'🌐', unknown:'❓' };

function _smartFetch(url, opts = {}) {
  return fetch(url, { headers: { 'Content-Type': 'application/json' }, ...opts });
}

function _renderDeviceCard(d, actions = []) {
  const icon = _typeIcons[d.device_type] || '❓';
  const proto = (d.protocols || []).join(', ') || '—';
  const method = d.control_method || '—';
  const actBtns = actions.map(a =>
    `<button class="smart-card-btn" onclick="${a.fn}">${a.label}</button>`
  ).join('');
  return `
    <div class="smart-card" data-id="${d.id}">
      <div class="smart-card-header">
        <span class="smart-card-icon">${icon}</span>
        <span class="smart-card-name">${d.name || d.ip}</span>
        <span class="smart-card-ip">${d.ip}</span>
      </div>
      <div class="smart-card-meta">
        <span>${d.manufacturer || ''}${d.model ? ' · ' + d.model : ''}</span>
        <span class="smart-badge">${method}</span>
      </div>
      <div class="smart-card-proto">${proto}</div>
      <div class="smart-card-actions">
        ${actBtns}
        <button class="smart-card-btn smart-card-btn-del" onclick="smartDeleteDevice('${d.id}')">✕</button>
      </div>
    </div>`;
}

/* ── Cámaras ── */
async function smartLoadCameras() {
  const el = $('smart-cameras-list');
  el.innerHTML = '<p class="cp-loading">◌ Cargando...</p>';
  try {
    const r = await _smartFetch('/api/smart/cameras');
    const { cameras } = await r.json();
    if (!cameras.length) { el.innerHTML = '<p class="cp-loading">◌ Sin cámaras registradas</p>'; return; }
    el.innerHTML = cameras.map(c => _renderDeviceCard(c, [
      { label: '⚙ Probar', fn: `smartProbeCamera('${c.id}')` },
      { label: '▶ RTSP',   fn: `smartOpenRtsp('${c.id}')` },
    ])).join('');
  } catch { el.innerHTML = '<p class="cp-loading">Error cargando cámaras</p>'; }
}

async function smartDiscoverOnvif() {
  addLog('Buscando cámaras ONVIF...', 'info');
  try {
    const r = await _smartFetch('/api/smart/cameras/discover/onvif', { method: 'POST' });
    const { found } = await r.json();
    if (!found.length) { addLog('No se encontraron cámaras ONVIF', 'warn'); return; }
    for (const cam of found) {
      await _smartFetch('/api/smart/devices', {
        method: 'POST',
        body: JSON.stringify({ ip: cam.ip, device_type: 'camera', name: 'Cámara ONVIF', protocols: ['onvif'] }),
      });
    }
    addLog(`${found.length} cámara(s) ONVIF encontrada(s)`, 'ok');
    smartLoadCameras();
  } catch { addLog('Error en descubrimiento ONVIF', 'err'); }
}

async function smartProbeCamera(id) {
  addLog('Probando cámara...', 'info');
  try {
    const r = await _smartFetch(`/api/smart/cameras/${id}/probe`, { method: 'POST' });
    const data = await r.json();
    const caps = data.capabilities || {};
    addLog(`Cámara: ONVIF=${caps.onvif} RTSP=${caps.rtsp}`, caps.rtsp ? 'ok' : 'warn');
    smartLoadCameras();
  } catch { addLog('Error probando cámara', 'err'); }
}

function smartOpenRtsp(id) {
  const card = document.querySelector(`.smart-card[data-id="${id}"]`);
  addLog(`Para ver el stream RTSP usa VLC o ffplay con la URL guardada`, 'info');
}

/* ── TVs ── */
async function smartLoadTvs() {
  const el = $('smart-tvs-list');
  el.innerHTML = '<p class="cp-loading">◌ Cargando...</p>';
  try {
    const r = await _smartFetch('/api/smart/tvs');
    const { tvs } = await r.json();
    if (!tvs.length) { el.innerHTML = '<p class="cp-loading">◌ Sin TVs registrados</p>'; return; }
    el.innerHTML = tvs.map(tv => _renderDeviceCard(tv, [
      { label: '⚙ Detectar', fn: `smartDetectTv('${tv.id}')` },
      { label: '⏻ ON/OFF',   fn: `smartControlTv('${tv.id}','power_off')` },
      { label: '🔊+',        fn: `smartControlTv('${tv.id}','volume_up')` },
      { label: '🔊-',        fn: `smartControlTv('${tv.id}','volume_down')` },
    ])).join('');
  } catch { el.innerHTML = '<p class="cp-loading">Error cargando TVs</p>'; }
}

async function smartDetectTv(id) {
  addLog('Detectando TV...', 'info');
  try {
    const r = await _smartFetch(`/api/smart/tvs/${id}/detect`, { method: 'POST' });
    const data = await r.json();
    addLog(data.ok ? `TV detectado: ${data.info?.control_method}` : 'TV no responde', data.ok ? 'ok' : 'warn');
    smartLoadTvs();
  } catch { addLog('Error detectando TV', 'err'); }
}

async function smartControlTv(id, command, value = '') {
  try {
    const r = await _smartFetch(`/api/smart/tvs/${id}/control`, {
      method: 'POST',
      body: JSON.stringify({ command, value }),
    });
    const data = await r.json();
    addLog(`TV ${command}: ${data.ok ? 'OK' : data.error || 'error'}`, data.ok ? 'ok' : 'err');
  } catch { addLog('Error controlando TV', 'err'); }
}

/* ── Enchufes ── */
async function smartLoadPlugs() {
  const el = $('smart-plugs-list');
  el.innerHTML = '<p class="cp-loading">◌ Cargando...</p>';
  try {
    const r = await _smartFetch('/api/smart/plugs');
    const { plugs } = await r.json();
    if (!plugs.length) { el.innerHTML = '<p class="cp-loading">◌ Sin enchufes registrados</p>'; return; }
    el.innerHTML = plugs.map(p => _renderDeviceCard(p, [
      { label: '⚙ Detectar', fn: `smartDetectPlug('${p.id}')` },
      { label: '● ON',       fn: `smartControlPlug('${p.id}','on')` },
      { label: '○ OFF',      fn: `smartControlPlug('${p.id}','off')` },
      { label: '↻ Estado',   fn: `smartControlPlug('${p.id}','status')` },
    ])).join('');
  } catch { el.innerHTML = '<p class="cp-loading">Error cargando enchufes</p>'; }
}

async function smartDetectPlug(id) {
  addLog('Detectando enchufe...', 'info');
  try {
    const r = await _smartFetch(`/api/smart/plugs/${id}/detect`, { method: 'POST' });
    const data = await r.json();
    addLog(data.ok ? `Protocolo: ${data.info?.control_method}` : 'Enchufe no responde', data.ok ? 'ok' : 'warn');
    smartLoadPlugs();
  } catch { addLog('Error detectando enchufe', 'err'); }
}

async function smartControlPlug(id, action) {
  try {
    const r = await _smartFetch(`/api/smart/plugs/${id}/control`, {
      method: 'POST',
      body: JSON.stringify({ command: action }),
    });
    const data = await r.json();
    addLog(`Enchufe ${action}: ${data.ok ? (data.state || 'OK') : data.error || 'error'}`, data.ok ? 'ok' : 'err');
    smartLoadPlugs();
  } catch { addLog('Error controlando enchufe', 'err'); }
}

/* ── IR ── */
async function smartLoadIr() {
  const el = $('smart-ir-list');
  el.innerHTML = '<p class="cp-loading">◌ Cargando...</p>';
  try {
    const r = await _smartFetch('/api/smart/ir');
    const { controllers } = await r.json();
    if (!controllers.length) { el.innerHTML = '<p class="cp-loading">◌ Sin controladores IR</p>'; }
    else el.innerHTML = controllers.map(c => _renderDeviceCard(c, [
      { label: '⚙ Detectar', fn: `smartDetectIr('${c.id}')` },
    ])).join('');
    smartLoadIrCodes();
  } catch { el.innerHTML = '<p class="cp-loading">Error cargando IR</p>'; }
}

async function smartDetectIr(id) {
  addLog('Detectando controlador IR...', 'info');
  try {
    const r = await _smartFetch(`/api/smart/ir/${id}/detect`, { method: 'POST' });
    const data = await r.json();
    addLog(data.ok ? `IR detectado: ${data.info?.control_method}` : 'No responde', data.ok ? 'ok' : 'warn');
    smartLoadIr();
  } catch { addLog('Error detectando IR', 'err'); }
}

async function smartLoadIrCodes() {
  const el = $('smart-ir-codes');
  try {
    const r = await _smartFetch('/api/smart/ir/codes');
    const { codes } = await r.json();
    const devices = Object.keys(codes);
    if (!devices.length) { el.innerHTML = '<p class="cp-loading">◌ Sin códigos guardados</p>'; return; }
    el.innerHTML = devices.map(dev => {
      const actions = Object.keys(codes[dev]);
      return `<div class="smart-ir-group">
        <div class="smart-ir-dev">${dev}</div>
        <div class="smart-ir-actions">${actions.map(a =>
          `<span class="smart-ir-code" title="${codes[dev][a].protocol}">${a}</span>`
        ).join('')}</div>
      </div>`;
    }).join('');
  } catch { el.innerHTML = ''; }
}

/* ── Escaneo ── */
async function smartStartScan() {
  const subnet = $('smart-subnet').value.trim();
  const btn = document.querySelector('#stab-discovery .smart-btn-primary');
  btn.disabled = true;
  btn.textContent = '⏳ Escaneando...';

  $('smart-scan-progress').style.display = 'block';
  $('smart-scan-results').innerHTML = '<p class="cp-loading">◌ Escaneando red...</p>';

  try {
    await _smartFetch('/api/smart/scan/start', {
      method: 'POST',
      body: JSON.stringify({ subnet }),
    });
    _scanPollInterval = setInterval(smartPollScan, 1500);
  } catch {
    addLog('Error iniciando escaneo', 'err');
    btn.disabled = false;
    btn.textContent = '▶ Escanear';
  }
}

async function smartLoadScanStatus() {
  try {
    const r = await _smartFetch('/api/smart/scan/status');
    const data = await r.json();
    if (data.running) {
      $('smart-scan-progress').style.display = 'block';
      const pct = data.total ? Math.round(data.progress / data.total * 100) : 0;
      $('smart-progress-fill').style.width = pct + '%';
      $('smart-progress-label').textContent = `${data.progress} / ${data.total}`;
    }
    if (data.results && data.results.length) _renderScanResults(data.results);
  } catch {}
}

async function smartPollScan() {
  try {
    const r = await _smartFetch('/api/smart/scan/status');
    const data = await r.json();
    const pct = data.total ? Math.round(data.progress / data.total * 100) : 0;
    $('smart-progress-fill').style.width = pct + '%';
    $('smart-progress-label').textContent = `${data.progress} / ${data.total}`;

    if (data.results) _renderScanResults(data.results);

    if (!data.running) {
      clearInterval(_scanPollInterval);
      const btn = document.querySelector('#stab-discovery .smart-btn-primary');
      if (btn) { btn.disabled = false; btn.textContent = '▶ Escanear'; }
      addLog(`Escaneo completo: ${data.results.length} dispositivos`, 'ok');
    }
  } catch { clearInterval(_scanPollInterval); }
}

function _renderScanResults(results) {
  const el = $('smart-scan-results');
  if (!results.length) { el.innerHTML = '<p class="cp-loading">◌ No se encontraron dispositivos</p>'; return; }
  el.innerHTML = results.map(r => `
    <div class="smart-scan-row">
      <span class="smart-card-icon">${_typeIcons[r.device_type] || '❓'}</span>
      <div class="smart-scan-info">
        <span class="smart-scan-ip">${r.ip}</span>
        <span class="smart-scan-name">${r.hostname || r.manufacturer || r.device_type}</span>
        <span class="smart-scan-proto">${(r.protocols || []).join(', ') || '—'}</span>
      </div>
      <button class="smart-card-btn" onclick="smartSaveFromScan(${JSON.stringify(r).replace(/"/g, '&quot;')})">＋</button>
    </div>`).join('');
}

async function smartSaveFromScan(result) {
  try {
    await _smartFetch('/api/smart/devices', {
      method: 'POST',
      body: JSON.stringify({
        ip: result.ip, mac: result.mac, hostname: result.hostname,
        manufacturer: result.manufacturer, device_type: result.device_type,
        open_ports: result.open_ports, protocols: result.protocols,
      }),
    });
    addLog(`${result.ip} guardado como ${result.device_type}`, 'ok');
    smartLoadAll();
  } catch { addLog('Error guardando dispositivo', 'err'); }
}

/* ── Config / Todos ── */
async function smartLoadAll() {
  const el = $('smart-all-list');
  el.innerHTML = '<p class="cp-loading">◌ Cargando...</p>';
  try {
    const r = await _smartFetch('/api/smart/devices');
    const { devices } = await r.json();
    if (!devices.length) { el.innerHTML = '<p class="cp-loading">◌ Sin dispositivos registrados</p>'; return; }
    el.innerHTML = devices.map(d => _renderDeviceCard(d)).join('');
  } catch { el.innerHTML = '<p class="cp-loading">Error cargando dispositivos</p>'; }
}

async function smartDeleteDevice(id) {
  if (!confirm('¿Eliminar dispositivo?')) return;
  try {
    await _smartFetch(`/api/smart/devices/${id}`, { method: 'DELETE' });
    addLog(`Dispositivo eliminado`, 'ok');
    smartInit();
  } catch { addLog('Error eliminando dispositivo', 'err'); }
}

function smartAddDevice(type) {
  switchSmartTab('config');
  const sel = $('sf-type');
  if (sel) sel.value = type;
  $('sf-ip') && $('sf-ip').focus();
}

async function smartSaveManual() {
  const ip   = $('sf-ip')?.value.trim();
  const name = $('sf-name')?.value.trim();
  const type = $('sf-type')?.value;
  if (!ip) { addLog('Ingresa una IP', 'warn'); return; }
  try {
    await _smartFetch('/api/smart/devices', {
      method: 'POST',
      body: JSON.stringify({ ip, name, device_type: type }),
    });
    addLog(`Dispositivo ${ip} guardado`, 'ok');
    $('sf-ip').value = ''; $('sf-name').value = '';
    smartLoadAll();
  } catch { addLog('Error guardando dispositivo', 'err'); }
}

async function smartAutodetect() {
  const ip = $('sf-ip')?.value.trim();
  if (!ip) { addLog('Ingresa una IP para auto-detectar', 'warn'); return; }
  addLog(`Auto-detectando ${ip}...`, 'info');
  try {
    const r = await _smartFetch('/api/smart/autodetect', {
      method: 'POST',
      body: JSON.stringify({ ip }),
    });
    const data = await r.json();
    $('sf-type').value = data.type;
    addLog(`Detectado como: ${data.type}`, 'ok');
  } catch { addLog('Error en auto-detección', 'err'); }
}
