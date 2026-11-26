/* MALETA-VAZIA-INICIO */
/* (r09) o aviso de vazio do A seguir na letra das telas dos toca-discos (a 5x7 do deck, 1 pixel
   da letra = 1 celula), num canvas de 1 px por celula mostrado a 2x, sem suavizar; o texto do DOM segue por cima, transparente.
   Cada linha centrada no eixo da maleta; o titulo na negrita (a do "Nada no prato"), a dica na regular, a sombra de 1 celula */
import { deckGlyphs } from "deck.js";
(() => {
  const BR = [251, 239, 217], DICA = [176, 160, 138], SOMB = [26, 11, 4];
  // do topo do aviso (a linha do chao da bandeja) ao topo das maiusculas, em px do palco; de base a base, em celulas
  const TOPO = 4, PASSO1 = 11, PASSO2 = 11, MAX = 300;   // (r15) a dica no passo 11 (a perna do p colava no T de baixo) e o bloco 1 celula acima para a ultima perna caber no piso (era 6 / 10 desde a r10)
  function quebra(L, s) {   // o menor numero de linhas que cabe em MAX celulas, com as linhas o mais iguais possivel
    const pal = s.split(/\s+/).filter(Boolean), w = t => L.larg('f', t) - 1;
    const gulosa = lim => { const ls = []; let cur = ''; for (const p of pal) { const t = cur ? cur + ' ' + p : p; if (cur && w(t) > lim) { ls.push(cur); cur = p; } else cur = t; } if (cur) ls.push(cur); return ls; };
    const n = gulosa(MAX).length;
    let lo = 1, hi = MAX;
    while (lo < hi) { const m = (lo + hi) >> 1; if (gulosa(m).length <= n) hi = m; else lo = m + 1; }
    return gulosa(lo);
  }
  function desenha() {
    const p = document.getElementById('fila-vazia'), L = deckGlyphs, mal = document.querySelector('.fila-parede.maleta');
    if (!p) return;
    const cv0 = p.querySelector('canvas.vazia-px');
    if (!document.body.classList.contains('mesa-dj') || p.hidden || !L.ready() || !mal || !mal.offsetWidth || mal.offsetParent !== p.offsetParent) {
      p.classList.remove('px-ok'); if (cv0) cv0.remove(); return;
    }
    const b = p.querySelector('b'), tit = (b ? b.textContent : '').trim();
    const dica = [...p.childNodes].filter(n => n !== b && (n.nodeType === 3 || n.nodeName === 'SPAN')).map(n => n.textContent).join(' ').replace(/\s+/g, ' ').trim();
    const linhas = [[tit, 'fb', BR], ...quebra(L, dica).map(t => [t, 'f', DICA])];
    const ws = linhas.map(([t, fk]) => L.larg(fk, t) - 1), W = Math.max(...ws) + 2;
    const base = linhas.map((_, i) => 7 + (i ? PASSO1 + (i - 1) * PASSO2 : 0)), H = base[base.length - 1] + 3;
    // em px do layout (o do palco, sem a escala dele): o aviso e a maleta tem o mesmo pai de posicao, entao o eixo da
    // maleta e o canto do aviso se medem um contra o outro na hora, sem depender da escala nem de quando o palco assentou
    const px0 = p.offsetLeft, py0 = p.offsetTop, cx = mal.offsetLeft + mal.offsetWidth / 2;
    const left = 2 * Math.floor((cx - W) / 2), top = 2 * Math.round((py0 + TOPO) / 2), eixo = (cx - left) / 2;
    const cv = cv0 || Object.assign(document.createElement('canvas'), { className: 'vazia-px' });
    if (!cv0) { cv.setAttribute('aria-hidden', 'true'); p.appendChild(cv); }
    cv.width = W; cv.height = H; cv.style.width = 2 * W + 'px'; cv.style.height = 2 * H + 'px';
    cv.style.left = left - px0 + 'px'; cv.style.top = top - py0 + 'px';
    const c = cv.getContext('2d'), im = c.createImageData(W, H);
    const ponto = (x, y, k) => { if (x < 0 || y < 0 || x >= W || y >= H) return; const o = (y * W + x) * 4; im.data[o] = k[0]; im.data[o + 1] = k[1]; im.data[o + 2] = k[2]; im.data[o + 3] = 255; };
    const escreve = (t, fk, x, yb, k, dy) => {
      let pen = x;
      for (const ch of t) {
        const g = L.gl(fk, ch);
        // (r15) na minuscula acentuada a marca (linhas 0 e 1 do glifo) sobe 1 celula: colada no corpo, o a virava um a com gancho
        const sobe = ch !== ch.toUpperCase() && ch.normalize('NFD').length > 1 && ch !== 'ç' ? 1 : 0;
        for (let j = 0; j < g.h; j++) for (let i = 0; i < g.w; i++) if (g.bits[j * g.w + i]) ponto(pen + g.dx + i, yb + g.dy + j + dy - (j < 2 ? sobe : 0), k);
        pen += g.adv;
      }
    };
    const xs = linhas.map((_, i) => Math.round(eixo - ws[i] / 2));
    linhas.forEach(([t, fk], i) => escreve(t, fk, xs[i], base[i], SOMB, 1));
    linhas.forEach(([t, fk, k], i) => escreve(t, fk, xs[i], base[i], k, 0));
    c.putImageData(im, 0, 0);
    p.classList.add('px-ok');
  }
  const p = document.getElementById('fila-vazia');
  const agenda = () => requestAnimationFrame(desenha);
  document.addEventListener('repinta-canvas', agenda);
  if (p) {
    new MutationObserver(agenda).observe(p, { attributes: true, attributeFilter: ['hidden'] });
    new ResizeObserver(agenda).observe(p);
  }
  new MutationObserver(agenda).observe(document.body, { attributes: true, attributeFilter: ['class'] });
  // o palco (o ajustarPalco grava a escala no estilo do html) e a maleta (a fileira que muda de largura) mexem no lugar
  // do aviso sem mudar o tamanho dele
  new MutationObserver(agenda).observe(document.documentElement, { attributes: true, attributeFilter: ['style'] });
  const mal = document.querySelector('.fila-parede.maleta');
  if (mal) new ResizeObserver(agenda).observe(mal);
  addEventListener('resize', agenda);
  document.addEventListener('px-letra', agenda);
  agenda();
})();
/* MALETA-VAZIA-FIM */
