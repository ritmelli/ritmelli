/* UPDATE-JS-INICIO */
'use strict';
/* ---------- versao nova (atualizacao.py): so no PC, que e onde o instalador roda. O aviso vem no estado ao vivo, e o
   dialogo pede as notas; baixado e conferido o setup, o Instalar agora roda o instalador, que fecha o Ritmelli e abre de
   novo. Na atualizacao automatica (a.automatica, atualizador.py), quem baixa e a tarefa do Windows, e a versao entra
   sozinha ao fechar: o Instalar agora so adianta isso ---------- */
function desenharAtualizacao() {
  const a = S.state && S.state.atualizacao, b = $('#b-atualizar');
  b.hidden = !(pode('POST /api/atualizacao/baixar') && a && a.nova);
  if (a && a.nova) b.title = I18N.t('update.titleVersion', { version: a.nova });
  if ($('#dlg-atualizar').open && a) pintarAtualizacao(a);
}
function pintarAtualizacao(a) {
  const ok = $('#da-ok'), barra = $('#da-barra'), msg = $('#da-msg');
  barra.hidden = a.estado !== 'baixando';
  barra.style.setProperty('--p', a.progresso || 0);
  barra.setAttribute('aria-valuenow', Math.round((a.progresso || 0) * 100));
  ok.disabled = ['baixando', 'consultando', 'instalando'].includes(a.estado);
  ok.textContent = a.estado === 'pronta' ? I18N.t('update.install') : a.estado === 'baixando' ? I18N.t('update.downloading', { pct: Math.round((a.progresso || 0) * 100) }) : I18N.t('update.download');
  msg.className = 'msg-dlg' + (a.erro ? ' erro' : '');
  msg.textContent = a.erro ? textoMsg(a.erro) : a.estado === 'pronta' ? I18N.t(a.automatica ? 'update.autoReady' : 'update.windowsAsks') : '';
}
async function abrirAtualizacao() {
  let a;
  try { a = await api('GET', '/api/atualizacao'); } catch (e) { avisar(e.message, true); return; }
  if (!a.nova) { avisar(I18N.t('update.none')); return; }
  $('#da-t').textContent = I18N.t('update.titleVersion', { version: a.nova.versao });
  $('#da-p').textContent = I18N.t('update.info', { current: a.versao, mb: Math.max(1, Math.round(a.nova.tamanho / 1048576)) });
  // as notas na lingua da tela; sem elas, as da outra (a versao pode vir so com as em portugues)
  const ns = a.nova.notas, notas = [ns[I18N.lingua], ns.en, ns.pt_BR].find(x => x && x.length) || [];
  const ul = $('#da-notas');
  ul.replaceChildren(...notas.map(n => el('li', null, n)));
  ul.hidden = !notas.length;
  pintarAtualizacao(a);
  $('#dlg-atualizar').showModal();
}
$('#b-atualizar').addEventListener('click', abrirAtualizacao);
$('#da-ok').addEventListener('click', async () => {
  const a = S.state && S.state.atualizacao, msg = $('#da-msg');
  try {
    if (a && a.estado === 'pronta') {
      await api('POST', '/api/atualizacao/instalar');
      S.atualizando = a.nova;
      $('#dlg-atualizar').close();
      mostrarFora();
    } else {
      await api('POST', '/api/atualizacao/baixar');
    }
  } catch (e) { msg.className = 'msg-dlg erro'; msg.textContent = e.message; }
});
/* o instalador fecha o Ritmelli: no lugar do fora do ar, a tela diz que ele volta sozinho */
function mostrarAtualizando(f) {
  $('#fora-tt').textContent = I18N.t('update.updatingTitle');
  $('#fora-p').textContent = I18N.t('update.updatingText', { version: S.atualizando });
  $('#lamp').className = 'lampada alerta piscando';
  f.hidden = false;
}
/* UPDATE-JS-FIM */
