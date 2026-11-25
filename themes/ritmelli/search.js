/* SEARCH-JS-INICIO */
'use strict';
/* ---------- busca ---------- */
function ehLink(q) { return /^https?:\/\//i.test(q) || /(youtu\.be\/|youtube\.com\/)/i.test(q); }
function idDoLink(q) { const m = q.match(/(?:v=|youtu\.be\/|shorts\/|embed\/)([A-Za-z0-9_-]{11})/); return m ? m[1] : null; }

async function buscar(q) {
  q = q.trim();
  if (!q) { $('#q').focus(); return; }
  abrirGaveta(false);   // os resultados aparecem na parede, onde a gaveta estava
  if (!celular() && !MESA.montada) abrirMaleta(false);   // a maleta aberta na prateleira nao entra na frente deles (na mesa a busca cai por cima de tudo)
  const seq = ++S.buscaSeq;
  if (ehLink(q)) {
    S.busca = { q, link: true, itens: [{ link: q, youtube_id: idDoLink(q) }], carregando: false, erro: null };
    $('#rolo-busca').scrollTop = 0;
    desenharBusca(); mostrarResultados(); return;
  }
  // buscando enquanto digita: os resultados da busca anterior ficam ate os novos chegarem
  S.busca = { q, link: false, itens: S.busca && !S.busca.link ? S.busca.itens : [], carregando: true, erro: null };
  $('#rolo-busca').scrollTop = 0;
  desenharBusca();
  mostrarResultados();
  try {
    const r = await api('GET', `/api/search?q=${encodeURIComponent(q)}&n=${POR_LEVA}`);
    if (seq !== S.buscaSeq || !S.busca) return;
    S.busca.itens = Array.isArray(r) ? r : [];
    S.busca.pedidos = POR_LEVA; S.busca.fim = !S.busca.itens.length;
  } catch (e) {
    if (seq !== S.buscaSeq || !S.busca) return;
    S.busca.erro = e.message; S.busca.semResposta = e.status === 0; S.busca.erroMsg = e.msg;
  }
  S.busca.carregando = false;
  desenharBusca();
  talvezMais();
}

/* carregar mais: chegando no fim da lista, pede a leva seguinte; o que ja
   esta na lista nao se repete. Servidor antigo devolve a primeira leva de novo: nada novo, fim */
const POR_LEVA = 20;
async function maisResultados() {
  const b = S.busca;
  if (!b || b.link || b.carregando || b.mais || b.fim || b.erro || !b.itens.length) return;
  b.mais = true; b.erroMais = null; desenharMais();
  try {
    const r = await api('GET', `/api/search?q=${encodeURIComponent(b.q)}&n=${POR_LEVA}&start=${b.pedidos || POR_LEVA}`);
    if (S.busca !== b) return;
    // o YouTube reordena as paginas a cada busca: a leva seguinte repete parte do que ja veio.
    // Acaba quando ele nao tem mais nada, em 200, ou depois de duas levas sem nada novo
    const lista = Array.isArray(r) ? r : [];
    const vistos = new Set(b.itens.map(x => x.youtube_id));
    const novos = lista.filter(x => x.youtube_id && !vistos.has(x.youtube_id));
    b.pedidos = (b.pedidos || POR_LEVA) + POR_LEVA;
    b.secas = novos.length ? 0 : (b.secas || 0) + 1;
    if (novos.length) b.itens = b.itens.concat(novos);
    if (!lista.length || b.secas >= 2 || b.pedidos >= 200) b.fim = true;
  } catch (e) {
    if (S.busca !== b) return;
    b.erroMais = e.message;
  }
  b.mais = false;
  desenharBusca();
  if (!b.erroMais) talvezMais();
}
/* o fim da lista ainda esta perto da tela depois da leva (lista curta, tela alta): pede mais */
function talvezMais() {
  const p = $('#mais-res');
  if (!S.busca || $('#vista-busca').hidden) return;
  const r = p.getBoundingClientRect(), c = $('#rolo-busca').getBoundingClientRect();
  const fundo = celular() ? innerHeight + 600 : Math.min(innerHeight, c.bottom) + 200;
  if (r.top < fundo) maisResultados();
}
function desenharMais() {
  const p = $('#mais-res'), b = S.busca;
  p.replaceChildren();
  if (!b || b.link || b.carregando || b.erro || !b.itens.length) return;
  if (b.mais) p.append(el('span', 'lampada acesa piscando'), document.createTextNode(I18N.t('search.loadingMore')));
  else if (b.erroMais) p.textContent = I18N.t('search.moreFailed');
  else if (b.fim) p.textContent = I18N.t('search.end');
}
new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) maisResultados(); }, { rootMargin: '0px 0px 600px 0px' })
  .observe($('#mais-res'));

/* no celular a busca entra na historia, como o palco: o voltar do Android fecha os resultados
   em vez de sair da pagina (review) */
let buscaNaHistoria = false;
function mostrarResultados() {
  if (matchMedia('(max-width: 899.98px)').matches) {
    // os resultados vem logo abaixo do campo: o topo mostra os dois, com a seta de voltar
    scrollTo({ top: 0, behavior: reduz.matches ? 'auto' : 'smooth' });
    if (!buscaNaHistoria) { history.pushState({ busca: true, vida: VIDA }, ''); buscaNaHistoria = true; }
  }
}
/* o motivo do download que falhou, pelo detalhe tecnico (o do yt-dlp, em ingles) */
function motivoDownload(t) {
  t = String(t || '');
  if (/unavailable|private/i.test(t)) return I18N.t('download.reason.unavailable');
  if (/429|too many/i.test(t)) return I18N.t('download.reason.rateLimit');
  if (/getaddrinfo|network|timed out|connection|resolve/i.test(t)) return I18N.t('download.reason.network');
  // o "not a bot" tambem diz "sign in", mas e o YouTube desconfiando dos pedidos, nao o video: vem antes
  if (/not a bot/i.test(t)) return I18N.t('download.reason.bot');
  if (/confirm your age|age[- ]restricted|inappropriate/i.test(t)) return I18N.t('download.reason.age');
  if (/sign in|members[- ]only|login/i.test(t)) return I18N.t('download.reason.login');
  return I18N.t('download.reason.generic');
}
function fecharBusca() {
  S.busca = null; S.buscaSeq++;
  desenharBusca();
  // fechou pelo botao ou tocando um resultado: tira a entrada, senao o voltar seguinte nao faria
  // nada; com o palco por cima (download que terminou tocando) o popstate pula ela depois
  if (buscaNaHistoria && !palcoNaHistoria) { buscaNaHistoria = false; history.back(); }
}
function naPrateleira(yid) { return yid ? S.lib.find(x => x.youtube_id === yid) : null; }
function jobDe(alvo) {
  if (!alvo) return null;
  // o servidor novo diz o alvo de cada download (inclusive os que a fila comecou); o antigo, so o mapa daqui
  return S.jobs.find(j => (S.jobAlvo[j.id] === alvo || j.alvo === alvo) && (j.status === 'running' || j.status === 'error'));
}
/* (#53) o salvar na prateleira do disco no prato e das linhas do A seguir: no que nao esta na prateleira (o do
   Automatico, que so toca pelo stream, e o da busca ou da fila ainda baixando, ou que falhou) e, com o visto que tira de
   novo, como na busca, no que chegou nela enquanto a pagina o mostrava. O que ja estava na prateleira fica sem: a fila
   inteira com o visto so repetiria o que ela e.
   O disco e o que o servidor baixa: o id do YouTube ou o link colado (de outro site, sem id do YouTube). O link que
   chegou se acha pelo item que o download dele trouxe: o servidor tira o download terminado da lista em 20 s, e a pagina
   guarda o que cada um trouxe (S.chegou) */
const alvoDisco = x => (x && (x.youtube_id || x.url || x.alvo)) || null;
function lembrarChegadas() {
  for (const j of S.jobs) {   // na ordem do servidor: o download mais novo do mesmo disco (baixado de novo) vale
    const a = S.jobAlvo[j.id] || j.alvo;
    if (j.status !== 'done' || !j.item_id || !a) continue;
    S.chegou.set(a, j.item_id);
    // o disco do prato passa para o item da prateleira quando o arquivo chega (o id dele, do YouTube ou do site): o
    // visto segue nele
    if (S.vistoFora.has(a)) S.vistoFora.add(j.item_id);
  }
}
function discoNaPrateleira(x) {
  const a = alvoDisco(x), id = a && S.chegou.get(a);
  return naPrateleira(x && x.youtube_id) || (id && S.lib.find(it => it.id === id)) || null;
}
function mostraSalvar(x) {
  const a = alvoDisco(x);
  if (!a) return false;
  // so com a prateleira ja carregada: antes dela, todo disco parece fora (e ficaria com o visto ao chegar a lista)
  if (!discoNaPrateleira(x)) { if (S.libOk) S.vistoFora.add(a); return true; }
  return !!x.auto || S.vistoFora.has(a);
}
// o estado do salvar do disco (o do estadoSalvar, com o link colado e o que chegou pelo download dele)
const estadoDisco = x => discoNaPrateleira(x) ? ['salvo', 0] : estadoSalvar(x.youtube_id, x.url || x.alvo);
// o clique: como o da busca, e o que chegou sai da prateleira pelo item que o download trouxe
function salvarDisco(x) {
  const r = { youtube_id: x.youtube_id, link: x.youtube_id ? undefined : (x.url || x.alvo), title: x.title, channel: x.channel,
              thumb: x.thumb, duration: x.duration };
  const ja = discoNaPrateleira(x);
  if (ja) tirarDaPrateleira(ja, r); else salvarResultado(r);
}
/* servidor com fila e stream (o 8799 antigo nao tem ate reiniciar): sem ele, nada de fila na tela */
const temFila = () => !!(S.state && Array.isArray(S.state.queue));

function desenharBusca() {
  const vb = $('#vista-busca'), vp = $('#vista-prateleira');
  const b = S.busca;
  vb.hidden = !b; vp.hidden = !!b;
  document.body.classList.toggle('com-busca', !!b);   // a seta de voltar dentro do campo, no celular
  vigiarGavetaDaBusca();   // (#113) o toque fora da gaveta, na mesa
  if (!b) return;
  medirBusca();   // na mesa a busca cai debaixo do campo
  $('#titulo-busca').textContent = b.link ? I18N.t('search.pastedLink') : I18N.t('search.resultsFor', { query: b.q });
  $('#titulo-busca').title = $('#titulo-busca').textContent;
  const av = $('#aviso-busca'); av.className = 'aviso-busca'; av.replaceChildren();
  if (b.carregando) av.append(el('span', 'lampada acesa piscando'), document.createTextNode(I18N.t('search.searching')));
  else if (b.erro) {
    av.classList.add('erro');
    // pelo tipo, e nao pelo texto: sem resposta e o status 0 do api(), a busca do YouTube e a chave da mensagem, e o
    // limite e o motivo tecnico dela (o do yt-dlp, em ingles). O YouTube que demorou ("o YouTube não respondeu a
    // tempo") e erro do YouTube, e nao do Ritmelli fora do ar
    const fora = b.semResposta;
    const doYoutube = !!b.erroMsg && b.erroMsg.key === 'server.search.failed';
    const limite = /429|too many/i.test(detalheMsg(b.erroMsg));
    // o espaco depois do negrito fica dentro dele, como sempre foi
    if (fora) {
      av.append(el('strong', null, I18N.t('search.error.offline') + ' '), document.createTextNode(I18N.t('search.error.offlineHint')));
    } else if (doYoutube || limite) {
      const dica = I18N.t(limite ? 'search.error.rateLimitHint' : 'search.error.youtubeHint');
      av.append(el('strong', null, I18N.t('search.error.youtube') + ' '), document.createTextNode(dica));
      av.append(el('small', 'detalhe', I18N.t('search.error.detail', { detail: detalheMsg(b.erroMsg) })));
    } else {
      // outra recusa do servidor, ja traduzida pelo api() (ex.: a server.search.empty)
      av.append(el('strong', null, b.erro));
    }
  } else if (!b.link && !b.itens.length) av.textContent = I18N.t('search.noResults');
  else av.textContent = b.link ? I18N.t('search.linkHint') : '';
  av.hidden = !av.textContent;

  // a lista so se monta quando chegam resultados novos; o resto (anel, ✓, tocando) muda no lugar,
  // senao o progresso do download (15 vezes por segundo) trocaria a linha embaixo do dedo
  desenharMais();
  const ul = $('#resultados');
  if (ul._itens !== b.itens) {
    if (S.puxandoRes) { S.buscaPendente = true; return; }
    // a leva seguinte entra no fim, sem remontar o que ja esta na tela
    const antes = ul._itens, mais = antes && antes.length < b.itens.length && antes.every((x, i) => b.itens[i] === x);
    ul._itens = b.itens;
    if (mais) ul.append(...b.itens.slice(antes.length).map(liResultado));
    else ul.replaceChildren(...b.itens.map(liResultado));
  }
  atualizarResultados();
}

const tituloRes = r => r.link || r.title || I18N.t('shelf.untitled');
function liResultado(r) {
  const li = el('li', 'resultado'); li._r = r;
  const yid = r.youtube_id;
  const fundo = el('span', 'fundo-fila'); fundo.innerHTML = IC.fila; fundo.setAttribute('aria-hidden', 'true');
  const corpo = el('div', 'corpo');
  const linha = el('button', 'linha'); linha.type = 'button'; linha.dataset.role = 'tocar';
  const mini = el('span', 'miniatura');
  if (r.link) {
    if (yid) mini.append(arte({ thumb: `https://i.ytimg.com/vi/${yid}/mqdefault.jpg`, id: yid, title: r.link }, false));
    else mini.append(capaGerada({ id: r.link, title: 'link' }, false));
  } else {
    mini.append(arte({ thumb: r.thumb, id: yid, title: r.title }, false));
    if (r.duration) mini.append(el('span', 'dur-m', fmt(r.duration)));
  }
  const txt = el('span', 'txt');
  txt.append(el('span', 'tit', tituloRes(r)), el('span', 'sub'));
  linha.append(mini, txt);
  const mais = el('button', 'acao-res'); mais.type = 'button'; mais.dataset.role = 'mais';
  mais.setAttribute('aria-label', I18N.t('search.result.moreOptions', { title: tituloRes(r) })); mais.setAttribute('aria-haspopup', 'menu'); mais.setAttribute('aria-expanded', 'false');
  mais.innerHTML = svgMais();
  const salvar = el('button', 'acao-res salvar'); salvar.type = 'button'; salvar.dataset.role = 'salvar';
  corpo.append(linha, mais, salvar);
  li.append(fundo, corpo);
  return li;
}
/* estado de cada linha: tocando agora, ⊕ livre, anel baixando, ✓ na prateleira ou erro */
function atualizarResultados() {
  const tr = S.state && S.state.track, st = S.state && S.state.status;
  for (const li of $('#resultados').children) {
    const r = li._r; if (!r) continue;
    const yid = r.youtube_id, t = tituloRes(r);
    const [est, pr] = estadoSalvar(yid, r.link);
    const tocando = !!tr && !!yid && tr.youtube_id === yid && st !== 'ended';
    const sig = [est, pr, tocando && st].join('|');
    if (li._sig === sig) continue;
    li._sig = sig;
    li.classList.toggle('no-prato', tocando);
    // uma linha so: a lampada quando esta no prato, o canal (ou o erro) e, no celular, a duracao;
    // o progresso do download fica no anel do ⊕
    const sub = li.querySelector('.sub'); sub.replaceChildren();
    if (tocando) sub.append(el('span', 'lampada acesa' + (st === 'buffering' ? ' piscando' : '')));
    sub.append(est === 'erro' ? el('span', 'canal erro-t', I18N.t('search.result.downloadFailed'))
      : el('span', 'canal', r.link ? I18N.t('search.pastedLink') : (r.channel || I18N.t('deck.noChannel'))));
    if (r.duration) sub.append(el('span', 'dur-s', `· ${fmt(r.duration)}`));
    li.querySelector('.linha').setAttribute('aria-label', I18N.t(tocando ? 'search.result.playOnPlatter' : 'search.result.play', { title: t }));
    pintarSalvar(li.querySelector('.salvar'), est, pr, t);
  }
}
/* o ⊕ de salvar na prateleira, o da busca e o da parecida no prato: livre, baixando (pr %), salvo ou erro */
function estadoSalvar(yid, link) {
  const jb = jobDe(yid) || (link && jobDe(link));
  const est = naPrateleira(yid) ? 'salvo' : jb && jb.status === 'running' ? 'baixando' : jb && jb.status === 'error' ? 'erro' : 'livre';
  return [est, jb ? Math.round((jb.progress || 0) * 100) : 0];
}
function pintarSalvar(s, est, pr, t) {
  const pixel = s.classList.contains('pixel');   // o da parecida no prato, desenhado pelo dev/pecas.py
  s.className = `acao-res salvar ${pixel ? 'pixel ' : ''}${est}`;
  s.setAttribute('aria-label', est === 'salvo' ? I18N.t('search.result.saved', { title: t })
    : est === 'baixando' ? I18N.t('search.result.downloading', { pct: pr, title: t })
    : I18N.t(est === 'erro' ? 'search.result.retry' : 'search.result.save', { title: t }));
  if (pixel) {   // baixando, o aro acende celula a celula no sentido do relogio (os rect ja vem nessa ordem)
    const aro = s.querySelectorAll('.sv-aro rect'), k = est === 'baixando' ? Math.round(aro.length * pr / 100) : 0;
    aro.forEach((r, i) => r.classList.toggle('on', i < k));
  }
  s.style.setProperty('--pr', pr + '%');
  if (!pixel) s.innerHTML = est === 'salvo' ? IC.salvo : est === 'baixando' ? '<span class="anel" aria-hidden="true"></span>' : IC.salvar;
}

const corpoDe = r => r.link ? { url: r.link } : { youtube_id: r.youtube_id, title: r.title, channel: r.channel, thumb: r.thumb, duration: r.duration };
/* tocar na linha: da prateleira se ja esta la; senao o servidor toca pelo stream na hora e baixa
   por tras (o antigo, sem stream, toca quando o download chega). A busca fica aberta, como no Spotify */
function tocarResultado(r) {
  const ja = naPrateleira(r.youtube_id);
  if (ja) tocar(ja.id);
  else baixar({ ...corpoDe(r), play: true }, r.link || r.youtube_id);
}
function salvarResultado(r) {
  const ja = naPrateleira(r.youtube_id);
  if (ja) { tirarDaPrateleira(ja, r); return; }
  const jb = jobDe(r.youtube_id) || jobDe(r.link);
  if (jb && jb.status === 'running') { avisar(I18N.t('download.already')); return; }
  baixar({ ...corpoDe(r), play: false }, r.link || r.youtube_id);
}

/* o ✓ da busca tira da prateleira, como no YouTube Music: sai na hora, com
   Desfazer no aviso (baixa de novo). Tocando agora, tambem sem perguntar: o disco segue no prato e o
   servidor apaga o arquivo quando ele sair */
async function tirarDaPrateleira(it, r) {
  try {
    await api('DELETE', `/api/library/${encodeURIComponent(it.id)}`);
    avisar(I18N.t('download.removed'), false, { rotulo: I18N.t('app.undo'), fn: () => baixar({ ...corpoDe(r), play: false }, r.link || r.youtube_id) });
  } catch (e) { avisar(e.message, true); }
}

async function baixar(corpo, alvo) {
  try {
    const r = await api('POST', '/api/library', corpo);
    if (r.job) {
      S.jobAlvo[r.job.id] = alvo; S.jobCorpo[r.job.id] = corpo;
      if (!S.jobs.some(j => j.id === r.job.id)) S.jobs = S.jobs.concat(r.job);
      if (!corpo.play) avisar(I18N.t('download.started'));
      else if (!r.streaming) avisar(I18N.t('download.startedPlay'));
    } else if (r.item && !corpo.play) avisar(I18N.t('download.alreadySaved'));
    if (S.busca) desenharBusca();
    desenharPrateleira();
  } catch (e) { avisar(e.message, true); }
}
/* no celular o texto curto cabe no campo mesmo com a fonte do sistema maior (review) */
function textoBusca() { $('#q').placeholder = I18N.t(celular() ? 'search.promptShort' : 'search.prompt'); }
textoBusca();
/* a busca sai sozinha enquanto digita: depois de uma pausa curta e com 3
   letras ou mais, para nao mandar uma busca ao YouTube por tecla; link colado vai na hora */
const BUSCA_PAUSA_MS = 600, BUSCA_MIN = 3;
let buscaT = 0;
const jaBuscando = q => S.busca && !S.busca.link && S.busca.q === q && !S.busca.erro;
$('#q').addEventListener('input', () => {
  clearTimeout(buscaT);
  const q = $('#q').value.trim();
  if (ehLink(q)) { buscar(q); return; }
  if (q.length < BUSCA_MIN) return;
  buscaT = setTimeout(() => { if (!jaBuscando(q)) buscar(q); }, BUSCA_PAUSA_MS);
});
// Buscar (o do teclado ou a lupa): busca na hora, sem repetir a que ja saiu; no toque o campo larga
// o foco, e o teclado do celular fecha e deixa ver os resultados
$('#form-busca').addEventListener('submit', e => {
  e.preventDefault(); clearTimeout(buscaT); abrirDisco(false);
  if (toque()) $('#q').blur();
  const q = $('#q').value.trim();
  if (!q || !jaBuscando(q)) buscar(q);
});
// the search form starts inert: while the theme's scripts load, Enter would submit it natively and reload the page
$('#form-busca').inert = false;
$('#q').addEventListener('keydown', e => { if (e.key === 'Escape' && S.busca) { e.preventDefault(); fecharBusca(); } });
$('#b-voltar').addEventListener('click', () => { fecharBusca(); if (!toque()) $('#q').focus(); });
/* celular: tocar em qualquer lugar fora do campo fecha o teclado, como nos
   apps: o aviso de "na fila" ficava escondido atras dele. A seta e o x de dentro do campo seguem
   com o teclado aberto */
document.addEventListener('pointerdown', e => {
  const q = $('#q');
  if (e.pointerType === 'touch' && document.activeElement === q && !e.target.closest('.campo-q')) q.blur();
}, true);
$('#b-sair-busca').addEventListener('click', () => { fecharBusca(); $('#q').value = ''; });
/* (#113) na mesa a busca cai como uma gaveta por cima da mesa: clicar fora dela e fora do campo fecha, como um menu
   suspenso. O clique que fecha so fecha: o pointerdown para aqui (sem o mousedown, o foco, o arrastar de um volume ou de
   um disco da prateleira), e o click, o menu de contexto e, no toque, os eventos de toque que vem dele sao engolidos. O
   menu "..." de um resultado, o aviso (com o desfazer) e os dialogos nao contam como fora. A pagina do PC e o celular
   ficam como estao: la a busca toma o lugar da prateleira, e no celular o voltar ja fecha */
let foraDaBusca = null, foraDaBuscaAte = 0;   // o ponteiro do clique que fechou, e ate quando o que vem dele e engolido
addEventListener('pointerdown', e => {
  if (!e.isPrimary) return;
  foraDaBusca = null; foraDaBuscaAte = 0;
  if (e.button !== 0 || !MESA.montada || !S.busca || $('#vista-busca').hidden || dialogoAberto()
      || e.target.closest('#vista-busca, #form-busca, #menu, #aviso')) return;
  e.preventDefault(); e.stopPropagation();
  foraDaBusca = e.pointerId; foraDaBuscaAte = Infinity;   // antes do fecharBusca: os ouvintes do toque ficam ate ele acabar
  fecharMenu(false); $('#q').blur(); fecharBusca();
}, true);
for (const t of ['pointerup', 'pointercancel'])
  addEventListener(t, e => {
    if (e.pointerId !== foraDaBusca) return;
    foraDaBuscaAte = performance.now() + 500;
    setTimeout(vigiarGavetaDaBusca, 600);
  }, true);
const engolindoForaDaBusca = () => foraDaBusca !== null && performance.now() < foraDaBuscaAte;
// so o que vem do ponteiro: o click do teclado (detail 0) e o do codigo (o .click() das chaves do menu) passam
function engolirForaDaBusca(e) {
  if (!engolindoForaDaBusca() || !e.cancelable || !e.isTrusted || (e.type === 'click' && !e.detail)) return;
  e.preventDefault(); e.stopImmediatePropagation();
}
addEventListener('click', engolirForaDaBusca, true);
addEventListener('contextmenu', engolirForaDaBusca, true);
/* no toque o pointerdown parado nao segura o resto: o volume (o input range) anda pelo touchstart e pelo touchmove, e o
   toque ainda vira click. Estes so existem com a gaveta aberta na mesa (o desenharBusca e o montarMesa chamam), e ate o
   fim do toque que a fechou: sem passive, a rolagem pelo toque espera por eles */
function vigiarGavetaDaBusca() {
  const on = !!(MESA.montada && S.busca) || engolindoForaDaBusca();
  for (const t of ['touchstart', 'touchmove', 'touchend'])
    window[on ? 'addEventListener' : 'removeEventListener'](t, engolirForaDaBusca, { capture: true, passive: false });
}
// limpar: no primeiro toque, com ou sem o cursor no campo; o campo fica pronto para a busca nova
// (os resultados de antes ficam ate ela sair, como enquanto digita)
$('#b-limpar-q').addEventListener('click', () => { clearTimeout(buscaT); const q = $('#q'); q.value = ''; q.focus(); });
/* SEARCH-JS-FIM */
