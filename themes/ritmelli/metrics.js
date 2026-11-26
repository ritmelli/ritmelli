/* METRICS-JS-INICIO */
'use strict';
/* ---------- dados de uso e erros (metricas.py), so no PC: a linha no Microfone e fone e o aviso de quem ainda nao
   escolheu. A escolha feita aqui vale sobre a da pagina do instalador ---------- */
let metricasVistas = null;   // a ultima resposta do GET/POST /api/metricas
function mostrarMetricas(m) {
  metricasVistas = m;
  const on = m.situacao === 'ligada';
  $('#dd-met').hidden = !(m.situacao === 'ligada' || m.situacao === 'desligada');
  $('#dd-met-txt').textContent = I18N.t(on ? 'metrics.on' : 'metrics.off');
  $('#dd-met-btn').textContent = I18N.t(on ? 'metrics.turnOff' : 'metrics.turnOn');
  $('#dd-met-btn').dataset.ligar = on ? '0' : '1';
  $('#dd-met-pol').href = $('#dm-pol').href = m.politica;
}
async function lerMetricas() {
  if (!pode('GET /api/metricas')) return null;
  try { const m = await api('GET', '/api/metricas'); mostrarMetricas(m); return m; } catch (e) { return null; }
}
async function escolherMetricas(ligar) {
  try { mostrarMetricas(await api('POST', '/api/metricas', { ligar })); }
  catch (e) { avisar(I18N.t('metrics.saveFailed', { reason: e.message }), true); }
}
function abrirAvisoMetricas(focoNoEnviar) {
  const d = $('#dlg-metricas');
  d.returnValue = '';
  d.showModal();
  if (focoNoEnviar) d.querySelector('button[value=sim]').focus();
}
$('#dd-met-btn').addEventListener('click', e => {
  const ligar = e.currentTarget.dataset.ligar === '1', m = metricasVistas;
  // ligar com a escolha feita num texto de antes do de agora: primeiro o aviso, com o texto de agora, e o Enviar dele liga
  if (ligar && m && m.texto < m.texto_atual) abrirAvisoMetricas(true);
  else escolherMetricas(ligar);
});
let metricasPedidas = false;
// o aviso: para quem nao escolheu, e para quem ligou num texto de antes do de agora (o Esc nao grava, e ele volta)
const metricasPrecisa = m => m.situacao === 'decidir' || (m.situacao === 'ligada' && m.texto < m.texto_atual);
async function metricasSePrecisar() {
  if (metricasPedidas || dialogoAberto()) return;
  const m = await lerMetricas();
  if (!m || !metricasPrecisa(m) || dialogoAberto()) return;
  metricasPedidas = true;
  abrirAvisoMetricas(m.situacao === 'ligada');   // quem ja enviava segue com um Enter
}
$('#dlg-metricas').addEventListener('close', () => {
  const v = $('#dlg-metricas').returnValue;
  if (v === 'sim' || v === 'nao') escolherMetricas(v === 'sim');   // o Esc nao escolhe: pergunta na proxima vez
});
/* METRICS-JS-FIM */
