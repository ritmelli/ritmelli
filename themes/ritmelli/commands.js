/* COMMANDS-JS-INICIO */
'use strict';
/* ---------- comandos ---------- */
async function tocar(id, extra) {
  try { await api('POST', '/api/play', { id, ...(extra || {}) }); return true; }
  catch (e) { avisar(e.message, true); return false; }
}
async function cmd(path, okTxt) {
  try { await api('POST', path); if (okTxt) avisar(okTxt); }
  catch (e) { avisar(e.message, true); }
}
function alternar() {
  const s = S.state;
  // sons por cima com o disco parado (ou sem disco): o Pausar so cala os sons, o disco fica como esta
  const tocando = s && s.track && (s.status === 'playing' || s.status === 'buffering');
  if (s && s.por_cima && s.por_cima.length && !tocando) { cmd('/api/pause'); return; }
  if (!s || !s.track) {
    avisar(!S.lib.length ? I18N.t('shelf.emptyToast')
      : celular() ? I18N.t('deck.pickFirstPhone')
      : I18N.t('deck.pickFirstPc'));
    return;
  }
  if (s.status === 'ended') cmd('/api/resume');
  else cmd('/api/toggle');
}

const enviando = {}, ultimoEnvio = {};
function ajustar(k, v) {
  S.segurando[k] = Date.now();
  if (S.state) S.state[k] = v;
  clearTimeout(enviando[k]);
  const manda = () => {
    ultimoEnvio[k] = Date.now();
    api('POST', '/api/settings', { [k]: v }).catch(e => avisar(e.message, true));
  };
  if (Date.now() - (ultimoEnvio[k] || 0) > 110) manda(); else enviando[k] = setTimeout(manda, 110);
}
/* COMMANDS-JS-FIM */
