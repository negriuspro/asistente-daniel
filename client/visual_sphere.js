/* ══════════════════════════════════════════════════════════════════
   JARVIS NEURAL CONSCIOUSNESS v1 — BACKUP
   Para volver a esta versión: en index.html cambia
   <script src="/app.js"> por:
   <script src="/visual_sphere.js">
   (y comenta la sección NEURAL MORPHING en app.js)
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

  window._setParticleIntensity = v => { target = Math.max(0, Math.min(1, v)); };

  function resize() {
    W  = pc.width  = window.innerWidth;
    H  = pc.height = window.innerHeight;
    CX = W / 2;
    CY = H * 0.46;
    SR = Math.min(W, H) * 0.36;
    dust = Array.from({ length: N_DUST }, makeDust);
  }

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
      x: 0, y: 0, z: 0,
    };
  }

  function updateNode(n) {
    const spd   = 1 + energy * 3.4;
    const chaos = energy * 0.00085;
    n.theta += (n.dTheta + n.jitter * Math.sin(t * 0.028)) * spd + (Math.random() - 0.5) * chaos;
    n.phi    = Math.max(0.03, Math.min(Math.PI - 0.03,
               n.phi + (n.dPhi + n.jitter * Math.cos(t * 0.021)) * spd + (Math.random() - 0.5) * chaos * 0.5));
    const r  = n.rFrac * activeSR * (1 + Math.sin(breatheT + n.theta * 0.6) * 0.018);
    const sp = Math.sin(n.phi);
    n.x = r * sp * Math.cos(n.theta);
    n.y = r * sp * Math.sin(n.theta);
    n.z = r * Math.cos(n.phi);
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
    const a = Math.floor(Math.random() * proj.length), b = Math.floor(Math.random() * proj.length);
    if (a !== b) sparks.push({ a, b, life: 1.0 });
  }

  function loop() {
    requestAnimationFrame(loop);
    t++; breatheT += 0.017;
    energy += (target - energy) * (energy < target ? 0.09 : 0.04);
    if (energy - prevEnergy > 0.022 && pulses.length < 10) emitPulse(energy);
    prevEnergy = energy;
    const rotSpd = 0.00048 + energy * 0.0035;
    rotY += rotSpd; rotX += rotSpd * 0.30;
    const breatheAmp = 0.028 + energy * 0.14;
    activeSR = SR * (1 + Math.sin(breatheT * 1.35) * breatheAmp);
    ctx.clearRect(0, 0, W, H);
    const aura = ctx.createRadialGradient(CX, CY, 0, CX, CY, activeSR * 1.55);
    aura.addColorStop(0, `rgba(0,16,52,${0.22 + energy * 0.22})`);
    aura.addColorStop(0.45, `rgba(0,6,22,${0.12 + energy * 0.10})`);
    aura.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = aura; ctx.fillRect(0, 0, W, H);
    ctx.save(); ctx.shadowColor = '#00d4ff'; ctx.shadowBlur = 5;
    for (const d of dust) {
      d.x += d.vx * (1 + energy * 0.9); d.y += d.vy * (1 + energy * 0.9);
      if (d.x < -8) d.x = W + 8; else if (d.x > W + 8) d.x = -8;
      if (d.y < -8) d.y = H + 8; else if (d.y > H + 8) d.y = -8;
      ctx.fillStyle = `rgba(0,210,255,${Math.min(0.22, d.alpha + energy * 0.14)})`;
      ctx.beginPath(); ctx.arc(d.x, d.y, d.r * (1 + energy * 0.5), 0, Math.PI * 2); ctx.fill();
    }
    ctx.restore();
    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i]; p.r += p.spd; p.o -= 0.009;
      if (p.o <= 0) { pulses.splice(i, 1); continue; }
      ctx.save(); ctx.shadowColor = '#00b0ff'; ctx.shadowBlur = 18; ctx.globalAlpha = p.o * 0.6;
      ctx.strokeStyle = 'rgba(0,192,255,0.95)'; ctx.lineWidth = 1.4;
      ctx.beginPath(); ctx.arc(CX, CY, p.r, 0, Math.PI * 2); ctx.stroke();
      ctx.strokeStyle = 'rgba(0,80,200,0.35)'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(CX, CY, Math.max(1, p.r - 5), 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
    }
    nodes.forEach(updateNode);
    const proj = nodes.map((n, i) => {
      const p = project(n);
      n.trail.unshift({ sx: p.sx, sy: p.sy, sc: p.sc });
      if (n.trail.length > 7) n.trail.pop();
      return { ...p, i };
    });
    proj.sort((a, b) => b.z - a.z);
    if (energy > 0.25) {
      const trailStrength = (energy - 0.25) / 0.75;
      for (const p of proj) {
        const n = nodes[p.i];
        for (let ti = 1; ti < n.trail.length; ti++) {
          const tp = n.trail[ti];
          const ta = (1 - ti / n.trail.length) * 0.32 * trailStrength;
          if (ta < 0.01) continue;
          ctx.fillStyle = `rgba(0,195,255,${ta.toFixed(3)})`;
          ctx.beginPath(); ctx.arc(tp.sx, tp.sy, n.size * tp.sc * 0.65, 0, Math.PI * 2); ctx.fill();
        }
      }
    }
    const connMax = SR * (0.37 + energy * 0.20), connAlphaMax = 0.18 + energy * 0.62;
    ctx.save(); ctx.lineWidth = 0.6;
    for (let a = 0; a < proj.length; a++) {
      for (let b = a + 1; b < proj.length; b++) {
        const ni = proj[a].i, nj = proj[b].i;
        const dx = nodes[ni].x - nodes[nj].x, dy = nodes[ni].y - nodes[nj].y, dz = nodes[ni].z - nodes[nj].z;
        const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (d >= connMax) continue;
        const norm = 1 - d / connMax;
        const alpha = norm * norm * (proj[a].sc + proj[b].sc) * 0.5 * connAlphaMax;
        ctx.strokeStyle = `rgba(0,204,255,${alpha.toFixed(3)})`;
        ctx.beginPath(); ctx.moveTo(proj[a].sx, proj[a].sy); ctx.lineTo(proj[b].sx, proj[b].sy); ctx.stroke();
      }
    }
    ctx.restore();
    if (energy > 0.48 && Math.random() < energy * 0.09) addSpark(proj);
    for (let i = sparks.length - 1; i >= 0; i--) {
      const sp = sparks[i]; sp.life -= 0.055 + energy * 0.04;
      if (sp.life <= 0 || !proj[sp.a] || !proj[sp.b]) { sparks.splice(i, 1); continue; }
      const pa = proj[sp.a], pb = proj[sp.b];
      ctx.save(); ctx.globalAlpha = sp.life; ctx.shadowColor = '#fff'; ctx.shadowBlur = 12;
      ctx.strokeStyle = `rgba(210,245,255,${sp.life * 0.85})`; ctx.lineWidth = 0.85;
      ctx.beginPath(); ctx.moveTo(pa.sx, pa.sy); ctx.lineTo(pb.sx, pb.sy); ctx.stroke();
      ctx.restore();
    }
    for (let k = proj.length - 1; k >= 0; k--) {
      const p = proj[k], n = nodes[p.i];
      const alpha = Math.min(0.93, (0.28 + n.bright * 0.47 + energy * 0.36) * Math.max(0.33, p.sc));
      const sz = n.size * p.sc * (1 + energy * 0.88);
      ctx.save(); ctx.shadowColor = '#00d4ff'; ctx.shadowBlur = (5 + energy * 17) * p.sc;
      const gr = ctx.createRadialGradient(p.sx, p.sy, 0, p.sx, p.sy, sz * 2.8);
      gr.addColorStop(0, `rgba(0,210,255,${alpha})`); gr.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(p.sx, p.sy, sz * 2.8, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 3; ctx.fillStyle = `rgba(198,248,255,${alpha * 0.90})`;
      ctx.beginPath(); ctx.arc(p.sx, p.sy, sz, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    }
  }

  function init() {
    resize(); activeSR = SR;
    nodes = Array.from({ length: N_NODES }, makeNode);
    window.addEventListener('resize', resize);
    setTimeout(() => emitPulse(0.4), 300);
    setTimeout(() => emitPulse(0.2), 800);
    loop();
  }

  init();
})();
