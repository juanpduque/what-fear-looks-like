/** Flickering white letters on section titles (same pulse as hero "Fear", staggered). */
function unwrapFear(el) {
  el.querySelectorAll('span.fear').forEach((s) => {
    s.replaceWith(document.createTextNode(s.textContent));
  });
  el.normalize();
}

function wrapFlickerLetters(el, titleIndex) {
  unwrapFear(el);
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const letters = [];
  let node;
  while ((node = walker.nextNode())) {
    const text = node.textContent;
    for (let i = 0; i < text.length; i++) {
      if (/\p{L}/u.test(text[i])) letters.push({ node, i });
    }
  }
  if (letters.length < 2) return;
  const count = Math.min(3, Math.max(2, Math.round(letters.length / 10)));
  const picks = [];
  for (let k = 0; k < count; k++) {
    const t = (k + 1) / (count + 1);
    const idx = Math.min(letters.length - 1, Math.round(t * (letters.length - 1)));
    if (picks.length && Math.abs(idx - picks[picks.length - 1]) < 2) continue;
    picks.push(idx);
  }
  if (!picks.length) picks.push(Math.floor(letters.length * 0.42));

  const byNode = new Map();
  picks.forEach((li, pi) => {
    const { node: n, i } = letters[li];
    if (!byNode.has(n)) byNode.set(n, []);
    byNode.get(n).push({ i, pi });
  });
  byNode.forEach((spots, n) => {
    spots.sort((a, b) => a.i - b.i);
    const text = n.textContent;
    const frag = document.createDocumentFragment();
    let cursor = 0;
    spots.forEach(({ i, pi }) => {
      if (i > cursor) frag.appendChild(document.createTextNode(text.slice(cursor, i)));
      const span = document.createElement('span');
      span.className = 'fear';
      span.textContent = text.slice(i, i + 1);
      const delay = ((titleIndex * 0.37 + pi * 1.15) % 3.2).toFixed(2);
      span.style.setProperty('--flicker-delay', delay + 's');
      frag.appendChild(span);
      cursor = i + 1;
    });
    if (cursor < text.length) frag.appendChild(document.createTextNode(text.slice(cursor)));
    n.replaceWith(frag);
  });
}

function applyFlickerTitles() {
  document.querySelectorAll('h2.section-title').forEach(wrapFlickerLetters);
}

export function initFlickerTitles() {
  document.addEventListener('aof:lang', applyFlickerTitles);
  if (document.readyState !== 'loading') applyFlickerTitles();
}
