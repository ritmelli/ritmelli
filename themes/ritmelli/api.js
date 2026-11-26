/* API-JS-INICIO */
'use strict';
const SITUACAO = { idle: I18N.t('deck.status.idle'), buffering: I18N.t('deck.status.buffering'), playing: I18N.t('deck.status.playing'),
                   paused: I18N.t('deck.status.paused'), ended: I18N.t('deck.status.ended') };
function semCaminho(t) { return String(t || '').replace(/[A-Za-z]:\\(?:[^\\\s]+\\)+([^\\\s]+)/g, '$1'); }
/* a mensagem do servidor ({key, params, text}, o formato no API.md) na lingua de quem usa: a chave pelos arquivos do
   tema, com os params (o param que e outra mensagem tambem se traduz); sem a chave, ou com uma que o tema nao tem, o
   texto em ingles dela. O caminho do Windows sai: o nome do arquivo basta */
function textoMsg(m) {
  if (!m) return '';
  if (typeof m === 'string') return semCaminho(m);
  if (!m.key || !I18N.tem(m.key)) return semCaminho(m.text);
  const p = {};
  for (const [k, v] of Object.entries(m.params || {})) p[k] = v && typeof v === 'object' ? textoMsg(v) : typeof v === 'string' ? semCaminho(v) : v;
  return I18N.t(m.key, p);
}
/* o detalhe tecnico de uma mensagem (o motivo do yt-dlp, na busca e no download), para a letra pequena */
function detalheMsg(m) {
  const r = m && m.params && m.params.reason;
  return r ? textoMsg(r) : '';
}

// sobe a cada pareamento aceito: o 401 de um pedido feito antes dele (que chega atrasado) nao volta a tela do codigo
let geracaoPareamento = 0;
async function api(method, path, data) {
  const geracao = geracaoPareamento;
  let r;
  try {
    r = await TRANSPORTE.pedir(method, path, data);
  } catch (e) {
    // status 0: nenhuma resposta (a busca testa o status, e nao o texto)
    const x = new Error(I18N.t('error.noResponse')); x.status = 0;
    throw x;
  }
  const j = r.json;
  if (!r.ok || (j && j.ok === false)) {
    // o 401 do pareamento traz o caps de antes de parear: a tela do codigo, sem os controles do PC
    if (r.status === 401 && j && j.parear && geracao === geracaoPareamento) pedirPareamento(j.desconectado, j.caps);
    // a mensagem do servidor ja traduzida; ela mesma segue no erro, para quem decide pelo tipo (a busca)
    const m = j && j.error;
    const e = new Error(m ? textoMsg(m) : I18N.t('error.generic', { status: r.status }));
    e.status = r.status; e.msg = m || null;
    throw e;
  }
  return j;
}
/* API-JS-FIM */
