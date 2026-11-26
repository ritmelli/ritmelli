/* SHELF-JS-INICIO */
'use strict';
/* ---------- prateleira ---------- */
const nos = new Map();     // chave -> li
function chaveItem(it, i) { return [it.title, it.thumb, it.channel, it.duration, i].join('|'); }

function svgMais() {
  return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="19" cy="12" r="1.8" fill="currentColor"/></svg>';
}
const SVG = d => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const IC = {
  aSeguir: SVG('<path d="M4 6.5h11M4 11.5h11M4 16.5h6"/><path d="M14.5 14v6.5l5.5-3.25z" fill="currentColor"/>'),
  fila: SVG('<path d="M4 6.5h12M4 11.5h12M4 16.5h7"/><path d="M17.5 13.5v7M14 17h7"/>'),
  salvar: SVG('<circle cx="12" cy="12" r="8.6"/><path d="M12 8v8M8 12h8"/>'),
  salvo: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9.6" fill="currentColor"/><path d="M7.8 12.3l2.8 2.8 5.6-5.8" fill="none" stroke="#2A1812" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  continuar: SVG('<path d="M7.5 5v14l11-7z" fill="currentColor"/>'),
  renomear: SVG('<path d="M4.5 19.5h4l10-10-4-4-10 10z"/><path d="M13 7l4 4"/>'),
  apagar: SVG('<path d="M4.5 7h15M10 11v6M14 11v6M6.5 7l1 12.5h9l1-12.5M9.5 7V4.5h5V7"/>'),
  youtube: SVG('<path d="M14 4.5h5.5V10M19.5 4.5L11 13"/><path d="M18 14v5.5H4.5V6H10"/>'),
  tirar: SVG('<path d="M7 7l10 10M17 7L7 17"/>'),
  alca: SVG('<path d="M5 9h14M5 15h14"/>'),
  rapido: SVG('<path d="M13.5 3L5 13.5h6.5L10 21l9-11h-6.5z"/>'),
  semRapido: SVG('<path d="M13.5 3L5 13.5h6.5L10 21l9-11h-6.5z"/><path d="M4 4l16 16"/>'),
};
// os mesmos na folha de opcoes do celular, em pixel (celulas de 1 px de CSS, desenhados no dev da contracapa)
const PX = d => `<svg viewBox="0 0 24 24" shape-rendering="crispEdges" aria-hidden="true"><path fill="currentColor" d="${d}"/></svg>`;
const IC_PX = {
  continuar: PX('M7 4h2v1h-2zM7 5h3v1h-3zM7 6h4v1h-4zM7 7h6v1h-6zM7 8h8v1h-8zM7 9h9v1h-9zM7 10h10v1h-10zM7 11h12v1h-12zM7 12h12v1h-12zM7 13h10v1h-10zM7 14h9v1h-9zM7 15h8v1h-8zM7 16h6v1h-6zM7 17h4v1h-4zM7 18h3v1h-3zM7 19h2v1h-2z'),
  seguir: PX('M3 5h13v1h-13zM3 6h13v1h-13zM3 10h13v1h-13zM3 11h13v1h-13zM13 13h2v1h-2zM13 14h3v1h-3zM3 15h7v1h-7zM13 15h5v1h-5zM3 16h7v1h-7zM13 16h6v1h-6zM13 17h7v1h-7zM13 18h6v1h-6zM13 19h5v1h-5zM13 20h3v1h-3zM13 21h2v1h-2z'),
  fila: PX('M3 5h13v1h-13zM3 6h13v1h-13zM3 10h13v1h-13zM3 11h13v1h-13zM16 12h2v1h-2zM16 13h2v1h-2zM16 14h2v1h-2zM3 15h7v1h-7zM16 15h2v1h-2zM3 16h7v1h-7zM12 16h10v1h-10zM12 17h10v1h-10zM16 18h2v1h-2zM16 19h2v1h-2zM16 20h2v1h-2zM16 21h2v1h-2z'),
  renomear: PX('M15 5h1v1h-1zM14 6h3v1h-3zM14 7h4v1h-4zM12 8h1v1h-1zM15 8h4v1h-4zM11 9h3v1h-3zM16 9h2v1h-2zM10 10h5v1h-5zM9 11h7v1h-7zM8 12h7v1h-7zM7 13h7v1h-7zM6 14h7v1h-7zM5 15h7v1h-7zM4 16h1v1h-1zM6 16h5v1h-5zM4 17h2v1h-2zM7 17h3v1h-3zM4 18h3v1h-3zM8 18h1v1h-1zM4 19h4v1h-4z'),
  youtube: PX('M13 3h8v1h-8zM13 4h8v1h-8zM18 5h3v1h-3zM3 6h7v1h-7zM17 6h4v1h-4zM3 7h7v1h-7zM16 7h5v1h-5zM3 8h2v1h-2zM15 8h3v1h-3zM19 8h2v1h-2zM3 9h2v1h-2zM14 9h3v1h-3zM19 9h2v1h-2zM3 10h2v1h-2zM13 10h3v1h-3zM19 10h2v1h-2zM3 11h2v1h-2zM12 11h3v1h-3zM3 12h2v1h-2zM11 12h3v1h-3zM3 13h2v1h-2zM10 13h3v1h-3zM16 13h2v1h-2zM3 14h2v1h-2zM10 14h2v1h-2zM16 14h2v1h-2zM3 15h2v1h-2zM16 15h2v1h-2zM3 16h2v1h-2zM16 16h2v1h-2zM3 17h2v1h-2zM16 17h2v1h-2zM3 18h2v1h-2zM16 18h2v1h-2zM3 19h15v1h-15zM3 20h15v1h-15z'),
  apagar: PX('M9 2h6v1h-6zM9 3h6v1h-6zM9 4h2v1h-2zM13 4h2v1h-2zM3 5h18v1h-18zM3 6h18v1h-18zM5 8h2v1h-2zM17 8h2v1h-2zM5 9h2v1h-2zM17 9h2v1h-2zM5 10h2v1h-2zM9 10h2v1h-2zM13 10h2v1h-2zM17 10h2v1h-2zM5 11h2v1h-2zM9 11h2v1h-2zM13 11h2v1h-2zM17 11h2v1h-2zM5 12h2v1h-2zM9 12h2v1h-2zM13 12h2v1h-2zM17 12h2v1h-2zM5 13h2v1h-2zM9 13h2v1h-2zM13 13h2v1h-2zM17 13h2v1h-2zM5 14h2v1h-2zM9 14h2v1h-2zM13 14h2v1h-2zM17 14h2v1h-2zM5 15h2v1h-2zM9 15h2v1h-2zM13 15h2v1h-2zM17 15h2v1h-2zM5 16h2v1h-2zM9 16h2v1h-2zM13 16h2v1h-2zM17 16h2v1h-2zM5 17h2v1h-2zM17 17h2v1h-2zM5 18h2v1h-2zM17 18h2v1h-2zM5 19h14v1h-14zM5 20h14v1h-14z'),
  salvar: PX('M10 2h4v1h-4zM7 3h10v1h-10zM6 4h5v1h-5zM13 4h5v1h-5zM5 5h3v1h-3zM16 5h3v1h-3zM4 6h3v1h-3zM17 6h3v1h-3zM3 7h3v1h-3zM11 7h2v1h-2zM18 7h3v1h-3zM3 8h2v1h-2zM11 8h2v1h-2zM19 8h2v1h-2zM3 9h2v1h-2zM11 9h2v1h-2zM19 9h2v1h-2zM2 10h3v1h-3zM11 10h2v1h-2zM19 10h3v1h-3zM2 11h2v1h-2zM7 11h10v1h-10zM20 11h2v1h-2zM2 12h2v1h-2zM7 12h10v1h-10zM20 12h2v1h-2zM2 13h3v1h-3zM11 13h2v1h-2zM19 13h3v1h-3zM3 14h2v1h-2zM11 14h2v1h-2zM19 14h2v1h-2zM3 15h2v1h-2zM11 15h2v1h-2zM19 15h2v1h-2zM3 16h3v1h-3zM11 16h2v1h-2zM18 16h3v1h-3zM4 17h3v1h-3zM17 17h3v1h-3zM5 18h3v1h-3zM16 18h3v1h-3zM6 19h5v1h-5zM13 19h5v1h-5zM7 20h10v1h-10zM10 21h4v1h-4z'),
  // o raio dos Sons rapidos, e cortado por uma barra para tirar
  rapido: PX('M12 2h6v1h-6zM11 3h6v1h-6zM10 4h6v1h-6zM9 5h6v1h-6zM8 6h6v1h-6zM7 7h6v1h-6zM6 8h6v1h-6zM5 9h14v1h-14zM5 10h14v1h-14zM11 11h7v1h-7zM10 12h7v1h-7zM10 13h6v1h-6zM9 14h6v1h-6zM9 15h5v1h-5zM8 16h5v1h-5zM8 17h4v1h-4zM7 18h4v1h-4zM7 19h3v1h-3zM6 20h3v1h-3zM6 21h2v1h-2z'),
  semRapido: PX('M2 2h2v1h-2zM12 2h6v1h-6zM3 3h2v1h-2zM11 3h6v1h-6zM4 4h2v1h-2zM10 4h6v1h-6zM5 5h2v1h-2zM9 5h6v1h-6zM6 6h2v1h-2zM9 6h5v1h-5zM7 7h2v1h-2zM10 7h3v1h-3zM6 8h1v1h-1zM8 8h2v1h-2zM11 8h1v1h-1zM5 9h3v1h-3zM9 9h2v1h-2zM12 9h7v1h-7zM5 10h4v1h-4zM10 10h2v1h-2zM13 10h6v1h-6zM11 11h2v1h-2zM14 11h4v1h-4zM10 12h1v1h-1zM12 12h2v1h-2zM15 12h2v1h-2zM10 13h2v1h-2zM13 13h2v1h-2zM9 14h4v1h-4zM14 14h2v1h-2zM9 15h5v1h-5zM15 15h2v1h-2zM8 16h5v1h-5zM16 16h2v1h-2zM8 17h4v1h-4zM17 17h2v1h-2zM7 18h4v1h-4zM18 18h2v1h-2zM7 19h3v1h-3zM19 19h2v1h-2zM6 20h3v1h-3zM20 20h2v1h-2zM6 21h2v1h-2zM21 21h2v1h-2z'),
};

function liDisco(it, i) {
  const li = el('li', 'disco-item'); li.dataset.id = it.id;
  const capa = el('button', 'capa'); capa.type = 'button'; capa.dataset.role = 'capa';
  capa.setAttribute('aria-label', I18N.t('shelf.playFromStart', { title: it.title }));
  capa.append(arte(it, false));
  const tag = el('span', 'no-prato-tag'); tag.append(el('span', 'lampada acesa'), document.createTextNode(I18N.t('shelf.onPlatter')));
  capa.append(tag);
  const borda = el('div', 'borda'); borda.setAttribute('aria-hidden', 'true');
  const ficha = el('div', 'ficha');
  const nome = el('p', 'nome');
  if (i < 9) { const k = el('kbd', null, String(i + 1)); k.title = I18N.t('shelf.keyHint', { n: i + 1 }); nome.append(k); }
  nome.append(document.createTextNode(it.title));
  const acoes = el('div', 'acoes');
  const mais = el('button', 'mais'); mais.type = 'button'; mais.dataset.role = 'mais';
  mais.setAttribute('aria-label', I18N.t('shelf.moreActions', { title: it.title })); mais.setAttribute('aria-haspopup', 'menu'); mais.setAttribute('aria-expanded', 'false');
  mais.innerHTML = svgMais();
  acoes.append(mais);
  // (07/11, pedido do dono) na mesa o cartao da prateleira e o da maleta: a musica em negrito e o artista e a duracao embaixo
  const pt = partirTitulo(it);
  ficha.append(nome, el('span', 'prat-t', pt.musica),
               el('span', 'prat-s', [pt.artista, it.duration ? fmt(it.duration) : null].filter(Boolean).join(' · ') || ' '), acoes);
  li.append(capa, borda, ficha);
  li._chave = chaveItem(it, i);
  return li;
}

function jobsVisiveis() {
  const ids = new Set(S.lib.map(x => x.id));
  return S.jobs.filter(j => j.status === 'running' || j.status === 'error' || (j.status === 'done' && !ids.has(j.item_id)));
}

function liJob(j) {
  const li = el('li', 'disco-item chegando'); li.dataset.job = j.id;
  const capa = el('div', 'capa'); const papel = el('div', 'papel'); const furo = el('div', 'furo');
  papel.append(furo); capa.append(papel);
  const borda = el('div', 'borda'); borda.setAttribute('aria-hidden', 'true');
  const ficha = el('div', 'ficha');
  ficha.append(el('p', 'nome', j.label), el('div', 'acoes'));
  li.append(capa, borda, ficha);
  atualizarJob(li, j);
  return li;
}
function atualizarJob(li, j) {
  const pr = Math.round((j.progress || 0) * 100);
  li.querySelector('.furo').style.setProperty('--pr', pr + '%');
  li.classList.toggle('falhou', j.status === 'error');
  li.querySelector('.nome').textContent = j.label;
  const acoes = li.querySelector('.acoes');
  const sig = j.status + '|' + JSON.stringify(j.error || null);
  if (li._sig === sig) return;
  li._sig = sig;
  acoes.replaceChildren();
  if (j.status === 'error') {
    const pe = el('p', 'erro-job', motivoDownload(detalheMsg(j.error)));
    if (j.error) { pe.append(el('small', null, detalheMsg(j.error))); pe.title = detalheMsg(j.error); }
    acoes.append(pe);
    if (S.jobCorpo[j.id]) {
      const b = el('button', 'btn-texto', I18N.t('shelf.retry')); b.type = 'button'; b.dataset.role = 'retentar'; b.dataset.job = j.id;
      acoes.append(b);
    }
  }
}

function desenharPrateleira() {
  const ul = $('#estante');
  const ativo = document.activeElement;
  const foco = ativo && ul.contains(ativo) ? { li: ativo.closest('li'), role: ativo.dataset.role } : null;
  const focoChave = foco && foco.li ? (foco.li.dataset.id || 'job:' + foco.li.dataset.job) : null;

  const queridos = [];
  S.lib.forEach((it, i) => {
    const k = 'i:' + it.id;
    let li = nos.get(k);
    if (!li || li._chave !== chaveItem(it, i)) {
      const novo = liDisco(it, i);
      if (li) li.replaceWith(novo);   // troca no lugar: o no velho nao fica pendurado na estante
      li = novo; nos.set(k, li);
    }
    queridos.push([k, li]);
  });
  for (const j of jobsVisiveis()) {
    const k = 'j:' + j.id;
    let li = nos.get(k);
    if (!li) { li = liJob(j); nos.set(k, li); } else atualizarJob(li, j);
    queridos.push([k, li]);
  }
  const vivos = new Set(queridos.map(q => q[0]));
  for (const [k, li] of nos) if (!vivos.has(k)) { li.remove(); nos.delete(k); }
  const vazio = ul.querySelector('.vazio');
  if (queridos.length) { if (vazio) vazio.remove(); }
  else if (!vazio) {
    const v = el('li', 'vazio');
    v.append(el('strong', null, I18N.t('shelf.empty')), document.createTextNode(I18N.t('shelf.emptyHint')));
    ul.append(v);
  }
  queridos.forEach(([, li], i) => { if (ul.children[i] !== li) ul.insertBefore(li, ul.children[i] || null); });
  // celular: 9 capas por pagina, lidas em fileiras de 3 (so o celular usa a posicao)
  queridos.forEach(([, li], i) => {
    mudar(li, '--c', String(Math.floor(i / 9) * 3 + i % 3 + 1)); mudar(li, '--r', String(Math.floor(i % 9 / 3) + 1));
    li.classList.toggle('pagina', i % 9 === 0);
  });
  const desejados = new Set(queridos.map(q => q[1]));
  [...ul.children].forEach(c => { if (!desejados.has(c) && !c.classList.contains('vazio')) c.remove(); });

  if (foco && !ul.contains(ativo)) {
    const alvo = focoChave && [...ul.children].find(x => (x.dataset.id || 'job:' + x.dataset.job) === focoChave);
    const b = alvo && (alvo.querySelector(`[data-role="${foco.role}"]`) || alvo.querySelector('button'));
    if (b) b.focus();
  }
  const n = S.lib.length;
  $('#conta').textContent = I18N.tp('shelf.count', n);
  if (S.state && !S.state.track) {
    $('#canal-faixa').textContent = dicaPrato();
    $('#mini-sub').textContent = dicaMini(); rotularMini();
  }
  marcarPrateleira();
  desenharRapidos();
  desenharContinuar();
  desenharPontos(queridos.length);
}

/* prateleira: as mais escutadas primeiro e as novas por ultimo (18/10; a escuta o
   servidor conta em `plays`). A ordem se faz quando a pagina abre: disco novo entra no fim, e
   ouvir um disco nao o tira do lugar com a pagina aberta (nada pula debaixo do dedo) */
const lugarLib = new Map();
function ordenarLib(lib) {
  if (!lugarLib.size) {
    [...lib].sort((a, b) => (b.plays || 0) - (a.plays || 0) || String(a.added || '').localeCompare(String(b.added || '')))
      .forEach((it, i) => lugarLib.set(it.id, i));
  }
  for (const it of lib) if (!lugarLib.has(it.id)) lugarLib.set(it.id, lugarLib.size);
  return [...lib].sort((a, b) => lugarLib.get(a.id) - lugarLib.get(b.id));
}

/* pontos da pagina da prateleira (celular), como no Jukebox digital do YouTube Music */
function desenharPontos(n) {
  const box = $('#pontos'), paginas = Math.ceil(n / 9);
  box.hidden = paginas < 2;
  if (box.childElementCount !== paginas) box.replaceChildren(...Array.from({ length: paginas }, () => el('span')));
  marcarPonto();
}
function marcarPonto() {
  const ul = $('#estante'), box = $('#pontos');
  if (box.hidden || !box.childElementCount) return;
  const i = Math.round(ul.scrollLeft / Math.max(1, ul.scrollWidth / box.childElementCount));
  [...box.children].forEach((p, k) => p.classList.toggle('aqui', k === i));
}

/* continuar ouvindo: os discos que pararam no meio, do jeito que estao na prateleira */
function desenharContinuar() {
  const its = S.lib.filter(it => (it.last_pos || 0) > 5 && it.duration - it.last_pos > 10).slice(0, 12);
  const ul = $('#cartoes');
  $('#continuar').hidden = !its.length;
  const chave = its.map(it => `${it.id}|${Math.round(it.last_pos)}|${it.title}`).join('/');
  if (ul._chave === chave) return;
  ul._chave = chave;
  ul.replaceChildren(...its.map(it => {
    const li = el('li', 'cartao'); li.dataset.id = it.id;
    const b = el('button', 'cartao-b'); b.type = 'button';
    b.setAttribute('aria-label', I18N.t('shelf.resumeFromItem', { time: fmt(it.last_pos), title: it.title }));
    const capa = el('span', 'cartao-capa'); capa.append(arte(it, false));
    const pr = el('span', 'cartao-prog'); pr.style.setProperty('--p', (it.last_pos / it.duration).toFixed(3));
    capa.append(pr);
    b.append(capa, el('span', 'cartao-tit', it.title), el('span', 'cartao-sub', I18N.t('shelf.resumeFrom', { time: fmt(it.last_pos) })));
    li.append(b);
    return li;
  }));
}

/* sons rapidos: os de ate 15 s, que o servidor toca por cima da musica, e os discos postos pelo
   menu de segurar (25/10), que tocam por cima inteiros, ate 2 min (RAPIDO_MAX_S do motor); a lampada acende
   enquanto o som esta tocando */
const CURTO_S = 15, RAPIDO_MAX_S = 120;
const curto = it => !!it.duration && it.duration <= CURTO_S;
function desenharRapidos() {
  const curtos = S.lib.filter(it => curto(it) || it.rapido);
  const chips = $('#chips');
  $('#rapidos').hidden = !curtos.length;
  $('#conta-rap').textContent = I18N.tp('pads.count', curtos.length);
  const chave = curtos.map(it => it.id + '|' + it.title).join('/');
  if (chips._chave !== chave) {
    chips._chave = chave;
    chips.replaceChildren(...curtos.map(it => {
      const b = el('button', 'compacto'); b.type = 'button'; b.dataset.id = it.id;
      b.setAttribute('aria-label', I18N.t('pads.playOver', { title: it.title }));
      // compacto de 7 polegadas: selo de papel na cor do som, como as capas geradas
      const [bg, fg] = PALETAS[hash(it.id || it.title) % PALETAS.length];
      const sete = el('span', 'sete'), gira = el('span', 'sete-gira'), rot = el('span', 'sete-rot');
      rot.style.setProperty('--bg', bg); rot.style.setProperty('--fg', fg);
      gira.append(rot); sete.append(gira); sete.setAttribute('aria-hidden', 'true');
      b.append(sete, el('span', 'lampada'), el('span', 't', it.title), el('span', 'd', fmt(Math.min(it.duration || 0, it.rapido ? RAPIDO_MAX_S : CURTO_S))));
      return b;
    }));
  }
  const tocando = new Set(((S.state && S.state.por_cima) || []).map(x => x.id));
  chips.querySelectorAll('.compacto').forEach(b => {
    const on = tocando.has(b.dataset.id);
    mudar(b.querySelector('.lampada'), 'class', 'lampada' + (on ? ' acesa' : ''));
    mudar(b, 'class', 'compacto' + (on ? ' tocando' : ''));
  });
  desenharPads(curtos);
}

function marcarPrateleira() {
  const tr = S.state && S.state.track;
  document.querySelectorAll('#estante .disco-item[data-id]').forEach(li => {
    li.classList.toggle('no-prato', !!tr && li.dataset.id === tr.id);
  });
}
let seguradaEm = 0;
function bindShelfClick() {
  $('#estante').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    const li = b.closest('li');
    const id = li && li.dataset.id;
    if (b.dataset.role === 'capa' && id) {
      if (Date.now() - seguradaEm > 900) {   // soltar depois de segurar nao toca
        tocar(id);
        // (07/11, pedido do dono) na mesa o disco clicado da uma subidinha e volta ao lugar (o que toca nao fica mais levantado)
        if (MESA.montada && !reduz.matches && li.animate)
          li.animate([{ transform: 'translateY(0)' }, { transform: 'translateY(-6px)', offset: .35 }, { transform: 'translateY(0)' }], { duration: 300, easing: 'ease-out' });
      }
    }
    else if (b.dataset.role === 'mais' && id) { if (menuBotao === b) fecharMenu(true); else { fecharMenu(false); abrirMenu(b, { tipo: 'disco', id }); } }
    else if (b.dataset.role === 'retentar') { const c = S.jobCorpo[b.dataset.job]; if (c) baixar(c, S.jobAlvo[b.dataset.job]); }
  });
}
function bindShelf() {
  $('#chips').addEventListener('click', e => {
    const b = e.target.closest('.compacto');
    if (b && Date.now() - seguradaEm > 900) tocar(b.dataset.id, { por_cima: true });   // soltar depois de segurar nao toca
  });
  /* segurar a capa no celular, ou o botao direito no computador, abre o menu do disco (como no YouTube Music); num
     compacto dos Sons rapidos, que nao tem os tres pontos, abre o mesmo menu (25/10) */
  $('#estante').addEventListener('contextmenu', e => {
    const b = e.target.closest('.capa'), li = b && b.closest('li[data-id]');
    if (!li) return;
    e.preventDefault(); seguradaEm = Date.now();
    fecharMenu(false); abrirMenu(b, { tipo: 'disco', id: li.dataset.id });
  });
  $('#chips').addEventListener('contextmenu', e => {
    const b = e.target.closest('.compacto');
    if (!b) return;
    e.preventDefault(); seguradaEm = Date.now();
    fecharMenu(false); abrirMenu(b, { tipo: 'disco', id: b.dataset.id });
  });
  /* (#52) arrastar um disco da prateleira ate um toca-discos, so na mesa, a unica tela com a prateleira e os dois
     toca-discos juntos: soltar no deck no ar toca agora, como o clique; no da deixa toca a seguir, como o "Tocar a
     seguir" do menu (o disco que ja esta na deixa fica como esta). No mouse, andar uns pixels com o botao apertado ja
     arrasta: o clique segue tocando, e o botao direito e o "..." seguem abrindo o menu. No dedo, segurar meio segundo
     levanta o disco (o celular vibra): andando, arrasta; soltando sem andar, abre o menu, que e o que o segurar fazia (o
     segurar do proprio navegador fica de fora na mesa, para nao abrir o menu no meio do arrasto). Fora da mesa nada
     muda. Soltar longe dos toca-discos, o Esc, o gesto cancelado ou a mesa desmontando devolvem o disco a prateleira */
  (() => {
    const est = $('#estante'), SEGURAR_MS = 450, FOLGA_DEDO = 8, FOLGA_MOUSE = 6;
    let g = null;          // o gesto em curso
    let dedoEm = 0;        // o fim do ultimo gesto de dedo: o menu do segurar do navegador que chega depois fica de fora
    let engolir = null;    // o ponteiro do arrasto cancelado pelo Esc: o soltar dele nao vira clique
    // o toca-discos que aparece no ponto: o que estiver por cima dele (a gaveta da busca, um aviso) tapa o alvo. A capa
    // solta e a placa do alvo nao pegam o ponteiro, entao nao contam
    function alvoEm(x, y) {
      const e = document.elementFromPoint(x, y), d = e && e.closest('.palco .deck');
      return d ? { d, acao: d.classList.contains('deck-deixa') ? 'seguir' : 'agora' } : null;
    }
    function apagarAlvo(d) { d.classList.remove('alvo-disco'); delete d.dataset.alvo; }
    function acender(alvo) {
      const d = alvo ? alvo.d : null;
      if (g.alvo && g.alvo !== d) apagarAlvo(g.alvo);
      if (d) { d.dataset.alvo = I18N.t(alvo.acao === 'agora' ? 'cue.playNow' : 'menu.playNext'); d.classList.add('alvo-disco'); }
      g.alvo = d;
    }
    const posicionar = () => { g.voa.style.transform = `translate(${g.x - g.dx}px, ${g.y - g.dy}px)`; };
    // a capa sai da prateleira: uma copia solta, presa ao ponteiro no ponto onde ele pegou
    function levantar() {
      clearTimeout(g.timer);
      if (!MESA.montada || !g.li.isConnected) { acabar(); return; }
      const r = g.capa.getBoundingClientRect();
      g.fase = 'levantado'; g.xl = g.x; g.yl = g.y; g.dx = g.x0 - r.left; g.dy = g.y0 - r.top;
      const v = el('div', 'disco-voando'), c = el('div', 'dv-capa'), arteNo = g.capa.querySelector('img, .capa-gerada');
      c.append(arteNo ? arteNo.cloneNode(true) : arte(g.it, false));
      v.append(c); v.setAttribute('aria-hidden', 'true');
      v.style.width = r.width + 'px'; v.style.height = r.height + 'px';
      document.body.append(v);
      g.voa = v; posicionar();
      g.li.classList.add('levantado');
      document.body.classList.add('arrastando-disco');
      getSelection().removeAllRanges();
      // preso a prateleira (que nunca e redesenhada): o soltar chega mesmo fora da janela ou com o disco redesenhado
      try { est.setPointerCapture(g.id); } catch (e) { /* o ponteiro ja saiu */ }
      if (g.dedo && navigator.vibrate) navigator.vibrate(12);
    }
    function acabar() {
      if (!g) return;
      clearTimeout(g.timer);
      if (g.alvo) apagarAlvo(g.alvo);
      if (g.voa) g.voa.remove();
      g.li.classList.remove('levantado');
      document.body.classList.remove('arrastando-disco');
      if (g.dedo) dedoEm = Date.now();
      g = null;
    }
    // a capa volta voando para o lugar do disco na prateleira (achado pelo id: ele pode ter sido redesenhado no caminho)
    function devolver() {
      const voa = g.voa, id = g.it.id;
      g.voa = null;
      acabar();
      if (!voa) return;
      const li = [...est.querySelectorAll('li[data-id]')].find(l => l.dataset.id === id), capa = li && li.querySelector('.capa');
      if (!capa || !MESA.montada || reduz.matches) { voa.remove(); return; }
      const r = capa.getBoundingClientRect();
      voa.classList.add('voltando');
      voa.style.transform = `translate(${r.left}px, ${r.top}px)`;
      setTimeout(() => voa.remove(), 200);
    }
    est.addEventListener('pointerdown', e => {
      if (g || !MESA.montada || e.button !== 0 || !e.isPrimary) return;
      const capa = e.target.closest('.capa'), li = capa && capa.closest('li[data-id]');
      const it = li && S.lib.find(x => x.id === li.dataset.id);
      if (!it) return;
      g = { id: e.pointerId, dedo: e.pointerType !== 'mouse', li, capa, it, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY,
            fase: 'espera', alvo: null, voa: null };
      if (g.dedo) g.timer = setTimeout(levantar, SEGURAR_MS);
    });
    addEventListener('pointermove', e => {
      if (!g || e.pointerId !== g.id) return;
      g.x = e.clientX; g.y = e.clientY;
      if (!g.dedo && !(e.buttons & 1)) { if (g.fase === 'espera') acabar(); else devolver(); return; }   // soltou fora da janela
      if (g.fase === 'espera') {
        const andou = Math.hypot(g.x - g.x0, g.y - g.y0);
        if (g.dedo) { if (andou > FOLGA_DEDO) acabar(); return; }   // o dedo andou antes do tempo: e a rolagem da prateleira
        if (andou < FOLGA_MOUSE) return;
        levantar();
        if (!g) return;
        g.fase = 'arrastando';
      } else if (g.fase === 'levantado') {
        if (Math.hypot(g.x - g.xl, g.y - g.yl) < FOLGA_DEDO) return;
        g.fase = 'arrastando';
      }
      if (!MESA.montada) { devolver(); return; }
      posicionar();
      acender(alvoEm(g.x, g.y));
    });
    addEventListener('pointerup', e => {
      if (engolir === e.pointerId) { engolir = null; seguradaEm = Date.now(); return; }
      if (!g || e.pointerId !== g.id) return;
      if (g.fase === 'espera') { acabar(); return; }   // o clique, ou o toque curto, de sempre: o click toca o disco
      seguradaEm = Date.now();   // o click que vem depois do soltar nao toca o disco
      if (g.fase === 'levantado') {   // segurou e soltou sem andar: o menu, como o segurar abria
        const { capa, it } = g;
        acabar();
        fecharMenu(false); abrirMenu(capa, { tipo: 'disco', id: it.id });
        return;
      }
      const alvo = MESA.montada ? alvoEm(g.x, g.y) : null, it = g.it;
      if (!alvo) { devolver(); return; }
      acabar();
      if (alvo.acao === 'agora') tocar(it.id);
      else if (!mesmoDisco(MESA.deixa, it)) executar('seguir', { tipo: 'disco', it });
    });
    addEventListener('pointercancel', e => {
      if (engolir === e.pointerId) engolir = null;
      if (!g || e.pointerId !== g.id) return;
      if (g.fase === 'espera') acabar(); else devolver();
    });
    document.addEventListener('keydown', e => {   // antes do Esc da pagina, que pararia a musica
      if (!g || g.fase === 'espera' || e.key !== 'Escape') return;
      e.preventDefault(); e.stopImmediatePropagation();
      engolir = g.id;
      devolver();
    }, true);
    // o menu do segurar do proprio navegador: na mesa, o dedo ja abre o menu ao soltar
    est.addEventListener('contextmenu', e => {
      if (!MESA.montada || !e.target.closest('.capa')) return;
      if ((g && g.dedo) || Date.now() - dedoEm < 800) { e.preventDefault(); e.stopImmediatePropagation(); }
    }, true);
    est.addEventListener('dragstart', e => { if (MESA.montada && e.target.closest && e.target.closest('.capa')) e.preventDefault(); });
    // com o disco levantado, o dedo nao rola a prateleira: o touchmove que bloqueia so existe na mesa (fora dela a
    // rolagem segue sem esperar por ele)
    const prende = e => { if (g && g.dedo && g.fase !== 'espera' && e.cancelable) e.preventDefault(); };
    const ligar = () => est[paginaUnica() ? 'addEventListener' : 'removeEventListener']('touchmove', prende, { passive: false });
    ligar();
    mqUnica.addEventListener('change', () => { ligar(); if (g && !paginaUnica()) acabar(); });
  })();
  $('#estante').addEventListener('scroll', () => requestAnimationFrame(marcarPonto), { passive: true });
  $('#cartoes').addEventListener('click', e => { const li = e.target.closest('li[data-id]'); if (li) tocar(li.dataset.id, { resume: true }); });
}
/* SHELF-JS-FIM */
