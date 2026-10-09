/**
 * Client-side color maps for the light-table autopsy.
 * Matches pipeline/fear_pipeline.py: L* < 20 = near-black, HSV blood-red mask.
 * Palette handles = centroid of pixels nearest each k-means swatch.
 */

function parseHex(hex) {
  const h = String(hex || '').replace('#', '');
  if (h.length < 6) return [128, 128, 128];
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function srgbToLin(c) {
  const x = c / 255;
  return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
}

function lumaL(r, g, b) {
  const Y = 0.2126 * srgbToLin(r) + 0.7152 * srgbToLin(g) + 0.0722 * srgbToLin(b);
  return Y > 0.008856 ? 116 * Math.cbrt(Y) - 16 : 903.3 * Y;
}

function hsv(r, g, b) {
  const R = r / 255;
  const G = g / 255;
  const B = b / 255;
  const mx = Math.max(R, G, B);
  const mn = Math.min(R, G, B);
  const d = mx - mn;
  let h = 0;
  if (d > 1e-9) {
    if (mx === R) h = (60 * ((G - B) / d) + 360) % 360;
    else if (mx === G) h = 60 * ((B - R) / d) + 120;
    else h = 60 * ((R - G) / d) + 240;
  }
  return [h, mx > 1e-9 ? d / mx : 0, mx];
}

export function heatColor(t) {
  const x = Math.max(0, Math.min(1, t));
  if (x < 0.25) {
    const u = x / 0.25;
    return [Math.round(20 + u * 90), Math.round(8 + u * 10), Math.round(40 + u * 80)];
  }
  if (x < 0.5) {
    const u = (x - 0.25) / 0.25;
    return [Math.round(110 + u * 83), Math.round(18), Math.round(120 - u * 89)];
  }
  if (x < 0.75) {
    const u = (x - 0.5) / 0.25;
    return [193, Math.round(18 + u * 142), Math.round(31 + u * -18)];
  }
  const u = (x - 0.75) / 0.25;
  return [Math.round(193 + u * 62), Math.round(160 + u * 68), Math.round(13 + u * 205)];
}

function spreadHandles(handles) {
  for (let i = 1; i < handles.length; i++) {
    for (let j = 0; j < i; j++) {
      const dx = handles[i].x - handles[j].x;
      const dy = handles[i].y - handles[j].y;
      if (Math.hypot(dx, dy) >= 0.08) continue;
      handles[i].x = Math.min(0.92, Math.max(0.08, handles[i].x + 0.07));
      handles[i].y = Math.min(0.9, Math.max(0.08, handles[i].y + 0.05));
    }
  }
  return handles;
}

function toHex(r, g, b) {
  const h = (n) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
  return `#${h(r)}${h(g)}${h(b)}`;
}

function kmeansPalette(data, k = 5) {
  const pts = [];
  for (let i = 0; i < data.length; i += 16) {
    pts.push([data[i], data[i + 1], data[i + 2]]);
  }
  if (!pts.length) return [];
  const cents = pts.filter((_, i) => i % Math.max(1, Math.floor(pts.length / k)) === 0).slice(0, k);
  while (cents.length < k) cents.push(pts[cents.length % pts.length]);
  const assign = new Int32Array(pts.length);
  for (let iter = 0; iter < 8; iter++) {
    for (let i = 0; i < pts.length; i++) {
      let best = 0;
      let bd = Infinity;
      for (let c = 0; c < k; c++) {
        const dr = pts[i][0] - cents[c][0];
        const dg = pts[i][1] - cents[c][1];
        const db = pts[i][2] - cents[c][2];
        const d = dr * dr + dg * dg + db * db;
        if (d < bd) {
          bd = d;
          best = c;
        }
      }
      assign[i] = best;
    }
    const sum = Array.from({ length: k }, () => [0, 0, 0, 0]);
    for (let i = 0; i < pts.length; i++) {
      const c = assign[i];
      sum[c][0] += pts[i][0];
      sum[c][1] += pts[i][1];
      sum[c][2] += pts[i][2];
      sum[c][3] += 1;
    }
    for (let c = 0; c < k; c++) {
      if (sum[c][3]) {
        cents[c] = [sum[c][0] / sum[c][3], sum[c][1] / sum[c][3], sum[c][2] / sum[c][3]];
      }
    }
  }
  const counts = new Float64Array(k);
  for (let i = 0; i < assign.length; i++) counts[assign[i]] += 1;
  return [...cents.keys()]
    .sort((a, b) => counts[b] - counts[a])
    .map((i) => toHex(cents[i][0], cents[i][1], cents[i][2]));
}

function hueBandIndex(h, s, v, L) {
  if (v < 0.12 || L < 15 || s < 0.15) return 5;
  if (h >= 345 || h < 15) return 0;
  if (h < 70) return 1;
  if (h < 170) return 2;
  if (h < 260) return 3;
  return 4;
}

export function analyzeColor(img, palHex, w = 200, h = 300) {
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(img, 0, 0, w, h);
  const { data } = ctx.getImageData(0, 0, w, h);
  const palHexUse = palHex && palHex.length ? palHex : kmeansPalette(data, 5);
  const pal = palHexUse.map(parseHex);
  const n = Math.max(pal.length, 1);
  const sumX = new Float64Array(n);
  const sumY = new Float64Array(n);
  const count = new Float64Array(n);
  const heatDark = ctx.createImageData(w, h);
  const heatRed = ctx.createImageData(w, h);
  const heatL = ctx.createImageData(w, h);
  const poster = ctx.createImageData(w, h);
  const heatSat = ctx.createImageData(w, h);
  const Lbuf = new Float32Array(w * h);
  let nDark = 0;
  let nRed = 0;
  let sumL = 0;
  let sumS = 0;
  const bandHits = new Float64Array(6);
  const nPix = w * h;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const L = lumaL(r, g, b);
      const [hh, s, v] = hsv(r, g, b);
      Lbuf[y * w + x] = L;
      sumL += L;
      sumS += s;
      bandHits[hueBandIndex(hh, s, v, L)] += 1;

      if (pal.length) {
        let best = 0;
        let bd = Infinity;
        for (let p = 0; p < pal.length; p++) {
          const dr = r - pal[p][0];
          const dg = g - pal[p][1];
          const db = b - pal[p][2];
          const d = dr * dr + dg * dg + db * db;
          if (d < bd) {
            bd = d;
            best = p;
          }
        }
        sumX[best] += x;
        sumY[best] += y;
        count[best] += 1;
        poster.data[i] = pal[best][0];
        poster.data[i + 1] = pal[best][1];
        poster.data[i + 2] = pal[best][2];
        poster.data[i + 3] = 255;
      } else {
        poster.data[i] = r;
        poster.data[i + 1] = g;
        poster.data[i + 2] = b;
        poster.data[i + 3] = 255;
      }

      if (L < 20) {
        nDark += 1;
        const t = 1 - L / 20;
        heatDark.data[i] = 229;
        heatDark.data[i + 1] = 160;
        heatDark.data[i + 2] = 13;
        heatDark.data[i + 3] = Math.round(28 + t * 100);
      }

      if ((hh >= 345 || hh <= 15) && s > 0.4 && v > 0.15) {
        nRed += 1;
        heatRed.data[i] = 193;
        heatRed.data[i + 1] = 18;
        heatRed.data[i + 2] = 31;
        heatRed.data[i + 3] = 175;
      }

      const col = heatColor(Math.max(0, Math.min(1, L / 100)));
      heatL.data[i] = col[0];
      heatL.data[i + 1] = col[1];
      heatL.data[i + 2] = col[2];
      heatL.data[i + 3] = 150;

      heatSat.data[i] = 229;
      heatSat.data[i + 1] = 160;
      heatSat.data[i + 2] = 13;
      heatSat.data[i + 3] = Math.round(s * 210);
    }
  }

  const edges = ctx.createImageData(w, h);
  const heatNeg = ctx.createImageData(w, h);
  for (let y = 1; y < h - 1; y++) {
    for (let x = 1; x < w - 1; x++) {
      const at = (yy, xx) => Lbuf[yy * w + xx];
      const gx =
        -at(y - 1, x - 1) +
        at(y - 1, x + 1) +
        -2 * at(y, x - 1) +
        2 * at(y, x + 1) +
        -at(y + 1, x - 1) +
        at(y + 1, x + 1);
      const gy =
        -at(y - 1, x - 1) -
        2 * at(y - 1, x) -
        at(y - 1, x + 1) +
        at(y + 1, x - 1) +
        2 * at(y + 1, x) +
        at(y + 1, x + 1);
      const mag = Math.hypot(gx, gy);
      const i = (y * w + x) * 4;
      if (mag < 14) {
        const t = 1 - mag / 14;
        heatNeg.data[i] = 232;
        heatNeg.data[i + 1] = 228;
        heatNeg.data[i + 2] = 218;
        heatNeg.data[i + 3] = Math.round(20 + t * 120);
      }
      const em = Math.min(1, mag / 140);
      if (em < 0.12) continue;
      edges.data[i] = 229;
      edges.data[i + 1] = 160;
      edges.data[i + 2] = 13;
      edges.data[i + 3] = Math.round(40 + em * 215);
    }
  }

  const handles = pal.map((c, i) => {
    if (!count[i]) {
      return { n: i + 1, hex: palHexUse[i], x: 0.18 + (i % 5) * 0.16, y: 0.88, empty: true };
    }
    return {
      n: i + 1,
      hex: palHexUse[i],
      x: sumX[i] / count[i] / w,
      y: sumY[i] / count[i] / h,
    };
  });

  return {
    handles: spreadHandles(handles),
    palHex: palHexUse,
    heatDark,
    heatRed,
    heatL,
    poster,
    edges,
    heatSat,
    heatNeg,
    darkShare: nDark / nPix,
    redShare: nRed / nPix,
    meanL: sumL / nPix,
    meanSat: sumS / nPix,
    bands: Array.from(bandHits, (v) => v / nPix),
  };
}

export function paintHeat(canvas, imageData) {
  if (!canvas || !imageData) return;
  canvas.width = imageData.width;
  canvas.height = imageData.height;
  canvas.getContext('2d').putImageData(imageData, 0, 0);
}

/** Colormap a grayscale MSI-Net PNG onto a canvas (0=cool, 1=hot). */
export async function paintSaliencyFromUrl(canvas, src) {
  if (!canvas || !src) return null;
  let res;
  try {
    res = await fetch(src, { cache: 'no-store' });
  } catch {
    return null;
  }
  if (!res.ok) return null;
  const ctype = res.headers.get('content-type') || '';
  if (ctype && !ctype.includes('image') && !ctype.includes('octet-stream')) return null;
  let bitmap;
  try {
    bitmap = await createImageBitmap(await res.blob());
  } catch {
    return null;
  }
  try {
    const w = bitmap.width;
    const h = bitmap.height;
    const off = document.createElement('canvas');
    off.width = w;
    off.height = h;
    const octx = off.getContext('2d', { willReadFrequently: true });
    octx.drawImage(bitmap, 0, 0);
    const { data } = octx.getImageData(0, 0, w, h);
    const out = octx.createImageData(w, h);
    let peak = -1;
    let px = 0.5;
    let py = 0.5;
    for (let i = 0, n = 0; i < data.length; i += 4, n++) {
      const t = data[i] / 255;
      if (data[i] > peak) {
        peak = data[i];
        px = (n % w + 0.5) / w;
        py = (Math.floor(n / w) + 0.5) / h;
      }
      const col = heatColor(t);
      out.data[i] = col[0];
      out.data[i + 1] = col[1];
      out.data[i + 2] = col[2];
      out.data[i + 3] = Math.round(28 + t * 200);
    }
    canvas.width = w;
    canvas.height = h;
    canvas.getContext('2d').putImageData(out, 0, 0);
    return { x: px, y: py };
  } finally {
    bitmap.close?.();
  }
}

export async function analyzeFromUrl(src, palHex) {
  const res = await fetch(src, { mode: 'cors', cache: 'no-store' });
  if (!res.ok) throw new Error(`color map fetch ${res.status}`);
  const blob = await res.blob();
  const bitmap = await createImageBitmap(blob);
  try {
    return analyzeColor(bitmap, palHex);
  } finally {
    bitmap.close?.();
  }
}
