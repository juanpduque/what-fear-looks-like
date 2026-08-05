/**
 * Poster Decompose — Fase A
 * CSS 3D VHS slipcase + scroll analysis beats (no WebGL / no local GPU).
 * Prefers vhs_reference.png (Media full-box) over poster.jpg.
 */
const HALLOWEEN = {
  id: 948,
  title: 'Halloween',
  year: 1978,
  pal: ['#070101', '#370f0e', '#711910', '#c53c0d', '#d5bda2'],
};

const REDUCE = matchMedia('(prefers-reduced-motion: reduce)').matches;

const state = {
  beat: 0,
  usingMediaCover: false,
  texLabel: 'poster.jpg',
};

async function exists(url) {
  try {
    const r = await fetch(url, { method: 'GET', cache: 'no-store' });
    if (!r.ok) return false;
    const ct = r.headers.get('content-type') || '';
    return ct.startsWith('image/') || ct.includes('octet-stream') || ct === '';
  } catch {
    return false;
  }
}

async function resolveFrontUrl() {
  if (await exists('./vhs_reference.png')) {
    state.usingMediaCover = true;
    state.texLabel = 'vhs_reference.png · Media cover';
    return './vhs_reference.png';
  }
  state.usingMediaCover = false;
  state.texLabel = 'poster.jpg · (falta vhs_reference.png Media)';
  return './poster.jpg';
}

function stampEdgeWear(ctx, w, h, intensity = 1) {
  // White cardboard showing through rubbed black/navy ink (Media shelf wear).
  const cardboard = '#f6edd8';
  ctx.save();
  // Continuous scuffed rails along left + bottom (most common Media wear)
  ctx.globalAlpha = 0.55 + 0.2 * intensity;
  ctx.strokeStyle = cardboard;
  ctx.lineWidth = 3 + 4 * intensity;
  ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(2, h * 0.35);
  for (let y = h * 0.35; y < h - 4; y += 7) {
    ctx.lineTo(2 + Math.random() * (6 + 8 * intensity), y);
  }
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(w * 0.08, h - 3);
  for (let x = w * 0.08; x < w * 0.95; x += 9) {
    ctx.lineTo(x, h - 2 - Math.random() * (5 + 10 * intensity));
  }
  ctx.stroke();

  for (let i = 0; i < 55 * intensity; i++) {
    const x = Math.random() * w;
    const y = h - Math.random() * (22 + 48 * intensity);
    ctx.globalAlpha = 0.45 + Math.random() * 0.5;
    ctx.fillStyle = cardboard;
    ctx.beginPath();
    ctx.ellipse(x, y, 5 + Math.random() * 32, 2 + Math.random() * 12, Math.random() * 0.5, 0, Math.PI * 2);
    ctx.fill();
  }
  for (let i = 0; i < 40 * intensity; i++) {
    const side = Math.random() < 0.6 ? 0 : 1;
    const x = side ? w - Math.random() * 18 : Math.random() * 18;
    const y = Math.random() * h;
    ctx.globalAlpha = 0.5 + Math.random() * 0.45;
    ctx.fillStyle = cardboard;
    ctx.fillRect(x, y, 2 + Math.random() * 10, 4 + Math.random() * 18);
  }
  // Corner blowouts
  ctx.globalAlpha = 0.92;
  ctx.fillStyle = cardboard;
  ctx.beginPath();
  ctx.moveTo(0, h);
  ctx.lineTo(0, h - 52 * intensity);
  ctx.quadraticCurveTo(22, h - 10, 70 * intensity, h);
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(w, h);
  ctx.lineTo(w, h - 30 * intensity);
  ctx.quadraticCurveTo(w - 14, h - 6, w - 40 * intensity, h);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function canvasUrl(w, h, paint) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  paint(c.getContext('2d'), w, h);
  return c.toDataURL('image/png');
}

function paintFrontChrome(ctx, w, h, mediaMode) {
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, '#0c1630');
  g.addColorStop(1, '#071022');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  if (!mediaMode) {
    const inset = Math.floor(w * 0.06);
    const top = Math.floor(h * 0.05);
    const bottom = Math.floor(h * 0.88);
    ['#c1121f', '#e07a12', '#e5c44a'].forEach((col, i) => {
      ctx.strokeStyle = col;
      ctx.lineWidth = 3;
      ctx.strokeRect(inset - i * 4, top - i * 4, w - inset * 2 + i * 8, bottom - top + i * 8);
    });
    ctx.fillStyle = 'rgba(243,234,215,.92)';
    ctx.fillRect(0, h * 0.9, w, h * 0.1);
    ctx.fillStyle = '#1a1208';
    ctx.font = `600 ${Math.floor(w * 0.035)}px "Space Mono", monospace`;
    ctx.fillText('COLOR · 90 MIN', w * 0.06, h * 0.955);
  }
  stampEdgeWear(ctx, w, h, mediaMode ? 0.5 : 1);
}

function paintSpine(ctx, w, h, mediaMode) {
  const g = ctx.createLinearGradient(0, 0, w, 0);
  g.addColorStop(0, '#0a1020');
  g.addColorStop(0.5, '#121a32');
  g.addColorStop(1, '#0a1020');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.save();
  ctx.translate(w * 0.68, h * 0.92);
  ctx.rotate(-Math.PI / 2);
  ctx.fillStyle = '#f4efe4';
  ctx.font = `700 ${Math.floor(w * 0.55)}px Anton, Impact, sans-serif`;
  ctx.fillText('HALLOWEEN', 0, 0);
  ctx.restore();
  if (!mediaMode) {
    ctx.fillStyle = 'rgba(193,18,31,.85)';
    ctx.fillRect(0, h * 0.04, w, 6);
  }
  stampEdgeWear(ctx, w, h, 0.7);
}

function paintBack(ctx, w, h, mediaMode) {
  ctx.fillStyle = '#0b1224';
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = 'rgba(232,228,218,.88)';
  ctx.font = `600 ${Math.floor(w * 0.055)}px Anton, Impact, sans-serif`;
  ctx.fillText('HALLOWEEN', w * 0.08, h * 0.12);
  ctx.fillStyle = 'rgba(232,228,218,.55)';
  ctx.font = `${Math.floor(w * 0.032)}px "Source Serif 4", Georgia, serif`;
  const lines = mediaMode
    ? [
        'Media Home Entertainment slipcase.',
        'Front art carries the real footer —',
        'this back stays quiet on purpose.',
      ]
    : [
        'The night HE came home.',
        'Stand-in theatrical art until the',
        'Media box cover lands as vhs_reference.png.',
      ];
  lines.forEach((t, i) => ctx.fillText(t, w * 0.08, h * (0.22 + i * 0.045)));
  ctx.strokeStyle = 'rgba(229,160,13,.25)';
  ctx.strokeRect(w * 0.08, h * 0.55, w * 0.35, h * 0.28);
  stampEdgeWear(ctx, w, h, 0.85);
}

function paintWear(ctx, w, h) {
  ctx.clearRect(0, 0, w, h);
  stampEdgeWear(ctx, w, h, 1.2);
}

function paintEdge(ctx, w, h) {
  ctx.fillStyle = '#efe4cf';
  ctx.fillRect(0, 0, w, h);
  for (let i = 0; i < 900; i++) {
    ctx.fillStyle = `rgba(120,90,50,${Math.random() * 0.07})`;
    ctx.fillRect(Math.random() * w, Math.random() * h, 1, 1);
  }
}

function buildStage(frontUrl, mediaMode) {
  const stage = document.getElementById('stage');
  const scene = document.createElement('div');
  scene.className = 'vhs-scene';
  scene.innerHTML = `
    <div class="vhs-box" id="vhsBox">
      <div class="face front" id="faceFront">
        <div class="art" id="faceArt"></div>
        <div class="wear" id="faceWear"></div>
        <div class="layer dark" data-layer="dark"></div>
        <div class="layer red" data-layer="red"></div>
        <div class="layer comp" data-layer="comp"></div>
      </div>
      <div class="face back" id="faceBack"></div>
      <div class="face spine" id="faceSpine"></div>
      <div class="face right" id="faceRight"></div>
      <div class="face top" id="faceTop"></div>
      <div class="face bottom" id="faceBottom"></div>
    </div>
  `;
  // Replace canvas
  const canvas = document.getElementById('c');
  if (canvas) canvas.remove();
  stage.insertBefore(scene, stage.firstChild);

  const frontChrome = canvasUrl(768, 1152, (ctx, w, h) => paintFrontChrome(ctx, w, h, mediaMode));
  const spine = canvasUrl(192, 1152, (ctx, w, h) => paintSpine(ctx, w, h, mediaMode));
  const back = canvasUrl(768, 1152, (ctx, w, h) => paintBack(ctx, w, h, mediaMode));
  const edge = canvasUrl(192, 192, paintEdge);
  const wear = canvasUrl(768, 1152, paintWear);

  const frontEl = document.getElementById('faceFront');
  const artEl = document.getElementById('faceArt');
  frontEl.style.backgroundImage = `url(${frontChrome})`;

  if (mediaMode) {
    frontEl.style.backgroundImage = `url(${frontUrl})`;
    artEl.style.display = 'none';
  } else {
    artEl.style.backgroundImage = `url(${frontUrl})`;
  }

  document.getElementById('faceWear').style.backgroundImage = `url(${wear})`;
  document.getElementById('faceBack').style.backgroundImage = `url(${back})`;
  document.getElementById('faceSpine').style.backgroundImage = `url(${spine})`;
  document.getElementById('faceRight').style.backgroundImage = `url(${edge})`;
  document.getElementById('faceTop').style.backgroundImage = `url(${edge})`;
  document.getElementById('faceBottom').style.backgroundImage = `url(${edge})`;
}

const POSES = [
  { rx: 10, ry: 38, rz: 2, tx: 22, ty: 0, s: 1 },
  { rx: 4, ry: 14, rz: 0, tx: 26, ty: 0, s: 1.04 },
  { rx: 14, ry: 52, rz: 3, tx: 6, ty: 2, s: 1.1 },
  { rx: 6, ry: 22, rz: 0, tx: 20, ty: 0, s: 1.12 },
  { rx: 5, ry: 16, rz: 0, tx: 22, ty: 0, s: 1.12 },
  { rx: -4, ry: -14, rz: 0, tx: 16, ty: 0, s: 1.06 },
  { rx: 12, ry: 42, rz: 2, tx: 14, ty: 0, s: 1 },
];

function applyPose(el, pose, idle = 0) {
  const { rx, ry, rz, tx, ty, s } = pose;
  el.style.transform =
    `translate3d(${tx}%, ${ty}%, 0) rotateX(${rx}deg) rotateY(${ry + idle}deg) rotateZ(${rz}deg) scale(${s})`;
}

async function main() {
  const texLabel = document.getElementById('texLabel');
  const bootMeta = document.getElementById('bootMeta');
  const swatches = document.getElementById('swatches');

  HALLOWEEN.pal.forEach((hex) => {
    const i = document.createElement('i');
    i.style.background = hex;
    i.title = hex;
    swatches.appendChild(i);
  });

  const frontUrl = await resolveFrontUrl();
  texLabel.textContent = `Fase A · ${state.texLabel}`;
  bootMeta.textContent = state.usingMediaCover
    ? 'Textura: vhs_reference.png (Media). Packaging procedural simplificado.'
    : 'Textura: poster.jpg. Añade vhs_reference.png para el box art Media Home Entertainment.';

  buildStage(frontUrl, state.usingMediaCover);

  const box = document.getElementById('vhsBox');
  const beats = [...document.querySelectorAll('.beat')];
  const layers = {
    dark: document.querySelector('.layer.dark'),
    red: document.querySelector('.layer.red'),
    comp: document.querySelector('.layer.comp'),
  };
  const wearEl = document.getElementById('faceWear');

  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((en) => {
        if (en.isIntersecting) {
          en.target.classList.add('is-active');
          state.beat = Number(en.target.dataset.beat) || 0;
          box.dataset.beat = String(state.beat);
          Object.entries(layers).forEach(([k, el]) => {
            el.classList.toggle('on', { 3: 'dark', 4: 'red', 5: 'comp' }[state.beat] === k);
          });
          wearEl.classList.toggle('strong', state.beat === 2);
          if (!REDUCE) applyPose(box, POSES[Math.min(state.beat, POSES.length - 1)]);
        } else {
          en.target.classList.remove('is-active');
        }
      });
    },
    { rootMargin: '-35% 0px -35% 0px', threshold: 0.01 }
  );
  beats.forEach((b) => io.observe(b));

  applyPose(box, POSES[0]);

  if (!REDUCE) {
    let t0 = performance.now();
    function drift(now) {
      const idle = Math.sin((now - t0) * 0.00045) * 1.8;
      const pose = POSES[Math.min(state.beat, POSES.length - 1)];
      applyPose(box, pose, idle);
      requestAnimationFrame(drift);
    }
    requestAnimationFrame(drift);
  }
}

main().catch((err) => {
  console.error(err);
  document.getElementById('bootMeta').textContent = 'Error: ' + err.message;
});
