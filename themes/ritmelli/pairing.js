/* PAIRING-JS-INICIO */
'use strict';
/* ---------- pareamento (no celular): a API responde 401 ate o celular mandar o codigo que o PC mostra. O QR ja
   traz o codigo no link (?parear=), e ai nada se digita ---------- */
let codigoQR = new URLSearchParams(location.search).get('parear');
if (typeof $ === 'function') {
  if (codigoQR) history.replaceState(null, '', location.pathname + location.hash);  // o codigo usado nao fica no historico
}
function pedirPareamento(desconectado, caps) {
  definirCaps(caps || null);
  if (S.pareando || scriptsMissing().length) return;
  S.pareando = true; S.online = false;
  clearTimeout(reconT); clearTimeout(foraT);
  if (es) { es.fechar(); es = null; }
  fecharMenu(false);
  document.querySelectorAll('dialog[open]').forEach(d => d.close());
  $('#fora').hidden = true;
  $('#pa-desc').hidden = !desconectado;
  $('#pa-msg').textContent = '';
  $('#lamp').className = 'lampada'; $('#conexao').textContent = I18N.t('app.noAccess'); $('#conexao').classList.remove('sr');
  $('#tela-parear').hidden = false;
}
async function parear(codigo) {
  const msg = $('#pa-msg');
  msg.className = 'msg-dlg'; msg.textContent = I18N.t('pair.connecting');
  $('#pa-ok').disabled = true;
  try { await api('POST', '/api/parear', { codigo }); }
  catch (e) { msg.className = 'msg-dlg erro'; msg.textContent = e.message; $('#pa-ok').disabled = false; return; }
  $('#pa-ok').disabled = false;
  geracaoPareamento++;
  S.pareando = false;
  $('#tela-parear').hidden = true; $('#pa-in').value = '';
  avisar(I18N.t('pair.done'));
  carregar();
}
$('#form-parear').addEventListener('submit', e => {
  e.preventDefault();
  const c = $('#pa-in').value.replace(/\D/g, '');
  if (c.length !== 6) { const m = $('#pa-msg'); m.className = 'msg-dlg erro'; m.textContent = I18N.t('pair.needCode'); return; }
  $('#pa-in').blur();   // fecha o teclado: a resposta aparece embaixo do campo
  parear(c);
});
/* PAIRING-JS-FIM */
