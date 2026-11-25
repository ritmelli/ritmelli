/* QUEUE-JS-INICIO */
'use strict';
/* ---------- fila (A seguir) ---------- */
/* o que nao esta na prateleira ja comeca a baixar quando entra na fila; na vez dele toca do arquivo,
   ou pelo stream se o download ainda nao chegou */
async function enfileirar(corpo, seguir, titulo, alvo) {
  try {
    const r = await api('POST', '/api/queue', { ...corpo, next: seguir });
    if (r.job) {
      if (alvo) S.jobAlvo[r.job.id] = alvo;
      if (!S.jobs.some(j => j.id === r.job.id)) S.jobs = S.jobs.concat(r.job);
    }
    // com nada no prato o servidor ja toca o que entrou
    if (r.playing) avisar(I18N.t('queue.playing', { title: titulo }));
    else avisar(I18N.t(seguir ? 'queue.playsNext' : 'queue.added', { title: titulo }), false, { rotulo: I18N.t('app.open'), fn: abrirFila });
    if (S.busca) atualizarResultados();
  } catch (e) { avisar(e.message, true); }
}
/* "Abrir" do aviso: abre o toca-discos ja na fila (no celular o palco, no computador a pagina do disco) */
function abrirFila() {
  const f = $(celular() ? '.fila-palco' : '.fila-parede');
  if (celular()) abrirPalcoComHistoria(); else abrirDisco(true);
  abrirMaleta(true);
  if (!f || f.hidden) return;
  requestAnimationFrame(() => {
    f.scrollIntoView({ block: celular() ? 'start' : 'nearest', behavior: reduz.matches ? 'auto' : 'smooth' });
    f.classList.add('realce'); setTimeout(() => f.classList.remove('realce'), 1200);
  });
}
function estadoEntrada(x) {
  if ((x.id && S.lib.some(it => it.id === x.id)) || naPrateleira(x.youtube_id)) return 'pronto';
  const j = x.job && S.jobs.find(jb => jb.id === x.job);
  if (j && j.status === 'running') return 'baixando ' + Math.round((j.progress || 0) * 100);
  return j && j.status === 'error' ? 'erro' : 'stream';
}
/* a capa do disco da maleta: o disco e a capa quadrada da largura dele (300 px de tela, 900 no celular de teste), entao a
   miniatura vem da maior que o YouTube tiver (a mqdefault da fila tem 320 px e a capa quadrada dela 180: borrava), e
   sem as faixas que o YouTube poe em volta (com elas a capa quadrada saia
   esticada): as Art Tracks (o video e so a capa do album) vem com uma faixa de uma cor de cada lado, e a sddefault e a
   hqdefault ainda com as pretas em cima e embaixo. Uma copia pequena com CORS (o i.ytimg.com manda) mede as faixas, o
   object-view-box corta nelas, e o tema mostra o quadrado do meio */
const CAPAS = new Map();   // id do video -> { src, corte }, ou as imagens esperando a medida
function capaInteira(img) {
  const m = /^https:\/\/i\.ytimg\.com\/vi\/([^/]+)\//.exec(img.src);
  if (!m) return;
  const id = m[1], ja = CAPAS.get(id);
  if (ja && !Array.isArray(ja)) return aplicaCapa(img, ja);
  if (ja) return void ja.push(img);
  const espera = [img];
  CAPAS.set(id, espera);
  const tenta = ([q, ...resto]) => {
    const p = new Image();
    p.crossOrigin = 'anonymous'; p.referrerPolicy = 'no-referrer';
    p.onload = () => {
      if (p.naturalWidth <= 120 && resto.length) return tenta(resto);   // o cinza do YouTube no lugar da que nao existe
      let corte = '';
      try { corte = medeFaixas(p); } catch { /* sem CORS a copia nao se le: fica sem cortar */ }
      const capa = { src: p.src, corte };
      CAPAS.set(id, capa);
      for (const i of espera) aplicaCapa(i, capa);
    };
    p.onerror = () => { if (resto.length) tenta(resto); else CAPAS.set(id, { src: '', corte: '' }); };
    p.src = `https://i.ytimg.com/vi/${id}/${q}.jpg`;
  };
  tenta(['maxresdefault', 'sddefault', 'hqdefault', 'mqdefault']);
}
function aplicaCapa(img, capa) {
  if (capa.src && img.src !== capa.src) {
    img.crossOrigin = 'anonymous';   // a mesma copia da medida, sem baixar de novo
    img.src = capa.src;
  }
  img.style.objectViewBox = capa.corte;
}
function medeFaixas(p) {
  const w = 160, h = Math.round(w * p.naturalHeight / p.naturalWidth), c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d', { willReadFrequently: true });
  g.drawImage(p, 0, 0, w, h);
  const d = g.getImageData(0, 0, w, h).data, ponto = (x, y) => (y * w + x) * 4;
  // faixa e a linha (ou a coluna) inteira da cor do meio da beira daquele lado, com a folga do JPEG
  const igual = (i, ref) => Math.abs(d[i] - d[ref]) + Math.abs(d[i + 1] - d[ref + 1]) + Math.abs(d[i + 2] - d[ref + 2]) <= 36;
  const linha = (y, ref) => { for (let x = 0; x < w; x += 2) if (!igual(ponto(x, y), ref)) return false; return true; };
  let t = 0, b = 0;
  while (t < h / 2 && linha(t, ponto(w >> 1, 0))) t++;
  while (b < h / 2 && linha(h - 1 - b, ponto(w >> 1, h - 1))) b++;
  if (t < h * .04) t = 0;
  if (b < h * .04) b = 0;
  if (t + b > h * .8) t = b = 0;
  const meio = (t + h - b) >> 1;
  const coluna = (x, ref) => { for (let y = t; y < h - b; y += 2) if (!igual(ponto(x, y), ref)) return false; return true; };
  let e = 0, r = 0;
  while (e < w / 2 && coluna(e, ponto(0, meio))) e++;
  while (r < w / 2 && coluna(w - 1 - r, ponto(w - 1, meio))) r++;
  if (e < w * .06 || r < w * .06 || e + r > w * .8) e = r = 0;
  const pc = (n, de) => n ? `${((n + 1) / de * 100).toFixed(2)}%` : '0';
  return t || b || e || r ? `inset(${pc(t, h)} ${pc(r, w)} ${pc(b, h)} ${pc(e, w)})` : '';
}
/* na maleta do celular cada disco segue a parede da caixa na altura dele: o lugar em --i e o total em --n */
function numerarFila(sec) {
  const ul = sec.querySelector('.lista-fila');
  sec.style.setProperty('--n', ul.children.length);
  [...ul.children].forEach((li, i) => li.style.setProperty('--i', i));
}
/* na etiqueta da maleta o nome da musica vai em cima e o artista embaixo (23/10, a variante B
   entre tres mocks): o titulo do YouTube "Artista - Musica" se parte no " - " (com o canal do lado direito, e "Musica -
   Artista", como no funk), sem o "(Official Video)" e parecidos; sem " - ", o artista e o canal, sem o " - Topic" */
const TITULO_LIXO = /\s*[\(\[](official( music)? video|official audio|audio|video ?clip|clipe oficial|lyric video|lyrics?|letra|visualizer|videoclipe|v[ií]deo oficial)[\)\]]/ig;
function partirTitulo(x) {
  const norm = v => (v || '').toLowerCase().normalize('NFD').replace(/[^a-z0-9]/g, '');
  const canal = (x.channel || '').replace(/ - Topic$/, '');
  // (07/11, pedido do dono) o disco que o servidor achou no YouTube Music traz o nome da musica e o artista de la
  if (x.ytm_titulo) return { musica: x.ytm_titulo, artista: x.ytm_artista || canal };
  let musica = (x.title || I18N.t('shelf.untitled')).replace(TITULO_LIXO, '').trim(), artista = canal;
  const i = musica.indexOf(' - ');
  if (i > 0) {
    let a = musica.slice(0, i).trim(), m = musica.slice(i + 3).trim();
    if (norm(canal) && norm(m).includes(norm(canal)) && !norm(a).includes(norm(canal))) [a, m] = [m, a];
    musica = m; artista = a;
  }
  return { musica: musica || x.title, artista };
}
function liFila(x) {
  const li = el('li', 'item-fila'); li.dataset.qid = x.qid;
  if (x.auto) li.classList.add('auto');
  const b = el('button', 'tocar-fila'); b.type = 'button'; b.dataset.role = 'tocar-fila';
  b.setAttribute('aria-label', I18N.t('queue.playNowItem', { title: x.title }));
  const capa = el('span', 'capinha');
  capa.append(arte({ thumb: x.thumb, id: x.id || x.youtube_id || x.qid, title: x.title }, true));
  const est = estadoEntrada(x);
  const p = partirTitulo(x);
  const s = est.startsWith('baixando') ? I18N.t('queue.downloading', { pct: est.split(' ')[1] })
    : est === 'erro' ? I18N.t('queue.notDownloaded')
    : [x.auto ? I18N.t('queue.auto') : null, p.artista, x.bpm ? `${Math.round(x.bpm)} BPM` : null,
       x.duration ? fmt(x.duration) : null].filter(Boolean).join(' · ');
  const txt = el('span', 'txt'); txt.dataset.proximo = I18N.t('queue.nextLabel'); txt.append(el('span', 't', p.musica), el('span', 's', s || ' '));
  b.append(capa, txt);
  const tirar = el('button', 'tirar'); tirar.type = 'button'; tirar.dataset.role = 'tirar';
  tirar.setAttribute('aria-label', I18N.t('queue.removeItem', { title: x.title })); tirar.innerHTML = IC.tirar;
  const alca = el('button', 'alca'); alca.type = 'button'; alca.dataset.role = 'alca';
  alca.setAttribute('aria-label', I18N.t('queue.move', { title: x.title })); alca.innerHTML = IC.alca;
  li.append(b);
  if (mostraSalvar(x)) {   // (#53) o salvar da busca, antes do tirar
    const sv = el('button', 'acao-res salvar'); sv.type = 'button'; sv.dataset.role = 'salvar';
    const [estS, prS] = estadoDisco(x);
    pintarSalvar(sv, estS, prS, x.title);
    li.append(sv);
  }
  li.append(tirar, alca);
  return li;
}
/* servidor com o Automatico (o 8799 antigo nao tem ate reiniciar): sem ele, a chave some */
const temAuto = () => !!(S.state && 'auto' in S.state);
/* o salvar do disco no prato, na linha do canal (o mostraSalvar: a parecida do Automatico, que sem ele toca so pelo
   stream e nao fica, e o que ainda baixa ou acabou de chegar); o ✓ tira de novo, como na busca */
function desenharAuto() {
  const tr = S.state && S.state.track, b = $('#b-guardar');
  b.hidden = !mostraSalvar(tr);
  if (b.hidden) return;
  const [est, pr] = estadoDisco(tr);
  const sig = [est, pr, tr.title].join('|');
  if (b._sig !== sig) { b._sig = sig; pintarSalvar(b, est, pr, tr.title); }
}
$('#b-guardar').addEventListener('click', () => {
  const tr = S.state && S.state.track;
  if (tr && alvoDisco(tr)) salvarDisco(tr);
});
function desenharFila() {
  lembrarChegadas();   // (#53) antes do salvar do prato e da fila: o que os downloads trouxeram
  desenharAuto();  // a linha do prato muda com o disco, os downloads e a prateleira, como a fila
  desenharMesa();  // a deixa e a primeira da fila
  const fila = temFila() ? S.state.queue : [];
  const auto = temAuto(), ligado = auto && S.state.auto;
  const fim = $('#b-parecidas');
  fim.hidden = !auto;
  fim.setAttribute('aria-checked', ligado ? 'true' : 'false');
  // (07/11) a chegada do estado tambem conta: a fila vazia antes e depois dele tinha a mesma assinatura e o aviso nunca saia
  // (#53) e o salvar de cada uma: a parecida salva pelo ⊕ baixa num download que nao e o da entrada
  const sig = (S.state ? '' : 'sem-estado|') + fila.map(x => [x.qid, x.title, estadoEntrada(x), mostraSalvar(x) && estadoDisco(x).join(':')].join('/')).join('|');
  if (sig === S.filaSig || S.arrastandoFila) return;
  S.filaSig = sig;
  // (07/11, pedido do dono) so com o estado na mao: no F5, antes dele chegar, a fila parecia vazia e o aviso aparecia no
  // meio da maleta ainda esticada (a prateleira sem discos), por cima de onde a prateleira fica
  $('#fila-vazia').hidden = !!fila.length || !S.state;
  // o foco (teclado) volta para o mesmo botao da mesma entrada depois de remontar
  const ativo = document.activeElement, li = ativo && ativo.closest && ativo.closest('.item-fila');
  const foco = li ? { qid: li.dataset.qid, role: ativo.dataset.role, lista: li.parentElement } : null;
  for (const sec of document.querySelectorAll('.fila')) {
    // o A seguir so aparece com fila: a chave do Tocar parecidas mora embaixo dos botoes do toca-discos
    // na mesa a maleta fica aberta mesmo vazia, com o aviso dentro
    sec.hidden = !fila.length && !(MESA.montada && sec.classList.contains('fila-parede'));
    sec.querySelector('.conta').textContent = !fila.length ? '' : I18N.tp('queue.count', fila.length);
    const limpar = sec.querySelector('.limpar-fila');   // so a do computador tem
    if (limpar) limpar.hidden = !fila.length;
    sec.querySelector('.lista-fila').replaceChildren(...fila.map(liFila));
    numerarFila(sec);
    for (const img of sec.querySelectorAll('.capinha img')) capaInteira(img);
  }
  if (foco) {
    const alvo = [...foco.lista.children].find(x => x.dataset.qid === foco.qid);
    const b = alvo && alvo.querySelector(`[data-role="${foco.role}"]`);
    if (b) b.focus();
  }
}
async function moverNaFila(qid, to) {
  try { await api('POST', '/api/queue/move', { qid, to }); } catch (e) { avisar(e.message, true); S.filaSig = null; desenharFila(); }
}
/* alvo do tamanho do desenho (22/10): o ::after marca a area, mas o Chrome do celular corrige o toque para o
   botao mais perto dentro da area do dedo (no mock, 9 px ao lado do x ainda tirava da fila). O ponto cru do
   pointerdown, que a correcao nao move, tem que cair dentro do ::after; o clique do teclado e o botao sem ::after
   (no computador) seguem como antes */
let ultimoToque = null;
addEventListener('pointerdown', e => { ultimoToque = e.pointerType === 'touch' ? { x: e.clientX, y: e.clientY } : null; }, true);
function noDesenho(b) {
  const s = getComputedStyle(b, '::after');
  if (!ultimoToque || s.content === 'none') return true;
  const r = b.getBoundingClientRect(), k = PALCO.k, x = r.left + k * parseFloat(s.left), y = r.top + k * parseFloat(s.top);
  return ultimoToque.x >= x && ultimoToque.x <= x + k * parseFloat(s.width) && ultimoToque.y >= y && ultimoToque.y <= y + k * parseFloat(s.height);
}
// so o vermelho da chave pega o toque (nao a linha toda) e alterna, como o teclado
$('#b-parecidas').addEventListener('click', e => {
  if (!S.state || (e.detail && !noDesenho($('#b-parecidas .ch')))) return;
  const v = !S.state.auto;
  $('#b-parecidas').setAttribute('aria-checked', v ? 'true' : 'false');
  ajustar('auto', v);
});
for (const sec of document.querySelectorAll('.fila')) {
  sec.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.classList.contains('abre-fila')) { abrirMaleta(!sec.classList.contains('aberta')); return; }
    if (b.classList.contains('limpar-fila')) {
      api('DELETE', '/api/queue').then(() => avisar(I18N.t('queue.cleared'))).catch(err => avisar(err.message, true));
      return;
    }
    const li = b.closest('.item-fila'); if (!li) return;
    const qid = li.dataset.qid;
    if (b.dataset.role === 'tocar-fila') api('POST', '/api/queue/play', { qid }).catch(err => avisar(err.message, true));
    else if (b.dataset.role === 'tirar' && (!e.detail || noDesenho(b))) api('DELETE', `/api/queue/${encodeURIComponent(qid)}`).catch(err => avisar(err.message, true));
    else if (b.dataset.role === 'salvar') {   // (#53) como o da busca: baixa, ou tira da prateleira o que ja chegou
      const x = (temFila() ? S.state.queue : []).find(q => q.qid === qid);
      if (x) salvarDisco(x);
    }
  });
  // teclado: as setas na alca sobem ou descem a entrada um lugar
  sec.addEventListener('keydown', e => {
    const a = e.target.closest('.alca'), deLado = MESA.montada && sec.classList.contains('fila-parede');
    const antes = e.key === 'ArrowUp' || (deLado && e.key === 'ArrowLeft'), depois = e.key === 'ArrowDown' || (deLado && e.key === 'ArrowRight');
    if (!a || (!antes && !depois)) return;
    e.preventDefault();
    const li = a.closest('.item-fila'), i = [...li.parentElement.children].indexOf(li);
    const to = antes ? i - 1 : i + 1;
    if (to < 0 || to >= li.parentElement.children.length) return;
    moverNaFila(li.dataset.qid, to);
  });
  // arrastar pela alca (dedo ou mouse): a entrada segue o ponteiro e troca de lugar com a vizinha
  // quando passa da metade dela (quem muda de lugar no DOM e a vizinha: mover a entrada soltaria
  // a captura do ponteiro); ao soltar, o servidor recebe a posicao nova
  sec.addEventListener('pointerdown', e => {
    const a = e.target.closest('.alca'); if (!a || e.button > 0 || !noDesenho(a)) return;
    const li = a.closest('.item-fila'), ul = li.parentElement;
    const de = [...ul.children].indexOf(li);
    // na mesa os discos da maleta estao lado a lado: o arrasto anda de lado
    const deLado = MESA.montada && sec.classList.contains('fila-parede'), eixo = ev => deLado ? ev.clientX : ev.clientY;
    const tam = x => deLado ? x.offsetWidth : x.offsetHeight;
    let y0 = eixo(e);
    a.setPointerCapture(e.pointerId);
    S.arrastandoFila = true; li.classList.add('arrastando');
    const mover = ev => {
      let dy = eixo(ev) - y0;
      const ant = li.previousElementSibling, prox = li.nextElementSibling;
      if (ant && dy < -tam(ant) / 2) { li.after(ant); y0 -= tam(ant); dy += tam(ant); }
      else if (prox && dy > tam(prox) / 2) { ul.insertBefore(prox, li); y0 += tam(prox); dy -= tam(prox); }
      numerarFila(sec);
      li.style.transform = deLado ? `translateX(${dy}px)` : `translateY(${dy}px)`;
    };
    const soltar = () => {
      a.removeEventListener('pointermove', mover); a.removeEventListener('pointerup', soltar); a.removeEventListener('pointercancel', soltar);
      li.style.transform = ''; li.classList.remove('arrastando');
      S.arrastandoFila = false;
      const para = [...ul.children].indexOf(li);
      if (para !== de) moverNaFila(li.dataset.qid, para);
      else { S.filaSig = null; desenharFila(); }
    };
    a.addEventListener('pointermove', mover); a.addEventListener('pointerup', soltar); a.addEventListener('pointercancel', soltar);
  });
}

/* busca: tocar na linha toca, o ⊕ salva, o ... abre as opcoes */
$('#resultados').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  const li = b.closest('.resultado'); if (!li || !li._r || li._semClique) return;
  if (b.dataset.role === 'tocar') tocarResultado(li._r);
  else if (b.dataset.role === 'salvar') salvarResultado(li._r);
  else if (b.dataset.role === 'mais') { if (menuBotao === b) fecharMenu(true); else { fecharMenu(false); abrirMenu(b, { tipo: 'resultado', r: li._r }); } }
});
/* puxar a linha para a direita poe na fila, como no Spotify: a faixa ambar
   aparece por baixo, o celular vibra quando passa do ponto e a linha volta sozinha ao soltar. So
   no dedo e so com o servidor novo; o pan-y deixa a pagina rolar na vertical */
(() => {
  const ul = $('#resultados'), PONTO = 88;
  let g = null;
  ul.addEventListener('pointerdown', e => {
    if (e.pointerType !== 'touch' || !temFila()) return;
    const li = e.target.closest('.resultado');
    if (!li || !li._r || e.target.closest('[data-role="mais"], [data-role="salvar"]')) return;
    g = { li, id: e.pointerId, x0: e.clientX, y0: e.clientY, ativo: false, passou: false };
  });
  ul.addEventListener('pointermove', e => {
    if (!g || e.pointerId !== g.id) return;
    const dx = e.clientX - g.x0, dy = e.clientY - g.y0;
    if (!g.ativo) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (dx <= 0 || Math.abs(dy) >= Math.abs(dx)) { g = null; return; }   // rolagem, ou para a esquerda
      g.ativo = true; S.puxandoRes = true;
      g.li.classList.remove('voltando'); g.li.classList.add('puxando');
    }
    const x = dx <= PONTO ? Math.max(0, dx) : PONTO + (dx - PONTO) * .3;
    g.li.querySelector('.corpo').style.transform = `translateX(${x}px)`;
    const passou = dx >= PONTO;
    if (passou !== g.passou) {
      g.passou = passou; g.li.classList.toggle('vai', passou);
      if (passou && navigator.vibrate) navigator.vibrate(12);
    }
  });
  function soltar(e, cancelou) {
    if (!g || e.pointerId !== g.id) return;
    const { li, ativo, passou } = g;
    g = null;
    if (!ativo) return;
    S.puxandoRes = false;
    li._semClique = true; setTimeout(() => { li._semClique = false; }, 400);   // o toque que puxou nao toca a linha
    li.classList.remove('puxando'); li.classList.add('voltando');
    li.querySelector('.corpo').style.transform = '';
    setTimeout(() => li.classList.remove('voltando', 'vai'), 260);
    if (passou && !cancelou) executar('fila', { tipo: 'resultado', r: li._r });
    if (S.buscaPendente) { S.buscaPendente = false; desenharBusca(); }
  }
  ul.addEventListener('pointerup', e => soltar(e, false));
  ul.addEventListener('pointercancel', e => soltar(e, true));
})();

/* each roller of the wall shades its top edge when it scrolls or changes size (sombrear, in shared.js) */
document.querySelectorAll('.rolo').forEach(r => {
  r.addEventListener('scroll', () => { fecharMenu(false); sombrear(r); }, { passive: true });
  const ro = new ResizeObserver(() => sombrear(r));
  ro.observe(r);
  for (const c of r.querySelectorAll(':scope > *, #vista-prateleira > *')) ro.observe(c);   // a vista da parede nao tem caixa
});
/* QUEUE-JS-FIM */
