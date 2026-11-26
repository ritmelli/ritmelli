/* DEVICES-JS-INICIO */
'use strict';
async function abrirDispositivos() {
  const d = $('#dlg-disp');
  const msg = $('#dd-msg'); msg.className = 'msg-dlg'; msg.textContent = I18N.t('devices.reading');
  $('#dd-mic').disabled = $('#dd-mon').disabled = true;
  lerMetricas();
  d.showModal();
  try {
    const r = await api('GET', '/api/devices');
    preencherDispositivos(r);
    msg.textContent = '';
  } catch (e) { msg.className = 'msg-dlg erro'; msg.textContent = e.message; }
}
/* a escolha gravada que esta desligada nao entra na lista (08/11): fica marcado o que esta em uso, e a escolha volta
   sozinha quando o aparelho voltar */
function opcoes(sel, lista, atual, emUso) {
  sel.replaceChildren();
  for (const [v, t] of lista) { const o = el('option', null, t); o.value = v; sel.append(o); }
  const tem = v => v != null && [...sel.options].some(o => o.value === v);
  sel.value = tem(atual) ? atual : tem(emUso) ? emUso : 'default';
}
function preencherDispositivos(r) {
  const cur = r.current || {}, act = r.active || {};
  S.disp = r;
  const semCabo = n => !/cable/i.test(n);
  // o padrao que e o cabo cede ao primeiro microfone de verdade, como no motor
  const micPadrao = r.default_input && !semCabo(r.default_input) ? (r.inputs || []).find(semCabo) : r.default_input;
  opcoes($('#dd-mic'), [['default', I18N.t('devices.windowsDefault', { name: micPadrao || I18N.t('devices.none') })], ...(r.inputs || []).filter(semCabo).map(n => [n, n])], cur.mic || 'default', act.mic);
  opcoes($('#dd-mon'), [['default', I18N.t('devices.windowsDefault', { name: r.default_output || I18N.t('devices.none') })], ...(r.outputs || []).filter(semCabo).map(n => [n, n]), ['', I18N.t('devices.noMonitor')]], cur.monitor == null ? 'default' : cur.monitor, act.monitor);
  $('#dd-mic').disabled = $('#dd-mon').disabled = false;
  mostrarAtivos(act, r.filtro);
}
/* o microfone em uso e se a musica chega nele: o filtro do Ritmelli (o instalador poe em todos; o que aparece depois o
   app prepara sozinho, e o som do PC some uns segundos). A frase inteira por chave, com o nome dentro */
function mostrarAtivos(act, f) {
  const prep = S.state && S.state.microfone && S.state.microfone.preparando;
  const k = !act.mic ? 'devices.inUse' : prep ? 'devices.inUsePreparing'
    : f && !(f.filtro && f.melhorias) ? 'devices.inUseNotReady' : f ? 'devices.inUseReady' : 'devices.inUse';
  $('#dd-mic-uso').textContent = I18N.t(k, { name: act.mic || I18N.t('devices.none') });
  $('#dd-mon-uso').textContent = act.monitor ? I18N.t('devices.inUse', { name: act.monitor }) : I18N.t('devices.inUseNoMonitor');
}
async function trocarDispositivo(k, v) {
  const msg = $('#dd-msg'); msg.className = 'msg-dlg'; msg.textContent = I18N.t('devices.switching');
  $('#dd-mic').disabled = $('#dd-mon').disabled = true;
  try {
    await api('POST', '/api/devices', { [k]: v });
    const r = await api('GET', '/api/devices');
    preencherDispositivos(r);
    msg.textContent = I18N.t('devices.switched');
  } catch (e) {
    msg.className = 'msg-dlg erro'; msg.textContent = I18N.t('devices.switchFailed', { reason: e.message });
    $('#dd-mic').disabled = $('#dd-mon').disabled = false;
  }
}
$('#dd-mic').addEventListener('change', e => trocarDispositivo('mic', e.target.value));
$('#dd-mon').addEventListener('change', e => trocarDispositivo('monitor', e.target.value));

async function desligar() {
  const ok = await confirmar(I18N.t('shutdown.title'), I18N.t('shutdown.text'), I18N.t('top.shutdown'));
  if (!ok) return;
  try { await api('POST', '/api/shutdown'); S.desligado = true; mostrarFora(); }
  catch (e) { avisar(e.message, true); }
}
function bindDeviceButtons() {
  $('#b-disp').addEventListener('click', abrirDispositivos);
  $('#dica-ouvir').addEventListener('click', e => { if (e.target.closest('.ir-disp')) abrirDispositivos(); });
  $('#b-desligar').addEventListener('click', desligar);
}
/* DEVICES-JS-FIM */
