/* DJ-DESK-JS-INICIO */
'use strict';
/* ---------- mesa de DJ (pedido dele, 05/11: "abrir o aplicativo e ter a impressao de estar olhando a mesa de um DJ em
   um show ao vivo", o mock B), so no computador largo, onde a pagina unica ja valia. Dois toca-discos que se revezam
   como num set: o deck no ar e o de sempre (o mesmo HTML e o mesmo JS do toca-discos), e o outro, o da deixa, mostra
   a proxima da fila, mais apagado. Quando a passagem (ou o Proxima) poe no ar o disco da deixa, os papeis trocam de
   lado e o disco fica no deck dele: o lado do deck no ar e o data-lado do body, e a grade troca os dois de lugar. O
   que saiu segue no deck de la enquanto ainda soa na passagem (SAINDO), e so entao a proxima da fila entra nele.
   Outro disco qualquer (a prateleira, o Anterior) troca so o do deck no ar. No meio, a tela grande com o visor de DJ
   (o mesmo desenho, so maior), o mixer com os volumes em pe, as chaves do set e o crossfader que anda sozinho pela
   passagem do visor; do lado, os Sons rapidos como pads; embaixo, a pedaleira em dois paineis. As leituras sao so
   as que o motor da (o tempo, a passagem medida, o andamento medido): o que ele nao mediu fica em branco ---------- */
const mesaDj = () => paginaUnica();
function montarMesa() {
  const on = mesaDj();
  if (MESA.montada === on || (!on && MESA.montada === null)) { MESA.montada = on; return; }
  MESA.montada = on;
  document.body.classList.toggle('mesa-dj', on);
  ajustarPalco();
  for (const e of document.querySelectorAll('#deck-deixa, #tv, #pads, #gaveta-dir, .mix-set, .xfader, .auto-luz, .deck-letra, .deck .faixa > .deck-cab, .prat-seta'))
    e.hidden = !on;
  // o visor de DJ muda de lugar: a tela grande do meio na mesa, a tela do titulo fora dela
  const v = $('#visor-dj');
  if (on) $('#tv-tela').append(v); else $('.deck .canal-faixa').after(v);
  V.img = null; V.sujo = true;
  if (on) abrirMaleta(true);
  rodinhas(on); if (!scriptsMissing().length) vigiarGavetaDaBusca();
  montarGaveta(); S.filaSig = null; desenharFila(); desenharRapidos(); desenharMesa(); setasPrateleira();
  $('#cabo-calha')._geo = ''; requestAnimationFrame(medirCabos);
  medirBusca();
}
/* onde a busca cai: debaixo do campo, da largura dele (ou mais) */
function medirBusca() {
  if (!MESA.montada) return;
  const r = rectP($('#form-busca')), b = document.body.style;
  b.setProperty('--busca-x', Math.round(r.left) + 'px');
  b.setProperty('--busca-y', Math.round(r.bottom + 10) + 'px');
  b.setProperty('--busca-w', Math.round(r.width) + 'px');
}
addEventListener('resize', medirBusca);
/* a mesma entrada da fila e o disco do prato: pelo id da prateleira ou pelo do video (o stream usa o do video) */
function mesmoDisco(x, tr) {
  return !!x && !!tr && ((!!x.id && x.id === tr.id) || (!!x.youtube_id && (x.youtube_id === tr.youtube_id || x.youtube_id === tr.id)));
}
/* o andamento medido do disco: o que veio com ele (a fila e o prato trazem), ou o guardado de quando estava na fila */
function bpmDe(x) {
  if (!x) return null;
  return x.bpm || MESA.bpm.get(x.youtube_id) || MESA.bpm.get(x.id) || null;
}
// com a virgula (ou o ponto) da lingua; sem andamento, os tracos no lugar dos algarismos
const BPM_VAZIO = I18N.num(10, 1).replace(/\d/g, '-');
$('#bpm-ar').textContent = $('#bpm-d').textContent = BPM_VAZIO;
const fmtBpm = b => b ? I18N.num(b, 1) : BPM_VAZIO;
const fmtPitch = v => Math.abs(v) < .0005 ? '' : `${v > 0 ? '+' : '-'}${I18N.num(Math.abs(v * 100), 1)}%`;
/* a troca de lado sem o braco e o disco deslizando de um jeito para o outro (o deck de cada lado e outro elemento) */
function semAnimar() {
  document.body.classList.add('mesa-troca');
  clearTimeout(MESA.trocaT);
  MESA.trocaT = setTimeout(() => document.body.classList.remove('mesa-troca'), 120);
}
function desenharMesa() {
  if (!MESA.montada || !S.state) return;
  const s = S.state, tr = s.track, fila = temFila() ? s.queue : [];
  for (const x of [...fila, tr]) if (x && x.bpm) { if (x.youtube_id) MESA.bpm.set(x.youtube_id, x.bpm); if (x.id) MESA.bpm.set(x.id, x.bpm); }
  const id = tr ? tr.id : null;
  if (id !== MESA.idAr) {
    if (tr && mesmoDisco(MESA.deixa, tr)) {
      MESA.lado = MESA.lado === 'a' ? 'b' : 'a';
      MESA.antes = MESA.trAr;
      semAnimar();
    } else MESA.antes = null;
    MESA.idAr = id;
  }
  MESA.trAr = tr;
  // a deixa: a primeira da fila que nao e o disco do prato (na virada o prato troca um instante antes de a fila andar)
  MESA.deixa = fila.find(x => !mesmoDisco(x, tr)) || null;
  document.body.dataset.lado = MESA.lado;
  // as chaves do set no mixer, no estado das do toca-discos (que ficam escondidas na mesa)
  const transp = 'shuffle' in s, auto = temAuto();
  $('#m-aleatorio').hidden = !transp; ligarChave($('#m-aleatorio'), transp && s.shuffle);
  ligarChave($('#m-repetir'), !!s.loop);
  $('#m-parecidas').hidden = !auto; ligarChave($('#m-parecidas'), auto && s.auto);
  // as chaves do set sairam da mesa (ordem dele, 06/11): o tocar parecidas fica sempre ligado
  if (auto && !s.auto && Date.now() - (ultimoEnvio.auto || 0) > 2000) ajustar('auto', true);
  desenharDeixa();
  tempoMesa();
  setasPrateleira();
}
/* o disco que saiu ainda soando na passagem que trouxe o do prato: ate o fim do cruzamento dele (o sai, em s de saida
   desde o t0), com a posicao dele (t) e o quanto da passagem ja foi (u, no relogio do visor) */
function saindoAgora() {
  const a = MESA.antes, s = S.state;
  if (!a || !s || !s.track) return null;
  const p = vdjPassagens().feita;
  if (!p || p.de !== a.id) return null;
  const u = vdjFiInv(p, S.pos - p.ini), e = (p.v - p.t0) / p.va;
  if (u > e + p.sai) return null;
  return { tr: a, p, u, e, t: p.t0 + p.va * Math.max(0, u) };
}
function bracoEm(b, ang) {
  mudar(b, '--ang', ang.toFixed(1) + 'deg');
  const f = desenhoDoBraco(ang);
  if (b.dataset.desenho !== f) b.dataset.desenho = f;
}
function desenharDeixa() {
  const d = $('#deck-deixa'), x = MESA.deixa, sai = saindoAgora(), mostra = sai ? sai.tr : x;
  d.classList.toggle('saindo', !!sai);
  d.classList.toggle('vazia', !mostra);
  const chave = sai ? 'sai:' + sai.tr.id : x ? `x:${x.qid}|${x.thumb || ''}|${x.title}` : '';
  if (d._chave !== chave) {
    d._chave = chave;
    $('#prato-d').classList.toggle('com-disco', !!mostra);
    $('#rotulo-d').replaceChildren(mostra ? arte({ thumb: mostra.thumb, id: mostra.id || mostra.youtube_id || mostra.qid, title: mostra.title }, true) : '');
    $('#tit-d').textContent = mostra ? mostra.title : I18N.t('cue.empty');
    $('#tit-d').title = mostra ? mostra.title : '';
    $('#canal-d').textContent = mostra ? (mostra.channel || I18N.t('deck.noChannel')).replace(/ - Topic$/, '')
      : I18N.t('cue.emptyHint');
    $('#dur-d').textContent = fmt(mostra && mostra.duration);
    const sk = $('#seek-d');
    sk.max = (mostra && mostra.duration) || 1;
    $('#tocar-d').setAttribute('aria-label', x ? I18N.t('queue.playNowItem', { title: x.title }) : I18N.t('cue.playNow'));
    $('#prox-d').setAttribute('aria-label', x ? I18N.t('queue.removeItem', { title: x.title }) : I18N.t('cue.remove'));
  }
  $('#tocar-d').disabled = !x || !!sai;
  $('#prox-d').disabled = !x || !!sai;
  mudar($('#luz-d-t'), 'textContent', sai ? I18N.t('cue.leaving') : x ? I18N.t('cue.cued') : I18N.t('deck.empty'));
  mudar($('#luz-d'), 'class', 'lampada' + (sai ? ' acesa piscando' : x ? ' acesa' : ''));
}
/* o que anda com o tempo: o braco e o tempo do disco que sai, os andamentos, o crossfader, a luz da transicao e a
   tela grande (o tick chega 15 vezes por segundo, e o mudar so escreve o que mudou) */
function tempoMesa() {
  if (!MESA.montada || !S.state) return;
  const s = S.state, tr = s.track, fila = temFila() ? s.queue : [], pos = S.pos;
  const dur = s.duration || (tr && tr.duration) || 0, sai = saindoAgora(), d = $('#deck-deixa');
  if (!!sai !== d.classList.contains('saindo')) desenharDeixa();
  const { feita, vem } = tr ? vdjPassagens() : { feita: null, vem: null };
  // o deck da deixa: parado, com o braco no descanso; saindo, girando com o braco no sulco do disco que sai
  d.classList.toggle('gira', !!sai && s.status === 'playing');
  const sk = $('#seek-d');
  if (sai) {
    const dd = sai.tr.duration || 0, f = dd ? clamp(sai.t / dd, 0, 1) : 0;
    bracoEm($('#braco-d'), anguloPara(f));
    mudar($('#pos-d'), 'textContent', fmt(sai.t));
    sk.value = sai.t; mudar(sk, '--f', f.toFixed(4)); mudar(sk, '--p', (f * 100).toFixed(1) + '%');
  } else {
    bracoEm($('#braco-d'), 0);
    mudar($('#pos-d'), 'textContent', '0:00');
    sk.value = 0; mudar(sk, '--f', '0'); mudar(sk, '--p', '0%');
  }
  // a luz do deck no ar: acesa tocando, piscando carregando, apagada pausado
  const st = s.status;
  mudar($('#luz-ar'), 'class', 'lampada' + (!tr ? '' : st === 'playing' ? ' acesa' : st === 'buffering' ? ' acesa piscando' : ''));
  mudar($('#luz-ar-t'), 'textContent', !tr ? I18N.t('deck.empty') : st === 'paused' ? I18N.t('deck.status.paused') : st === 'ended' ? I18N.t('deck.lampEnded') : I18N.t('deck.onAir'));
  // os andamentos: o medido na passagem (o fim do que sai e o comeco do que entra) vale mais que o de antes, e o
  // quanto a passagem estica cada um (o do no ar volta a 1 devagar depois da virada)
  let bAr = bpmDe(tr), pAr = 0;
  if (vem && vem.grade_de) bAr = vem.grade_de.bpm;
  else if (feita && feita.grade_para) bAr = feita.grade_para.bpm;
  if (feita && feita.no_tempo) pAr = vdjVel(feita, vdjFiInv(feita, pos - feita.ini)) - 1;
  let bDx = bpmDe(MESA.deixa), pDx = 0;
  if (sai) { bDx = sai.p.grade_de ? sai.p.grade_de.bpm : bpmDe(sai.tr); pDx = sai.p.va - 1; }
  else if (vem && MESA.deixa && mesmoDisco(MESA.deixa, { id: vem.para, youtube_id: vem.para })) {
    if (vem.grade_para) bDx = vem.grade_para.bpm;
    if (vem.no_tempo) pDx = vem.vb - 1;
  }
  mudar($('#bpm-ar'), 'textContent', fmtBpm(bAr)); mudar($('#pitch-ar'), 'textContent', fmtPitch(pAr));
  mudar($('#bpm-d'), 'textContent', fmtBpm(bDx)); mudar($('#pitch-d'), 'textContent', fmtPitch(pDx));
  // o crossfader: todo no lado do deck no ar; na passagem, pelos volumes do plano (o que sai cai no cosseno e o que
  // entra sobe no seno), a fracao de potencia do que entra
  let xf = MESA.lado === 'a' ? 0 : 1;
  if (sai) {
    const p = sai.p, r = sai.u - sai.e;
    const seg = p.segura || 0;   // o que sai segue cheio ate a troca (a passagem de DJ do motor)
    const nv = p.nivel == null ? 1 : p.nivel;
    const gIn = nv * Math.sin(clamp(r / Math.max(1e-3, p.entra), 0, 1) * Math.PI / 2) + (nv < 1 ? (1 - nv) * clamp((r - p.entra) / Math.max(1e-3, (p.cheia || p.entra) - p.entra), 0, 1) : 0);
    const gOut = Math.cos(clamp((r - seg) / Math.max(1e-3, p.sai - seg), 0, 1) * Math.PI / 2);
    const f = Math.atan2(gIn, gOut) / (Math.PI / 2);
    xf = MESA.lado === 'a' ? 1 - f : f;
  }
  mudar($('#xf-pino'), '--x', xf.toFixed(3));
  $('#xfader').setAttribute('aria-label', xf < .02 ? I18N.t('mixer.crossfaderAllA') : xf > .98 ? I18N.t('mixer.crossfaderAllB')
    : I18N.t('mixer.crossfaderMix', { a: Math.round((1 - xf) * 100), b: Math.round(xf * 100) }));
  // a luz da transicao automatica: acesa com a proxima na fila (ela entra sozinha), piscando na passagem
  const armada = !!tr && fila.some(x => !mesmoDisco(x, tr)) && !s.loop;
  mudar($('#lamp-auto'), 'class', 'lampada' + (sai ? ' acesa piscando' : armada ? ' acesa' : ''));
  const falta = vem ? Math.max(0, vem.t0 - pos) : 0;
  mudar($('#auto-luz'), 'title', sai ? I18N.t('mixer.auto.happening')
    : vem ? I18N.t(vem.no_tempo ? 'mixer.auto.inTime' : 'mixer.auto.inVolume', { time: fmt(falta) })
    : armada ? I18N.t('mixer.auto.armed')
    : tr && s.loop ? I18N.t('mixer.auto.repeat') : I18N.t('mixer.auto.none'));
  // a tela grande: no alto o que ela mostra; embaixo os tempos dos dois lados, a passagem, os andamentos e o Automatico
  const p = sai ? sai.p : vem;
  mudar($('#tv-titulo'), 'textContent', p ? I18N.t(p.no_tempo ? 'tv.inTime' : 'tv.inVolume')
    : s.error && st !== 'playing' ? I18N.t('deck.status.error') : (SITUACAO[st] || I18N.t('tv.title')));
  mudar($('#tv-luz'), 'class', 'lampada' + (tr && st === 'playing' ? ' alerta' : ''));
  const ar = tr ? fmt(pos) : '-:--', dx = sai ? fmt(sai.t) : MESA.deixa ? '0:00' : '-:--';
  const [ta, tb] = MESA.lado === 'a' ? [ar, dx] : [dx, ar];
  const [ca, cb] = MESA.lado === 'a' ? ['ar', 'dx'] : ['dx', 'ar'];
  const passagem = vem ? I18N.t('tv.transitionIn', { time: fmt(falta) }) : sai ? I18N.t('tv.crossing')
    : armada ? I18N.t('tv.endIn', { time: fmt(Math.max(0, dur - pos)) })
    : tr && s.loop ? I18N.t('tv.repeating') : tr ? I18N.t('tv.noNext') : '';
  const [ba, bb] = MESA.lado === 'a' ? [bAr, bDx] : [bDx, bAr];
  const bpm = ba || bb ? `<span class="tl bpm">${fmtBpm(ba)}/${fmtBpm(bb)} BPM</span>` : '';
  const h = `<span class="tl ${ca}"><b>A</b>${ta}</span><span class="tl ${cb}"><b>B</b>${tb}</span><span class="tl-vao"></span>` +
            (passagem ? `<span class="tl">${passagem}</span>` : '') + bpm;
  const lt = $('#tv-leituras');
  if (lt._h !== h) { lt._h = h; lt.innerHTML = h; }
}
/* os Sons rapidos como pads de controladora: os de verdade, na ordem da prateleira, cada um numa cor; as casas que
   sobram ficam apagadas (o pad sem som de uma controladora de verdade), tres por fileira */
const PAD_CORES = ['#F2D21E', '#38C83A', '#2FD3E0', '#E02C34', '#9240E2', '#2F6BE0', '#DE52D6', '#FF8A1C', '#9ACD32'];
function desenharPads(curtos) {
  if (!MESA.montada) return;
  const g = $('#pads-grade'), chave = curtos.map(it => it.id + '|' + it.title).join('/');
  if (g._chave !== chave) {
    g._chave = chave;
    const pads = curtos.map((it, i) => {
      const b = el('button', 'pad'); b.type = 'button'; b.dataset.id = it.id;
      b.style.setProperty('--pad', PAD_CORES[i % PAD_CORES.length]);
      b.setAttribute('aria-label', I18N.t('pads.playOver', { title: it.title }));
      b.title = `${it.title} (${fmt(Math.min(it.duration || 0, it.rapido ? RAPIDO_MAX_S : CURTO_S))})`;
      b.append(el('span', 'pad-face'), el('span', 'pad-nome', it.title));
      return b;
    });
    while (pads.length < Math.max(9, Math.ceil(curtos.length / 3) * 3)) {
      const v = el('span', 'pad sem-som'); v.setAttribute('aria-hidden', 'true'); v.append(el('span', 'pad-face'));
      pads.push(v);
    }
    g.replaceChildren(...pads);
    $('#pads').classList.toggle('sem-sons', !curtos.length);
    requestAnimationFrame(medirCabos);   // a caixa dos pads mudou de altura: os cabos saem do pe dela
  }
  const tocando = new Set(((S.state && S.state.por_cima) || []).map(x => x.id));
  g.querySelectorAll('.pad[data-id]').forEach(b => b.classList.toggle('tocando', tocando.has(b.dataset.id)));
}
/* na mesa a pedaleira e dois paineis, um de cada lado do mixer: os grupos ficam na esquerda ate ela ter metade dos
   pedais, e o resto vai para a direita (a corrente segue: a saida da esquerda vai para o mixer, e a entrada da
   direita vem dele) */
function repartirPedais() {
  if (!MESA.montada) return;
  const grupos = [...$('#banco').querySelectorAll(':scope > .grupo-ef')];
  const total = grupos.reduce((n, g) => n + g.querySelectorAll('.tecla').length, 0);
  let n = 0;
  for (const g of grupos) {
    if (n >= total / 2) $('#banco-dir').append(g);
    n += g.querySelectorAll('.tecla').length;
  }
}
/* as setas da prateleira ficam acesas nas pontas (pedido do dono): na ultima pagina a da direita volta ao comeco e
   na primeira a da esquerda vai ao fim; apagam so quando os discos cabem sem rolar */
function setasPrateleira() {
  if (!MESA.montada) return;
  const ul = $('#estante'), sem = ul.scrollWidth - ul.clientWidth <= 2;
  $('#prat-esq').disabled = $('#prat-dir').disabled = sem;
}

/* mostradores VU: escala em dBFS, -50 a 0 */
const ANG = 50;
function dbParaAng(db) { const t = clamp((db + 50) / 50, 0, 1); return -ANG + 2 * ANG * Math.pow(t, 1.6); }
function montarMostradores() {
  // o svg vazio so segura a altura do mostrador: a face e a agulha sao os canvas de pixel (desenharVUs)
  const face = `<svg viewBox="0 0 120 78" aria-hidden="true"></svg><canvas class="vu-face" aria-hidden="true"></canvas><span class="agulha-m" aria-hidden="true"><canvas class="vu-agulha"></canvas></span>`;
  // moldura e nome numa camada propria, acima do escurecimento da voz cortada
  const tampa = `<svg class="tampa-m" viewBox="0 0 120 78" aria-hidden="true"><path class="moldura" d="M-8 54.5 L128 54.5 L128 104 L-8 104 Z"/></svg><span class="nome-m" aria-hidden="true"></span>`;
  // o nome impresso em cada mostrador, na lingua; o data-nome e o que o mixer da mesa desenha (MIX-JS)
  const NOMES = { mic: I18N.t('mixer.meter.voice'), track: I18N.t('mixer.meter.record'), out: I18N.t('mixer.meter.game') };
  document.querySelectorAll('.mostrador').forEach(m => {
    m.dataset.nome = NOMES[m.dataset.k];
    m.insertAdjacentHTML('afterbegin', face + tampa);
    m.querySelector('.nome-m').textContent = m.dataset.nome;
  });
}
/* os VUs em pixel: a face (arco, marcas, numeros e a zona do 0) e a agulha
   em celulas de 1 px, cada uma num canvas do tamanho em celulas que o CSS mostra sem suavizar, nas
   medidas do viewBox 120 x 78 na largura do mostrador. A face so se redesenha quando a
   medida muda; os numeros em algarismos de pixel proprios, 6 de altura com a haste de 2 (os grossos do
   mock p1: a Silkscreen fina ficava leve e, em negrito, fechava o 4). A agulha anda a cada leitura
   do servidor (15 por segundo, o passo dos objetos do hotel), sem laco de quadro: sobe na hora e cai
   devagar, com a constante de 300 ms, e um temporizador termina a queda quando as leituras param */
const VU_COR = '#120A04', VU_ZONA = '#8A0202', VU_AGULHA = '#1D120C';
const VU_DIGITO = {
  '-': ['....', '....', '####', '####', '....', '....'],
  '0': ['.###.', '##.##', '##.##', '##.##', '##.##', '.###.'],
  '1': ['.##', '###', '.##', '.##', '.##', '.##'],
  '2': ['.###.', '##.##', '...##', '..##.', '.##..', '#####'],
  '4': ['...##', '..###', '.####', '##.##', '#####', '...##'],
  '5': ['#####', '##...', '####.', '...##', '##.##', '.###.'],
};
const vuMedida = m => {
  const w = Math.round(m.clientWidth - 8), s = w / 120;
  return { w, h: Math.round(78 * s), s, px: 60 * s, py: 96 * s, r: 66 * s };
};
function celulasSegmento(g, a, r0, r1, meia) {   // as celulas a ate meia celula do segmento, no angulo a (graus)
  const t = a * Math.PI / 180, dx = Math.sin(t), dy = -Math.cos(t), out = [];
  const xs = [g.px + dx * r0, g.px + dx * r1], ys = [g.py + dy * r0, g.py + dy * r1];
  for (let y = Math.floor(Math.min(...ys) - 1); y <= Math.ceil(Math.max(...ys) + 1); y++)
    for (let x = Math.floor(Math.min(...xs) - 1); x <= Math.ceil(Math.max(...xs) + 1); x++) {
      const cx = x + .5 - g.px, cy = y + .5 - g.py, ao = cx * dx + cy * dy;
      if (ao >= r0 && ao <= r1 && Math.abs(cx * dy - cy * dx) <= meia) out.push([x, y]);
    }
  return out;
}
function desenharFaceVU(m) {
  const c = m.querySelector('.vu-face'), g = vuMedida(m);
  if (!c || g.w < 20) return;
  c.width = g.w; c.height = g.h; c.style.width = g.w + 'px'; c.style.height = g.h + 'px';
  const x = c.getContext('2d');
  const pinta = (cels, cor) => { x.fillStyle = cor; for (const [cx, cy] of cels) x.fillRect(cx, cy, 1, 1); };
  const arco = (a1, a2, d1, d2) => {
    const cels = [];
    for (let y = 0; y < g.h; y++) for (let xx = 0; xx < g.w; xx++) {
      const cx = xx + .5 - g.px, cy = y + .5 - g.py, d = Math.hypot(cx, cy), a = Math.atan2(cx, -cy) * 180 / Math.PI;
      if (a >= a1 && a <= a2 && d >= d1 && d < d2) cels.push([xx, y]);
    }
    return cels;
  };
  pinta(arco(-ANG, ANG, g.r - 1.5, g.r + .5), VU_COR);                          // o arco de 2 celulas
  pinta(arco(dbParaAng(-3), ANG, g.r + .5, g.r + 2.5), VU_ZONA);                // a zona do 0, por fora
  const marcas = [[-40, '-40'], [-20, '-20'], [-10, '-10'], [-5, '-5'], [0, '0']];
  for (let db = -48; db < 0; db += 2)
    if (!marcas.some(mm => mm[0] === db)) pinta(celulasSegmento(g, dbParaAng(db), g.r - 3.5 * g.s, g.r, .5), VU_COR);
  for (const [db, t] of marcas) {
    const a = dbParaAng(db), ang = a * Math.PI / 180;
    pinta(celulasSegmento(g, a, g.r - 7 * g.s, g.r, .9), db > -4 ? VU_ZONA : VU_COR);   // as grossas, de 2 celulas
    // o numero sai do arco ate os quatro cantos dele ficarem 2 celulas longe (com o raio fixo, o -40 batia no
    // arco, que ali ja sobe), e fica dentro da janela
    const tw = [...t].reduce((s, ch) => s + VU_DIGITO[ch][0].length + 1, -1), th = VU_DIGITO['0'].length;
    let nx, ny;
    for (let rr = g.r + 5; rr < g.r + 30; rr += .5) {
      nx = Math.min(Math.max(Math.round(g.px + rr * Math.sin(ang) - tw / 2), 1), g.w - tw - 1);
      ny = Math.round(g.py - rr * Math.cos(ang) - th / 2);
      const cantos = [[nx, ny], [nx + tw, ny], [nx, ny + th], [nx + tw, ny + th]];
      if (cantos.every(([cx, cy]) => Math.hypot(cx - g.px, cy - g.py) >= g.r + 2.5)) break;
    }
    x.fillStyle = db > -4 ? VU_ZONA : VU_COR;
    for (const ch of t) {
      VU_DIGITO[ch].forEach((linha, y) => [...linha].forEach((c, xx) => { if (c === '#') x.fillRect(nx + xx, ny + y, 1, 1); }));
      nx += VU_DIGITO[ch][0].length + 1;
    }
  }
  m.vuG = g; m.vuAng = null;
}
const angPixel = { mic: -ANG, track: -ANG, out: -ANG };
let caindo = 0;
function agulhasPixel() {
  clearTimeout(caindo);
  let mexe = false;
  for (const k of ['mic', 'track', 'out']) {
    const m = document.querySelector(`.mostrador[data-k="${k}"]`), c = m && m.querySelector('.vu-agulha');
    if (!c || !m.vuG) continue;
    const r = S.online ? (S.levels[k] || 0) : 0;
    const alvo = dbParaAng(20 * Math.log10(Math.max(r, 1e-6)));
    let a = angPixel[k];
    a = alvo > a ? alvo : a + (alvo - a) * .2;   // sobe na hora, cai com a constante de 300 ms por leitura de 66 ms
    if (Math.abs(a - alvo) < .3) a = alvo; else mexe = true;
    angPixel[k] = a;
    const g = m.vuG, q = Math.round(a * 2) / 2;
    if (q === m.vuAng) continue;
    m.vuAng = q;
    if (c.width !== g.w || c.height !== g.h) { c.width = g.w; c.height = g.h; c.style.width = g.w + 'px'; c.style.height = g.h + 'px'; }
    const x = c.getContext('2d');
    x.clearRect(0, 0, g.w, g.h); x.fillStyle = VU_AGULHA;
    // 2 celulas de grossura, como as marcas grossas (a de 1 ficava fina demais)
    for (const [cx, cy] of celulasSegmento(g, q, 0, g.r + 3 * g.s, .9)) if (cy >= 0 && cy < g.h) x.fillRect(cx, cy, 1, 1);
  }
  if (mexe) caindo = setTimeout(agulhasPixel, 66);
}
function desenharVUs() {
  document.querySelectorAll('.mostrador').forEach(desenharFaceVU);
  agulhasPixel();
}
/* com a aba muito tempo escondida, o Chrome pode jogar fora o desenho dos canvas e devolver todos em branco
   (25/10: ao voltar depois de um tempo, os VUs apareciam sem a agulha): a face do VU e os
   fios so se pintavam quando a medida mudava, e a agulha so quando andava, entao o VU parado voltava sem escala e
   sem agulha e o do disco so com a agulha. Com o canvas devolvido (contextrestored, que nao sobe: pega na descida)
   ou a pagina de volta na tela, todos se pintam de novo.
   (#119) Cada desenho que guarda uma chave e so pinta quando ela muda ficava em branco. Os daqui zeram a chave abaixo;
   os dos modulos de pixel art (os toca-discos, o mixer, o monitor, os Sons rapidos, os titulos das placas e o aviso de
   vazio do A seguir) ouvem o repinta-canvas ao lado das chaves deles e zeram a chave, ou desenham de novo, ali mesmo.
   Um desenho novo com chave propria ouve o repinta-canvas tambem.
   A mesa inteira (mesa = true) custa uns 150 a 300 ms de tela parada: na volta da aba ela so vem quando os canvas
   voltaram mesmo em branco (provaCanvas, abaixo) */
let repintando = 0, repintaMesa = false;
function repintarCanvas(mesa = true) {
  repintaMesa = repintaMesa || mesa;   // dois pedidos no mesmo quadro: vale o que pede a mesa inteira
  cancelAnimationFrame(repintando);
  repintando = requestAnimationFrame(() => {
    for (const cv of document.querySelectorAll('#cabo-calha, .cabos-pedais, canvas.ped-px, canvas.gav-px')) cv._geo = '';
    // o footswitch em canvas e o icone do Troca de voz (PEDAL-JS) guardam a chave no _f: zerada, o desenha() do pedal
    // (com o _geo do canvas dele zerado acima) os pinta de novo
    for (const cv of document.querySelectorAll('canvas.pe-px, canvas.ico-fino')) cv._f = '';
    pedacosFios(true);
    medirCabos(); medirCabosPedais(); desenharVUs();
    if (repintaMesa) {
      // o visor de DJ: o contextrestored dele so chega quando e o canvas dele que volta (a aba de volta nao tem nenhum)
      V.sujo = true;
      document.dispatchEvent(new Event('repinta-canvas'));
    }
    repintaMesa = false;
  });
}
/* (#119) a prova de que a aba voltou com os canvas em branco: o pixel do meio do mixer e dos toca-discos, lido ao
   esconder e de novo ao voltar (pintado entao e vazio agora, o navegador jogou o desenho fora). Sem prova (fora da
   mesa, ou nada pintado ainda), a mesa inteira, como no contextrestored. O pixel passa por um canvas de 1 x 1: o
   getImageData no canvas da mesa a cada troca de aba faria o Chrome reclamar e tirar o canvas da placa de video */
let provaCanvas = null;
const sonda = Object.assign(document.createElement('canvas'), { width: 1, height: 1 })
  .getContext('2d', { willReadFrequently: true });
function alfaNoMeio(cv) {
  if (!cv.width || !cv.height) return 0;
  sonda.clearRect(0, 0, 1, 1);
  sonda.drawImage(cv, cv.width >> 1, cv.height >> 1, 1, 1, 0, 0, 1, 1);
  return sonda.getImageData(0, 0, 1, 1).data[3];
}
document.addEventListener('contextrestored', () => repintarCanvas(), true);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    provaCanvas = [...document.querySelectorAll('canvas.mx-px, canvas.dk-px')].filter(alfaNoMeio);
    return;
  }
  const emBranco = !provaCanvas || !provaCanvas.length || provaCanvas.some(cv => !alfaNoMeio(cv));
  provaCanvas = null;
  repintarCanvas(emBranco);
});
addEventListener('pageshow', e => { if (e.persisted) repintarCanvas(); });
/* DJ-DESK-JS-FIM */
