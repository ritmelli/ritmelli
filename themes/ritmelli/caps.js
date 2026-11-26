/* CAPS-JS-INICIO */
'use strict';
/* ---------- o que esta pagina pode: o caps que o servidor manda (no /api/state, no 401 do pareamento e no comeco do
   SSE), e nao o endereco dela. Ate ele chegar, nenhum controle do PC aparece ---------- */
const pode = rota => !!(S.caps && S.caps.rotas && S.caps.rotas.includes(rota));
function definirCaps(c) {
  const metricasAntes = pode('GET /api/metricas');
  S.caps = c && Array.isArray(c.rotas) ? c : null;
  for (const b of document.querySelectorAll('[data-pode]')) b.hidden = !pode(b.dataset.pode);   // only for whoever may call it
  desenharAtualizacao();
  if (!pode('GET /api/metricas')) $('#dd-met').hidden = true;
  else if (!metricasAntes && $('#dlg-disp').open) lerMetricas();   // o Microfone e fone aberto antes do caps chegar
}
/* CAPS-JS-FIM */
