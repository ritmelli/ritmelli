/* VOICE-EFFECTS-INICIO */
'use strict';
/* ---------- efeitos de voz: seletor no receptor e gaveta de teclas ---------- */
const angDial = (i, n) => n > 1 ? -135 + i * 270 / (n - 1) : 0;

async function carregarEfeitos() {
  try {
    const r = await api('GET', '/api/effects');
    S.efeitos = Array.isArray(r) ? r : [];
    S.erroEfeitos = null;
  } catch (e) { S.erroEfeitos = e.message; }
  montarGaveta();
  desenharEfeito();
}


/* pedaleira do celular: a cara de cada pedal mini, em esmalte vintage do tema
   (alguns com pintura martelada). Os knobs sao pintura: o pedal inteiro e o botao, e os efeitos
   nao tem parametro para girar */
const PEDAIS = {
  'radio-policia': { cor: '#2B4957', letra: '#EEE3CF', tipo: 'LO-FI', fonte: 'estreita', acabamento: 'martelado' },
  'megafone': { cor: '#C9922C', letra: '#261710', tipo: 'LO-FI', fonte: 'larga' },
  'locutor': { cor: '#4A2620', letra: '#EBDDC4', tipo: 'COMP', fonte: 'italica' },   // escuro: desligado se camufla entre os outros
  'eco': { cor: '#3B563B', letra: '#EAE0C8', tipo: 'DELAY', fonte: 'larga', acabamento: 'martelado' },
  'banheiro': { cor: '#769688', letra: '#1B2823', tipo: 'REVERB', fonte: 'normal' },
  'catedral': { cor: '#4B2835', letra: '#E4C07A', tipo: 'REVERB', fonte: 'italica' },
  'robo': { cor: '#9E9585', letra: '#231C16', tipo: 'RING MOD', fonte: 'larga', acabamento: 'martelado' },
  'voz-grossa': { cor: '#2E201B', letra: '#E89B42', tipo: 'OCTAVE', fonte: 'larga' },
  'esquilo': { cor: '#B85328', letra: '#F5EAD6', tipo: 'OCTAVE', fonte: 'larga' },
  'demonio': { cor: '#541B20', letra: '#F07A5B', tipo: 'PITCH', fonte: 'estreita' },
  'alien': { cor: '#7D8C3C', letra: '#1D220E', tipo: 'MOD', fonte: 'italica' },
  'estourado': { cor: '#983228', letra: '#F3E6D0', tipo: 'FUZZ', fonte: 'estreita', acabamento: 'martelado' },
  'mina': { cor: '#983228', letra: '#F3E6D0', tipo: 'MINA', fonte: 'estreita', acabamento: 'martelado' },
  'pistavoz': { cor: '#4B2245', letra: '#EBCB7A', tipo: 'VOX', fonte: 'larga' },
};
/* knobs e footswitch de niquel em pixel art na grade de 1 px css, gerados pelo dev/pecas.py no gerado/pecas.js (em KNOBS, cada knob e o
   SVG com um dos seus 11 ponteiros no lugar de PONTEIRO; no chicken-head o ponteiro e o knob inteiro, que gira; e
   PE_SVG); a pedaleira do celular mostra as pecas, e a mesa do PC so o PE_SVG (o footswitch, por cima do canvas de
   cada pedal, no PEDAL-JS). O knob de cada familia pela silhueta, do mock E1: chicken-head no Radio e alto-falante, baquelite escuro no Ambiente, o creme no resto */
const KNOB_DO_GRUPO = { radio: 'frango', ambiente: 'baquelite' };
/* o nome, o que faz e o grupo de um efeito: o /api/effects so manda os ids, e os textos sao do tema (effect.<id>.name,
   effect.<id>.desc, effect.group.<grupo>); efeito novo que o tema ainda nao conhece aparece pelo id */
const textoEf = (chave, reserva) => (I18N.tem(chave) ? I18N.t(chave) : reserva);
// o nome no pedal pode trazer o hifen opcional (­: onde a palavra comprida quebra, no caberNomes); fora dele, sai
const nomePedal = ef => textoEf(`effect.${ef.id}.name`, ef.id);
const nomeEf = ef => nomePedal(ef).replace(/­/g, '');
const descEf = ef => textoEf(`effect.${ef.id}.desc`, '');
const nomeGrupo = g => textoEf(`effect.group.${g}`, g);
$('#b-parecidas .ch').innerHTML = CHAVE_PARECIDAS;
$('#b-guardar').innerHTML = SALVAR_PIXEL;
const hashTxt = t => { let h = 7; for (const c of String(t)) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); };
function vestirPedal(b, ef) {
  const p = PEDAIS[ef.id] || { cor: ['#56677A', '#7A4B5C', '#4B7A5E'][hashTxt(ef.id) % 3], letra: '#F3EFE6', tipo: I18N.t('effects.pedalType'), fonte: 'normal' };
  b.style.setProperty('--cor', p.cor); b.style.setProperty('--letra', p.letra);
  b.dataset.fonte = p.fonte;
  if (p.acabamento) b.dataset.acabamento = p.acabamento;
  // na mesa do PC o pedal e todo do canvas: o knob, o footswitch, o LED, a plaquinha e o selo ficariam invisiveis por
  // baixo dele (o .lampada fica, vem do tecla(); a mesa monta a gaveta de novo quando o modo muda)
  if (MESA.montada) return;
  const parte = (cls, txt) => { const e = el('span', cls, txt); e.setAttribute('aria-hidden', 'true'); return e; };
  b.querySelector('.lampada').innerHTML = LED_SVG;
  const g = parte('p-grande');   // o ponteiro no risco mais perto do angulo de sempre do pedal (-120 a 120 graus, 27,3 entre riscos)
  const [knob, ponteiros] = KNOBS[KNOB_DO_GRUPO[ef.grupo]] || KNOBS.creme;
  g.innerHTML = knob.replace('PONTEIRO', ponteiros[Math.round((hashTxt(ef.id) % 240 - 120) / 27.3) + 5]);
  b.prepend(g);
  const pe = parte('p-pe'); pe.innerHTML = PE_SVG;
  b.append(pe, parte('p-tipo', p.tipo));
  if (ef.latencia_ms > 0) b.append(parte('p-adesivo', `${Math.round(ef.latencia_ms)} ms`));
}

function tecla(ef) {
  const b = el('button', 'tecla'); b.type = 'button'; b.dataset.ef = ef.id;
  b.setAttribute('aria-pressed', 'false');
  b.append(el('span', 'lampada'));
  const n = el('span', 't-nome');
  // o nome inteiro, e o com o hifen opcional para o caberNomes() tentar antes da letra menor
  n.dataset.nome = nomeEf(ef);
  if (nomePedal(ef) !== n.dataset.nome) {
    n.dataset.quebra = nomePedal(ef);
    // o nome lido inteiro: quebrado, o leitor de tela dizia "MEGA PHONE" (as duas linhas da mesa) ou levava o ­
    b.setAttribute('aria-label', n.dataset.nome);
  }
  n.append(document.createTextNode(n.dataset.nome));
  b.append(n);
  // no Troca de voz, o como escolher a voz (clicar no nome dela embaixo do visor) so entra na mesa do PC: os nomes das
  // vozes no pedal so existem la, e fora dela o leitor de tela e a dica diriam para clicar no que nao ha (revisao da r08)
  const desc = descEf(ef) + (ef.id === 'pistavoz' && MESA.montada ? ' ' + I18N.t('effects.voicePedal.howTo') : '');
  if (desc) b.append(el('span', 't-desc', desc));
  // so os de mudanca de tom atrasam a voz: diz quanto, discreto
  if (ef.latencia_ms > 0) b.append(el('span', 't-atraso', I18N.t('effects.delay', { ms: Math.round(ef.latencia_ms) })));
  vestirPedal(b, ef);
  return b;
}

function montarGaveta() {
  const banco = $('#banco');
  const foco = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.ef : null;
  banco.replaceChildren();
  $('#banco-dir').replaceChildren();
  if (!S.efeitos) {
    banco.append(el('p', 'aviso-gav', S.erroEfeitos
      ? I18N.t('effects.loadFailed')
      : I18N.t('effects.loading')));
    montarMarcas();
    return;
  }
  const grupos = new Map();
  for (const ef of S.efeitos) {
    if (!ef.grupo) continue;   // grupo vazio = Sem efeito: nao tem pedal
    if (!grupos.has(ef.grupo)) grupos.set(ef.grupo, []);
    grupos.get(ef.grupo).push(tecla(ef));
  }
  for (const [g, teclas] of grupos) {
    const sec = el('div', 'grupo-ef');
    const h = el('h3', 'suporte', nomeGrupo(g));
    const t = el('div', 'teclas'); t.setAttribute('role', 'group'); t.setAttribute('aria-label', nomeGrupo(g));
    t.append(...teclas);
    sec.append(h, t);
    banco.append(sec);
  }
  if (!S.efeitos.length) banco.append(el('p', 'aviso-gav', I18N.t('effects.noneSent')));
  repartirPedais();
  montarMarcas();
  caberNomes();
  medirCabosPedais();
  if (foco) { const b = document.querySelector(`.tecla[data-ef="${CSS.escape(foco)}"]`); if (b) b.focus(); }
}

/* os pedais mini do celular: o nome cabe inteiro no pedal, em ate 2 linhas, nas duas letras. No celular de teste (360 px
   de largura) "Megafone" e "Alienigena" saiam cortados e o Locutor e o Alto-falante perdiam o fim; com a letra de pixel
   (19/10) a letra so desce da maior para a menor, os dois tamanhos dela sem pixel borrado. Na mesa o nome e pintado no
   canvas do pedal (PEDAL-JS) e o do DOM fica transparente, so para o leitor de tela: nada a medir */
const linhasDoTexto = e => { const r = document.createRange(); r.selectNodeContents(e); return new Set([...r.getClientRects()].map(q => Math.round(q.top))).size; };
function caberNomes() {
  if (document.body.classList.contains('mesa-dj')) return;
  for (const n of document.querySelectorAll('.banco .tecla .t-nome')) {
    // desfaz a quebra no hifen opcional da medida anterior
    if (n.dataset.nome && n.textContent !== n.dataset.nome) n.textContent = n.dataset.nome;
    n.classList.remove('miuda', 'na-margem');
    if (!n.clientWidth) continue;   // gaveta fora da tela de verdade (sem caixa): mede quando aparecer
    // a letra de pixel so tem dois tamanhos sem borrar (1 e 2/3 de px por pixel): a maior em ate duas linhas,
    // desde que nenhuma palavra passe da largura (com o pisador 9 px abaixo o nome grande
    // pode ocupar duas linhas, e alienigena e uma palavra so: a palavra que nao cabe grande fica numa
    // linha, na menor); as linhas se contam pelos retangulos do texto: a altura da caixa vem presa pelo max-height
    // (tres linhas passavam por duas e a terceira sumia) e a caixa de desenho da letra passa da linha (o scrollHeight)
    const cabe = () => linhasDoTexto(n) <= 2 && n.scrollWidth <= n.clientWidth + 0.5;
    if (cabe()) continue;
    n.classList.add('na-margem');   // a grande ainda pode usar a margem do pedal (o MEGAFONE na tela de 360)
    if (cabe()) continue;
    // (r16) a palavra que nao cabe grande quebra no hifen opcional do nome (MEGA-PHONE, CATHE-DRAL), em duas linhas
    // como os nomes de duas palavras, antes de descer para a letra menor
    if (n.dataset.quebra) {
      n.classList.remove('na-margem'); n.textContent = n.dataset.quebra;
      if (cabe()) continue;
      n.classList.add('na-margem');
      if (cabe()) continue;
      n.textContent = n.dataset.nome;
    }
    n.classList.replace('na-margem', 'miuda');
  }
}
document.fonts.ready.then(caberNomes);
/* fios RCA em pixel no celular, como no mock p1: cada pedaco e um canvas de
   celulas de 4/3 px (4 px de tela no celular de teste, a grade do braco) que o CSS amplia sem suavizar.
   O fio e uma faixa de 6 celulas pela distancia ao traco (contorno, brilho do lado da luz de cima a
   esquerda, corpo, sombra clara, sombra escura, contorno), com as cores amostradas do mock; o plugue e o retangulo girado
   de antes (13 x 9 e a ponta), em celulas, com o anel da cor do fio. Desenha so quando a medida muda */
const CEL = 4 / 3, CONTORNO_FIO = [16, 14, 14];
const COR_FIO = {   // brilho, corpo, sombra clara, sombra escura
  branco: [[255, 252, 245], [240, 234, 226], [205, 201, 188], [130, 132, 126]],
  vermelho: [[250, 90, 88], [246, 50, 50], [214, 16, 18], [128, 0, 0]],
};
function bezier(a, c1, c2, b, n = 20) {
  const out = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n, u = 1 - t;
    out.push([0, 1].map(k => u * u * u * a[k] + 3 * u * u * t * c1[k] + 3 * u * t * t * c2[k] + t * t * t * b[k]));
  }
  return out;
}
/* os fios do celular e da calha, na rampa deles (COR_FIO) e com o contorno deles; os cabos da mesa de DJ sao do telaPixel
   (cabosMesa e cabosDaMesa) */
function fiosPixel(cv, larg, alt, fios, plugues, cel = CEL) {
  const pal = COR_FIO, cont = CONTORNO_FIO;
  const W = Math.ceil(larg / cel), H = Math.ceil(alt / cel);
  // (#43) uma area sem largura ou altura (o layout no meio de uma troca) fica sem cabo ate a medida seguinte, em vez
  // de o Uint8ClampedArray de tamanho negativo derrubar o desenho
  if (!(W > 0 && H > 0)) { cv.width = cv.height = 0; return; }
  const px = new Uint8ClampedArray(W * H * 4);
  const pinta = (i, [r, g, b], a = 255) => { px.set([r, g, b, a], i * 4); };
  const faixas = pts => {   // celula -> distancia com sinal ao traco, em celulas (+ do lado da luz)
    const d = new Map();
    for (let i = 0; i < pts.length - 1; i++) {
      const [ax, ay] = pts[i], [bx, by] = pts[i + 1], dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1, L = Math.sqrt(L2);
      let nx = -dy / L, ny = dx / L;
      if (nx + ny > 0) { nx = -nx; ny = -ny; }
      const r = 3 * cel;
      for (let j = Math.max(0, Math.floor((Math.min(ay, by) - r) / cel)); j <= Math.min(H - 1, Math.floor((Math.max(ay, by) + r) / cel)); j++)
        for (let k = Math.max(0, Math.floor((Math.min(ax, bx) - r) / cel)); k <= Math.min(W - 1, Math.floor((Math.max(ax, bx) + r) / cel)); k++) {
          const cx = (k + .5) * cel, cy = (j + .5) * cel, t = Math.max(0, Math.min(1, ((cx - ax) * dx + (cy - ay) * dy) / L2));
          const ex = cx - ax - t * dx, ey = cy - ay - t * dy, s = Math.hypot(ex, ey) / cel, o = d.get(j * W + k);
          if (s <= 3 && (o === undefined || s < Math.abs(o))) d.set(j * W + k, ex * nx + ey * ny >= 0 ? s : -s);
        }
    }
    return d;
  };
  const tracos = fios.map(f => [faixas(f.pts), pal[f.cor]]);
  // (r11) sem dente de 1 coluna: no fundo de uma curva a distancia ao traco cai de um lado e a coluna do meio ganhava 1
  // celula a mais embaixo (ou em cima); quando as duas vizinhas concordam entre si, a coluna copia a da esquerda
  for (const [d] of tracos) {
    const col = new Map();
    for (const i of d.keys()) { const k = i % W, j = (i / W) | 0, c = col.get(k); if (c) { c.t = Math.min(c.t, j); c.b = Math.max(c.b, j); } else col.set(k, { t: j, b: j }); }
    for (const [k, c] of col) {
      const e = col.get(k - 1), f = col.get(k + 1);
      if (!e || !f || e.t !== f.t || e.b !== f.b || (c.t === e.t && c.b === e.b) || Math.abs(c.t - e.t) > 1 || Math.abs(c.b - e.b) > 1) continue;
      for (let j = Math.min(c.t, e.t); j <= Math.max(c.b, e.b); j++) {
        const i = j * W + k, v = d.get(i - 1);
        if (v === undefined) d.delete(i); else d.set(i, v);
      }
    }
  }
  for (const [d] of tracos) for (const i of d.keys()) {   // a sombra dura: 1 celula para baixo e a direita
    const k = i + W + 1;
    if (k < W * H && px[k * 4 + 3] === 0) pinta(k, [12, 5, 2], 115);
  }
  for (const [d, [brilho, corpo, sombra, escuro]] of tracos)
    for (const [i, s] of d) pinta(i, Math.abs(s) > 2 ? cont : s > 1 ? brilho : s > 0 ? corpo : s > -1 ? sombra : escuro);
  for (const { t: [tx, ty], ang, cor } of plugues) {   // o plugue: corpo de metal, anel e capa da cor do fio (como no mock)
    const a = ang * Math.PI / 180, cs = Math.cos(a), sn = Math.sin(a), lado = Math.sign(sn - cs) || 1, dentro = new Map();
    for (let j = Math.max(0, Math.floor((ty - 22) / cel)); j <= Math.min(H - 1, Math.floor((ty + 22) / cel)); j++)
      for (let k = Math.max(0, Math.floor((tx - 22) / cel)); k <= Math.min(W - 1, Math.floor((tx + 22) / cel)); k++) {
        const ex = (k + .5) * cel - tx, ey = (j + .5) * cel - ty, lx = ex * cs + ey * sn, ly = -ex * sn + ey * cs;
        let c = null;
        if (lx >= 0 && lx <= 13 && ly >= 0 && ly <= 9) {
          const u = (ly - 4.5) * lado;
          c = lx >= 3 && lx <= 5.4 ? pal[cor][1] : u > 1.5 ? [238, 236, 230] : u < -1.5 ? [140, 138, 132] : [200, 198, 192];
        } else if (lx > 13 && lx <= 19 && Math.abs(ly - 4.5) <= 3.1 - (lx - 13) * .15) c = pal[cor][2];
        if (c) dentro.set(j * W + k, c);
      }
    for (const i of dentro.keys())
      for (const v of [i - 1, i + 1, i - W, i + W]) if (v >= 0 && v < W * H && !dentro.has(v)) pinta(v, cont);
    for (const [i, c] of dentro) pinta(i, c);
  }
  cv.width = W; cv.height = H;
  cv.style.width = W * cel + 'px'; cv.style.height = H * cel + 'px';
  cv.getContext('2d').putImageData(new ImageData(px, W, H), 0, 0);
}
/* os pedacos parados (os plugues do toca-discos e do receiver e a alca do receiver ao FX-12), nas
   medidas dos svg de antes; o canvas sai 4 px para fora de cada lado, onde os plugues passam da caixa */
const PEDACOS_FIOS = {
  '.cabo-mesa': [68, 48, [], [{ t: [19, -2], ang: 72, cor: 'branco' }, { t: [35, -2], ang: 74, cor: 'vermelho' }]],
  '.cabo-rec': [68, 50, [], [{ t: [11, 50], ang: -78, cor: 'branco' }, { t: [27, 50], ang: -76, cor: 'vermelho' }]],
  '.cabo-gav': [116, 48, [{ pts: bezier([24.5, 10], [27, 20], [39, 22], [38, 34]), cor: 'branco' }, { pts: bezier([41, 10], [44, 21], [53, 22], [51, 34]), cor: 'vermelho' }],
    [{ t: [27, -2], ang: 72, cor: 'branco' }, { t: [43, -2], ang: 70, cor: 'vermelho' }]],
};
function pedacosFios(repinta) {   // repinta: os que ja existem tambem (o canvas voltou em branco)
  for (const [sel, [w, h, fios, plugues]] of Object.entries(PEDACOS_FIOS)) {
    const caixa = document.querySelector('.palco ' + sel);
    let cv = caixa && caixa.querySelector('.fios-pixel');
    if (!caixa || (cv && !repinta)) continue;
    if (!cv) { cv = document.createElement('canvas'); cv.className = 'fios-pixel'; caixa.append(cv); }
    const mais = ([x, y]) => [x + 4, y + 4];
    fiosPixel(cv, w + 8, h + 8, fios.map(f => ({ ...f, pts: f.pts.map(mais) })), plugues.map(p => ({ ...p, t: mais(p.t) })));
  }
}
/* cabos RCA no celular: o par desce pela calha da direita, do toca-discos ate o receiver, num traco
   so por cor (o pedaco que esticava era uma faixa chapada e a emenda aparecia). As
   curvas das pontas sao as do mock, ligadas por uma reta na calha; o vao entre os aparelhos
   (titulo, fila, erro) vem do layout */
function medirCabos() {
  if (!celular()) { cabosDoComputador(); return; }
  const cv = $('#cabo-calha'), p = $('#palco');
  const m = p.querySelector('.mesa'), r = p.querySelector('.receptor');
  if (!m.offsetParent) return;
  pedacosFios();
  const pr = p.getBoundingClientRect(), mr = m.getBoundingClientRect(), rr = r.getBoundingClientRect();
  const R = p.clientWidth - 1;   // a calha e os plugues do toca-discos se alinham por aqui (a 1 px da tela)
  // os do receiver, pela beira dele: o .cabo-rec passa 15 px dela, e no celular grande o receiver nao chega na calha
  const Rr = Math.min(R, Math.round(rr.right - pr.left) + 15);
  const mb = mr.bottom - pr.top + p.scrollTop, rt = rr.top - pr.top + p.scrollTop;
  // o canto do canvas num terco de px: a celula de 4/3 px cai em 4 px de tela no celular de densidade 3
  const x0 = Rr - 72, y0 = Math.round((mb - 30) * 3) / 3, alt = Math.max(60, rt + 20 - y0);
  const pt = (x, y) => [x - x0, y - y0];
  const fio = (a, c1, c2, b, e, f1, f2, z) => [...bezier(pt(...a), pt(...c1), pt(...c2), pt(...b)), ...bezier(pt(...e), pt(...f1), pt(...f2), pt(...z))];
  // a textura do palco cobre o conteudo inteiro (ate o fim da gaveta), nao so a tela
  const g = p.querySelector('.gaveta');
  mudar(p, '--alto-palco', Math.max(p.clientHeight, g.offsetTop + g.offsetHeight + parseFloat(getComputedStyle(p).paddingBottom)) + 'px');
  const geo = `${x0}|${y0.toFixed(1)}|${alt.toFixed(1)}`;
  if (cv._geo === geo) return;
  cv._geo = geo;
  cv.style.left = x0 + 'px'; cv.style.top = y0 + 'px';
  fiosPixel(cv, R - x0, alt, [
    // o par a 5 celulas um do outro na calha (o contorno do meio e dos dois), cada um no meio de uma celula
    { pts: fio([R - 55, mb - 20], [R - 47, mb + 4], [R - 18, mb - 4], [R - 14, mb + 24], [R - 14, rt - 31], [R - 17, rt - 7], [Rr - 46, rt - 15], [Rr - 54, rt + 11]), cor: 'branco' },
    { pts: fio([R - 39, mb - 20], [R - 33, mb - 2], [R - 9.33, mb - 8], [R - 7.33, mb + 24], [R - 7.33, rt - 31], [R - 9.33, rt - 1], [Rr - 31, rt - 11], [Rr - 38, rt + 11]), cor: 'vermelho' },
  ], []);
}
/* cabos RCA no computador: o par sai de tras do toca-discos, pende no vao e entra de lado no receiver, com os fios e
   os plugues num canvas so, atras dos dois aparelhos. As curvas sao proporcoes do vao, para o par sempre chegar nos
   dois lados; com o vao estreito o plugue entra mais, e sobra fio. A celula e o pixel inteiro de tela mais perto dos
   4/3 px do celular, e o canto do canvas cai na grade da tela */
function cabosDoComputador() {
  if (MESA.montada) { cabosDaMesa(); return; }
  pedacosFios();
  const cv = $('#cabo-calha'), t = $('.tampo').getBoundingClientRect(), r = $('.receptor').getBoundingClientRect();
  const d = devicePixelRatio || 1, cel = Math.max(1, Math.round(d * 4 / 3)) / d;
  const geo = ['pc', t.right, t.top, t.height, r.left, r.top, cel].join('|');
  if (cv._geo === geo) return;
  cv._geo = geo;
  const x0 = Math.round((t.right - 32) * d) / d, y0 = Math.round((Math.min(t.top, r.top) + 20) * d) / d;
  const fundo = Math.max(t.top + 60, Math.min(t.bottom - 40, t.top + clamp(t.height * .3, 120, 190)));   // o ponto mais baixo do fio branco
  const entra = Math.max(3, (78 - (r.left - t.right)) / 2);
  const plugue = (x, y, ang, cor) => {   // pelo meio da ponta; o rabo e de onde sai o fio
    const a = ang * Math.PI / 180, cs = Math.cos(a), sn = Math.sin(a);
    return { t: [x - x0 + 4.5 * sn, y - y0 - 4.5 * cs], ang, cor, rabo: [x - x0 + 18 * cs, y - y0 + 18 * sn] };
  };
  const fio = (a, b, f, [k1, k2, k3, k4, k5], cor) => {   // da ponta a ao fundo f e dali a b, em proporcoes do vao
    const x = k => a.rabo[0] + k * (b.rabo[0] - a.rabo[0]), [xa, ya] = a.rabo, [xb, yb] = b.rabo;
    return { pts: [...bezier([xa, ya], [x(k1), ya + 1], [x(k2), f], [x(k3), f]), ...bezier([x(k3), f], [x(k4), f], [x(k5), yb + 2], [xb, yb])], cor };
  };
  const pb = plugue(t.right - entra, t.top + 40, 8, 'branco'), pv = plugue(t.right - entra, t.top + 58, 8, 'vermelho');
  const qb = plugue(r.left + entra, r.top + 44, 172, 'branco'), qv = plugue(r.left + entra, r.top + 61, 170, 'vermelho');
  cv.style.left = x0 + 'px'; cv.style.top = y0 + 'px';
  fiosPixel(cv, r.left + 32 - x0, fundo + 32 - y0, [
    fio(pb, qb, fundo - y0, [.37, .29, .58, .81, .76], 'branco'),
    fio(pv, qv, fundo + 18 - y0, [.26, .18, .52, .82, .79], 'vermelho'),
  ], [pb, pv, qb, qv], cel);
}
/* onde os cabos entram no mixer, em px do palco e em celulas pares (as do mixer e as dos canvas dos cabos caem juntas):
   no lado esquerdo, em cima a que manda o sinal para a pedaleira da esquerda (na Catedral, logo ali) e embaixo a que o
   recebe de volta (do Radio, pelo chao); no lado direito, embaixo dos pads, onde ha chao livre, o par dos Sons rapidos,
   a que recebe a pedaleira da direita (do Robo) e a que manda para ela (no Alto-falante, pelo chao). O desenhaMx poe as
   tomadas de aco nos mesmos lugares */
function jacksMesa() {
  const par = v => Math.round(v / 2) * 2, G = rectP($('#gaveta')), P = rectP($('#pads')), M = rectP($('.palco .receptor'));
  const fim = par(M.bottom - 24), v = Math.min(par(P.bottom + 22), fim - 60), b = v + 18, p2 = Math.min(b + 42, fim), p = Math.min(b + 22, p2 - 18);
  return { a: par(G.top + 26), a2: par(M.bottom - 30), v, b, p, p2 };
}
/* o par vermelho e branco dos Sons rapidos ao mixer, no canvas da calha (atras dos aparelhos), em celulas de 2 px como os
   da pedaleira, com o jeito do par da main: os plugues no pe dos pads, os cabos caem com folga e entram de lado no mixer,
   o vermelho por cima do branco sem cruzar; o branco com mais sobra, a barriga mais funda */
function cabosDaMesa() {
  const cv = $('#cabo-calha'), P = rectP($('#pads')), M = rectP($('.palco .receptor')), J = jacksMesa();
  const par = v => Math.round(v / 2) * 2;
  const geo = ['mesa-c1', P.left, P.width, P.bottom, M.right, M.bottom, J.v, J.b].map(v => typeof v === 'number' ? Math.round(v) : v).join('|');
  if (!P.width || cv._geo === geo) return;
  const x0 = par(M.right - 6), x1 = par(P.left + P.width * .5), y0 = par(Math.min(P.bottom, J.v - 10) - 6), y1 = PALCO_H;
  const W = (x1 - x0) / 2, H = Math.ceil((y1 - y0) / 2);
  if (W < 1 || H < 1) return;   // (#43) o layout no meio de uma troca (saindo da mesa): sem cabo ate a medida seguinte
  cv._geo = geo;
  const T = telaPixel(W, H);
  const cx = v => Math.floor((v - x0) / 2), cy = v => Math.floor((v - y0) / 2);
  [[.15, J.v, 'vermelho', 6], [.29, J.b, 'branco', 8]].forEach(([f, yj, cor, fundo]) => {
    const a = plugueMesa(T, cx(P.left + P.width * f), cy(P.bottom), 1), b = plugueMesa(T, cx(M.right), cy(yj), 2), yb = b.y + fundo;
    const c = T.peca(T.cabo(curvaB([[a.x, a.y], [a.x, a.y + 4], [a.x - 1, yb - 3], [a.x - 6, yb], [b.x + 9, yb - 1], [b.x + 3, b.y + 1], [b.x, b.y]]),
      PAL_CABO[cor], new Map(), 1.5));
    T.peca(a.m, [c]); T.peca(b.m, [c]);
  });
  T.sombra();
  cv.style.cssText = `left:${x0}px;top:${y0}px;width:${W * 2}px;height:${H * 2}px`;
  T.em(cv);
}
/* cabos dos pedais em pixel como no mock "Cabos B corrigido",
   de quem ligou com pressa so para fazer funcionar num show: entre vizinhos da
   mesma fileira um cabinho em U de plugue angulado (pancake) nas duas pontas; de uma fileira para a de
   baixo o cabo desce pela margem direita, corre no vao e entra na fileira de baixo pela esquerda, cada
   um de um jeito (o vermelho preso por fita crepe; o preto liso; o preto com a sobra enrolada em oito
   com abracadeira e emendado por um acoplador com a fita "SHOW SEXTA"). A entrada sai de um buraco no
   feltro em cima a esquerda e a saida, num cabo branco com a fita "VOZ", entra num buraco embaixo a
   direita, a caminho do FX-12. Celulas de 1 px de CSS (3 de tela no celular de teste) num canvas por cima
   dos pedais, com contorno de 1 celula e a sombra dura 1 celula para baixo e a direita; as fitas
   escritas sao etiquetas no DOM, na letra dos selos de atraso. Refeito so quando a geometria muda */
const CONTORNO_PIX = [10, 8, 7], SOMBRA_PIX = [12, 6, 3, 115];
const PAL_CABO = {   // brilho (o lado da luz, em cima a esquerda), meio-brilho, corpo, sombra
  preto: [[118, 115, 113], [68, 66, 66], [36, 35, 36], [20, 19, 20]],   // mais escuro que o feltro, com o brilho cinza (o branco gritava, 19/10)
  vermelho: [[246, 122, 106], [226, 66, 58], [196, 36, 32], [128, 16, 14]],
  branco: [[255, 253, 248], [242, 237, 228], [222, 215, 203], [168, 161, 148]],
};
const PAL_PECA = {   // luz, meio, escuro
  preto: [[116, 113, 111], [46, 45, 46], [24, 23, 24]],
  niquel: [[236, 236, 232], [166, 166, 164], [100, 100, 98]],
  vermelho: [[244, 112, 98], [206, 44, 40], [132, 18, 16]],
  branco: [[255, 253, 248], [228, 222, 212], [162, 156, 144]],
  crepe: [[242, 228, 176], [226, 205, 140], [178, 152, 94]],   // a fita crepe amarelada do palco, um rolo mais amarelo que o das etiquetas
  cromo: [[242, 242, 242], [150, 152, 156], [74, 76, 80]],      // o corpo do plugue em L do mock, de mais contraste
  borracha: [[118, 120, 124], [66, 68, 72], [36, 37, 40]],    // o alivio escuro dele
};

// sorteio fixo: a mesma bagunca a cada redesenho e em todo aparelho
const sorteCabo = (i, k) => { const v = Math.sin(i * 127.1 + k * 311.7) * 43758.5453; return v - Math.floor(v); };

/* B-spline cubica uniforme pelos pontos de controle, com as pontas triplicadas: a curva sai do primeiro
   ponto na direcao do segundo e chega ao ultimo vinda do penultimo, e a curvatura muda aos poucos (os
   cantos viram arcos largos sem quina, curvas graduais). Amostra cerca
   de 1 ponto por celula */
/* os trechos retos dos pontos de controle (em pe ou deitados, mais de 6 celulas) ganham um ponto a 2 celulas de cada
   ponta: com tres pontos em linha a curva passa reta neles, e o cabo da mesa corre na mesma fileira de celulas de canto
   a canto, sem o degrau do brilho que a curva solta deixava */
function retas(P) {
  const out = [P[0]];
  for (let i = 1; i < P.length; i++) {
    const [ax, ay] = P[i - 1], [bx, by] = P[i], L = Math.hypot(bx - ax, by - ay);
    if ((ax === bx || ay === by) && L > 6) {
      const ux = (bx - ax) / L, uy = (by - ay) / L;
      out.push([ax + 2 * ux, ay + 2 * uy], [bx - 2 * ux, by - 2 * uy]);
    }
    out.push(P[i]);
  }
  return out;
}
function curvaB(P) {
  const Q = [P[0], P[0], ...P, P[P.length - 1], P[P.length - 1]], out = [];
  for (let i = 0; i + 3 < Q.length; i++) {
    const [a, b, c, d] = Q.slice(i, i + 4), n = Math.max(3, Math.ceil(Math.hypot(c[0] - b[0], c[1] - b[1])));
    for (let s = i ? 1 : 0; s <= n; s++) {
      const u = s / n, u2 = u * u, u3 = u2 * u, w = [(1 - u) ** 3 / 6, (3 * u3 - 6 * u2 + 4) / 6, (-3 * u3 + 3 * u2 + 3 * u + 1) / 6, u3 / 6];
      out.push([0, 1].map(k => w[0] * a[k] + w[1] * b[k] + w[2] * c[k] + w[3] * d[k]));
    }
  }
  return out;
}

/* a tela de celulas: cada peca e um mapa celula -> cor, pintada por cima das anteriores com o contorno
   de 1 celula em volta (menos por cima das pecas coladas nela: o cabo emenda no alivio do plugue sem
   risco); dono guarda quem pintou cada celula, para a sombra cair so no feltro e nos pedais */
function telaPixel(W, H) {
  const px = new Uint8ClampedArray(W * H * 4), dono = new Int16Array(W * H).fill(-1);
  let ids = 0;
  const cel = (x, y) => x >= 0 && y >= 0 && x < W && y < H ? y * W + x : -1;
  const pinta = (i, c, id) => { px[i * 4] = c[0]; px[i * 4 + 1] = c[1]; px[i * 4 + 2] = c[2]; px[i * 4 + 3] = 255; dono[i] = id; };
  return {
    W, H, cel,
    // retangulo com a luz em cima e a esquerda e o escuro embaixo e a direita; cantos = sem as quinas
    caixa(m, x0, y0, w, h, [luz, meio, esc], cantos = true) {
      for (let y = y0; y < y0 + h; y++) for (let x = x0; x < x0 + w; x++) {
        const i = cel(x, y), bx = x === x0 || x === x0 + w - 1, by = y === y0 || y === y0 + h - 1;
        if (i >= 0 && !(cantos && bx && by)) m.set(i, y === y0 || x === x0 ? luz : y === y0 + h - 1 || x === x0 + w - 1 ? esc : meio);
      }
      return m;
    },
    // cabo de 6 celulas (traco na linha entre duas) pela distancia com sinal ao traco (+ do lado da luz); r = a meia
    // grossura (na mesa, em celulas de 2 px, o cabo e de 3: r = 1,5, as faixas na mesma proporcao)
    cabo(pts, [brilho, meio, corpo, sombra], m = new Map(), r = 3) {
      const d = new Map();
      for (let i = 0; i < pts.length - 1; i++) {
        const [ax, ay] = pts[i], [bx, by] = pts[i + 1], dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1, L = Math.sqrt(L2);
        let nx = -dy / L, ny = dx / L;
        if (nx + ny > 0) { nx = -nx; ny = -ny; }
        for (let y = Math.floor(Math.min(ay, by) - 4); y <= Math.ceil(Math.max(ay, by) + 4); y++)
          for (let x = Math.floor(Math.min(ax, bx) - 4); x <= Math.ceil(Math.max(ax, bx) + 4); x++) {
            const c = cel(x, y);
            if (c < 0) continue;
            const ox = x + .5 - ax, oy = y + .5 - ay, t = Math.max(0, Math.min(1, (ox * dx + oy * dy) / L2));
            const ex = ox - t * dx, ey = oy - t * dy, s = Math.hypot(ex, ey), o = d.get(c);
            if (s <= r && (o === undefined || s < Math.abs(o))) d.set(c, ex * nx + ey * ny >= 0 ? s : -s);
          }
      }
      const k = 3 / r;
      for (const [c, s] of d) m.set(c, s * k >= 2 ? brilho : s * k >= 1 ? meio : s * k >= -1 ? corpo : sombra);
      return m;
    },
    // m.vazias: as celulas que ficam vazias (o feltro aparece), sem o contorno e sem a sombra (a fresta do U da mesa)
    peca(m, coladas = []) {
      const id = ids++, vaz = m.vazias;
      for (const i of m.keys()) {
        const x = i % W;
        for (const v of [x > 0 ? i - 1 : -1, x < W - 1 ? i + 1 : -1, i - W, i + W])
          if (v >= 0 && v < W * H && !m.has(v) && dono[v] !== -2 && !coladas.includes(dono[v]) && !vaz?.has(v)) pinta(v, CONTORNO_PIX, id);
      }
      for (const [i, c] of m) pinta(i, c, id);
      if (vaz) for (const v of vaz) if (dono[v] === -1) dono[v] = -3;
      return id;
    },
    // buraco rasgado no feltro: o miolo escuro, a beira de baixo pegando a luz e a de cima na sombra, e
    // fibras soltas; frente = so a metade do lado (ux, uy), repintada por cima da ponta do cabo que entra
    buraco(hx, hy, i, frente) {
      // na mesa a caixa e de tolex: um ilhos de metal de 1 celula (a luz em cima a esquerda, a sombra embaixo a direita),
      // o miolo escuro com a parede de baixo pegando um pouco de luz, sem fibra solta
      const ilhos = document.body.classList.contains('mesa-dj');
      for (let y = hy - 9; y <= hy + 9; y++) for (let x = hx - 9; x <= hx + 9; x++) {
        const c = cel(x, y), ox = x + .5 - hx, oy = y + .5 - hy;
        if (c < 0 || (frente && ox * frente[0] + oy * frente[1] < .8)) continue;
        if (ilhos) {
          // o passa-cabo maior que o cabo (a boca aparece em volta da ponta): o fundo escuro e o labio de 1 celula, claro
          // embaixo e a direita (a parede de dentro que pega a luz de cima a esquerda) e escuro em cima (r03)
          // (r06) o ilhos de niquel de verdade em volta da boca (o labio escuro de 1 celula lia como a ponta cortada do cabo):
          // contorno escuro, anel de metal com a luz em cima a esquerda, a parede de dentro e o fundo escuro
          const r = Math.hypot(ox, oy), R = 7.4, k = (ox + oy) / (r || 1);
          if (r <= R - 3.4) pinta(c, [12, 10, 8], -2);
          else if (r <= R - 2.2) pinta(c, k > -.2 ? [74, 68, 62] : [26, 22, 20], -2);
          else if (r <= R - 1) pinta(c, k < -.35 ? [118, 115, 113] : k > .35 ? [74, 68, 62] : [96, 92, 88], -2);   // (r07) o niquel no tom do chao (o claro lia como um o branco)
          else if (r <= R) pinta(c, [20, 16, 14], -2);
          continue;
        }
        const a = Math.atan2(oy, ox), r = Math.hypot(ox, oy), R = 4.6 + 1.5 * sorteCabo(i, Math.round((a + Math.PI) * 2.2));
        if (r <= R) pinta(c, r <= R - 1.2 ? [4, 3, 3] : [14, 11, 10], -2);
        else if (r <= R + 1.4) pinta(c, oy > -1 ? [158, 144, 126] : [104, 94, 84], -2);
        else if (r <= R + 2.6 && sorteCabo(i, x * 13 + y * 7) < .3) pinta(c, [132, 120, 106], -2);
      }
    },
    // a sombra dura de tudo, 1 celula para baixo e a direita, so no que ficou vazio
    sombra() {
      for (let i = 0; i < W * H; i++) {
        const k = i + W + 1;
        if (dono[i] >= 0 && i % W < W - 1 && k < W * H && dono[k] === -1) px.set(SOMBRA_PIX, k * 4);
      }
    },
    em(cv) {
      cv.width = W; cv.height = H;
      cv.getContext('2d').putImageData(new ImageData(px, W, H), 0, 0);
    },
  };
}

/* plugue angulado (pancake) do cabinho em U, no vao de 12 px entre vizinhos: borda e a primeira coluna
   fora da caixa do pedal (lado 1, a direita dele) ou a ultima (lado -1), y a linha da tomada; a cabeca
   entra 3 colunas no pedal, como no mock, e o cabo sai para baixo. Devolve a peca e a ponta do alivio
   frisado, de onde sai o cabo */
function plugueAng(T, borda, y, lado, pal) {
  const m = new Map(), x0 = Math.min(borda - lado * 3, borda + lado * 4);
  T.caixa(m, x0, y - 6, 8, 12, pal);
  for (let j = -5; j <= 2; j++) m.set(T.cel(x0 + 1, y + j), pal[0]);   // o brilho do lado da luz
  // (r09) a porca do jack na lateral do pedal, saindo de tras da cabeca (os plugues em L das pontas ja tinham): 2 colunas
  // de niquel por 6 linhas na linha da tomada, a de cima clara
  const xn = lado > 0 ? x0 - 2 : x0 + 8;
  for (let j = -3; j <= 2; j++) for (let c = 0; c < 2; c++) {
    const i = T.cel(xn + c, y + j);
    if (i >= 0) m.set(i, j === -3 ? [242, 242, 242] : c === (lado > 0 ? 1 : 0) ? [150, 152, 156] : [112, 114, 118]);
  }
  for (let j = 1; j <= 3; j++) for (let c = 1; c <= 6; c++) {
    const i = T.cel(x0 + c, y + 5 + j);
    if (i >= 0) m.set(i, j % 2 ? pal[1] : pal[2]);
  }
  m.delete(-1);
  return { m, x: x0 + 4, y: y + 8.5 };
}

/* plugue em L das pontas da corrente, como o do mock:
   da tomada para fora o colar de niquel alto, a luva curta, o braco do cotovelo
   e o corpo em pe com a quina de fora arredondada, o alivio frisado e o pescoco de onde sai o cabo
   (para = -1 sobe, 1 desce). O corpo na cor do plugue (o cromado com o alivio de borracha escura), o
   colar e a luva sempre cromados; a luz vem de cima a esquerda dos dois lados. Devolve a peca e a ponta
   do pescoco */
function plugueL(T, borda, y, lado, para, pal) {
  const m = new Map(), ni = PAL_PECA.cromo, alivio = pal === PAL_PECA.cromo ? PAL_PECA.borracha : pal, col = k => borda + lado * k, f = j => y + para * j;
  const faixa = (k0, k1, j0, j1, cor) => {   // colunas k0..k1 da tomada para fora, linhas j0..j1 (para cima quando para = -1)
    const xa = Math.min(col(k0), col(k1)), xb = Math.max(col(k0), col(k1)), ya = Math.min(f(j0), f(j1)), yb = Math.max(f(j0), f(j1));
    for (let yy = ya; yy <= yb; yy++) for (let x = xa; x <= xb; x++) {
      const i = T.cel(x, yy);
      if (i >= 0) m.set(i, cor(x, yy, xa, xb, ya, yb));
    }
  };
  // cilindro em pe (sombra por coluna) e deitado (sombra por linha)
  const mistura = (c1, c2) => c1.map((v, i) => Math.round((v + c2[i]) / 2));
  const empe = ([luz, meio, esc]) => (x, yy, xa, xb) => {   // a faixa de brilho estreita e o lado de la mais escuro, como o cromado do mock
    const u = (x - xa + .5) / (xb - xa + 1);
    return u < .12 ? meio : u < .34 ? luz : u < .62 ? meio : u < .84 ? mistura(meio, esc) : esc;
  };
  const deitado = ([luz, meio, esc]) => (x, yy, xa, xb, ya, yb) => { const v = (yy - ya + .5) / (yb - ya + 1); return v < .3 ? luz : v < .72 ? meio : esc; };
  faixa(0, 2, -6, 6, x => x === Math.min(col(0), col(2)) ? ni[0] : x === Math.max(col(0), col(2)) ? ni[2] : ni[1]);   // o colar
  faixa(3, 5, -2, 2, deitado(ni));                                     // a luva
  faixa(6, 10, -5, 5, deitado(pal));                                   // o braco do cotovelo
  faixa(11, 20, -5, 17, empe(pal));                                    // o corpo
  // a quina de fora do cotovelo arredondada, e as de cima do corpo quebradas
  for (const [k, j] of [[20, -5], [20, -4], [20, -3], [19, -5], [19, -4], [18, -5], [11, 17], [20, 17]]) m.delete(T.cel(col(k), f(j)));
  const frisos = empe(alivio);
  faixa(12, 19, 18, 25, (x, yy, xa, xb, ya, yb) => (yy - f(18)) * para % 2 ? alivio[2] : frisos(x, yy, xa, xb));   // o alivio frisado
  faixa(13, 18, 26, 28, empe(alivio));                                 // o pescoco
  m.delete(-1);
  return { m, x: Math.max(col(15), col(16)), y: f(27.5) };
}

/* fita crepe atravessada no cabo (no lugar da silver tape do mock: a fita amarela e a
   mais usada na pratica): torta (sobe inclina celulas por coluna para a direita, como no mock),
   pontas rasgadas a mao, fosca (sem o vinco brilhante da silver tape) e o volume do cabo marcado */
function fitaCrepe(T, x, y, i, meia = 10, alt = 10, inclina = 0) {
  const m = new Map(), [luz, meio, esc] = PAL_PECA.crepe;
  for (let c = -meia; c <= meia; c++) for (let j = 0; j < alt; j++) {
    if (Math.abs(c) === meia && sorteCabo(i, c * 7 + j) < .45) continue;
    const k = T.cel(x + c, y + j - Math.round((c + meia) * inclina));
    if (k >= 0) m.set(k, j === 0 ? luz : j === alt - 1 ? esc : c === -4 || c === 3 ? [206, 182, 118] : meio);
  }
  return m;
}

/* fita crepe escrita a caneta, enrolada no cabo e torta como no mock (na
   diagonal, como era no mock, e a fita VOZ enrolada no cabo branco, nao sobre ele):
   a manga da volta no cabo, clara do lado da luz e escura do outro como um cilindro, e as duas pontas coladas
   uma na outra saem para a direita numa bandeirinha com o texto, dobradas na beira da manga. A manga tem a
   beira esquerda na do cabo, com o contorno em cima do dele, e a direita 1 celula alem dele, onde a dobra sai
   (a versao uma celula mais larga, encolhida 1 celula para dentro do
   cabo so na esquerda). No canvas, porque girada no DOM ela borrava o
   pixel: a fita sobe inclina celulas por coluna para a direita, e as letras, no traco fino das outras
   etiquetas, sobem com ela mas ficam em pe (a variante B). cx = a coluna do meio do cabo, cy =
   a linha do meio da fita no cabo */
// as letras da fita VOZ nas duas linguas (o VOX do ingles e a fita de voz do estudio, da largura do VOZ); a letra que
// nao esta aqui fica em branco, e o dev/testa_i18n.py confere as duas linguas
const LETRAS_FITA = {   // 5 x 6 celulas, o traco da caneta
  V: ['X...X', 'X...X', 'X...X', '.X.X.', '.X.X.', '..X..'],
  O: ['.XXX.', 'X...X', 'X...X', 'X...X', 'X...X', '.XXX.'],
  Z: ['XXXXX', '...X.', '..X..', '.X...', 'X....', 'XXXXX'],
  X: ['X...X', '.X.X.', '..X..', '..X..', '.X.X.', 'X...X'],
};
function fitaEscrita(T, cx, cy, i, texto, inclina, lado = 1) {
  const m = new Map(), [luz, meio, esc] = PAL_PECA.crepe, caneta = [38, 24, 18], alt = 10, esq = 3, dir = 4, folga = 3;
  const x0 = cx - esq, dobra = esq + dir, larg = dobra + texto.length * 6 - 1 + 2 * folga;   // a manga: do cabo ate 1 alem dele a direita
  const sobe = c => Math.round((c - esq) * inclina), y0 = cy - alt / 2;
  // lado -1: a bandeirinha sai para a esquerda do cabo (na mesa, a beira da pedaleira cortava a da direita); a coluna c
  // da fita fica em xc(c), espelhada no cabo, e o texto segue lido da esquerda para a direita
  const xc = c => lado > 0 ? x0 + c : cx + esq - c;
  for (let c = 0; c < larg; c++) for (let j = 0; j < alt; j++) {
    // (r18) a ponta em rabo de andorinha: um V so, no meio da altura (os tres dentes de 2 linhas da r05 liam como "VOZ:")
    if ((c === larg - 1 && j >= 3 && j <= 6) || (c === larg - 2 && j >= 4 && j <= 5)) continue;
    const k = T.cel(xc(c), Math.round(y0 + j - sobe(c)));
    if (k < 0) continue;
    // a manga: o cilindro com a luz a esquerda e a dobra escura na beira de saida; a bandeirinha: chapada, a beira
    // de cima clara e a de baixo escura
    m.set(k, c < dobra ? (c < 2 ? luz : c === dobra - 1 ? esc : j === 0 ? luz : meio) : j === 0 ? luz : j === alt - 1 ? esc : meio);
  }
  [...texto].forEach((l, n) => {
    // espelhada, a letra n vai na coluna da fita que fica n letras a direita do fim do texto
    // (r18) o texto 1 px para o lado da dobra: com a ponta em V ele fica no meio entre a dobra e o fundo do V
    const c0 = lado > 0 ? dobra + folga - 1 + n * 6 : dobra + folga - 1 + (texto.length - 1 - n) * 6 + 4, s = sobe(c0 + 2 * lado);   // a letra inteira sobe o tanto do meio dela
    (LETRAS_FITA[l] || []).forEach((linha, j) => [...linha].forEach((v, c) => {
      const k = T.cel(xc(c0) + c, Math.round(y0 + 2 + j - s));
      if (v === 'X' && k >= 0) m.set(k, caneta);
    }));
  });
  return m;
}

/* fita isolante preta enrolada no cabo, como o trecho preto do cabo vermelho no mock: fina, quase na grossura do cabo, em voltas de cerca de 16 px com um degrau de meia celula de uma
   sobre a outra e a emenda marcada so por uma celula mais
   escura, e o brilho fino do lado da luz. pts e o trecho da curva que ela cobre */
function fitaIsolante(T, pts) {
  const m = new Map(), brilho = [128, 132, 138], meio = [76, 80, 86], corpo = [50, 53, 58], sombra = [27, 29, 32], emenda = [34, 36, 40];
  const perto = new Map(), acc = [0];
  for (let i = 1; i < pts.length; i++) acc.push(acc[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  for (let i = 0; i + 1 < pts.length; i++) {
    const [ax, ay] = pts[i], [bx, by] = pts[i + 1], dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy || 1, L = Math.sqrt(L2);
    let nx = -dy / L, ny = dx / L;
    if (nx + ny > 0) { nx = -nx; ny = -ny; }
    for (let y = Math.floor(Math.min(ay, by) - 5); y <= Math.ceil(Math.max(ay, by) + 5); y++)
      for (let x = Math.floor(Math.min(ax, bx) - 5); x <= Math.ceil(Math.max(ax, bx) + 5); x++) {
        const c = T.cel(x, y), ox = x + .5 - ax, oy = y + .5 - ay, cru = (ox * dx + oy * dy) / L2;
        if (c < 0 || (i === 0 && cru < 0) || (i === pts.length - 2 && cru > 1)) continue;   // as pontas cortadas retas
        const u = Math.max(0, Math.min(1, cru)), ex = ox - u * dx, ey = oy - u * dy, s = Math.hypot(ex, ey), o = perto.get(c);
        if (s <= 3.4 && (!o || s < Math.abs(o[0]))) perto.set(c, [ex * nx + ey * ny >= 0 ? s : -s, acc[i] + u * L]);
      }
  }
  for (const [c, [s, a]] of perto) {
    const volta = Math.floor(a / 16), raio = volta % 2 ? 3.05 : 3.35, fase = a - volta * 16;
    if (Math.abs(s) > raio) continue;
    m.set(c, fase < 1 && volta && s > -1.6 ? emenda : s > raio - 1.2 && s <= raio - .4 ? brilho : s > 1.4 ? meio : s < -1.6 ? sombra : corpo);
  }
  return m;
}

/* acoplador femea-femea emendando dois cabos: os dois plugues retos e o tubo no meio, em niquel; y e a
   linha entre as duas do meio do cabo */
function acoplador(T, x, y) {
  const m = new Map(), ni = PAL_PECA.niquel;
  T.caixa(m, x - 14, y - 4, 9, 8, ni, false);
  T.caixa(m, x - 5, y - 5, 10, 10, ni, false);
  T.caixa(m, x + 5, y - 4, 9, 8, ni, false);
  for (const c of [x - 3, x + 2]) for (let j = -4; j <= 3; j++) m.set(T.cel(c, y + j), ni[2]);   // os aneis do tubo
  m.delete(-1);
  return m;
}

/* abracadeira de nylon preta apertando a cintura do oito, com a cabeca de um lado */
function abracadeira(T, x, y) {
  const m = new Map(), pr = PAL_PECA.preto;
  T.caixa(m, x - 10, y - 2, 20, 4, pr, false);
  T.caixa(m, x + 10, y - 3, 4, 6, pr, false);
  m.delete(-1);
  return m;
}

/* o caminho dos dois primeiros cabos da corrente como no mock B corrigido (o mesmo
   caminho do mock): os pontos de controle da curvaB ajustados por minimos quadrados a linha central
   deles no mock, levada para a escala do tema, com uma penalidade que segura a curvatura (raio minimo de
   cerca de 22 px); a margem esquerda reajustada sozinha ao mock, com o S pequeno ate o plugue (mais
   proximo do mock, 20/10). Cada ponto: 'd' = x da caixa do ultimo pedal de cima, 'f' = fracao do primeiro pedal
   de baixo ao ultimo de cima, 'e' = x da caixa do primeiro pedal de baixo; y do pe da fileira de cima.
   fita = altura da fita crepe */
const CAMINHO_MOCK = [
  {   // o vermelho, da fileira do Locutor para a do Eco
    isolante: true,
    pts: [['d', 16, -62.2], ['d', 22.5, -36.3], ['d', 19.4, -14.5], ['d', 4.7, .6], ['f', .928, 8.3], ['f', .82, 11.7], ['f', .705, 13.8], ['f', .589, 14.8],
      ['f', .474, 13.7], ['f', .36, 11.3], ['f', .247, 8.5], ['f', .138, 5.9], ['f', .042, 5.3], ['e', -13.8, 13.2], ['e', -22.1, 37.3], ['e', -16, 62.7]],
    fita: -60,
  },
  {   // o preto, da fileira da Catedral para a do Robo
    pts: [['d', 16, -56.7], ['d', 18.9, -27.2], ['d', 12.3, -4.1], ['f', .984, 10.8], ['f', .896, 18.3], ['f', .797, 20.5], ['f', .692, 19.2], ['f', .586, 16.3],
      ['f', .478, 13.1], ['f', .367, 10.4], ['f', .254, 8.2], ['f', .145, 6.1], ['f', .048, 5.2], ['e', -11.6, 10.4], ['e', -18.9, 34.3], ['e', -16, 61]],
  },
];

/* o plugue dos cabos da mesa (mock de 20/11), em celulas de 2 px: o corpo creme frisado e a porca de niquel no aparelho;
   para = -1, o cabo sai para cima (a porca embaixo, no topo do pedal), 1 para baixo (a porca em cima, no pe do aparelho),
   2 para a direita e -2 para a esquerda (num lado do aparelho). col e lin: a celula da porca colada no aparelho, col no
   meio do plugue (lin no meio, deitado). Devolve a peca e a ponta de onde sai o cabo */
const PAL_PLUGUE = [[246, 234, 204], [216, 196, 152], [158, 134, 92]];
function plugueMesa(T, col, lin, para) {
  const m = new Map(), ni = PAL_PECA.niquel, [luz, meio, esc] = PAL_PLUGUE;
  if (Math.abs(para) === 1) {
    const ny = para < 0 ? lin - 1 : lin, cy0 = para < 0 ? lin - 6 : lin + 2;
    T.caixa(m, col - 3, ny, 7, 2, ni, false);
    for (let j = 0; j < 5; j++) for (let i = -2; i <= 2; i++) {
      const k = T.cel(col + i, cy0 + j);
      if (k >= 0) m.set(k, i === -2 ? luz : i === 2 ? esc : (j % 2 ? esc : i === -1 ? luz : meio));
    }
    m.delete(-1);
    return { m, x: col + .5, y: para < 0 ? cy0 : cy0 + 4.5 };
  }
  const nx = para > 0 ? col : col - 1, cx0 = para > 0 ? col + 2 : col - 6;
  T.caixa(m, nx, lin - 3, 2, 7, ni, false);
  for (let i = 0; i < 5; i++) for (let j = -2; j <= 2; j++) {
    const k = T.cel(cx0 + i, lin + j);
    if (k >= 0) m.set(k, j === -2 ? luz : j === 2 ? esc : (i % 2 ? esc : j === -1 ? luz : meio));
  }
  m.delete(-1);
  return { m, x: para > 0 ? cx0 + 4.5 : cx0, y: lin + .5 };
}
/* a porca de niquel de uma tomada de pedal, a mesma no plugue em L das pontas e nas cabecas do U: 2 colunas por 8
   linhas, a luz em cima e na coluna da esquerda, a sombra embaixo e na da direita; x: a coluna da esquerda; y: a linha
   de cima. E o pino de metal que sai dela (1 coluna por 4 linhas, das linhas 2 a 5 da porca, mais escuro, para a porca
   se destacar do corpo do plugue) na coluna px */
function porcaPedal(put, x, y, px) {
  const ni = PAL_PECA.niquel;
  for (let j = 0; j < 8; j++) {
    put(x, y + j, j < 6 ? ni[0] : ni[1]);
    put(x + 1, y + j, j === 0 ? ni[0] : j < 6 ? ni[1] : ni[2]);
  }
  for (let j = 2; j < 6; j++) put(px, y + j, j === 2 ? ni[1] : ni[2]);
}
/* o cabinho em U entre dois pedais vizinhos, o da versao antiga redesenhado a mao na grade de 2 px: em cima do vao, os
   dois plugues lado a lado, cada um com a mesma porca e o mesmo pino do plugue em L das pontas (a porca por cima da
   lateral do seu pedal, o pino na beira dele) e a cabeca de plastico preto no vao, a luz em cima e na beira da esquerda;
   embaixo de cada um o alivio frisado e uma perna de cabo de 3 celulas (brilho, meio e corpo, a luz do lado esquerdo,
   como nos cabos longos), as duas separadas pelo contorno e por uma fresta de feltro, e a curva redonda embaixo, com o
   brilho em cima do fundo. O vao tem 4 celulas: as pernas passam 2 celulas por cima da lateral de cada pedal e a porca
   3, na altura dela (abaixo do icone, longe do nome, do LED e do footswitch). xe: a ultima coluna do pedal da esquerda;
   xd: a primeira do da direita; y: a linha de cima das cabecas (a porca comeca uma acima); L: o comprimento das pernas.
   A fresta vai em m.vazias (sem contorno nem sombra) */
function uMesa(T, xe, xd, y, L = 9) {
  const m = new Map(), [luz, , esc] = PAL_PECA.preto, bo = PAL_PECA.borracha, [cb, cm, ck, cs] = PAL_CABO.preto;
  const put = (x, yy, c) => { const i = T.cel(x, yy); if (i >= 0) m.set(i, c); };
  const b = xe - 1, i = xd + 1;   // de b a i: as pernas, de fora a fora
  // as porcas e os pinos, e as cabecas de plastico no vao (2 colunas cada, 6 linhas)
  porcaPedal(put, xe - 2, y - 1, xe); porcaPedal(put, xd + 1, y - 1, xd);
  for (const a of [xe + 1, xd - 2]) for (let j = 0; j < 6; j++) {
    put(a, y + j, j === 5 ? esc : luz); put(a + 1, y + j, j === 0 ? luz : esc);
  }
  // as pernas: a da esquerda de b a xe + 1, a da direita de xd - 1 a i; entre elas o contorno da da esquerda e a fresta
  const pernas = [b, xd - 1], fresta = xd - 2, y0 = y + 9, y1 = y0 + L;   // o alivio nas linhas 7 e 8, as pernas de y0 a y1 - 1
  for (const p of pernas) {
    for (let k = 0; k < 3; k++) { put(p + k, y + 7, k ? bo[1] : bo[0]); put(p + k, y + 8, bo[2]); }
    for (let j = y0; j < y1; j++) { put(p, j, cb); put(p + 1, j, cm); put(p + 2, j, ck); }
  }
  m.vazias = new Set();
  for (let j = y + 8; j < y1 - 1; j++) { const k = T.cel(fresta, j); if (k >= 0) m.vazias.add(k); }
  // a curva de baixo: a primeira linha fecha a fresta (o brilho em cima do fundo), a segunda vai de xe a xd, a terceira so
  // no meio; as quinas de fora ficam no contorno e a curva sai redonda
  for (let x = b; x <= i; x++) put(x, y1, x === b ? cb : x === b + 1 ? cm : x === i ? ck : x >= xe + 2 && x <= xd - 1 ? cb : cm);
  for (let x = xe; x <= xd; x++) put(x, y1 + 1, x === xd ? ck : cm);
  for (let x = xe + 1; x <= xd - 1; x++) put(x, y1 + 2, x === xd - 1 ? cs : ck);
  return m;
}
/* o plugue em L das pontas do painel (a primeira e a ultima tomada de cada fileira de pedais; no receiver todas as
   entradas usam o plugueMesa), o da versao antiga redesenhado a mao na grade de 2 px, na proporcao de la medida pelo
   pedal (o corpo e o alivio com cerca de 1/5 da altura do pedal): a porca de niquel com a coluna de dentro na beira do
   pedal, o pino, e o corpo cromado em L, o braco deitado na altura da tomada e o corpo em pe saindo de lado (6 colunas
   por 15 linhas, a quina de fora redonda, o brilho em pe perto da beira da esquerda), e o alivio frisado de borracha
   onde o cabo sai, para baixo (para = 1) ou para cima (-1). A mesma peca nas quatro pontas: no lado direito espelhada, e
   para cima virada de ponta-cabeca em volta da tomada; a luz fica sempre em cima e a esquerda. e: a coluna da beira do
   pedal do lado da tomada; lado: 1 a direita dele, -1 a esquerda; y: a linha de cima das cabecas do U (a porca comeca
   uma acima). Devolve a peca e a ponta de onde sai o cabo */
function plugueLMesa(T, e, y, lado, para) {
  const m = new Map(), cr = PAL_PECA.cromo, bo = PAL_PECA.borracha, cl = cr[0].map((v, k) => Math.round((v + cr[1][k]) / 2));
  const put = (x, yy, c) => { const i = T.cel(x, yy); if (i >= 0) m.set(i, c); };
  const c = k => e + lado * k, lin = j => para > 0 ? y + j : 2 * y + 5 - (y + j);   // j: a linha com o cabo para baixo
  const col = (k0, k1) => [Math.min(c(k0), c(k1)), Math.max(c(k0), c(k1))];
  // a porca (a coluna de dentro na beira do pedal) e o pino
  porcaPedal(put, Math.min(c(0), c(1)), y - 1, c(2));
  // o corpo cromado: o braco (c(3) e c(4), linhas 0 a 5) e o corpo em pe (c(5) a c(10), linhas 0 a 14), sem a quina de
  // fora do lado da tomada; a luz em cima e na beira da esquerda, o brilho em pe na segunda coluna do corpo, a sombra
  // embaixo e na beira da direita
  const cromo = new Set(), pos = (x, j) => x + ',' + j, quina = new Set([pos(10, 0), pos(9, 0), pos(10, 1)]);
  for (let j = 0; j < 15; j++) for (let k = 3; k <= 10; k++)
    if ((k >= 5 || j < 6) && !quina.has(pos(k, j))) cromo.add(pos(c(k), lin(j)));
  const [b0, b1] = col(5, 10);
  for (const s of cromo) {
    const [x, j] = s.split(',').map(Number), tem = (dx, dj) => cromo.has(pos(x + dx, j + dj));
    const corpo = x >= b0 && x <= b1;
    put(x, j, !tem(0, -1) || !tem(-1, 0) ? cr[0] : !tem(1, 0) || !tem(0, 1) ? cr[2] : corpo && x === b0 + 1 ? cr[0] : corpo && x === b0 + 2 ? cl : cr[1]);
  }
  // o alivio frisado, 7 linhas de 4 colunas (c(6) a c(9)): faixas escuras e claras alternadas
  const [f0, f1] = col(6, 9);
  for (let j = 15; j < 22; j++) for (let x = f0; x <= f1; x++) put(x, lin(j), j % 2 ? bo[2] : x === f0 ? bo[0] : bo[1]);
  return { m, x: (f0 + f1 + 1) / 2, y: para > 0 ? y + 22 : y - 16 };
}
/* fita crepe atravessada no cabo, prendendo ele no feltro: uma tira curta perpendicular a ele, meio torta (desliza
   inclina celulas por linha), as pontas rasgadas na mao, a borda de cima clara e a de baixo escura, a beira da esquerda
   na luz e a da direita na sombra, e o volume do cabo marcado no meio (a tira sobe por cima dele e pega a luz, e desce
   de volta ao feltro logo abaixo, na sombra). x, y: o meio da tira (em cima do cabo); comp: o comprimento atravessado,
   larg: a largura */
function fitaAtravessada(T, x, y, i, comp = 10, larg = 5, inclina = .2) {
  const m = new Map(), [luz, meio, esc] = PAL_PECA.crepe, dobra = [206, 182, 118];
  const rasga = (j, c) => (j === 0 || j === comp - 1) && (c === 0 || c === larg - 1 || sorteCabo(i, c * 5 + j) < .3);
  for (let j = 0; j < comp; j++) for (let c = 0; c < larg; c++) {
    if (rasga(j, c)) continue;   // as pontas rasgadas
    const k = T.cel(Math.round(x - larg / 2 + c + (j - (comp - 1) / 2) * inclina), Math.round(y - comp / 2 + j));
    if (k < 0) continue;
    const d = j + .5 - comp / 2, noCabo = Math.abs(d) < 1.6, desce = d >= 1.6 && d < 2.6;
    const ponta = j === 0 || (j === 1 && rasga(0, c)), pe = j === comp - 1 || (j === comp - 2 && rasga(comp - 1, c));
    m.set(k, ponta ? luz : pe ? esc : c === larg - 1 ? (noCabo ? meio : dobra) : noCabo || c === 0 ? luz : desce ? dobra : meio);
  }
  return m;
}
/* o pe do feltro das pedaleiras da mesa, em px do palco: 20 px abaixo do pedal mais alto das duas (a sombra dele, o
   feltro liso e o bisel), ou 16 com o Troca de voz, que desce 18 alem dos outros (revisao da r09: os comuns ficam com os
   34 de feltro embaixo de antes, e a altura do feltro nao muda); o mesmo nas duas, e nunca acima de 2 px do pe da
   gaveta. O desenhaGav (o feltro) e o cabosMesa (o pe da faixa de feltro em que o cabo longo ondula) usam o mesmo */
function fundoDoFeltro(gav) {
  const t0 = document.querySelector('.palco .banco .tecla[data-ef]');
  let alto = 0;
  for (const t of document.querySelectorAll('.palco .banco .tecla[data-ef]')) alto = Math.max(alto, t.offsetHeight);
  const G = rectP(gav);
  const margem = document.querySelector('.palco .banco .tecla[data-ef="pistavoz"]') ? 16 : 20;
  return Math.max(G.bottom - 2, t0 && alto ? rectP(t0).top + alto + margem : 0);
}
/* os cabos das pedaleiras da mesa, de quem ligou tudo as pressas num bar, quinze minutos antes do show. Cada painel e um
   laco que sai do receiver e volta para ele, com o sinal da direita para a esquerda, como nos pedais de verdade: a
   tomada de entrada no lado direito de cada pedal e a de saida no esquerdo, a 1/3 da altura (logo abaixo do icone).
   Entre vizinhos, o cabinho curto em U da versao antiga, descendo no vao; nas pontas, plugues em L. Na esquerda o mixer
   manda pelo lado esquerdo dele para a Catedral (curto, pela quina do painel) e o Radio devolve ate o lado esquerdo do
   mixer; na direita o Robo devolve por cima da parede de dentro, pelo vao e por baixo dos Sons rapidos ate o lado direito
   do mixer, e o mixer manda ate o Alto-falante. O cabo longo de cada painel (o do Radio e o do Alto-falante) sai da
   tomada da ponta numa barriga para fora, pendurado na beira de fora por cima da madeira, volta para o feltro e corre
   jogado em ondas largas na faixa de feltro embaixo dos pedais ate sair pela beira de dentro, preso com fita crepe
   atravessada. Nada passa por cima do nome, do LED, do footswitch ou do visor */
function cabosMesa(banco, cv) {
  banco.querySelectorAll('.fita-escrita').forEach(x => x.remove());
  const esq = banco.id === 'banco', gav = banco.closest('.gaveta'), recep = $('.palco .receptor'), pads = $('#pads');
  const peds = [...banco.querySelectorAll('.teclas > .tecla')].filter(p => p.offsetWidth);
  if (!peds.length || !recep || !pads || !pads.offsetWidth) { cv.width = 0; cv._geo = ''; return; }
  const G = rectP(gav), B = rectP(banco), M = rectP(recep), P = rectP(pads), R = peds.map(p => rectP(p)), J = jacksMesa(), F = fundoDoFeltro(gav);
  const par = v => Math.round(v / 2) * 2;
  // o canvas: da madeira de fora do painel (a barriga do cabo longo) ate o lado do mixer
  const x0 = par(esq ? G.left - 20 : M.right - 4), x1 = par(esq ? M.left + 6 : G.right + 20), y0 = par(G.top - 12), y1 = PALCO_H;
  const geo = ['mesa-c7', x0, x1, y0, G.left, G.right, G.top, B.left, B.top, M.left, M.right, M.bottom, P.right, P.bottom, F,
    ...Object.values(J), ...R.flatMap(r => [r.left, r.top, r.width])].map(v => typeof v === 'number' ? Math.round(v) : v).join(',');
  if (cv._geo === geo) return;
  cv._geo = geo;
  const W = (x1 - x0) / 2, H = Math.ceil((y1 - y0) / 2), T = telaPixel(W, H);
  const cx = v => Math.floor((v - x0) / 2), cy = v => Math.floor((v - y0) / 2);
  const n = R.length, yj = cy(R[0].top) + 40;   // a linha das tomadas
  const liga = (ctrl, ...plugues) => {
    const pts = curvaB(ctrl), c = T.peca(T.cabo(pts, PAL_CABO.preto, new Map(), 1.5));
    for (const p of plugues) T.peca(p.m, [c]);
    return pts;
  };
  // a faixa de feltro embaixo dos pedais: o meio do cabo de 3,5 celulas abaixo do pe do pedal que esta em cima (o contorno
  // nao encosta nele) ate 5,5 acima do pe do feltro. Na faixa estreita (a de 20 px, sem o Troca de voz, e a de 16 embaixo
  // dele) o cabo (12 px com o contorno e a sombra) nao tem onde ondular: a crista encosta no pe do pedal e o vale passa da
  // beira da frente, o cabo jogado meio para fora do painel; embaixo do Troca de voz ele passa reto no meio da faixa (as
  // ondas pulam ele)
  const xp0 = cx(R[0].left), xp1 = cx(R[n - 1].right);
  const pe = x => Math.max(cy(R[0].bottom), ...R.filter(r => x >= cx(r.left) - 3 && x <= cx(r.right) + 3).map(r => cy(r.bottom)));
  const estreita = x => cy(F) - pe(x) <= 10;
  const teto = x => pe(x) + (estreita(x) ? 3 : 3.5);
  const fundo = x => Math.max(teto(x), cy(F) + (estreita(x) ? 1 : -5.5)), meio = x => (teto(x) + fundo(x)) / 2;
  // as ondas largas e irregulares, de xa para xb: meia onda de 20 a 38 celulas, cada crista com dois pontos (a curva chega
  // perto dela), a de cima rente aos pedais e a de baixo perto do pe do feltro (na faixa larga sem encostar em nenhum dos
  // dois); alto: a primeira crista e a de cima. Embaixo do pedal que desce mais (o Troca de voz) o cabo passa reto no meio
  // da faixa, com dois pontos de cada lado da beira dele (a curva so sobe depois dela). Devolve os pontos da esquerda para
  // a direita
  const ondas = (xa, xb, i, alto) => {
    const s = Math.sign(xb - xa), pts = [], base = Math.min(...R.map(r => cy(r.bottom)));
    const fundos = R.filter(r => cy(r.bottom) > base).map(r => [cx(r.left) - 7, cx(r.right) + 7, (cy(r.bottom) + cy(F)) / 2 + .5])
      .filter(([l, r]) => l > Math.min(xa, xb) && r < Math.max(xa, xb));
    for (let j = 0, x = xa; ; j++, alto = !alto) {
      x += s * (20 + sorteCabo(i, j) * 18);
      if ((xb - x) * s < 14) break;
      if (fundos.some(([l, r]) => x > l - 6 && x < r + 6)) continue;
      const y = alto ? teto(x) + sorteCabo(i, j + 20) * 2 : fundo(x) - sorteCabo(i, j + 40) * 2.5;
      pts.push([x - 3, Math.min(fundo(x), y)], [x + 3, Math.min(fundo(x), y)]);
    }
    for (const [l, r, y] of fundos) pts.push([l, y], [l + 9, y], [r - 9, y], [r, y]);
    return pts.sort((p, q) => p[0] - q[0]);
  };
  // a curva assentada na faixa: onde ela ainda sobe demais embaixo de um pedal, o ponto das ondas mais perto, entre os
  // quatro que fazem a curva ali, desce (no maximo ao fundo do lugar onde ela subiu), ate caber; a e b: o trecho das ondas
  // no ctrl, da esquerda para a direita
  const assenta = (ctrl, a, b) => {
    for (let volta = 0; volta < 160; volta++) {
      let pior = .5, px = null;   // meia celula de folga: o contorno ainda fica longe do pe
      for (const [x, y] of curvaB(ctrl)) if (x > xp0 + 1 && x < xp1 - 1 && teto(x) - y > pior) { pior = teto(x) - y; px = x; }
      if (px === null) break;
      const lim = j => Math.max(fundo(ctrl[j][0]), fundo(px));
      let j0 = a, k = -1;
      while (j0 + 1 < b && ctrl[j0 + 1][0] <= px) j0++;
      for (let j = Math.max(a, j0 - 1); j <= Math.min(b - 1, j0 + 2); j++)
        if (ctrl[j][1] < lim(j) - .01 && (k < 0 || Math.abs(ctrl[j][0] - px) < Math.abs(ctrl[k][0] - px))) k = j;
      if (k < 0) break;
      ctrl[k][1] = Math.min(lim(k), ctrl[k][1] + pior + .3);
    }
    return ctrl;
  };
  // a fita crepe atravessada no cabo, perto de um x, no ponto mais deitado e mais perto do meio da faixa de feltro,
  // perpendicular ao cabo e meio torta; mais curta na faixa estreita, para caber inteira no feltro
  const fita = (pts, x, i) => {
    let q = -1, melhor = Infinity;
    for (let j = 2; j + 2 < pts.length; j++) {
      const [px, py] = pts[j];
      if (Math.abs(px - x) > 30 || px < xp0 + 6 || px > xp1 - 6) continue;
      const d = Math.abs(py - (pe(px) + cy(F)) / 2) + 4 * Math.abs((pts[j + 2][1] - pts[j - 2][1]) / ((pts[j + 2][0] - pts[j - 2][0]) || 1));
      if (d < melhor) { melhor = d; q = j; }
    }
    if (q < 0) return;
    const incl = (pts[q + 2][1] - pts[q - 2][1]) / ((pts[q + 2][0] - pts[q - 2][0]) || 1);
    const comp = Math.min(11, cy(F) - pe(pts[q][0]) - 2);
    T.peca(fitaAtravessada(T, pts[q][0], pts[q][1], i, comp, 6, -incl + (sorteCabo(i, 7) < .5 ? -.2 : .2)));
  };
  // a barriga do cabo longo na ponta: do alivio do plugue em L, o cabo sai para fora da beira do painel por cima da
  // madeira, redondo, e volta para o feltro embaixo do pedal da ponta. x, y: a ponta do plugue; f: 1 para a direita, -1
  // para a esquerda; r: a coluna de referencia do caminho (a 3,5 celulas da beira do pedal da ponta do lado esquerdo e a
  // 4,5 do direito, onde a barriga foi aprovada; a parte de baixo nao muda com o tamanho do plugue); ry: a linha dela
  // (12 abaixo das cabecas do U). Da tomada para o feltro
  const barriga = (x, y, f, r, ry) => [[x, y], [x, y + 3], [(x + r + 7 * f) / 2, y + 7], [r + 7 * f, Math.max(y + 12, ry + 24)],
    [r + 7 * f, ry + 42], [r + 5 * f, ry + 54], [r + f, teto(r - 3 * f) + 1.5], [r - 9 * f, meio(r - 9 * f)]];
  // os U entre vizinhos, cada um com o seu comprimento
  for (let k = 0; k + 1 < n; k++) T.peca(uMesa(T, cx(R[k].right) - 1, cx(R[k + 1].left), yj, 8 + Math.round(sorteCabo(k + (esq ? 0 : 9), 5) * 3)));
  if (esq) {
    // a entrada: do lado esquerdo do mixer (em cima) ao lado direito da Catedral, pela quina do painel. O cabo e curto e
    // meio esticado: sai do L para cima, faz uma curva so, larga, num C com uma barriga leve para o lado do painel, e entra
    // deitado no plugue do receiver
    const ent = plugueLMesa(T, cx(R[n - 1].right) - 1, yj, 1, -1), m = plugueMesa(T, cx(M.left) - 1, cy(J.a), -2);
    const h = ent.y - m.y;   // a subida, do alivio do L ao plugue
    liga([[ent.x, ent.y], [ent.x, ent.y - 4], [ent.x - 2, ent.y - h * .35], [ent.x - 3, m.y + h * .3], [ent.x - 1, m.y + 2],
      [m.x - 2, m.y], [m.x, m.y]], ent, m);
    // a saida: do lado esquerdo do Radio, a barriga para fora da beira, de volta ao feltro, as ondas embaixo dos pedais e a
    // saida pela beira de dentro, no meio da faixa, subindo por cima da parede ate o lado esquerdo do mixer (embaixo), no
    // mesmo plugue deitado das outras entradas do receiver (o L fica so nas pontas dos pedais)
    const sai = plugueLMesa(T, cx(R[0].left), yj, -1, 1), v = plugueMesa(T, cx(M.left) - 1, cy(J.a2), -2), xin = cx(B.right);
    const rx = cx(R[0].left) - 3.5, ini = barriga(sai.x, sai.y, -1, rx, yj + 12), o = ondas(rx + 12, xin - 6, 3, true);
    const pts = liga(assenta([...ini, ...o, [xin - 4, meio(xin - 4)], [xin + 1, meio(xin - 4) - 1], [v.x - 4, v.y + 3], [v.x - 1, v.y], [v.x, v.y]],
      ini.length, ini.length + o.length), sai, v);
    fita(pts, cx(n > 1 ? (R[(n >> 1) - 1].right + R[n >> 1].left) / 2 : (R[0].left + R[0].right) / 2), 5);
  } else {
    // a saida: do lado esquerdo do Robo, por cima da parede de dentro, desce no vao e corre embaixo dos Sons rapidos ate
    // o lado direito do mixer
    const sai = plugueLMesa(T, cx(R[0].left), yj, -1, 1), m = plugueMesa(T, cx(M.right), cy(J.p), 2);
    const xv = cx((P.right + G.left) / 2), yp = cy(P.bottom) + 8, yc = Math.max(cy(J.p), cy(P.bottom)) + 8;
    // (do vao para baixo os mesmos pontos de antes do plugue novo: a linha yj + 28 e a de referencia)
    liga([[sai.x, sai.y], [sai.x, sai.y + 2], [sai.x - 4, yj + 26], [xv, yj + 28], [xv, yp], [xv - 2, yc - 4], [xv - 14, yc],
      [m.x + 28, yc + 1], [m.x + 8, m.y + 3], [m.x, m.y]], sai, m);
    // a entrada: o mixer manda por baixo dos Sons rapidos, numa barriga na madeira entre o mixer e o painel, entra no feltro
    // pela beira de dentro, no meio da faixa, corre em ondas embaixo dos pedais (a primeira, a de cima, embaixo do
    // Alto-falante) e sobe pela barriga para fora da beira de fora ate o lado direito dele
    const m2 = plugueMesa(T, cx(M.right), cy(J.p2), 2), ent = plugueLMesa(T, cx(R[n - 1].right) - 1, yj, 1, 1), xin = cx(B.left);
    const xm = cx((M.right + G.left) / 2), chao = cy(Math.min(M.bottom + 10, F - 2));
    const ini = [[m2.x, m2.y], [m2.x + 6, m2.y + 2], [m2.x + 12, m2.y + 9], [xm - 30, chao - 1], [xm, chao], [xm + 34, chao - 3],
      [xin - 12, meio(xin + 8) + 2], [xin - 2, meio(xin + 8) + 1], [xin + 8, meio(xin + 8)]], xa = cx((R[n - 1].left + R[n - 1].right) / 2);
    const o = [...ondas(xa - 6, xin + 12, 4, false), [xa - 3, teto(xa) + 1], [xa + 3, teto(xa) + 1]];   // a crista de cima embaixo do Alto-falante
    const pts = liga(assenta([...ini, ...o, ...barriga(ent.x, ent.y, 1, cx(R[n - 1].right) - 1 + 4.5, yj + 12).reverse()], ini.length, ini.length + o.length), m2, ent);
    fita(pts, cx(n > 1 ? (R[(n >> 1) - 1].right + R[n >> 1].left) / 2 : (R[0].left + R[0].right) / 2), 6);
  }
  T.sombra();
  cv.style.cssText = `left:${x0 - B.left}px;top:${y0 - B.top}px;width:${W * 2}px;height:${H * 2}px`;
  T.em(cv);
}

function medirCabosPedais() {
  medirCabosBanco($('#banco'));
  medirCabosBanco($('#banco-dir'));   // a outra metade, na mesa de DJ
}
function medirCabosBanco(banco) {
  const limpa = () => { banco?.querySelector(':scope > .cabos-pedais')?.remove(); banco?.querySelectorAll('.fita-escrita').forEach(x => x.remove()); };
  if (!banco || !banco.offsetParent) { if (banco && banco.id === 'banco-dir') limpa(); return; }
  // as margens dos cabos: o feltro no celular, o proprio banco no computador, com a lista rolando sob o FX-12 (a mesa de
  // DJ tem os dela, no cabosMesa)
  const gav = celular() ? banco.closest('.gaveta') : banco, listas = banco.querySelectorAll('.teclas');
  if (!listas.length) { limpa(); return; }
  let cv = banco.querySelector(':scope > .cabos-pedais');
  if (!cv) {
    cv = document.createElement('canvas');
    if (banco.id === 'banco') cv.id = 'cabos-pedais';
    cv.className = 'cabos-pedais';
    cv.setAttribute('aria-hidden', 'true');
  }
  if (cv.parentNode !== banco) { cv._geo = ''; banco.append(cv); }
  if (MESA.montada) { cabosMesa(banco, cv); return; }

  // a grade das celulas comeca na borda da gaveta, em px inteiros do banco (os pedais caem em px inteiros dela)
  const gr = rectP(gav), br = rectP(banco);
  const xOff = Math.round(br.left - gr.left), W = Math.round(gr.width), H = Math.ceil(br.height);
  // o canvas passa da beira do feltro ate perto da beira do palco, para a fita VOZ sair por cima da parede;
  // W segue a largura do feltro, a beira de tudo o mais
  const Wc = Math.max(W, Math.round(rectP(banco.closest('.palco')).right - 2 - gr.left));
  const X = v => Math.round(v - gr.left), Y = v => Math.round(v - br.top);
  /* cada fileira: as caixas dos pedais (esquerda e direita), a linha das tomadas (y, a dos tracos de
     IN/OUT), o topo livre de cima (a etiqueta do grupo, quando a fileira abre um), topo e pe das caixas */
  const linhas = [];   // os pedais pela altura: no computador uma fileira pode juntar dois grupos
  for (const t of listas) {
    const rot = t.previousElementSibling;
    t.querySelectorAll(':scope > .tecla').forEach((p, i) => {
      const r = rectP(p), l = linhas[linhas.length - 1];
      if (l && Math.abs(l.rs[0].top - r.top) < 1) l.rs.push(r);
      else linhas.push({ rs: [r], rot: i === 0 ? rot : null });
    });
  }
  const filas = linhas.map(({ rs, rot }) => {
    const topoP = Math.min(...rs.map(r => r.top));
    return {
      cx: rs.map(r => [X(r.left), X(r.right)]), y: Y(rs[0].top) + 51, topoP: Y(topoP),
      topo: Y(Math.min(topoP, rot ? rectP(rot).top : Infinity)), pe: Y(Math.max(...rs.map(r => r.bottom))),
    };
  });
  const geo = `${W}|${Wc}|${H}|${xOff}|` + filas.map(q => [...q.cx.flat(), q.y, q.topo, q.pe].join(',')).join(';');
  if (cv._geo === geo) return;
  cv._geo = geo;

  const T = telaPixel(Wc, H), vivas = new Set();
  // a fita crepe escrita, no DOM: x e y no canvas, centrada na altura y
  const fita = (k, texto, x, y) => {
    let e = banco.querySelector(`.fita-escrita[data-k="${k}"]`);
    if (!e) {
      e = document.createElement('span');
      e.className = 'fita-escrita';
      e.dataset.k = k;
      e.setAttribute('aria-hidden', 'true');
      e.textContent = texto;
      banco.append(e);
    }
    e.style.left = (x - xOff) + 'px';
    e.style.top = Math.round(y - e.offsetHeight / 2) + 'px';
    vivas.add(e);
  };
  // o cabo e depois os plugues das pontas por cima dele, emendados
  const liga = (ctrl, cor, ...plugues) => {
    const pts = curvaB(ctrl), c = T.peca(T.cabo(pts, cor));
    for (const p of plugues) T.peca(p.m, [c]);
    return pts;
  };
  // o ponto da curva mais perto de uma altura (ou de um x), num trecho dela
  const naAltura = (pts, y, f = () => true) => pts.filter(f).reduce((m, p) => Math.abs(p[1] - y) < Math.abs(m[1] - y) ? p : m);
  const noX = (pts, x, f = () => true) => pts.filter(f).reduce((m, p) => Math.abs(p[0] - x) < Math.abs(m[0] - x) ? p : m);

  // o cabinho em U entre vizinhos: as pernas descendo dos dois plugues e a volta embaixo, cada um com o seu caimento
  filas.forEach((q, f) => {
    for (let k = 0; k + 1 < q.cx.length; k++) {
      const a = plugueAng(T, q.cx[k][1], q.y, 1, PAL_PECA.preto);
      const b = plugueAng(T, q.cx[k + 1][0] - 1, q.y, -1, PAL_PECA.preto);
      const raio = (b.x - a.x) / 2, cx = (a.x + b.x) / 2, cy = a.y + 9 + Math.round(sorteCabo(f * 3 + k, 1) * 5);
      const pts = [[a.x, a.y], [a.x, cy]];
      for (let s = 1; s < 8; s++) { const t = Math.PI * (1 - s / 8); pts.push([cx + raio * Math.cos(t), cy + raio * Math.sin(t)]); }
      pts.push([b.x, cy], [b.x, b.y]);
      const c = T.peca(T.cabo(pts, PAL_CABO.preto));
      T.peca(a.m, [c]);
      T.peca(b.m, [c]);
    }
  });

  // de uma fileira para a de baixo: margem direita, vao, margem esquerda
  for (let i = 0; i + 1 < filas.length; i++) {
    const a = filas[i], b = filas[i + 1], r = k => sorteCabo(i, k), jeito = i % 3;
    const ra = a.cx[a.cx.length - 1][1], lb = b.cx[0][0];
    const pa = plugueL(T, ra, a.y, 1, 1, jeito === 0 ? PAL_PECA.vermelho : PAL_PECA.preto);
    const pb = plugueL(T, lb - 1, b.y, -1, -1, PAL_PECA.cromo);
    const cor = jeito === 0 ? PAL_CABO.vermelho : PAL_CABO.preto;
    /* o vao: abaixo da sombra dura dos pedais de cima (8 px) e longe das tomadas de fonte dos de baixo.
       Entre fileiras do mesmo grupo o feltro livre nao cabe o cabo, e as fileiras nao se afastam
       (20/10): o cabo corre colado no pe dos pedais de cima, por cima da sombra deles, e as tomadas
       de baixo ficam a mostra. O cabo faz curva aberta nos cantos e nao corre reto: pesa e ondula */
    const aperto = b.topo - a.pe - 16 < 8, yv = aperto ? a.pe + 5 : a.pe + Math.round(Math.min(13, 8 + Math.max(4, (b.topo - a.pe - 16) / 2)));
    /* o vao em pontos de controle da curvaB: a quina de cada canto puxa a curva sem ser tocada, e o arco
       sai largo; no vao o cabo pesa um pouco no meio */
    const vao = [[pa.x + 1, yv], [ra - 40, yv + 1], [(ra + lb) / 2 + (r(3) - .5) * 30, yv + (aperto ? 1 : 3)], [lb + 30, yv + 1], [lb - 16, yv]];
    // na margem esquerda desce um pouco por fora do plugue e entra nele num S pequeno, como no mock
    const desce = [[lb - 19.5, yv + (pb.y - yv) * .35], [pb.x, pb.y - (pb.y - yv) * .35], [pb.x, pb.y]];
    if (jeito === 2) {
      // a sobra enrolada em oito na margem direita, com a abracadeira na cintura
      const xr = Math.round((ra + 3 + W) / 2), y1 = a.y + 50, y2 = y1 + 18, roda = (cy, de) => {
        const pts = [];
        for (let s = 0; s <= 32; s++) { const t = de + s / 32 * Math.PI * 2; pts.push([xr + 9 * Math.cos(t), cy + 9 * Math.sin(t)]); }
        return pts;
      };
      liga([[pa.x, pa.y], [pa.x, pa.y + 7], [xr - 9, y1 - 11], [xr - 6.5, y1 - 6.5]], cor, pa);
      const pts = liga([[xr + 6.5, y2 + 6.5], [xr + 8.5, y2 + 14], [xr + 6, yv - 16], [xr + 3, yv + 1], ...vao.slice(1), ...desce], cor, pb);
      T.peca(T.cabo(roda(y1, -2.4), cor));
      T.peca(T.cabo(roda(y2, -1.2), cor));
      T.peca(abracadeira(T, Math.floor(xr), Math.floor((y1 + y2) / 2)));
      const xa = Math.round((pa.x + pb.x) / 2 + 14);
      T.peca(acoplador(T, xa, Math.round(noX(pts, xa, p => p[1] < yv + 8)[1])));
      fita('show', I18N.t('effects.tape.show'), Math.round(pb.x + 9), noX(pts, pb.x + 38, p => p[1] < yv + 8)[1]);
    } else if (!aperto) {
      const c = CAMINHO_MOCK[jeito], mx = ([q, v]) => q === 'd' ? Math.min(ra + v, W - 3) : q === 'e' ? lb + v : lb + (ra - lb) * v;
      const pts = liga([[pa.x, pa.y], ...c.pts.map(p => [mx(p), a.pe + p[2]]), [pb.x, pb.y]], cor, pa, pb);
      if (c.fita) { const [tx, ty] = naAltura(pts, a.pe + c.fita, p => p[0] > ra); T.peca(fitaCrepe(T, Math.round(tx), Math.round(ty) - 5, i, 9, 12, .35)); }
      // a fita isolante cobre o trecho de baixo da fileira, da curva da direita ate a da esquerda
      if (c.isolante) T.peca(fitaIsolante(T, pts.filter(p => p[1] > a.pe + 2 && p[0] < ra - 8 && p[0] > lb + 2)));
    } else {
      /* sem a etiqueta de grupo no caminho: desce do plugue abrindo ate
         perto da beira da gaveta, contorna o canto do pedal num arco largo, corre logo abaixo da fileira
         e desce em arco largo rente a beira esquerda ate o plugue; a fita crepe no trecho aberto */
      liga([[pa.x, pa.y], [pa.x, pa.y + 10], [pa.x + 6, (pa.y + yv) / 2], [pa.x + 2, yv - 6], ...vao, ...desce], cor, pa, pb);
    }
  }

  // as pontas da corrente: a entrada sai de um buraco em cima a esquerda e a saida, branca, entra num embaixo a direita
  const q0 = filas[0], qn = filas[filas.length - 1];
  const pin = plugueL(T, q0.cx[0][0] - 1, q0.y, -1, -1, PAL_PECA.cromo);
  const hx = Math.max(7, Math.round(pin.x - 12)), hy = Math.round(pin.y - 30);
  T.buraco(hx, hy, 100);
  liga([[hx, hy], [hx + 1, hy + 9], [pin.x, pin.y - 14], [pin.x, pin.y]], PAL_CABO.preto, pin);
  T.buraco(hx, hy, 100, [-.2, -1]);
  const rn = qn.cx[qn.cx.length - 1][1], pout = plugueL(T, rn, qn.y, 1, 1, PAL_PECA.branco);
  const sx = Math.min(W - 9, Math.round(pout.x + 14)), sy = Math.round(pout.y + 44);
  T.buraco(sx, sy, 101);
  liga([[pout.x, pout.y], [pout.x, pout.y + 12], [pout.x + 1, pout.y + 26], [sx - 5, sy - 9], [sx, sy]], PAL_CABO.branco, pout);
  T.buraco(sx, sy, 101, [.5, 1]);
  // a fita VOZ enrolada no cabo branco, a bandeirinha subindo para a direita por cima do feltro e da parede
  T.peca(fitaEscrita(T, Math.round(pout.x), Math.round(pout.y + 17), 102, I18N.t('effects.tape.voice'), 0));   // (r13) reta: girada, a letra de meia celula serrilhava

  T.sombra();
  cv.style.cssText = `left:${-xOff}px;top:0;width:${Wc}px;height:${H}px`;
  T.em(cv);
  for (const e of banco.querySelectorAll('.fita-escrita')) if (!vivas.has(e)) e.remove();
}

/* a descricao do efeito no computador: ao passar o mouse ou com o foco do teclado no pedal (o leitor de tela le a do
   proprio pedal); no pedal ligado, embaixo, como desligar. Nos botoes das vozes do Troca de voz, o que eles fazem,
   embaixo (em cima cobriria o visor, que confirma a escolha; na mesa, embaixo da base do pedal). No pedal, em cima, ou
   embaixo se nao couber */
let dicaAlvo = null;
function dicaDoPedal(p) {
  const d = $('#dica-pedal'), voz = !!p && p.classList.contains('voz-pedal');
  // a da voz vem do data-dica (na ja escolhida, que ela ja e a escolhida), ou do aria-label
  const desc = p && !voz ? p.querySelector('.t-desc') : null, txt = voz ? p.dataset.dica || p.getAttribute('aria-label') : desc ? desc.textContent : '';
  d.hidden = !txt;
  dicaAlvo = txt ? p : null;
  if (!txt) return;
  const on = !voz && p.getAttribute('aria-pressed') === 'true';
  d.dataset.on = on;
  d.replaceChildren(txt);
  if (on) d.append(el('br'), el('b', '', I18N.t('effects.pedalOnHint')));
  const r = rectP(p), q = rectP(d);
  if (voz && MESA.montada) {
    // na mesa, a dica das vozes (do mouse e do foco) abre embaixo da base do Troca de voz, no eixo dele, 4 px abaixo e
    // presa na janela: logo embaixo do rotulo ela cobria o footswitch dele e o do vizinho (revisao da r07)
    const b = rectP(p.closest('.vozes-pedal').previousElementSibling), fundo = (innerHeight - PALCO.y) / PALCO.k;
    d.style.left = clamp(b.left + b.width / 2 - q.width / 2, 8, larguraPalco() - q.width - 8) + 'px';
    d.style.top = Math.min(b.bottom + 4, fundo - q.height - 4) + 'px';
    return;
  }
  d.style.left = clamp(r.left + r.width / 2 - q.width / 2, 8, larguraPalco() - q.width - 8) + 'px';
  d.style.top = (!voz && r.top - q.height - 8 >= 8 ? r.top - q.height - 8 : r.bottom + 8) + 'px';
}
for (const bc of [$('#banco'), $('#banco-dir')]) bc.addEventListener('pointerover', e => { if (e.pointerType === 'mouse' && !celular()) dicaDoPedal(e.target.closest('.tecla, .voz-pedal')); });
for (const bc of [$('#banco'), $('#banco-dir')]) bc.addEventListener('pointerleave', () => dicaDoPedal(null));
for (const bc of [$('#banco'), $('#banco-dir')]) bc.addEventListener('focusin', e => { if (!celular()) dicaDoPedal(e.target.matches(':focus-visible') ? e.target.closest('.tecla, .voz-pedal') : null); });
for (const bc of [$('#banco'), $('#banco-dir')]) bc.addEventListener('focusout', () => dicaDoPedal(null));
for (const r of [$('#rolo-gav'), $('#gaveta'), $('#gaveta-dir')]) r.addEventListener('scroll', () => dicaDoPedal(null), { passive: true });

const roCabos = new ResizeObserver(() => medirCabos());
for (const x of document.querySelectorAll('.palco .deck, .palco .mesa, .palco .receptor, .palco .gaveta')) roCabos.observe(x);
addEventListener('resize', medirCabos);
const roBanco = new ResizeObserver(() => { caberNomes(); medirCabosPedais(); });
roBanco.observe($('#banco')); roBanco.observe($('#banco-dir'));
// as tomadas do lado direito do mixer (jacksMesa) ficam embaixo dos Sons rapidos, e o cabo do painel da direita passa
// embaixo deles: o #pads muda de altura sozinho (o aviso de vazio, a fileira nova do decimo som), e os plugues iam ficando
// na altura antiga
new ResizeObserver(() => { if (MESA.montada) { medirCabosPedais(); medirCabos(); } }).observe($('#pads'));   // (c1) e o par dos Sons rapidos
/* toque: a cara de apertado entra no instante do dedo e sai 90 ms depois de soltar no minimo. O :active do Chrome no celular so chega depois de ele decidir que o toque
   nao e rolagem, e um toque rapido nem mostrava o botao apertado; a rolagem solta na hora */
const PRESSAVEIS = '.btn, .btn-madeira, .limpar-q, .sair-busca, .transp, .tocar-grande, .tecla, .capa, .resultado .linha, .acao-res, .tocar-fila, .aviso-acao, .desliga-ef, .compacto, .cartao-b, .mini-btn, .mini-abrir, .mais, .mini-ef';
let apertados = [], apertouEm = 0, soltaT = 0;
function soltarApertados(ja) {
  clearTimeout(soltaT);
  const vai = () => { for (const x of apertados) x.classList.remove('apertado'); apertados = []; };
  if (ja) vai(); else soltaT = setTimeout(vai, Math.max(0, 90 - (performance.now() - apertouEm)));
}
document.addEventListener('pointerdown', e => {
  if (e.pointerType !== 'touch') return;
  soltarApertados(true);
  for (let x = e.target; x && x !== document.body; x = x.parentElement) if (x.matches(PRESSAVEIS)) apertados.push(x);
  for (const x of apertados) x.classList.add('apertado');
  apertouEm = performance.now();
}, { capture: true, passive: true });
document.addEventListener('pointerup', e => { if (e.pointerType === 'touch') soltarApertados(false); }, { capture: true, passive: true });
document.addEventListener('pointercancel', e => { if (e.pointerType === 'touch') soltarApertados(true); }, { capture: true, passive: true });
// pisar: o botao afunda no toque e volta em 90 ms no minimo (um toque rapido ainda mostra a pisada)
for (const bc of [$('#banco'), $('#banco-dir')]) bc.addEventListener('pointerdown', e => {
  const t = e.target.closest('.tecla'); if (!t) return;
  clearTimeout(t._pisa); t.classList.add('pisando'); t._pisouEm = performance.now();
});
// solta onde o dedo (ou o mouse) sair; a rolagem que comeca no pedal (pointercancel) solta na hora
const soltarPe = e => {
  for (const t of document.querySelectorAll('.banco .tecla.pisando')) {
    clearTimeout(t._pisa);
    t._pisa = setTimeout(() => t.classList.remove('pisando'), e.type === 'pointercancel' ? 0 : Math.max(0, 90 - (performance.now() - t._pisouEm)));
  }
};
for (const ev of ['pointerup', 'pointercancel']) document.addEventListener(ev, soltarPe);

/* marcas da chave rotativa: uma por efeito, na ordem da lista */
function montarMarcas() {
  const n = S.efeitos ? S.efeitos.length : 0;
  let h = '';
  for (let i = 0; i < n; i++) {
    const a = angDial(i, n) * Math.PI / 180, s = Math.sin(a), c = Math.cos(a);
    h += `<line data-i="${i}" x1="${(20 + 16.4 * s).toFixed(2)}" y1="${(20 - 16.4 * c).toFixed(2)}" x2="${(20 + 19.4 * s).toFixed(2)}" y2="${(20 - 19.4 * c).toFixed(2)}"/>`;
  }
  $('#marcas').innerHTML = h;
  $('#marcas-gav').innerHTML = h;
}

/* visor LCD: texto em 14 segmentos com as casas que cabem, todas com o fantasma; o que nao cabe
   anda uma casa por vez, como nos aparelhos de som. Acento e o que o segmento nao desenha viram
   a letra base ou espaco, como era */
const LCD_PASSO_MS = 330, LCD_PAUSA_MS = 1500, LCD_VAO = 3, LCD_CASA_EM = 0.815;   // largura de cada casa na DSEG
function lcdTexto(t) {
  return String(t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase()
    .replace(/[^A-Z0-9'\-\/?]+/g, ' ').replace(/\s+/g, ' ').trim();
}
function lcd14(el) {
  const l = { txt: '', n: 0, i: 0, t: 0 };
  function desenhar(reinicia) {
    clearTimeout(l.t);
    if (!el.clientWidth) return;   // escondido (o visor do outro tamanho de tela): volta pelo ResizeObserver
    const fs = parseFloat(getComputedStyle(el).fontSize) || 16;
    const n = Math.max(1, Math.floor((el.clientWidth + 1) / (fs * LCD_CASA_EM)));
    if (n !== l.n) { l.n = n; el.dataset.f = '~'.repeat(n); reinicia = true; }
    const s = l.txt.replace(/ /g, '!');   // na DSEG o ! e a casa em branco
    if (s.length <= n || reduz.matches) { el.textContent = s.length > n ? s.slice(0, n) : s.padEnd(n, '!'); return; }
    if (reinicia) l.i = 0;
    const fita = s + '!'.repeat(LCD_VAO);
    el.textContent = (fita + fita).slice(l.i, l.i + n);
    l.t = setTimeout(() => { l.i = (l.i + 1) % fita.length; desenhar(false); }, l.i === 0 ? LCD_PAUSA_MS : LCD_PASSO_MS);
  }
  new ResizeObserver(() => desenhar(false)).observe(el);
  if (document.fonts) document.fonts.ready.then(() => desenhar(true));
  reduz.addEventListener('change', () => desenhar(true));
  return { por(txt) { txt = lcdTexto(txt); if (txt === l.txt) return; l.txt = txt; desenhar(true); } };
}
const lcdEf = lcd14($('#seg-ef')), lcdEfGav = lcd14($('#seg-ef-gav'));

// o passo do ajuste do pedal de troca de voz (o pedal_voz do Estado): no canvas do pedal na mesa, nos visores de texto
// fora dela e no leitor de tela
const CHAVE_VISOR = { fale: 'effects.voicePedal.say', ouvindo: 'effects.voicePedal.listening', pronto: 'effects.voicePedal.ready' };

function efeitoAtual() {
  const id = (S.state && S.state.effect) || SEM_EFEITO;
  return { id, ef: S.efeitos ? S.efeitos.find(x => x.id === id) : null };
}

function desenharEfeito() {
  const s = S.state; if (!s) return;
  const { id, ef } = efeitoAtual();
  const com = id !== SEM_EFEITO;
  document.querySelectorAll('.tecla[data-ef]').forEach(b => {
    const on = b.dataset.ef === id;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.querySelector('.lampada').className = 'lampada' + (on ? ' acesa' : '');
  });
  // a dica aberta acompanha o ligar e o desligar (a linha de como desligar entra e sai)
  if (dicaAlvo && dicaAlvo.dataset.ef && $('#dica-pedal').dataset.on !== String(dicaAlvo.getAttribute('aria-pressed') === 'true')) dicaDoPedal(dicaAlvo);
  const sel = $('#b-efeito');
  sel.classList.toggle('com-efeito', com);
  $('#nome-ef').textContent = ef ? nomeEf(ef) : (com ? id : I18N.t('effects.none'));
  const ms = ef && ef.latencia_ms > 0 ? Math.round(ef.latencia_ms) : 0;
  $('#atraso-ef').textContent = ms ? `${ms} MS` : '';
  $('#atraso-ef-sr').textContent = ms ? ', ' + I18N.t('effects.delay', { ms }) : '';
  // no Troca de voz, o passo do ajuste (FALE ALGO, OUVINDO, PRONTO) ou a voz escolhida vai junto do nome nos visores de
  // texto: fora da mesa (celular, janela estreita) e o unico lugar dele, que na mesa o canvas do pedal mostra (revisao
  // da r07). O lcd14.por() so redesenha quando o texto muda
  const pv = id === 'pistavoz' ? s.pedal_voz : null, passo = pv && CHAVE_VISOR[pv.visor] ? I18N.t(CHAVE_VISOR[pv.visor]) : '';
  const nomeGav = $('#nome-ef').textContent + (pv ? ' ' + (passo || pv.voz) : '');
  // o passo em caixa de frase (o texto do visor vem em maiuscula, e o leitor de tela soletraria) para o leitor de tela,
  // no #passo-voz, fora do palco (no celular o palco recolhido fica inert, e regiao viva inert nao fala), que vale na
  // mesa e fora dela (revisao da r08); so quando muda, para nao repetir a cada estado
  const frase = passo.charAt(0) + passo.slice(1).toLowerCase(), vivo = $('#passo-voz');
  if (vivo.textContent !== frase) vivo.textContent = frase;
  lcdEf.por(nomeGav); lcdEfGav.por(nomeGav);
  const n = S.efeitos ? S.efeitos.length : 0, i = S.efeitos ? S.efeitos.findIndex(x => x.id === id) : -1;
  $('#ponteiro').style.setProperty('--ang', angDial(Math.max(0, i), n) + 'deg');
  $('#ponteiro-gav').style.setProperty('--ang', angDial(Math.max(0, i), n) + 'deg');
  document.querySelectorAll('#marcas line, #marcas-gav line').forEach(l => l.classList.toggle('ativa', +l.dataset.i === i));
  // visor da gaveta: o efeito escolhido e o x que desliga
  $('#visor-gav').classList.toggle('com-efeito', com);
  $('#nome-ef-gav').textContent = nomeGav;
  $('#desliga-ef').hidden = !com;
  sel.setAttribute('aria-expanded', S.gaveta || celular() ? 'true' : 'false');
  // barra de baixo (celular): a etiqueta ambar diz que a voz esta alterada e desliga com um toque
  const pe = $('#mini-ef');
  pe.hidden = !com;
  $('#mini').classList.toggle('com-efeito', com);
  if (com) {
    // na janela estreita a etiqueta da barra de baixo e o que se ve do efeito: o passo do ajuste vai nela tambem, em
    // caixa de frase (Troca de voz: Fale algo), e no nome dela para o leitor de tela
    const nomePe = $('#nome-ef').textContent + (frase ? ': ' + frase : '');
    $('#mini-ef-nome').textContent = nomePe;
    pe.setAttribute('aria-label', I18N.t('effects.onAria', { name: nomePe }));
    pe.title = I18N.t('effects.backToNatural');
  }

  // ouvir a propria voz: precisa de um fone; com a voz cortada, so ele ouve
  const semFone = !!s.active_devices && !s.active_devices.monitor;
  const bo = $('#b-ouvir');
  ligarChave(bo, !!s.voice_monitor && !semFone);
  bo.disabled = semFone;
  const dica = $('#dica-ouvir');
  if (semFone) {
    // so remonta quando muda: um estado novo no meio do toque engoliria o clique
    if (!dica.querySelector('.ir-disp')) {
      const ir = el('button', 'ir-disp', I18N.t('effects.chooseHeadphones')); ir.type = 'button';
      dica.replaceChildren(document.createTextNode(I18N.t('effects.noHeadphones') + ' '), ir);
    }
  } else if (s.voice_monitor && s.mic_mute) {
    dica.replaceChildren(el('b', null, I18N.t('effects.mutedListening') + ' '), document.createTextNode(I18N.t('effects.nobodyHears')));
  } else dica.textContent = I18N.t('effects.listenHint');
  dica.classList.toggle('so-dica', !semFone && !(s.voice_monitor && s.mic_mute));   // no celular, so a que informa aparece
  const atraso = ef && ef.latencia_ms > 0 ? ', ' + I18N.t('effects.delay', { ms: Math.round(ef.latencia_ms) }) : '';
  sel.title = I18N.t('effects.selectorTitle', { name: $('#nome-ef').textContent, delay: atraso });
}

async function escolherEfeito(id) {
  if (!S.state) return false;
  const antes = S.state.effect;
  if (antes === id) return false;
  S.state.effect = id; desenharEfeito();
  try { await api('POST', '/api/settings', { effect: id }); }
  catch (e) {
    if (S.state.effect === id) { S.state.effect = antes; desenharEfeito(); }
    avisar(e.message, true);
  }
  return true;
}

function abrirGaveta(on) {
  S.gaveta = !!on;
  document.body.classList.toggle('com-gaveta', S.gaveta);
  $('#b-efeito').setAttribute('aria-expanded', S.gaveta || celular() ? 'true' : 'false');
  if (S.gaveta && !celular()) {
    fecharMenu(false);
    // a tecla do efeito em uso aparece sem precisar rolar
    const ativa = document.querySelector('#banco .tecla[aria-pressed="true"]'), rolo = $('#rolo-gav');
    if (ativa) {
      const r = rectP(ativa), q = rectP(rolo);
      if (r.bottom > q.bottom - 30 || r.top < q.top) rolo.scrollTop += r.top - q.top - (q.height - r.height) / 2;
    }
  }
  sombrear($('#rolo-gav'));
}
function desligarEfeito() { escolherEfeito(SEM_EFEITO); }   // sem aviso: o visor ja mostra Sem efeito
// tocar de novo no efeito ligado desliga, como no Voicemod
const pisarPedal = e => {
  const b = e.target.closest('.tecla[data-ef]'); if (!b) return;
  const ligado = !!S.state && efeitoAtual().id === b.dataset.ef;
  if (b.dataset.ef !== SEM_EFEITO && ligado) desligarEfeito();
  else escolherEfeito(b.dataset.ef);
};
function bindVoiceEffects() {
  $('#b-ouvir').addEventListener('click', () => {
    const v = !(S.state && S.state.voice_monitor);
    ligarChave($('#b-ouvir'), v); ajustar('voice_monitor', v);
    // sem volume proprio: o teste toca em 100%, o mesmo nivel que vai para o jogo
    if (v && S.state && S.state.voice_mon_vol !== 1) ajustar('voice_mon_vol', 1);
    desenharEfeito();
  });
  $('#gaveta').addEventListener('click', pisarPedal);
  $('#gaveta-dir').addEventListener('click', pisarPedal);
  $('#desliga-ef').addEventListener('click', desligarEfeito);
  $('#b-efeito').addEventListener('click', () => {
    // no celular a gaveta ja esta aberta logo abaixo: o seletor so leva ate ela
    if (celular()) { $('#gaveta').scrollIntoView({ block: 'start', behavior: reduz.matches ? 'auto' : 'smooth' }); return; }
    abrirGaveta(!S.gaveta);
  });
  $('#b-fechar-gav').addEventListener('click', () => { abrirGaveta(false); $('#b-efeito').focus(); });
  $('#mini-ef').addEventListener('click', desligarEfeito);
}
/* VOICE-EFFECTS-FIM */
