/* DISC-PAGE-JS-INICIO */
'use strict';
/* ---------- pagina do disco (computador): a seta da barra de baixo troca a parede pelo toca-discos, o receiver e a
   maleta do A seguir, como a pagina do player do YouTube Music. A seta de novo, o Esc ou uma busca voltam ---------- */
/* pagina unica (computador largo): tudo numa tela so, a do toca-discos, que nao fecha */
const mqUnica = matchMedia('(min-width: 1400px) and (min-aspect-ratio: 20/19)');
function paginaUnica() { return mqUnica.matches; }
function abrirDisco(on) {
  on = !!on && !celular();
  if (!on && paginaUnica()) return;
  if (on === !!S.disco) return;
  S.disco = on;
  document.body.classList.toggle('com-disco', on);
  if (on) { fecharMenu(false); abrirMaleta(true); }
  else if (S.gaveta) abrirGaveta(false);
  const rot = on ? I18N.t('nav.backToShelf') : I18N.t('nav.openDeck'), seta = $('#mini-seta');
  $('#b-pagina').title = rot;
  seta.setAttribute('aria-expanded', on ? 'true' : 'false'); seta.setAttribute('aria-label', rot); seta.title = rot;
  rotularMini();
}
function bindDiscPage() {
  $('#b-pagina').addEventListener('click', () => abrirDisco(!S.disco));
  mqUnica.addEventListener('change', () => { if (paginaUnica()) abrirDisco(true); });
  if (paginaUnica()) abrirDisco(true);
}
/* DISC-PAGE-JS-FIM */
