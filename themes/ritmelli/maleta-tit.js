/* MALETA-TIT-INICIO */
/* o titulo da placa da maleta em letra de pixel (canvas de 1 px por celula, mostrado a 2x): o "A seguir"
   na negrita da placa da prateleira e a contagem na regular dela (LETRA-PLACA), centrados entre os parafusos e o botao (madrugada, 07/11) */
(() => {
  const { negrita: T, regular: G, desce: D } = LETRA_PLACA, TA = 9, GA = 9;
  const TINTA = 'rgb(42,24,18)';
  function desenhaTit() {
    if (!document.body.classList.contains('mesa-dj')) return;
    for (const cab of document.querySelectorAll('.fila-parede.maleta .cabeca-fila')) {
      const conta = cab.querySelector('.conta'), n = conta ? conta.textContent.trim() : '';
      const tit = [...I18N.t('queue.title')], extra = n ? [...('\u00b7 ' + n)] : [];
      let cv = cab.querySelector('canvas.tit-px');
      // a letra que falta leva o titulo e a contagem para o HTML, sem o canvas por cima
      if (tit.some(ch => ch !== ' ' && !T[ch]) || extra.some(ch => !G[ch])) { cab.classList.remove('tit-px'); if (cv) cv.remove(); continue; }
      if (!cv) { cv = document.createElement('canvas'); cv.className = 'tit-px'; cv.setAttribute('aria-hidden', 'true'); cab.appendChild(cv); }
      const larg = (ch, F) => ch === ' ' ? 3 : F[ch][0].length;
      const wT = tit.reduce((s, ch, i) => s + larg(ch, T) + (i < tit.length - 1 ? 1 : 0), 0);
      const wC = extra.reduce((s, ch, i) => s + larg(ch, G) + (i < extra.length - 1 ? 1 : 0), 0);
      const w = wT + (extra.length ? 4 + wC : 0), h = TA + 2;
      cv.width = w; cv.height = h; cv.style.width = (2 * w) + 'px'; cv.style.height = (2 * h) + 'px';
      // no eixo da placa (celula 74,5 do recorte dela), o mesmo da alca e do texto de vazio, numa celula inteira; no
      // meio do vao ate o botao ele ficava 6 celulas a esquerda e destoava do "Nada no A seguir" logo abaixo (r02)
      // perto do botao (o desenho da placa depois do padding da direita), ele anda para a esquerda: 3 celulas de folga, as
      // do "12 discos" (a contagem de 2 algarismos em ingles encostava nele)
      const ate = Math.floor((cab.clientWidth - parseFloat(getComputedStyle(cab).paddingRight)) / 2) - 3;
      cv.style.left = (2 * Math.min(Math.round(74.5 - w / 2), ate - w)) + 'px';
      const c = cv.getContext('2d');
      c.clearRect(0, 0, w, h);
      c.fillStyle = TINTA;
      let x = 0;
      const poe = (ch, F, alt) => {
        if (ch === ' ') { x += 3 + 1; return; }
        const g = F[ch], dsc = F === T ? (D[ch] || 0) : 0, y0 = alt - (g.length - dsc) + (TA - alt);
        g.forEach((linha, j) => { [...linha].forEach((p, k) => { if (p === '#') c.fillRect(x + k, y0 + j, 1, 1); }); });
        x += g[0].length + 1;
      };
      for (const ch of tit) poe(ch, T, TA);
      if (extra.length) { x += 3; for (const ch of extra) poe(ch, G, GA); }
      cab.classList.add('tit-px');
    }
  }
  // redesenha quando a contagem muda, quando a mesa monta (a classe do body) e quando o canvas volta em branco (o
  // repinta-canvas do repintarCanvas, #119); nada mais dispara
  const obs = new MutationObserver(desenhaTit);
  obs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  for (const c of document.querySelectorAll('.fila-parede .cabeca-fila .conta')) obs.observe(c, { childList: true, characterData: true, subtree: true });
  document.addEventListener('repinta-canvas', desenhaTit);
  desenhaTit();
})();
/* MALETA-TIT-FIM */
