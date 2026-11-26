/* COVERS-JS-INICIO */
'use strict';
/* ---------- capas ---------- */
const PALETAS = [
  ['#F3A73C', '#2A1812', '#23382E'],
  ['#23382E', '#EEE3CF', '#F3A73C'],
  ['#5E1C25', '#EEE3CF', '#F3A73C'],
  ['#CFC7B8', '#2A1812', '#5E1C25'],
  ['#1E4A52', '#EEE3CF', '#F3A73C'],
];
function hash(s) { let h = 2166136261; for (const c of String(s)) { h ^= c.codePointAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function capaGerada(it, curta) {
  const h = hash(it.id || it.title);
  const [bg, fg, dot] = PALETAS[h % PALETAS.length];
  const d = el('div', 'capa-gerada');
  d.style.setProperty('--bg', bg); d.style.setProperty('--fg', fg); d.style.setProperty('--dot', dot);
  const titulo = (it.title || I18N.t('shelf.untitled')).trim();
  if (!curta) {
    // bolas no alto da capa: uma cheia grande, um aro e uma pequena, em posicoes que variam por som
    const g = 28 + (h >> 4) % 10;
    const gx = 50 + (h >> 8) % (92 - 50 - g + 1), gy = 8 + (h >> 12) % 8;
    const b1 = el('span', 'bola'); b1.style.cssText = `width:${g}cqw;height:${g}cqw;left:${gx}cqw;top:${gy}cqw`;
    // o aro cruza a bola cheia, como um disco saindo da capa
    const a = Math.round(g * .82);
    const ax = gx - a * .55, ay = gy + g * .38;
    const b2 = el('span', 'bola aro'); b2.style.cssText = `width:${a}cqw;height:${a}cqw;left:${ax}cqw;top:${ay}cqw`;
    d.append(b1, b2);
  }
  d.append(el('span', 't', curta ? titulo.charAt(0).toUpperCase() : titulo));
  return d;
}
function arte(it, curta) {
  if (!it.thumb) return capaGerada(it, curta);
  const img = new Image();
  img.alt = ''; img.decoding = 'async'; img.referrerPolicy = 'no-referrer';
  img.src = it.thumb;
  img.addEventListener('error', () => img.replaceWith(capaGerada(it, curta)), { once: true });
  return img;
}
/* COVERS-JS-FIM */
