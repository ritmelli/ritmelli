/* MESA-TOPO-INICIO */
/* na mesa a plaqueta e as teclas do topo em largura par do palco. Com a largura do texto (176,8 px
   na plaqueta) tudo a direita andava meia celula e a moldura de pixel borrava; a largura vem do estilo computado, que
   nao sofre a escala do palco */
(() => {
  const topo = document.querySelector('header.topo');
  if (!topo) return;
  function ajusta() {
    const els = [topo.querySelector('.marca'), ...topo.querySelectorAll('.botoes-topo > .btn-madeira')].filter(Boolean);
    const busca = topo.querySelector('.busca');
    for (const e of els) e.style.width = '';
    if (busca) busca.style.flex = '';
    if (!document.body.classList.contains('mesa-dj')) return;
    for (const e of els) {
      const w = parseFloat(getComputedStyle(e).width);
      if (w > 0) e.style.width = 2 * Math.ceil(w / 2 - 1e-3) + 'px';
    }
    // (r11) a busca termina na borda de fora da moldura da prateleira, como no mock: esticada ela passava 40 css por cima
    // dela. A sobra vai para as quatro teclas, em celulas inteiras. Com a prateleira escondida (a vista da busca), a
    // coluna dela: a borda direita da maleta mais o vao da grade e os 2 px da moldura
    const rolo = document.getElementById('rolo-prateleira'), mal = document.querySelector('.fila-parede.maleta'), app = topo.closest('.app');
    if (!busca || !app) return;
    const rb = rectP(busca);
    const borda = rolo && rolo.offsetWidth ? rectP(rolo).left
      : mal && mal.offsetWidth ? rectP(mal).right + (parseFloat(getComputedStyle(app).columnGap) || 0) + 2 : 0;
    if (!borda) return;
    const alvo = 2 * Math.round((borda - rb.left) / 2), sobra = 2 * Math.floor((rb.width - alvo) / 2);
    const bts = [...topo.querySelectorAll('.botoes-topo > .btn-madeira')].filter(e => e.offsetWidth);
    if (alvo < 200 || sobra <= 0 || !bts.length) return;
    busca.style.flex = `0 0 ${alvo}px`;
    let resto = sobra;
    bts.forEach((e, i) => { const mais = 2 * Math.round(resto / 2 / (bts.length - i)); resto -= mais; e.style.width = parseFloat(e.style.width) + mais + 'px'; });
  }
  const mo = new MutationObserver(() => requestAnimationFrame(ajusta));
  mo.observe(topo, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['hidden', 'class', 'aria-pressed'] });
  mo.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  if (document.fonts) document.fonts.ready.then(ajusta);
  ajusta();
})();
/* MESA-TOPO-FIM */
