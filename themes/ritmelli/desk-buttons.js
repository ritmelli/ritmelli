/* DESK-BUTTONS-JS-INICIO */
'use strict';
/* ---------- mesa de DJ: os botoes ---------- */
function bindDeskButtons() {
  for (const [de, para] of [['#b-anterior', '#ant-d'], ['#b-tocar', '#tocar-d'], ['#b-proxima', '#prox-d'], ['#b-aleatorio', '#m-aleatorio'], ['#b-repetir', '#m-repetir']]) {
    const c = $(de + ' svg').cloneNode(true); c.removeAttribute('id'); $(para).prepend(c);
  }
  // a deixa: o Tocar e o Proximo de hoje (a fila anda, o que esta no ar sai na hora); o Proxima dela tira da fila
  $('#tocar-d').addEventListener('click', () => { if (MESA.deixa) cmd('/api/next'); });
  $('#prox-d').addEventListener('click', () => {
    const x = MESA.deixa;
    if (x) api('DELETE', `/api/queue/${encodeURIComponent(x.qid)}`).catch(err => avisar(err.message, true));
  });
  $('#m-aleatorio').addEventListener('click', () => { $('#b-aleatorio').click(); ligarChave($('#m-aleatorio'), !!(S.state && S.state.shuffle)); });
  $('#m-repetir').addEventListener('click', () => { $('#b-repetir').click(); ligarChave($('#m-repetir'), !!(S.state && S.state.loop)); });
  $('#m-parecidas').addEventListener('click', () => { if (!S.state) return; const v = !S.state.auto; ligarChave($('#m-parecidas'), v); ajustar('auto', v); });
  $('#pads-grade').addEventListener('click', e => {
    const b = e.target.closest('.pad[data-id]');
    if (b && Date.now() - seguradaEm > 900) tocar(b.dataset.id, { por_cima: true });
  });
  $('#pads-grade').addEventListener('contextmenu', e => {
    const b = e.target.closest('.pad[data-id]'); if (!b) return;
    e.preventDefault(); seguradaEm = Date.now();
    fecharMenu(false); abrirMenu(b, { tipo: 'disco', id: b.dataset.id });
  });
  for (const [b, lado] of [[$('#prat-esq'), -1], [$('#prat-dir'), 1]]) b.addEventListener('click', () => {
    const ul = $('#estante'), fim = ul.scrollWidth - ul.clientWidth, comp = reduz.matches ? 'auto' : 'smooth';
    if (lado > 0 ? ul.scrollLeft >= fim - 2 : ul.scrollLeft <= 2) ul.scrollTo({ left: lado > 0 ? 0 : fim, behavior: comp });
    else ul.scrollBy({ left: lado * Math.max(120, ul.clientWidth * .8), behavior: comp });
  });
  $('#estante').addEventListener('scroll', () => requestAnimationFrame(setasPrateleira), { passive: true });
  new ResizeObserver(setasPrateleira).observe($('#estante'));
  mqUnica.addEventListener('change', montarMesa);
  montarMesa();
}
/* DESK-BUTTONS-JS-FIM */
