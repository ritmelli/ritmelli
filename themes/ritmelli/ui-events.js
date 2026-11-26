/* UI-EVENTS-JS-INICIO */
'use strict';
/* ---------- eventos da interface ---------- */
if (scriptLoaded('shelf.js')) bindShelfClick();
if (!scriptsMissing().length) bindVoiceEffects();
matchMedia('(max-width: 899.98px)').addEventListener('change', () => {
  abrirGaveta(S.gaveta); if (!celular()) abrirPalco(false); else abrirDisco(false); inertPalco(); textoBusca();
});
if (scriptLoaded('stage.js')) bindMiniBar();
$('#b-mudo-topo').addEventListener('click', mutarComAviso);
if (scriptLoaded('disc-page.js')) bindDiscPage();
/* na mesa a prateleira, os pedais e a maleta correm de lado: a rodinha do mouse, que rola em pe, corre os tres. O
   ouvinte so existe com a mesa montada (montarMesa): o wheel que bloqueia a rolagem, preso na pedaleira em toda tela,
   mudava o desenho do feltro no celular (um a seis pontos de cor, no compara) */
const rodaDeLado = e => {
  if (!paginaUnica() || e.ctrlKey || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
  const ul = e.currentTarget;
  if (ul.scrollWidth <= ul.clientWidth + 1) return;
  e.preventDefault();
  ul.scrollLeft += e.deltaY * (e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? ul.clientWidth : 1);
};
function rodinhas(on) {
  for (const rolo of [$('#estante'), $('#gaveta'), $('#gaveta-dir'), $('.fila-parede .lista-fila')])
    rolo[on ? 'addEventListener' : 'removeEventListener']('wheel', rodaDeLado, { passive: false });
}
if (scriptLoaded('stage.js')) bindStageButtons();
/* a pilha e [pagina, busca, palco, opcoes]: cada voltar fecha o que esta por cima. Entrada
   morta (de antes de a pagina recarregar, ou que diz aberto o que ja fechou) o voltar pula:
   senao um voltar nao fazia nada, e a busca so fechava no segundo (18/10) */
addEventListener('popstate', e => {
  // so a mesma pagina chega aqui pelo popstate: marca de outra carga e entrada de uma vida que
  // ja acabou (com ela, a base dessa vida: o voltar dali e para sair)
  const alheia = !!e.state && (e.state.vida ? e.state.vida !== VIDA : nossa(e.state));
  const st = alheia ? {} : e.state || {};
  if (folhaNaHistoria && !st.folha) { folhaNaHistoria = false; fecharMenu(false); }
  if (!st.palco) { palcoNaHistoria = false; abrirPalco(false); }
  if (!st.palco && !st.busca) { buscaNaHistoria = false; if (S.busca) { fecharBusca(); $('#q').value = ''; } }
  if (alheia || (st.folha && $('#menu').hidden) || (st.palco && !S.palco) || (st.busca && !st.palco && !S.busca)) {
    if (st.busca && !S.busca) buscaNaHistoria = false;
    history.back();
  }
});
if (scriptLoaded('stage.js')) bindStageGestures();
if (scriptLoaded('shelf.js')) bindShelf();
/* no toque a barra so muda arrastando o cursor: encostar em outro ponto da canaleta (sem
   querer, rolando a pagina) pulava o volume ou a faixa para la; o mouse
   e o teclado seguem como antes */
const CURSOR_PX = 16, DEDO_PX = 24;
document.querySelectorAll('input[type=range]').forEach(r => {
  let vale = true, antes = r.value;
  r.addEventListener('pointerdown', e => {
    antes = r.value;
    if (e.pointerType !== 'touch') { vale = true; return; }
    const b = r.getBoundingClientRect(), min = +r.min, max = +r.max;
    const cw = PALCO.k * (parseFloat(getComputedStyle(r).getPropertyValue('--cursor-w')) || CURSOR_PX);   // o pino do palco tem 24 px
    const x = b.left + cw / 2 + (max > min ? (r.value - min) / (max - min) : 0) * (b.width - cw);
    vale = Math.abs(e.clientX - x) <= DEDO_PX;
  }, { capture: true, passive: true });
  // o change do toque chega depois do pointerup: so o proximo gesto ou tecla destrava
  r.addEventListener('keydown', () => { vale = true; }, true);
  const barrar = e => { if (!vale) { e.stopImmediatePropagation(); r.value = antes; } };
  r.addEventListener('input', barrar, true);
  r.addEventListener('change', barrar, true);
});
if (scriptLoaded('receiver.js')) bindReceiver();
if (scriptLoaded('turntable.js')) bindTurntable();
if (!scriptsMissing().length) bindSearch();
if (scriptLoaded('phone.js')) bindPhoneButton();
if (scriptLoaded('devices.js')) bindDeviceButtons();

function campoDeTexto(t) {
  if (!t || !t.closest) return false;
  if (t.closest('textarea, select, [contenteditable="true"]')) return true;
  const i = t.closest('input');
  return !!i && !['range', 'checkbox', 'radio', 'button', 'submit'].includes(i.type);
}
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (!$('#menu').hidden) { if (e.key === 'Escape') { e.preventDefault(); fecharMenu(true); } return; }
  if (S.palco && e.key === 'Escape' && !dialogoAberto()) { e.preventDefault(); fecharPalco(); return; }
  if (S.disco && !paginaUnica() && e.key === 'Escape' && !dialogoAberto() && !campoDeTexto(e.target)) { e.preventDefault(); abrirDisco(false); return; }
  // (#114) a busca aberta tambem esta por cima: o Esc fecha ela, como no campo, e a musica segue (antes ele chegava ao
  // fim e parava a musica). O foco que estava nos resultados, que somem, vai para o campo, como no voltar
  if (S.busca && e.key === 'Escape' && !dialogoAberto() && !campoDeTexto(e.target)) {
    e.preventDefault();
    const nosResultados = $('#vista-busca').contains(document.activeElement);
    fecharBusca();
    if (nosResultados && !toque()) $('#q').focus();
    return;
  }
  if (dialogoAberto() || campoDeTexto(e.target)) return;
  if (e.code === 'Space' || e.key === ' ') { e.preventDefault(); if (!e.repeat) alternar(); }
  else if (/^[1-9]$/.test(e.key)) { const it = S.lib[+e.key - 1]; if (it) { e.preventDefault(); tocar(it.id); } }
  else if (e.key === '0') {
    e.preventDefault();
    if (!e.repeat && S.state && S.state.effect !== SEM_EFEITO) escolherEfeito(SEM_EFEITO);
  }
  else if (e.key === 'Escape') { e.preventDefault(); if (S.state && S.state.track) cmd('/api/stop'); }
});
document.addEventListener('keyup', e => {
  if ((e.code === 'Space' || e.key === ' ') && !dialogoAberto() && !campoDeTexto(e.target) && $('#menu').hidden) e.preventDefault();
});
/* UI-EVENTS-JS-FIM */
