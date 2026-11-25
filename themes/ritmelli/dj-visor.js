/* DJ-VISOR-JS-INICIO */
'use strict';
/* ---------- visor de DJ (computador): a onda do disco no prato correndo com o ponto de toque fixo no meio, a grade de
   batidas onde o motor mediu e, na passagem, a proxima entrando na metade de baixo em ciano, no mesmo tempo (os formatos
   no Engine.onda e no Engine.snapshot do servidor). Uma celula de 2 px por coluna da onda (40 ms): o visor mostra uns 7 s.
   Cada coluna e (grave, medio, agudo), empilhados do meio para fora como no Rekordbox (o agudo claro por dentro, o grave
   escuro por fora), e o que ja tocou sai mais apagado. Na passagem a tela se divide no trecho em que as duas soam: em
   cima o que sai, embaixo a que entra, cada uma no volume e no grave do plano (a troca de grave aparece), e com as
   batidas das duas na mesma coluna quando a passagem e no tempo; fora desse trecho a onda volta a ser uma so. Quando o
   que saiu some da tela, a que entrou passa do ciano para o ambar: virou o disco do prato.
   Desenho por quadro so com o disco tocando e o visor na tela (no celular, nem o temporizador roda); parado, so quando
   algo muda. A posicao anda pelo relogio da pagina entre um tick e outro e se corrige devagar em cada um, para a onda
   correr lisa. Com movimento reduzido a onda fica parada e o ponto de toque anda por ela, virando a pagina na beira ---------- */
const VDJ_CEL = 2, VDJ_PASSO = 1 / 30;   // 30 colunas por segundo, o VISOR_PASSO do engine (07/11)
const VDJ_AMP = Float32Array.from({ length: 256 }, (_, b) => b ? Math.pow(10, (b / 255 * 60 - 60) / 20) : 0);   // o byte e dB de -60 a 0
const vdjRgb = (r, g, b) => (255 << 24 | b << 16 | g << 8 | r) >>> 0;
const vdjMistura = (a, b, f) => a.map((x, i) => Math.round(x + (b[i] - x) * f));
const VDJ_FUNDO = [11, 8, 7];
// cada disco em tres tons (grave, medio, agudo): o do prato no ambar do tema, o que entra em ciano
const VDJ_AMBAR = [[168, 84, 22], [243, 167, 60], [255, 228, 170]], VDJ_CIANO = [[24, 104, 134], [58, 194, 222], [204, 246, 255]];
const VDJ_EIXO = vdjRgb(46, 34, 25), VDJ_JUNTAS = vdjRgb(16, 24, 26), VDJ_AGULHA = vdjRgb(255, 246, 228);
const VDJ_BATIDA = [255, 236, 204], VDJ_BATIDA_C = [210, 250, 255];
const vdjPc = matchMedia('(min-width: 900px)');
const V = { ondas: new Map(), base: null, ultPos: null, arrasto: null, ancora: null, img: null, px: null, raf: 0, sujo: true,
            chave: '', mapa: null, cor: new Map(), idVisto: null, posTroca: null, tTroca: 0 };

/* as cores de um disco em pixel pronto: os tres tons a frente do ponto de toque (vem) e atras dele (foi: mais escuros, e o
   agudo no ambar em vez do claro, que apagado ficava cinza), no volume dele na passagem em 8 degraus (o que sai vai
   escurecendo e a que entra acendendo: a onda segue inteira, para a que entra aparecer desde a primeira batida) */
function vdjPaleta(base, g = 1) {
  const n = Math.round(clamp(g, 0, 1) * 8), k = base.join('|') + '|' + n, f = .45 + .55 * n / 8;
  let p = V.cor.get(k);
  if (!p) {
    const luz = c => vdjMistura(VDJ_FUNDO, c, f);
    const foi = [vdjMistura(base[0], VDJ_FUNDO, .45), vdjMistura(base[1], VDJ_FUNDO, .5), vdjMistura(base[1], VDJ_FUNDO, .28)];
    V.cor.set(k, p = { vem: base.map(c => vdjRgb(...luz(c))), foi: foi.map(c => vdjRgb(...luz(c))) });
  }
  return p;
}
/* a posicao da proxima no tempo dela, u s de saida depois do t0 (sem o ini): a velocidade vb pelo sob, a volta em meio
   cosseno pela rampa, e 1 depois; antes do t0, o silencio que ela leva na frente anda a 1 */
function vdjFi(p, u) {
  if (u <= 0) return u;
  if (u <= p.sob) return p.vb * u;
  const r = u - p.sob, R = p.rampa;
  if (r <= R) return p.vb * p.sob + r + p.k * (r / 2 + R / (2 * Math.PI) * Math.sin(Math.PI * r / R));
  return p.vb * p.sob + R + p.k * R / 2 + (r - R);
}
function vdjFiInv(p, y) {
  if (y <= 0) return y;
  let a = 0, b = y / .9 + 1;
  for (let i = 0; i < 40; i++) { const m = (a + b) / 2; if (vdjFi(p, m) < y) a = m; else b = m; }
  return (a + b) / 2;
}
function vdjVel(p, u) {
  if (u <= 0) return 1;
  if (u <= p.sob) return p.vb;
  const r = u - p.sob;
  return r <= p.rampa ? 1 + p.k * (1 + Math.cos(Math.PI * r / p.rampa)) / 2 : 1;
}

/* a onda do disco id, pedida ao servidor uma vez (a incompleta, de novo a cada 2 s ou quando o estado avisa que uma
   ficou pronta); null enquanto nao chega */
function vdjOnda(id) {
  if (!id) return null;
  let w = V.ondas.get(id);
  const agora = performance.now(), versao = S.state && S.state.visor ? S.state.visor.ondas : 0;
  if (!w) {
    w = { id, cols: null, n: 0, passo: VDJ_PASSO, completa: false, quando: -1e9, versao: null, buscando: false };
    V.ondas.set(id, w);
    for (const k of V.ondas.keys()) { if (V.ondas.size <= 8) break; if (k !== id) V.ondas.delete(k); }
  }
  if (!w.buscando && !w.completa && (w.versao !== versao || agora - w.quando > 2000)) vdjBusca(w, versao);
  return w.cols ? w : null;
}
async function vdjBusca(w, versao) {
  w.buscando = true; w.versao = versao;
  try {
    const r = await TRANSPORTE.pedir('GET', '/api/onda/' + encodeURIComponent(w.id));
    if (r.ok) {
      const j = r.json, bin = atob(j.onda), cols = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) cols[i] = bin.charCodeAt(i);
      // a altura de cada byte: a amplitude pelo nivel forte do disco (o maior das tres faixas em 95% das colunas),
      // um pouco comprimida, para o disco baixo e o alto encherem o visor igual
      const hist = new Uint32Array(256);
      for (let i = 0; i < j.n; i++) hist[Math.max(cols[3 * i], cols[3 * i + 1], cols[3 * i + 2])]++;
      let b = 255;
      for (let soma = 0; b > 0 && soma < j.n * .05; b--) soma += hist[b];
      const ref = Math.max(VDJ_AMP[b], 1e-3);
      w.alt = Float32Array.from(VDJ_AMP, a => Math.pow(Math.min(1, a / ref), .8));
      Object.assign(w, { cols, n: j.n, passo: j.passo, completa: j.completa, resumo: null });
    }
  } catch (e) { /* sem a onda, o visor fica so com a linha do meio */ }
  w.buscando = false; w.quando = performance.now(); V.sujo = true;
}

/* a posicao do disco do prato agora, no tempo dele: a do ultimo tick andando pelo relogio na velocidade dele (1, ou a do
   plano logo depois de uma passagem), corrigida um quarto do erro a cada tick */
function vdjPos(agora) {
  const s = S.state, tr = s && s.track, id = tr ? tr.id : null, tocando = !!tr && s.status === 'playing';
  if (V.arrasto && V.arrasto.alvo != null) return V.arrasto.alvo;
  const b = V.base;
  if (S.pos !== V.ultPos || !b || b.id !== id || b.tocando !== tocando) {
    const pf = vdjPassagens().feita, velEm = q => pf ? vdjVel(pf, vdjFiInv(pf, q - pf.ini)) : 1;
    let p = S.pos, ajuste = 0;
    if (b && b.id === id && b.tocando && tocando && S.pos !== V.ultPos) {
      // (07/11, pedido do dono) o relogio anda liso: o erro se mede na hora em que o tick chegou (no quadro ele vinha ate
      // 16 ms atrasado), ate 15 ms e ruido (a posicao vem em centesimos, 15 vezes por segundo) e nao corrige; acima disso
      // a velocidade fecha o erro em ~1 s, sem salto (puxar 1/4 do erro a cada tick tirava o passo da tela da cadencia de
      // 2 quadros, e o grafico inteiro dava mexidinhas para o lado); mais de 0,25 s e pulo de verdade
      const em = S.posEmDe === S.pos ? S.posEm : agora, err = S.pos - (b.pos + (em - b.t) / 1000 * b.vel);
      if (Math.abs(err) < .25) {
        p = b.pos + (agora - b.t) / 1000 * b.vel;
        ajuste = Math.abs(err) < .015 ? 0 : clamp(err, -.1, .1);
      }
    } else if (b && b.id === id && S.pos === V.ultPos) p = b.pos + (b.tocando ? (agora - b.t) / 1000 * b.vel : 0);
    V.base = { pos: p, t: agora, id, tocando, vel: velEm(p) * (1 + ajuste) };
    V.ultPos = S.pos;
  }
  return V.base.tocando ? V.base.pos + (agora - V.base.t) / 1000 * V.base.vel : V.base.pos;
}
function vdjPassagens() {
  const s = S.state, id = s && s.track ? s.track.id : null, ps = (s && s.visor && s.visor.passagens) || [];
  return { feita: ps.find(p => p.para === id && p.de !== id) || null, vem: ps.find(p => p.de === id) || null };
}

function vdjPedeQuadro() { if (!V.raf) V.raf = requestAnimationFrame(vdjQuadro); }
function vdjQuadro(ts) {
  V.raf = 0;
  // o tempo do quadro (o da tela, de 16,7 em 16,7 ms) e nao a hora em que o callback rodou: o relogio do visor anda
  // exatamente um quadro por quadro
  if (desenharVisor(ts || performance.now()) && !reduz.matches) vdjPedeQuadro();
}
/* parado (ou com movimento reduzido), o visor so se redesenha quando algo muda: o temporizador olha 15 vezes por segundo,
   e so no computador com a pagina do disco aberta */
setInterval(() => {
  if (!vdjPc.matches || document.hidden || !document.body.classList.contains('com-disco') || V.raf) return;
  if (desenharVisor(performance.now()) && !reduz.matches) vdjPedeQuadro();
}, 66);
document.addEventListener('visibilitychange', () => { V.sujo = true; });
$('#vdj-tela').addEventListener('contextrestored', () => { V.sujo = true; });

/* um quadro: true se o disco esta tocando (o proximo quadro anda) */
function desenharVisor(agora) {
  const box = $('#visor-dj'), cv = $('#vdj-tela');
  if (!box.offsetParent) return false;
  const W = Math.max(8, Math.floor(box.clientWidth / VDJ_CEL)), H = Math.max(12, Math.floor(box.clientHeight / VDJ_CEL));
  if (cv.width !== W || cv.height !== H) {
    cv.width = W; cv.height = H; cv.style.width = W * VDJ_CEL + 'px'; cv.style.height = H * VDJ_CEL + 'px';
    V.img = null; V.sujo = true;
  }
  const s = S.state, tr = s && s.track, dur = (s && (s.duration || (tr && tr.duration))) || 0;
  const tocando = !!tr && s.status === 'playing';
  // o disco do prato mudou (a virada, ou outro disco) e o tick com a posicao do novo ainda nao chegou: o estado e o
  // tick sao eventos separados, e um quadro entre eles punha o novo na posicao do velho
  if (tr && tr.id !== V.idVisto) { V.idVisto = tr.id; V.posTroca = S.pos; V.tTroca = agora; }
  if (tr && V.base && V.base.id !== tr.id && S.pos === V.posTroca && agora - V.tTroca < 250) return tocando;
  const pos = tr ? clamp(vdjPos(agora), 0, dur || Infinity) : 0;
  const { feita, vem } = tr ? vdjPassagens() : { feita: null, vem: null };
  // a onda de cada disco que pode aparecer (pedir antes de saber se esta na tela: a proxima chega a tempo)
  const ondaAtual = tr ? vdjOnda(tr.id) : null;
  const ondaFeita = feita ? vdjOnda(feita.de) : null, ondaVem = vem ? vdjOnda(vem.para) : null;
  const span = W * VDJ_PASSO;

  // quem a tela mostra: a passagem que trouxe este disco (enquanto a sobreposicao e a volta da velocidade dele estao
  // na tela), a dele para a proxima (quando ela chega perto), ou so ele
  let p = null, ondaDe = null, ondaPara = null, agoraU = 0;
  if (feita) {
    // ate a beira esquerda passar do fim do que saiu (e da troca de cor) e da volta da velocidade: dali em diante a tela
    // de um disco so desenha igual
    const u = vdjFiInv(feita, pos - feita.ini), fim = Math.max(feita.sob + feita.rampa, (feita.v - feita.t0) / feita.va + feita.sai + 1.3);
    if (u - Math.floor(W / 2) * VDJ_PASSO < fim) { p = feita; ondaDe = ondaFeita; ondaPara = ondaAtual; agoraU = u; }
  }
  if (!p && vem) {
    const u = (pos - vem.t0) / vem.va;
    if (u > -(span + 2)) { p = vem; ondaDe = ondaAtual; ondaPara = ondaVem; agoraU = u; }
  }
  let agoraX = p ? agoraU : pos;   // o "agora" na coordenada da tela: s de saida desde o t0, ou o tempo do disco
  // (07/11, pedido do dono) tocando, o agora da tela nunca volta por um tiquinho: a posicao chega 15 vezes por segundo,
  // em centesimos, e a correcao de cada tick puxava o agora uns ms para tras; na beira de uma celula a tela inteira voltava
  // 1 coluna e avancava no quadro seguinte (a linha da batida tremia 1 pixel para o lado enquanto passava). Pulo de verdade
  // (mais de 0,25 s, outro disco, outra passagem, arrasto) segue na hora
  const kMono = p ? `${p.de}>${p.para}` : `${tr && tr.id}`, mono = V.mono;
  if (tocando && !V.arrasto && mono && mono.k === kMono && agoraX < mono.x && mono.x - agoraX < .25) agoraX = mono.x;
  V.mono = { k: kMono, x: agoraX };
  // a esquerda da tela, presa na grade das celulas (a tela so muda de celula em celula, 30 vezes por segundo): com o
  // ponto de toque no meio; com movimento reduzido, a pagina fica e o ponto anda
  let esq = (Math.floor(agoraX / VDJ_PASSO) - Math.floor(W / 2)) * VDJ_PASSO;
  if (reduz.matches) {
    const k = p ? `${p.de}>${p.para}` : `${tr && tr.id}`;
    const a = V.ancora;
    if (!a || a.k !== k || agoraX < a.esq + span * .05 || agoraX > a.esq + span * .9)
      V.ancora = { k, esq: Math.floor((agoraX - span * .15) / VDJ_PASSO) * VDJ_PASSO };
    esq = V.ancora.esq;
  }
  const agulha = Math.floor((agoraX - esq) / VDJ_PASSO + 1e-6);
  // a coluna x e a celula iEsq + x, contada em inteiros: somar esq + x * VDJ_PASSO em ponto flutuante caia um tiquinho
  // abaixo da celula em algumas colunas, que liam a coluna vizinha da onda; como esq muda a cada passo, as colunas
  // erradas mudavam junto e a onda piscava (linhas que aparecem e somem, pedido dele, 06/11)
  const iEsq = Math.round(esq / VDJ_PASSO);
  V.mapa = { esq, p, dur };

  const ambar = vdjPaleta(VDJ_AMBAR);   // o mapa de baixo
  // a que entra vira ambar quando o que saiu sai da tela pela esquerda (com movimento reduzido, de uma vez)
  let fCor = 0;
  if (p && p === feita) {
    const fimSai = (p.v - p.t0) / p.va + p.sai, f = (esq - fimSai) / 1.2;
    fCor = reduz.matches ? (f > 0 ? 1 : 0) : Math.round(clamp(f, 0, 1) * 12) / 12;   // em degraus: as cores ficam guardadas
  }
  // o quadro so se refaz quando muda o que ele mostra: a celula do ponto de toque, o disco, a passagem, a onda que chegou
  const chave = [W, H, Math.round(esq / VDJ_PASSO), agulha, fCor, s && s.status, tr && tr.id, Math.floor(pos),
                 JSON.stringify(s && s.visor && s.visor.passagens), V.arrasto ? 'a' : ''].join('|');
  if (!V.sujo && chave === V.chave) return tocando || !!V.arrasto;
  V.sujo = false; V.chave = chave;
  if (!V.img) { V.img = cv.getContext('2d').createImageData(W, H); V.px = new Uint32Array(V.img.data.buffer); }
  const px = V.px;
  px.fill(vdjRgb(...VDJ_FUNDO));
  // a faixa da onda (linhas impares, o eixo no meio) e o mapa do disco inteiro em 3 linhas embaixo
  const hw = (H - 4) % 2 ? H - 4 : H - 5, c = (hw - 1) / 2, meia = c;
  const cEntra = VDJ_AMBAR.map((cc, i) => vdjMistura(VDJ_CIANO[i], cc, fCor));
  const e = p ? (p.v - p.t0) / p.va : 0, fimSai = p ? e + p.sai : 0;
  const troca = u => !p || !p.grave ? 1 : clamp((u - e - p.grave[0]) / Math.max(1e-3, p.grave[1] - p.grave[0]), 0, 1);

  // uma metade de uma coluna: o disco no tempo t, no volume g (a cor acende com ele, a altura so um pouco) e com o grave
  // gr (a troca de grave tira o grave de um e poe no outro), do eixo para fora (dir = -1 sobe, 1 desce). Devolve o tom
  // de dentro, para o eixo
  const metade = (x, onda, t, g, gr, base, foi, dir) => {
    if (!onda) return null;
    const i = Math.floor(t / onda.passo + 1e-6);
    if (i < 0 || i >= onda.n) return null;
    const pal = vdjPaleta(base, g), cor = foi ? pal.foi : pal.vem, a = onda.alt, alt = (.7 + .3 * g) * meia;
    const hg = Math.round(a[onda.cols[3 * i]] * gr * alt), hm = Math.round(a[onda.cols[3 * i + 1]] * alt);
    const ha = Math.round(a[onda.cols[3 * i + 2]] * alt), top = Math.max(hg, hm, ha);
    for (let k = 1; k <= top; k++) px[(c + dir * k) * W + x] = k <= ha ? cor[2] : k <= hm ? cor[1] : cor[0];
    return ha ? cor[2] : hm ? cor[1] : top ? cor[0] : null;
  };
  for (let x = 0; x < W; x++) {
    const xu = (iEsq + x) * VDJ_PASSO, foi = xu < agoraX;
    let sobe = null, desce = null;   // [onda, t, g, gr, paleta]
    if (!p) {
      if (tr) sobe = desce = [ondaAtual, xu, 1, 1, VDJ_AMBAR];
    } else {
      // o que sai segue cheio ate a troca (p.segura, a passagem de DJ do motor) e cai no cosseno ate p.sai
      const seg = p.segura || 0;
      const sai = [ondaDe, p.t0 + p.va * xu, xu < e + seg ? 1 : Math.cos(clamp((xu - e - seg) / Math.max(1e-3, p.sai - seg), 0, 1) * Math.PI / 2), p.grave ? 1 - troca(xu) : 1, VDJ_AMBAR];
      // a que entra sobe em seno ate p.nivel em p.entra e dali reto ate cheia em p.cheia (a passagem de DJ do motor)
      const nv = p.nivel == null ? 1 : p.nivel;
      const gEntra = nv * Math.sin(clamp((xu - e) / Math.max(1e-3, p.entra), 0, 1) * Math.PI / 2) + (nv < 1 ? (1 - nv) * clamp((xu - e - p.entra) / Math.max(1e-3, (p.cheia || p.entra) - p.entra), 0, 1) : 0);
      const entra = xu >= 0 ? [ondaPara, p.ini + vdjFi(p, xu), gEntra, troca(xu), cEntra] : null;
      if (!entra) sobe = desce = sai;
      else if (xu > fimSai) sobe = desce = entra;
      else { sobe = sai; desce = entra; }
    }
    if (sobe !== desce) for (let y = c + 1; y < hw; y++) px[y * W + x] = VDJ_JUNTAS;   // o trecho das duas juntas
    const t1 = sobe ? metade(x, sobe[0], sobe[1], sobe[2], sobe[3], sobe[4], foi, -1) : null;
    const t2 = desce ? metade(x, desce[0], desce[1], desce[2], desce[3], desce[4], foi, 1) : null;
    // o eixo: a onda continua quando e um disco so; no trecho das duas, a linha que separa
    px[c * W + x] = sobe === desce && (t1 || t2) ? t1 || t2 : VDJ_EIXO;
  }

  // as batidas: cada grade no trecho em que o motor mediu, so na metade em que o disco dela esta desenhado
  const batida = (x, y0, y1, cor) => {
    if (x < 0 || x >= W) return;
    for (let y = y0; y <= y1; y++) {
      const i = y * W + x, q = px[i], borda = y === 0 || y === hw - 1;
      const f = borda ? 1 : .3, r = q & 255, g = q >> 8 & 255, b = q >> 16 & 255;
      px[i] = vdjRgb(Math.round(r + (cor[0] - r) * f), Math.round(g + (cor[1] - g) * f), Math.round(b + (cor[2] - b) * f));
    }
  };
  const grade = (gd, paraX, lados, cor) => {
    if (!gd) return;
    for (let n = Math.ceil((gd.de - gd.fase) / gd.periodo); ; n++) {
      const t = gd.fase + n * gd.periodo;
      if (t > gd.ate) break;
      const xu = paraX(t), x = Math.round((xu - esq) / VDJ_PASSO);
      if (x > W) break;
      if (x < 0) continue;
      const l = lados(xu);
      if (l === 'tudo') batida(x, 0, hw - 1, cor); else if (l === 'cima') batida(x, 0, c - 1, cor); else if (l === 'baixo') batida(x, c + 1, hw - 1, cor);
    }
  };
  const corEntra = vdjMistura(VDJ_BATIDA_C, VDJ_BATIDA, fCor);
  if (p) {
    if (p.no_tempo) {
      grade(p.grade_de, t => (t - p.t0) / p.va, xu => xu < 0 ? 'tudo' : xu <= fimSai ? 'cima' : null, VDJ_BATIDA);
      grade(p.grade_para, t => vdjFiInv(p, t - p.ini), xu => xu < 0 ? null : xu <= fimSai ? 'baixo' : 'tudo', corEntra);
    }
  } else if (tr) {
    // so o disco do prato: a grade dele do comeco (a passagem que o trouxe) e a do fim (a medida para a proxima)
    if (feita && feita.no_tempo) grade(feita.grade_para, t => t, () => 'tudo', VDJ_BATIDA);
    if (vem && vem.no_tempo) grade(vem.grade_de, t => t, () => 'tudo', VDJ_BATIDA);
  }

  // o ponto de toque: a linha clara com o T de pixel em cima e embaixo
  if (agulha >= 0 && agulha < W) {
    for (let y = 0; y < hw; y++) px[y * W + agulha] = VDJ_AGULHA;
    for (const y of [0, hw - 1]) for (const x of [agulha - 1, agulha + 1]) if (x >= 0 && x < W) px[y * W + x] = VDJ_AGULHA;
  }

  // o mapa do disco inteiro: a onda resumida (o maior de cada pedaco), o que ja tocou aceso, o ponto de toque e onde a
  // proxima entra
  if (tr && dur) {
    const y0 = H - 3;
    const w = ondaAtual;
    if (w && (!w.resumo || w.resumo.length !== W || w.resumoN !== w.n)) {
      const r = new Float32Array(W);
      for (let x = 0; x < W; x++) {
        let m = 0;
        let i = Math.floor(x * dur / W / w.passo), q = 0;
        for (const f = Math.min(w.n, Math.ceil((x + 1) * dur / W / w.passo)); i < f; i++, q++)
          m += Math.max(w.alt[w.cols[3 * i]], w.alt[w.cols[3 * i + 1]], w.alt[w.cols[3 * i + 2]]);
        r[x] = q ? m / q : 0;   // a media do pedaco: o maior enchia o mapa inteiro
      }
      w.resumo = r; w.resumoN = w.n;
    }
    const xp = Math.min(W - 1, Math.floor(pos / dur * W));
    for (let x = 0; x < W; x++) {
      const alto = w ? Math.max(1, Math.round(w.resumo[x] * 3.4)) : 1, cor = x < xp ? ambar.vem[1] : ambar.foi[0];
      for (let k = 0; k < alto; k++) px[(H - 1 - k) * W + x] = cor;
    }
    if (vem && vem.t0 < dur) { const xv = Math.min(W - 1, Math.floor(vem.t0 / dur * W)); for (let y = y0; y < H; y++) px[y * W + xv] = vdjPaleta(VDJ_CIANO).vem[1]; }
    for (let y = y0 - 1; y < H; y++) px[y * W + xp] = VDJ_AGULHA;
  }
  cv.getContext('2d').putImageData(V.img, 0, 0);

  // o tempo, e a etiqueta da passagem que esta na tela
  mudar($('#vdj-pos'), 'textContent', fmt(pos));
  mudar($('#vdj-resta'), 'textContent', tr && dur ? '-' + fmt(Math.ceil(dur - pos)) : fmt(dur));
  const selo = $('#vdj-selo'), naTela = p && fimSai >= esq && 0 <= esq + span;
  let txt = '', dica = '';
  if (naTela && p.no_tempo) {
    const pct = (p.vb - 1) * 100;
    txt = I18N.t('tv.badge.inTime') + (Math.abs(pct) >= .05 ? ` ${pct > 0 ? '+' : '-'}${I18N.num(Math.abs(pct), 1)}%` : '');
    const bpm = g => g ? Math.round(g.bpm) : null, a = bpm(p.grade_de), b = bpm(p.grade_para);
    const k = Math.abs(pct) >= .05 ? (a && b ? 'tv.hint.inTimeBpmPitch' : 'tv.hint.inTimePitch') : a && b ? 'tv.hint.inTimeBpm' : 'tv.inTime';
           dica = I18N.t(k, { bpmOut: a, bpmIn: b, pct: `${pct > 0 ? '+' : '-'}${I18N.num(Math.abs(pct), 1)}` });
  } else if (naTela) { txt = I18N.t('tv.badge.fade'); dica = I18N.t('tv.hint.volumeOnly'); }
  if (selo.hidden !== !txt) selo.hidden = !txt;
  mudar(selo, 'textContent', txt);
  selo.classList.toggle('fade', !!naTela && !p.no_tempo);
  mudar(box, 'title', dica);
  return tocando || (!!V.arrasto) || fCor > 0 && fCor < 1;
}

/* o tempo do disco do prato na coluna x do visor (o clique e o arrasto pulam para la) */
function vdjTempoNaColuna(x) {
  const m = V.mapa; if (!m) return 0;
  const xu = m.esq + x * VDJ_PASSO, p = m.p;
  let t = xu;
  if (p && S.state && S.state.track && p.para === S.state.track.id) t = xu < 0 ? 0 : p.ini + vdjFi(p, xu);
  else if (p) t = p.t0 + p.va * xu;
  return clamp(t, 0, Math.max(0, m.dur - .5));
}
/* clicar na onda pula para o ponto clicado; arrastar puxa a onda como o disco na mao (solta, pula); no mapa de baixo,
   clicar ou arrastar pula para aquele ponto do disco inteiro, como a barra fazia */
function vdjPula(t) {
  S.pos = t; V.base = null; V.sujo = true; desenharTempo();
  api('POST', '/api/seek', { t }).catch(err => avisar(err.message, true));
}
const vdjBox = $('#visor-dj');
vdjBox.addEventListener('pointerdown', e => {
  const s = S.state, dur = s && (s.duration || (s.track && s.track.duration));
  if (!s || !s.track || !dur || e.button !== 0 || !V.mapa) return;
  e.preventDefault();
  try { vdjBox.setPointerCapture(e.pointerId); } catch (err) { /* o ponteiro ja saiu: o arrasto segue so dentro do visor */ }
  const r = $('#vdj-tela').getBoundingClientRect();
  const noMapa = e.clientY - r.top >= r.height - 5 * VDJ_CEL;
  V.arrasto = { id: e.pointerId, x0: e.clientX, pos0: vdjPos(performance.now()), noMapa, mexeu: noMapa, alvo: null, r, dur };
  if (noMapa) V.arrasto.alvo = clamp((e.clientX - r.left) / r.width, 0, 1) * Math.max(0, dur - .5);
  vdjBox.classList.add('arrastando'); V.sujo = true; vdjPedeQuadro();
});
vdjBox.addEventListener('pointermove', e => {
  const a = V.arrasto; if (!a || a.id !== e.pointerId) return;
  const dx = e.clientX - a.x0;
  if (a.noMapa) a.alvo = clamp((e.clientX - a.r.left) / a.r.width, 0, 1) * Math.max(0, a.dur - .5);
  else if (a.mexeu || Math.abs(dx) > 3) { a.mexeu = true; a.alvo = clamp(a.pos0 - dx / VDJ_CEL * VDJ_PASSO, 0, Math.max(0, a.dur - .5)); }
  V.sujo = true; vdjPedeQuadro();
});
const vdjSolta = e => {
  const a = V.arrasto; if (!a || a.id !== e.pointerId) return;
  V.arrasto = null; vdjBox.classList.remove('arrastando');
  if (e.type === 'pointercancel') { V.sujo = true; return; }
  vdjPula(a.mexeu ? a.alvo : vdjTempoNaColuna(Math.floor((e.clientX - a.r.left) / VDJ_CEL)));
};
vdjBox.addEventListener('pointerup', vdjSolta);
vdjBox.addEventListener('pointercancel', vdjSolta);
/* DJ-VISOR-JS-FIM */
