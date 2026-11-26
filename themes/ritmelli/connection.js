/* CONNECTION-JS-INICIO */
'use strict';
/* ---------- conexao ---------- */
let es = null, foraT = null, reconT = null;
// o transporte.js que nao carregou (o servidor fora quando a pagina abriu): a conexao tenta carregar de novo, uma
// carga por vez e a cada 3 s, e com ele de volta a pagina segue a carga normal
let buscandoTransporte = false;
function carregarTransporte() {
  if (buscandoTransporte) return;
  buscandoTransporte = true;
  const s = document.createElement('script');
  s.src = 'transporte.js';
  s.onload = () => {
    buscandoTransporte = false;
    // carregou sem definir o TRANSPORTE (o portal do Wi-Fi respondendo com uma pagina, o script cortado): o mesmo
    // prazo do erro, sem laco
    if (typeof TRANSPORTE === 'undefined') { s.remove(); reconT = setTimeout(conectar, 3000); return; }
    carregar();
  };
  s.onerror = () => { buscandoTransporte = false; s.remove(); reconT = setTimeout(conectar, 3000); };
  document.head.append(s);
}
function conectar() {
  clearTimeout(reconT);
  if (typeof TRANSPORTE === 'undefined') { carregarTransporte(); return; }
  if (es) es.fechar();
  try { es = TRANSPORTE.eventos('/api/events'); } catch (e) { reconT = setTimeout(conectar, 3000); return; }
  const fonte = es;
  es.ao('open', () => online(true));
  // o primeiro evento: o que esta conexao pode (o papel nao muda nela; a revogacao a encerra)
  es.ao('caps', c => definirCaps(c));
  es.ao('desconectado', () => {
    // o PC desconectou este celular: a tela do codigo, e o caps de antes de parear vem no 401 do /api/state
    pedirPareamento(true);
    api('GET', '/api/state').catch(() => {});
  });
  es.ao('state', st => {
    online(true); S.state = st;
    desenharFaixa(); desenharReceptor(); desenharFila(); if (S.busca) atualizarResultados();
    desenharAtualizacao();
  });
  es.ao('library', lib => { S.lib = ordenarLib(lib); S.libOk = true; desenharPrateleira(); desenharFila(); if (S.busca) atualizarResultados(); });
  es.ao('jobs', jobs => {
    const antes = new Map(S.jobs.map(j => [j.id, j.status]));
    S.jobs = jobs;
    for (const j of S.jobs) if (j.status === 'error' && antes.get(j.id) === 'running') avisar(I18N.t('download.failed', { label: j.label, reason: motivoDownload(detalheMsg(j.error)) }), true);
    desenharPrateleira(); desenharFila(); if (S.busca) atualizarResultados();
  });
  es.ao('tick', t => {
    S.pos = t.pos; S.levels = t.levels || S.levels;
    S.posEm = performance.now(); S.posEmDe = t.pos;   // quando a posicao chegou: o relogio do visor mede o erro ali
    desenharTempo(); agulhasPixel();
  });
  es.aoFalhar(() => {
    if (S.pareando) return;
    online(false);
    if (!fonte.fechada()) return;
    fonte.fechar();
    // recusada de cara: o servidor fora, ou o 401 do celular desconectado no PC (o fluxo de eventos nao diz o status;
    // o /api/state diz, e o api() ja abre o pedido do codigo)
    api('GET', '/api/state').then(() => true, e => e.status !== 401)
      .then(volta => { if (volta && !S.pareando) reconT = setTimeout(conectar, 3000); });
  });
}
/* o aviso de fora do ar so conta o tempo com a pagina na tela (ao desbloquear o celular o aviso
   aparecia por uns 0,8 s): com o celular bloqueado a conexao cai e o prazo vencia escondido. Escondida, a pagina
   nunca arma o aviso; ao voltar, reconecta na hora (a conexao do tempo bloqueado pode estar morta sem ter avisado,
   e a nova traz o estado) e o prazo comeca dali */
function armarFora() {
  clearTimeout(foraT);
  if (document.hidden || S.pareando) return;
  foraT = setTimeout(() => { if (!S.online && !document.hidden) mostrarFora(); }, S.desligado ? 0 : 2500);
}
// (#107) o celular que muda de rede com o cartao aberto (sai dos dados moveis, liga o Wi-Fi): o texto acompanha
const redeMudou = () => { if (!$('#fora').hidden && !S.online && !S.desligado && !S.atualizando) mostrarFora(); };
if (typeof $ === 'function') {
  addEventListener('online', redeMudou); addEventListener('offline', redeMudou);
  if (navigator.connection) navigator.connection.addEventListener('change', redeMudou);
}
function online(on) {
  if (on === S.online) return;
  S.online = on; agulhasPixel();
  const lamp = $('#lamp'), cx = $('#conexao');
  if (on) {
    S.jaConectou = true; S.desligado = false;
    if (S.atualizando) { location.reload(); return; }   // a versao nova abriu: a pagina passa a ser a dela
    clearTimeout(foraT); $('#fora').hidden = true;
    if (!S.efeitos && S.erroEfeitos) carregarEfeitos();
    lamp.className = 'lampada acesa'; cx.textContent = I18N.t('app.connected');
  } else {
    lamp.className = 'lampada alerta piscando'; cx.textContent = I18N.t('app.reconnecting');
    armarFora();
  }
  cx.classList.toggle('sr', on);   // conectado, a lampada acesa ja diz: o "ligado" fica so para o leitor de tela
}
function mostrarFora() {
  const f = $('#fora');
  fecharMenu(false);
  if (S.atualizando) { mostrarAtualizando(f); return; }
  if (S.desligado) {
    $('#fora-tt').textContent = I18N.t('offline.offTitle');
    I18N.rico($('#fora-p'), 'offline.offText');
  } else if (!(S.caps ? S.caps.papel === 'pc' : typeof TRANSPORTE === 'undefined' || TRANSPORTE.local)) {
    // (#107) no celular, o que mais cai e o caminho ate o computador (o celular nos dados moveis, sem Wi-Fi, numa rede
    // de convidados), e nao o Ritmelli: o cartao diz so o que se sabe, e o que o navegador conta da conexao (sem
    // nenhuma; nos dados moveis, o Chrome do Android pela Network Information API)
    const c = navigator.connection;
    $('#fora-tt').textContent = I18N.t('offline.phone.title');
    $('#fora-p').textContent = I18N.t(navigator.onLine === false ? 'offline.phone.noConnection'
      : c && c.type === 'cellular' ? 'offline.phone.mobileData' : 'offline.phone.text');
  } else {
    $('#fora-tt').textContent = I18N.t(S.jaConectou ? 'offline.stopped' : 'offline.notResponding');
    I18N.rico($('#fora-p'), 'offline.downText', { folder: '%LOCALAPPDATA%\\Ritmelli\\logs' });
  }
  $('#lamp').className = 'lampada'; $('#conexao').textContent = S.desligado ? I18N.t('app.off') : I18N.t('app.offline');
  $('#conexao').classList.remove('sr');
  f.hidden = false;
}
/* CONNECTION-JS-FIM */
