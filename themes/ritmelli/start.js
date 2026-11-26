/* START-JS-INICIO */
'use strict';
bindDeskButtons();

/* ---------- inicio ---------- */
montarMostradores();
new ResizeObserver(desenharVUs).observe($('.janela'));
$('#mini-cortar').innerHTML = $('#palco-cortar').innerHTML = IC_MIC;
inertPalco();
FADERS.forEach(([fi]) => pintarFader($(fi)));
if (location.hash === '#efeitos' && !celular()) abrirGaveta(true);
function carregar() {
  if (scriptsMissing().length) return;
  const geracao = geracaoPareamento;
  Promise.all([api('GET', '/api/state'), api('GET', '/api/library'), api('GET', '/api/jobs')])
    .then(([st, lib, jobs]) => {
      // o celular desconectado (ou pareado de novo) enquanto esta carga corria: ela nao vale mais
      if (S.pareando || geracao !== geracaoPareamento) return;
      S.state = st; S.pos = st.pos || 0; S.levels = st.levels || S.levels; S.lib = ordenarLib(lib); S.libOk = true; S.jobs = jobs;
      definirCaps(st.caps);
      online(true); desenharFaixa(); desenharReceptor(); desenharPrateleira(); desenharFila();
      boasVindasSePrecisar();
    })
    .catch(e => {
      if (geracao !== geracaoPareamento) return;   // a carga de antes do pareamento de agora: o erro dela nao vale mais
      if (e.status !== 401) { online(false); return; }
      // o codigo do QR so se usa sem pareamento: ja pareado (ou no proprio PC), ele segue valendo para outro celular
      if (codigoQR) { const c = codigoQR; codigoQR = null; parear(c); }
    })
    .finally(() => { if (!S.pareando && geracao === geracaoPareamento) conectar(); });
}
document.addEventListener('DOMContentLoaded', () => {
  if (scriptsMissing().length) return;
  carregarEfeitos();
  carregar();
  // registered after carregar(): the browser can run events while it loads the ui-events.js above, and a tab shown in
  // that gap would connect before the page starts
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { clearTimeout(foraT); return; }
    if (S.desligado || S.pareando) return;
    conectar();
    if (!S.online) armarFora();
  });
});
/* START-JS-FIM */
