export function pct(x) {
  return x == null ? '—' : Math.round(x * 100) + '%';
}

export function num(x, d = 2) {
  return x == null || x === '' ? '—' : (+x).toFixed(d).replace(/\.?0+$/, '');
}
