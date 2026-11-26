/* WELCOME-JS-INICIO */
'use strict';
/* ---------- boas-vindas (so no PC): o passo a passo da primeira vez, quando o GET /api/boas-vindas diz. Fechar de
   qualquer jeito marca como vistas, e elas nao voltam. Abertas, conferem os dispositivos a cada 3 s: o microfone
   conectado com elas na tela acende sozinho ---------- */
let boasT = 0, boasPedidas = false;
async function boasVindasSePrecisar() {
  // pelo caps, como o botao Celular; o servidor tambem so diz que sim para o PC
  if (boasPedidas || !pode('POST /api/boas-vindas')) return;
  boasPedidas = true;
  let r;
  try { r = await api('GET', '/api/boas-vindas'); } catch (e) { return; }
  if (r.mostrar && !dialogoAberto()) { $('#dlg-boas').showModal(); conferirBoasVindas(); }
  else metricasSePrecisar();   // com as boas-vindas na tela, o aviso dos dados vem quando elas fecham
}
async function conferirBoasVindas() {
  clearTimeout(boasT);
  const d = $('#dlg-boas'), msg = $('#db-msg');
  if (!d.open) return;
  try {
    const r = await api('GET', '/api/devices'), act = r.active || {}, cur = r.current || {};
    S.disp = r;
    // como no seletor de Microfone e fone: o jogo tambem mostra "Padrao", e e assim que a pessoa compara os dois
    const nome = (escolha, ativo) => escolha === 'default' ? I18N.t('welcome.devices.windowsDefault', { name: ativo }) : ativo;
    $('#db-disp-l').className = `lampada ${act.mic ? 'acesa' : 'alerta'}`;
    if (act.mic) $('#db-disp').replaceChildren(
      el('span', null, I18N.t('welcome.devices.mic', { name: nome(cur.mic || 'default', act.mic) })),
      el('span', null, I18N.t('welcome.devices.monitor', { name: act.monitor ? nome(cur.monitor == null ? 'default' : cur.monitor, act.monitor)
                                                                             : I18N.t('welcome.devices.noMonitor') })));
    else $('#db-disp').textContent = I18N.t('welcome.devices.noMic');
    msg.textContent = '';
  } catch (e) { msg.className = 'msg-dlg erro'; msg.textContent = e.message; }
  if (d.open) boasT = setTimeout(conferirBoasVindas, 3000);
}
$('#dlg-boas').addEventListener('close', () => {
  clearTimeout(boasT);
  api('POST', '/api/boas-vindas').catch(() => {});
  if ($('#dlg-boas').returnValue === 'buscar') $('#q').focus();
  setTimeout(metricasSePrecisar, 0);   // depois de o dialogo sair da tela
});
$('#db-trocar').addEventListener('click', abrirDispositivos);
// a troca feita no dialogo de dispositivos aparece no passo na hora, sem esperar a proxima conferencia
$('#dlg-disp').addEventListener('close', () => { if ($('#dlg-boas').open) conferirBoasVindas(); });
$('#db-cel').addEventListener('click', abrirCelular);
/* WELCOME-JS-FIM */
