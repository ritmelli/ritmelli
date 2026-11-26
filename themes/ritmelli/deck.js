/* DECK-JS-INICIO */
/* os dois toca-discos da mesa inteiros em pixel art (1 celula = 2 px), num canvas por deck por cima
   dele: a caixa de madeira e a chapa creme com os parafusos, a letra do lado, o prato (anel do estroboscopio em marcas
   fixas de 2x3, o vinil com os sulcos e o brilho, o rotulo com o aro), a base do pivo, o descanso em garfo, o braco
   (contrapeso, tubo de largura constante, bola, cabeca em 3 tons e o levantador), o botao redondo do canto, a etiqueta
   de estado com a lampada, a tela do titulo, os tempos, a barra de tempo, os botoes e a plaquinha RITMELLI, com os
   textos numa fonte de bitmap (a Jersey 10 e a VT323 lidas na grade delas). Os elementos de verdade seguem ali,
   transparentes por cima: o clique, o estado, os textos e o lugar de cada coisa vem deles (o giro do prato e o angulo
   do braco tambem, do CSS de sempre). Cada deck vai para x e y pares. */
import { glyphs, ruido, cor, O, O2, SOMBRA, SOMBRA_F, TINTA, CREME_L, fontesProntas, pincel, px, ret, recorte, solto, caixa, sombraCaixa, disco, esfera3, lg, mapa, stamp } from "pixel.js";
import { RITMELLI, MIUDA } from "letters.js";
const M = { M0: cor(248, 190, 140), P1: cor(234, 146, 92), P2: cor(206, 116, 68), P3: cor(184, 94, 52), WF: cor(166, 82, 44),
            P35: cor(150, 70, 38), W6: cor(142, 67, 35), W5: cor(134, 64, 33), P4: cor(120, 52, 26) };
const CH = { veio: cor(223, 216, 201), base: cor(227, 220, 205), risca: cor(220, 213, 197), risca2: cor(231, 225, 212), luz: cor(244, 239, 228), sombra: cor(196, 187, 170) };
const CREME = cor(239, 230, 213), CREME_S = cor(206, 192, 168);
const ICONE = {
  ant: ["##.....#", "##....##", "##...###", "##..####", "##.#####", "##.#####", "##..####", "##...###", "##....##", "##.....#"],
  prox: ["#.....##", "##....##", "###...##", "####..##", "#####.##", "#####.##", "####..##", "###...##", "##....##", "#.....##"],
  tocar: ["#..........", "###........", "####.......", "######.....", "#######....", "#########..", "##########.", "###########",
          "##########.", "#########..", "#######....", "######.....", "####.......", "###........", "#.........."],
  pausar: ["###...###", "###...###", "###...###", "###...###", "###...###", "###...###", "###...###", "###...###", "###...###",
           "###...###", "###...###", "###...###", "###...###"],
};
const icone = (P, nome, cx, cy, c, k = 1) => stamp(P, ICONE[nome], cx, cy, c, k);
const { gl, larg, texto } = glyphs({ ",": ["..", "..", "..", "..", "..", "..", ".#", ".#", "#."], "⋯": [".....", ".....", ".....", ".....", "#.#.#", ".....", "....."] });
let fontesOk = false;
export const deckGlyphs = { gl, larg, ready: () => fontesOk };
(() => {
  const AMBAR = [cor(255, 214, 110), cor(240, 170, 54), cor(178, 106, 28)];
  // (#53) o salvar do disco no prato, na tela, no fim da linha do artista: o ⊕ da pagina em 9 celulas (o botao de verdade
  // fica por baixo, apagado como o resto da tela, e e ele que pega o clique). O aro acende no sentido do relogio
  // enquanto baixa; chegou, o disco ambar com o visto
  const SV_TAM = 9, SV_ARO = ['...###...', '.##...##.', '.#.....#.', '#.......#', '#.......#', '#.......#', '.#.....#.', '.##...##.', '...###...'];
  const svAng = ([x, y]) => (Math.atan2(x + .5 - 4.5, 4.5 - y - .5) + 2 * Math.PI) % (2 * Math.PI);
  const SV_CELS = SV_ARO.flatMap((l, y) => [...l].map((c, x) => c === '#' ? [x, y] : null).filter(Boolean)).sort((a, b) => svAng(a) - svAng(b));
  const SV_DENTRO = SV_ARO.flatMap((l, y) => { const a = l.indexOf('#'), b = l.lastIndexOf('#'); return [...l].map((c, x) => x > a && x < b ? [x, y] : null).filter(Boolean); })
    .filter(([x, y]) => y > 0 && y < 8);
  const SV_MAIS = [[4, 2], [4, 3], [2, 4], [3, 4], [4, 4], [5, 4], [6, 4], [4, 5], [4, 6]];
  const SV_VISTO = [[2, 4], [3, 5], [4, 6], [5, 5], [6, 4], [7, 3]];
  function salvarNaTela(P, b, x0, y0) {
    const est = ['salvo', 'baixando', 'erro'].find(k => b.classList.contains(k)) || 'livre';
    const n = est === 'baixando' ? Math.round(SV_CELS.length * (parseFloat(b.style.getPropertyValue('--pr')) || 0) / 100) : 0;
    const APAGADO = cor(176, 160, 138), CLARO = cor(251, 239, 217);
    const cels = SV_CELS.map(([x, y], i) => [x, y, est === 'salvo' ? AMBAR[2] : i < n ? AMBAR[1] : APAGADO]);
    if (est === 'salvo') cels.push(...SV_DENTRO.map(([x, y]) => [x, y, AMBAR[1]]), ...SV_VISTO.map(([x, y]) => [x, y, cor(42, 24, 18)]));
    else cels.push(...SV_MAIS.map(([x, y]) => [x, y, est === 'erro' ? cor(242, 115, 94) : est === 'baixando' ? cor(110, 98, 84) : CLARO]));
    for (const [x, y] of cels) px(P, x0 + x, y0 + y + 1, O);   // a sombra de 1 celula, a das letras
    for (const [x, y, c] of cels) px(P, x0 + x, y0 + y, c);
  }
  // as dicas do prato vazio na forma curta que cabe na tela (a inteira segue no DOM, para o leitor de tela)
  const CURTAS = new Map([[I18N.t('deck.hint'), I18N.t('deck.screen.hint')], [I18N.t('deck.hintEmpty'), I18N.t('deck.screen.hintEmpty')],
                          [I18N.t('cue.emptyHint'), I18N.t('cue.screen.emptyHint')]]);


  // ---------------- os decks
  const decks = new Map();
  const ang = el => { const m = getComputedStyle(el).transform; if (!m || m === 'none') return 0; const v = m.match(/-?[\d.e]+/g).map(Number); return Math.atan2(v[1], v[0]); };
  const rel = (el, D) => { const r = rectP(el); return { x0: Math.round((r.left - D.left) / 2), y0: Math.round((r.top - D.top) / 2), x1: Math.round((r.right - D.left) / 2), y1: Math.round((r.bottom - D.top) / 2), w: r.width, h: r.height }; };
  const visivel = el => el && el.offsetParent !== null && getComputedStyle(el).display !== 'none';
  // o angulo do braco da pagina vira o nosso (prato maior, pivo 3 celulas a direita) como antes do #50, pelo ponto no eixo
  // do tubo de um e do outro, mais a diferenca do comeco da faixa, que diminui com ela ate sumir no fim (#50): no comeco,
  // a ponta da nossa cabeca na borda do disco, como a da pagina; no fim, o mesmo angulo de antes (o quadro(), abaixo)
  const fPagina = eixoNoDisco;
  // a nossa cabeca (o braco() abaixo): comeca CAB_HL celulas antes do fim do tubo e dobra 30 graus para o eixo do prato;
  // a ponta dela e a agulha
  const CAB_HL = 16, CAB_FI = 30 * Math.PI / 180;
  function cabecaDeck(g, th) {
    const dx = -Math.sin(th), dy = Math.cos(th), wx = g.cx - (g.Px + dx * g.L), wy = g.cy - (g.Py + dy * g.L);
    const fi = (Math.sign(-dy * wx + dx * wy) || 1) * CAB_FI;
    return { H0x: g.Px + dx * (g.L - CAB_HL), H0y: g.Py + dy * (g.L - CAB_HL),
             hdx: dx * Math.cos(fi) - dy * Math.sin(fi), hdy: dx * Math.sin(fi) + dy * Math.cos(fi) };
  }
  let thBorda = null;
  function borda() {
    if (thBorda !== null) return thBorda;
    let a = 0, b = 1.4;
    for (let i = 0; i < 40; i++) { const m = (a + b) / 2; if (fPagina(m) > 1) a = m; else b = m; }
    return (thBorda = (a + b) / 2);
  }

  function prepara(deck) {
    let d = decks.get(deck);
    if (d) return d;
    const cv = document.createElement('canvas');
    cv.className = 'dk-px'; cv.setAttribute('aria-hidden', 'true');
    deck.appendChild(cv);
    cv.style.left = -deck.clientLeft + 'px'; cv.style.top = -deck.clientTop + 'px';
    const q = s => deck.querySelector(s);
    d = { deck, cv, ctx: cv.getContext('2d'), tampo: q('.tampo'), prato: q('.prato'), gira: q('.giratorio'), braco: q('.braco'),
          rotulo: q('.rotulo'), faixa: q('.faixa'), letra: q('.deck-letra'), luz: q('.deck-luz'), luzT: q('.deck-luz-t'),
          lamp: q('.deck-luz .lampada'), titulo: q('.titulo-faixa'), canal: q('.canal-faixa > span'), salvar: q('.canal-faixa .salvar'), bpm: q('.deck-bpm'),
          seek: q('.linha-tempo input[type=range]'), tempos: [...deck.querySelectorAll('.linha-tempo .tempo')],
          botoes: [...deck.querySelectorAll('.comandos button')],
          chaveE: '', chaveC: '', rot: NaN, th: NaN, lab: null, labChave: '' };
    decks.set(deck, d);
    deck.classList.add('dk-ok');
    return d;
  }

  // ---- o desenho parado: caixa, chapa, parafusos, letra, prato, base, descanso, botao do canto, plaquinha
  function estatico(d, W, H, D, g) {
    const P = pincel(W, H);
    // a caixa de madeira de 7: contorno com a quina em degrau de 3, 1 de luz em cima e a esquerda (1 de sombra embaixo e a
    // direita), 4 de madeira com veio em tracos curtos ao longo do lado, a linha escura do rebaixo e a chapa em degrau de 2
    const E = 9, CF = 4, chx0 = E, chy0 = E, chx1 = W - E, chy1 = H - E;
    const naChapa = (x, y) => x >= chx0 && x < chx1 && y >= chy0 && y < chy1 &&
      Math.min(x - chx0, chx1 - 1 - x) + Math.min(y - chy0, chy1 - 1 - y) >= 3;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const ex = Math.min(x, W - 1 - x), ey = Math.min(y, H - 1 - y);
      if (ex + ey < CF) continue;
      if (naChapa(x, y)) continue;
      let c;
      const viz = naChapa(x + 1, y) || naChapa(x - 1, y) || naChapa(x, y + 1) || naChapa(x, y - 1) ||
                  naChapa(x + 1, y + 1) || naChapa(x - 1, y - 1) || naChapa(x + 1, y - 1) || naChapa(x - 1, y + 1);
      if (ex + ey === CF || ex === 0 || ey === 0) c = O;
      else if (viz) c = O2;
      else if (ex + ey === CF + 1) c = (x < W / 2 && y < H / 2) || (x < W / 2 && y > H / 2 && ex === 1) || (y < H / 2 && x > W / 2 && ey === 1) ? M.M0 : M.P4;
      else if (x === 1 || y === 1) c = M.M0;
      else if (x === W - 2 || y === H - 2) c = M.P4;
      else {
        const ao = ey < ex, al = ao ? x : y, tr = ao ? ey : ex;           // ao longo do lado e a distancia da borda
        const seg = Math.floor((al + ruido(tr, ao ? 1 : 2) * 9) / (4 + Math.floor(ruido(tr, 7) * 5)));
        const v = ruido(tr, seg, ao ? 3 : 4);
        c = v < .2 ? M.P35 : v < .3 ? M.P3 : v < .36 ? M.W6 : M.WF;
        const fundo = ao ? y > H / 2 : x > W / 2;
        if (fundo) { if (tr === 2 || tr === 3) c = v < .3 ? M.P35 : M.P4; else if (tr >= E - 3) c = v < .3 ? M.P3 : M.WF; }
        else if (tr === 2 || tr === 3) c = v < .3 ? M.P1 : M.P2;                     // a face de cima da madeira, mais clara
      }
      px(P, x, y, c);
    }
    // a chapa creme: a sombra da madeira em cima e a esquerda, o filete claro embaixo e a direita, tracinhos de 1 a 3 raros
    for (let y = chy0; y < chy1; y++) for (let x = chx0; x < chx1; x++) {
      if (!naChapa(x, y)) continue;
      let c = CH.base;
      if (x % 2 === 0) c = CH.veio;
      if (!naChapa(x - 1, y) || !naChapa(x, y - 1)) c = CH.sombra;
      else if (!naChapa(x + 1, y) || !naChapa(x, y + 1)) c = CH.luz;
      px(P, x, y, c);
    }
    // os parafusos nos cantos de cima a direita e de baixo a direita
    const parafuso = (x, y) => {
      const f = ["..###..", ".#hhm#.", "#hhmxm#", "#hmxls#", "#mxlss#", ".#mss#.", "..###.."];
      const k = { "#": O, h: cor(250, 246, 236), m: cor(206, 198, 184), s: cor(150, 140, 126), x: cor(62, 52, 46), l: cor(236, 230, 218) };
      f.forEach((l, j) => [...l].forEach((q, i) => { if (q !== '.') px(P, x + i, y + j, k[q]); }));
      f.forEach((l, j) => [...l].forEach((q, i) => {
        if (q === '.') return;
        const l2 = f[j + 1], q2 = l2 ? l2[i + 1] : undefined;
        if (!q2 || q2 === '.') px(P, x + i + 1, y + j + 1, SOMBRA_F);
      }));
    };
    parafuso(chx1 - 11, chy0 + 4); parafuso(chx1 - 11, chy1 - 12);
    // a letra do lado: plaquinha pessego de 17 com a quina em degrau de 2, o filete de dentro e a letra de 8x9
    if (d.letraTxt) {
      // (r06) 1 celula mais alta em cima e embaixo, a letra no mesmo lugar: as 11 linhas dela encostavam nos filetes
      const lx0 = chx0 + 5, ly0 = chy0 + 4, lx1 = lx0 + 23, ly1 = ly0 + 19;
      sombraCaixa(P, lx0, ly0, lx1, ly1, 1, 2, 2);
      caixa(P, lx0, ly0, lx1, ly1, cor(250, 222, 180), cor(255, 240, 214), cor(222, 182, 132), 2);
      for (let x = lx0 + 3; x < lx1 - 3; x++) { px(P, x, ly0 + 2, cor(236, 200, 152)); px(P, x, ly1 - 3, cor(236, 200, 152)); }
      for (let y = ly0 + 3; y < ly1 - 3; y++) { px(P, lx0 + 2, y, cor(236, 200, 152)); px(P, lx1 - 3, y, cor(236, 200, 152)); }
      const LETRA = { A: ["....###....", "...#####...", "..###.###..", "..###.###..", ".###...###.", ".###...###.", ".#########.", ".#########.",
                          "###.....###", "###.....###", "###.....###"],
                      B: ["########.", "#########", "###...###", "###...###", "########.", "########.", "###...###", "###...###", "###...###",
                          "#########", "########."] };
      const gl = LETRA[d.letraTxt];
      if (gl) { const ox = lx0 + Math.floor((23 - gl[0].length + 1) / 2), oy = ly0 + 4;
        gl.forEach((l, j) => [...l].forEach((q, i) => { if (q === '#') px(P, ox + i, oy + j, TINTA); })); }
    }
    // o botao redondo do canto de baixo a esquerda (o liga do mock)
    disco(P, chx0 + 13, chy1 - 13, 4.5, (dx, dy, r) => r < 1.5 ? O : esfera3(cor(228, 222, 210), cor(255, 252, 244), cor(176, 168, 154), 4.5, 1.1)(dx, dy), [1, 2]);   // (r09) a sombra 1 a direita e 2 embaixo, como as outras pecas em relevo
    // o prato (centro inteiro: os quadrantes saem iguais): a lateral escura embaixo, a sombra curta, o contorno, o aro com o
    // filete aceso no arco de cima e da esquerda, a linha escura do vinil, os sulcos finos, o brilho em duas cunhas, o rotulo
    const { cx, cy, Rp, Rr, Rl, Ri, com } = g;
    P.dim = g.dim;
    const Rin = com ? Rr : g.Rf;
    for (let y = Math.floor(cy - Rp - 2); y <= Math.ceil(cy + Rp + 6); y++) for (let x = Math.floor(cx - Rp - 2); x <= Math.ceil(cx + Rp + 4); x++) {
      const dx = x + .5 - cx, dy = y + .5 - cy, r = Math.hypot(dx, dy);
      if (r > Rp) {
        const rl = Math.hypot(dx, dy - 1);
        if (rl <= Rp) px(P, x, y, cor(80, 72, 66));                              // o labio: a espessura do prato
        else if (rl <= Rp + 1 || r <= Rp + 1) px(P, x, y, O);
        else if (Math.hypot(dx - 1, dy - 3) <= Rp + 1) px(P, x, y, SOMBRA);
        continue;
      }
      if (r > Rin + 1) { px(P, x, y, r > Rp - 1 && (dx + dy) < -.35 * r ? cor(100, 94, 90) : cor(36, 33, 31)); continue; }
      if (r > Rin) { px(P, x, y, O); continue; }
      if (!com) {
        const f = r / g.Rf;
        let a = Math.atan2(dx, -dy) * 180 / Math.PI;
        if (a < 0) a += 360;
        const da = Math.min(Math.abs(a - 315), 360 - Math.abs(a - 315));
        // (r06) o brilho afina nas pontas (a meia largura cai com o angulo): o setor reto terminava em bloco quadrado
        const hw = .09 * Math.max(0, 1 - (da / 23) ** 2), dr = Math.abs(f - .81), arco = dr < hw;
        const sulco = [.57, .7, .82].some(q => Math.abs(r - q * g.Rf) < .5);
        let c = f > .9 ? cor(25, 42, 34) : cor(33, 55, 45);
        if (arco && dr < hw * .6 && da <= 15) c = cor(52, 82, 68); else if (arco) c = cor(43, 69, 57);
        if (sulco) c = arco ? cor(60, 92, 77) : cor(41, 67, 56);
        px(P, x, y, c); continue;
      }
      if (r <= Ri) { P.u[y * W + x] = 0; continue; }
      if (r <= Rl - 1) { px(P, x, y, (dx + dy) < 0 ? cor(198, 186, 166) : cor(156, 144, 126)); continue; }
      if (r <= Rl) { px(P, x, y, O); continue; }
      const fr = Math.floor(r), sulco = fr % 3 === 0;
      let c = sulco ? cor(24, 22, 21) : cor(17, 15, 14);
      if (r > Rl + 1 && r < Rin - 1) {
        let a = Math.atan2(dx, -dy) * 180 / Math.PI;
        if (a < 0) a += 360;
        const da = Math.min(...[340.5, 160.5].map(m => { const q = Math.abs(a - m) % 360; return Math.min(q, 360 - q); }));
        if (da <= 13) c = sulco ? cor(70, 66, 61) : cor(57, 53, 50);
        else if (da <= 17) c = sulco ? cor(64, 60, 56) : cor(49, 45, 42);
        else if (da <= 21) c = sulco ? cor(51, 48, 45) : cor(37, 34, 32);
        else if (da <= 25) c = sulco ? cor(39, 36, 34) : cor(25, 23, 21);
      }
      if (r > Rin - 1 && (dx + dy) < -.3 * r) c = cor(54, 49, 45);                 // o labio do vinil, aceso
      px(P, x, y, c);
    }
    // o eixo: 4x4 sem as quinas, com o contorno e o brilho em cima a esquerda
    if (com || true) {
      const ex0 = Math.round(cx) - 3, ey0 = Math.round(cy) - 3;
      [".####..", "#hlll#.", "#llls#z", "#llss#z", "#lsss#z", ".####z.", "..zzz.."].forEach((l, j) => [...l].forEach((q, i) => {
        if (q !== '.') px(P, ex0 + i, ey0 + j, { "#": O, h: cor(248, 244, 234), l: cor(212, 205, 190), s: cor(140, 128, 110),
                                                 z: com ? cor(10, 9, 8) : cor(18, 30, 24) }[q]);
      }));
    }
    // o anel do estroboscopio parado: 64 quadrados de 4x4 no meio da faixa (passo ~6.6, vao ~2.6), um oitavo calculado e
    // espelhado celula a celula nos outros sete
    {
      const N = 64, rm = (Rin + Rp) / 2, C0 = Math.round(cx), C1 = Math.round(cy), cel = [];
      // (r08) o padrao meio passo girado: com o centro na fronteira de celula, o ponto de 3 no eixo saia 4x3; assim os
      // eixos ficam num vao e os pontos vem em pares espelhados, todos 3x3
      for (let k = 0; k < N / 8; k++) {
        // (r07) quadrados de 3x3: os de 4x4 quase se tocavam nas diagonais (folga de 1 contra 4 nos eixos, cara de ziper)
        const a = (k + .5) * 2 * Math.PI / N, i0 = Math.round(rm * Math.cos(a) - 1.5), j0 = Math.round(rm * Math.sin(a) - 1.5);
        for (let di = 0; di < 3; di++) for (let dj = 0; dj < 3; dj++) cel.push([i0 + di, j0 + dj]);
      }
      for (const [i, j] of cel) for (const [a, b] of [[i, j], [j, i]]) for (const sx of [1, -1]) for (const sy of [1, -1])
        px(P, C0 + (sx > 0 ? a : -1 - a), C1 + (sy > 0 ? b : -1 - b), cor(241, 233, 216));
    }
    // a base do pivo: o disco creme largo e o anel de metal (a bola vem com o braco)
    disco(P, g.Px, g.Py, g.Rb, (dx, dy, r) => r > 8 && r <= 9 ? cor(140, 128, 110) :
      Math.hypot(dx + 1.6, dy + 1.6) > g.Rb - .2 ? cor(184, 175, 158) :
      Math.hypot(dx - 1.3, dy - 1.3) > g.Rb - .3 ? cor(248, 244, 234) : r <= 8 ? cor(224, 217, 203) : cor(212, 205, 190), [1, 2]);
    // o descanso visto de cima: o pe redondo de 9 com a luz em cima a esquerda e a sombra embaixo a direita, e o garfo de
    // duas abas de 2x4 abertas na largura do tubo com contorno (5): no deck vazio o vao e escuro, na deixa o tubo passa nele
    {
      // (r04) o pedestal de metal em degrau, mais largo que o tubo, e o garfo claro de duas pontas dos lados dele: o oval
      // com as abas escuras, cortado pelo tubo, lia como "( )"
      const fx_ = Math.floor(g.Px), fy = Math.round(g.Dy) - 2;
      const x0 = fx_ - 6, x1 = fx_ + 7, y0 = fy - 3, y1 = fy + 3;
      for (let y = y0 - 1; y <= y1 + 1; y++) for (let x = x0 - 1; x <= x1 + 1; x++) {
        const ex = Math.min(x - (x0 - 1), x1 + 1 - x), ey = Math.min(y - (y0 - 1), y1 + 1 - y);
        if (ex + ey < 1) continue;
        const borda = x === x0 - 1 || x === x1 + 1 || y === y0 - 1 || y === y1 + 1 || ex + ey === 1;
        px(P, x, y, borda ? O : y === y0 ? cor(248, 244, 234) : y === y1 ? cor(186, 176, 158) : x === x0 ? cor(236, 230, 218) : cor(220, 213, 198));
      }
      for (let x = x0 + 1; x <= x1 + 2; x++) px(P, x, y1 + 2, SOMBRA_F);
      for (let y = y0 + 1; y <= y1 + 2; y++) px(P, x1 + 2, y, SOMBRA_F);
      // (r05) cada ponta do garfo sem o contorno escuro em volta (o contorno fechado com o fundo escuro lia "UU"): o pino
      // claro em pe com a sombra so a direita e embaixo, no corpo do pedestal
      for (const ax of [fx_ - 4, fx_ + 4]) {
        ret(P, ax, fy - 3, ax + 1, fy + 1, cor(240, 236, 226));
        ret(P, ax + 1, fy - 2, ax + 2, fy + 2, cor(172, 164, 148));
        px(P, ax, fy + 1, cor(172, 164, 148));
      }
    }
    P.dim = 1;
    // a plaquinha RITMELLI no meio da coluna da direita, embaixo do transporte
    const w1 = lg('RITMELLI', RITMELLI), w2 = lg('33 / 45 RPM', MIUDA), sw = Math.max(w1, w2) + 10, sh = 22;   // (r09) 2 celulas mais alta embaixo: 2 de folga entre o filete e as letras
    const fx = g.faixa, sx0 = Math.round((fx.x0 + fx.x1 - sw) / 2), sy0 = g.cmdY1 + 10;   // (r07) 3 celulas mais longe do play
    sombraCaixa(P, sx0, sy0, sx0 + sw, sy0 + sh, 1, 2);
    caixa(P, sx0, sy0, sx0 + sw, sy0 + sh, CREME, CREME_L, CREME_S);
    for (let x = sx0 + 2; x < sx0 + sw - 2; x++) { px(P, x, sy0 + 2, cor(198, 182, 156)); px(P, x, sy0 + sh - 3, cor(198, 182, 156)); }
    for (let y = sy0 + 2; y < sy0 + sh - 2; y++) { px(P, sx0 + 2, y, cor(198, 182, 156)); px(P, sx0 + sw - 3, y, cor(198, 182, 156)); }
    mapa(P, 'RITMELLI', RITMELLI, sx0 + Math.floor((sw - w1) / 2), sy0 + 5, TINTA);
    mapa(P, '33 / 45 RPM', MIUDA, sx0 + Math.floor((sw - w2) / 2), sy0 + 12, cor(48, 34, 26));
    return P;
  }

  // ---- os controles: etiqueta de estado, tela do titulo, tempos, barra, botoes
  function controles(d, W, H, D, g, est) {
    const P = pincel(W, H);
    P.u.set(est.u);
    const fx = g.faixa;
    // a tela: do topo do titulo ao fim do BPM, na largura da coluna; a moldura de 4 (contorno, luz e sombra, a madeira,
    // a linha do rebaixo) e o vidro escuro com a sombra de cima
    const T = rel(d.titulo, D), B = d.bpm && visivel(d.bpm) ? rel(d.bpm, D) : rel(d.canal || d.titulo, D);
    const tx0 = fx.x0, tx1 = fx.x1 + 1, ty0 = T.y0 - 5, ty1 = Math.max(B.y1 + 3, ty0 + 44);
    sombraCaixa(P, tx0, ty0, tx1, ty1, 1, 2, 2);
    caixa(P, tx0, ty0, tx1, ty1, cor(112, 58, 32), cor(168, 100, 62), cor(62, 30, 15), 2);
    ret(P, tx0 + 2, ty0 + 2, tx1 - 2, ty1 - 2, cor(112, 58, 32));
    ret(P, tx0 + 2, ty0 + 2, tx1 - 2, ty0 + 3, cor(140, 78, 44)); ret(P, tx0 + 2, ty0 + 2, tx0 + 3, ty1 - 2, cor(140, 78, 44));
    ret(P, tx0 + 3, ty0 + 3, tx1 - 3, ty1 - 3, O);
    const ix0 = tx0 + 4, iy0 = ty0 + 4, ix1 = tx1 - 4, iy1 = ty1 - 4;
    ret(P, ix0, iy0, ix1, iy1, cor(22, 17, 14));
    ret(P, ix0, iy0, ix1, iy0 + 1, cor(10, 8, 6)); ret(P, ix0, iy0, ix0 + 1, iy1, cor(14, 11, 9));
    // a etiqueta de estado em cima da tela, dividindo o contorno com ela, com a cor do estado
    if (d.luz && visivel(d.luz) && fontesOk) {
      const t = (d.luzT ? d.luzT.textContent : '').trim().toUpperCase(), cl = d.lamp ? d.lamp.classList : { contains: () => false };
      const pisca = cl.contains('piscando') && (Date.now() / 450 | 0) % 2, acesa = cl.contains('acesa') && !pisca;
      const deixa = d.deck.classList.contains('deck-deixa');
      const ambar = deixa && cl.contains('acesa');
      const w = larg('fb', t) + 17, lx0 = tx0 + 3, ly1 = ty0 + 1, ly0 = ly1 - 13;
      sombraCaixa(P, lx0, ly0, lx0 + w, ly1, 1, 1, 2);   // (r06) o corte da sombra no da etiqueta (2), sem o furo na quina
      if (ambar) caixa(P, lx0, ly0, lx0 + w, ly1, cor(240, 170, 60), cor(255, 214, 120), cor(186, 112, 30), 2);
      else caixa(P, lx0, ly0, lx0 + w, ly1, CREME, CREME_L, CREME_S, 2);
      const led = !acesa ? [cor(196, 150, 140), cor(128, 72, 62), cor(90, 46, 40)]
        : deixa ? [cor(255, 250, 200), cor(255, 226, 70), cor(200, 150, 20)] : [cor(255, 190, 170), cor(232, 46, 34), cor(150, 20, 14)];
      const f = [".###.", "#lcc#", "#ccs#", "#css#", ".###."], k = { "#": O, l: led[0], c: led[1], s: led[2] };
      f.forEach((l, j) => [...l].forEach((q, i) => { if (q !== '.') px(P, lx0 + 4 + i, ly0 + 4 + j, k[q]); }));
      texto(P, 'fb', t, lx0 + 12, ly0 + 10, TINTA);
    }
    if (fontesOk) {
      // as tres linhas no meio do vidro: o titulo, o artista e o BPM
      const ih = iy1 - iy0, y1 = iy0 + Math.max(2, Math.floor((ih - 28) / 2)) + 7;
      recorte(P, ix0 + 3, iy0, ix1 - 3, iy1);
      P.dim = g.dim;
      const let_ = d.titulo.querySelector('.letreiro');
      const tt = !g.com && !d.deck.classList.contains('deck-deixa') ? I18N.t('deck.screen.noDisc')
        : (let_ ? (let_.firstElementChild || let_).textContent : d.titulo.textContent).trim();
      const wt = larg('fb', tt), area = ix1 - 3 - (ix0 + 3), SEP = '  \u2022  ', ws = larg('fb', SEP);
      const BR = cor(251, 239, 217);
      // o letreiro so quando nao cabe: parado 2 s no comeco de cada volta, depois anda 12 celulas por segundo
      d.mqInfo = { tt, per: wt + ws, rola: wt > area };
      if (wt > area) {
        const off = d.mqOff || 0;
        texto(P, 'fb', tt + SEP + tt + SEP, ix0 + 3 + off, y1, BR, { sombra: O });
        // as pontas da janela apagam ate o vidro (a coluna de fora inteira, a de dentro em xadrez): a letra entra e sai por
        // baixo da moldura em vez de aparecer cortada no meio
        const VIDRO = cor(22, 17, 14);
        for (let y = Math.max(iy0 + 1, y1 - 10); y < Math.min(iy1, y1 + 3); y++)
          for (const [x, cheio] of [[ix0 + 3, true], [ix0 + 4, false], [ix1 - 4, true], [ix1 - 5, false]])
            if (cheio || (x + y) % 2) P.u[y * P.W + x] = VIDRO;
      } else texto(P, 'fb', tt, ix0 + 3, y1, BR, { sombra: O });
      // a dica do prato vazio na forma curta que cabe inteira (a prateleira esta logo acima): o texto do app segue no DOM
      const art0 = (d.canal ? d.canal.textContent : '').trim();
      const art = CURTAS.has(art0) ? CURTAS.get(art0) : art0;
      let a2 = art;
      // (#53) com o salvar no fim da linha, o artista para antes dele
      const sv = !!d.salvar && !d.salvar.hidden;
      const maxa = ix1 - 3 - (ix0 + 3) - (sv ? SV_TAM + 3 : 0);
      if (larg('f', a2) > maxa) {
        while (a2.length > 1 && larg('f', a2 + '...') > maxa) a2 = a2.slice(0, -1);
        const esp = a2.lastIndexOf(' ');
        if (!/\s/.test(art[a2.length] || ' ') && esp > a2.length / 2) a2 = a2.slice(0, esp);
        a2 = a2.trimEnd().replace(/[,.;:\-]+$/, '') + '...';
      }
      texto(P, 'f', a2, ix0 + 3, y1 + 10, cor(176, 160, 138), { sombra: O });
      if (sv) salvarNaTela(P, d.salvar, ix1 - 3 - SV_TAM, y1 + 2);
      P.dim = 1;
      if (d.bpm && visivel(d.bpm)) {
        const v = (d.bpm.querySelector('b') || {}).textContent || '', pit = (d.bpm.querySelector('.bpm-pitch') || {}).textContent || '';
        let x = texto(P, 'f', 'BPM', ix0 + 3, y1 + 21, cor(176, 154, 124), { sombra: O });
        x = texto(P, 'f', v.trim(), x + 3, y1 + 21, cor(243, 167, 60), { sombra: O });
        if (pit.trim()) texto(P, 'f', pit.trim(), x + 3, y1 + 21, cor(127, 227, 245), { sombra: O });
      }
      solto(P);
    }
    P.dim = g.dim;
    // os tempos (1 celula mais apertados que a fonte: o CSS aperta igual)
    if (fontesOk) for (const t of d.tempos) {
      if (!visivel(t)) continue;
      const s = t.textContent.trim(), w = larg('ft', s) - 1;
      if (t.style.width !== 2 * w + 'px') { t.style.width = 2 * w + 'px'; t.style.minWidth = 2 * w + 'px'; t.style.flex = 'none'; }
      const R = rel(t, D), x = t.classList.contains('total') ? R.x1 - w : R.x0;
      texto(P, 'ft', s, x, Math.round((R.y0 + R.y1) / 2) + 4, TINTA);
    }
    // a barra de tempo: o trilho rebaixado, o ambar ate o cursor e o pino creme
    if (d.seek && visivel(d.seek)) {
      const R = rel(d.seek, D), cyb = Math.round((R.y0 + R.y1) / 2), x0 = R.x0, x1 = R.x1 + 1;
      const max = parseFloat(d.seek.max) || 0, f = max > 0 ? Math.min(1, Math.max(0, parseFloat(d.seek.value) / max)) : 0;
      const pw = 9, xp = Math.round(x0 + f * (x1 - x0 - pw));
      caixa(P, x0, cyb - 3, x1, cyb + 4, cor(52, 37, 28), cor(24, 16, 12), cor(84, 62, 46), 1);
      for (let x = x0 + 2; x < x1 - 1; x++) px(P, x, cyb + 4, cor(248, 243, 232));
      if (xp + 4 > x0 + 1) { ret(P, x0 + 1, cyb - 1, xp + 4, cyb + 3, AMBAR[1]); ret(P, x0 + 1, cyb - 1, xp + 4, cyb, AMBAR[0]); ret(P, x0 + 1, cyb + 2, xp + 4, cyb + 3, AMBAR[2]); }
      sombraCaixa(P, xp, cyb - 6, xp + pw, cyb + 7, 1, 1);
      caixa(P, xp, cyb - 6, xp + pw, cyb + 7, CREME, CREME_L, CREME_S);
      for (const gx_ of [xp + 3, xp + 5]) ret(P, gx_, cyb - 3, gx_ + 1, cyb + 4, cor(150, 132, 110));
      ret(P, xp + 4, cyb - 3, xp + 5, cyb + 4, CREME_L);
    }
    // os botoes: as teclas de madeira com a face, a lateral de baixo e a sombra; o tocar redondo com o aro ambar em 4 tons
    const deixa = d.deck.classList.contains('deck-deixa');
    const tocando = !deixa && (['playing', 'buffering'].includes(document.body.dataset.status) || document.body.hasAttribute('data-sobre'));
    for (const b of d.botoes) {
      if (!visivel(b)) continue;
      const R = rel(b, D), aperta = !b.disabled && (b.matches(':active') || b.classList.contains('apertado'));
      if (b.classList.contains('tocar-grande')) {
        const cx = (R.x0 + R.x1) / 2, cy = (R.y0 + R.y1) / 2 + (aperta ? 1 : 0), Rr = 18;
        // o aro em rampa que acompanha a curva: 5 faixas pelo angulo com a luz (de cima e da esquerda)
        // (r06) o brilho de 3x3 celulas, 1 celula mais para o canto: o de 4x4 encostava no triangulo do play
        const face = esfera3(cor(243, 236, 222), cor(255, 253, 248), cor(208, 196, 176), Rr - 5, 1.6, 1.6, .55);
        const off = b.disabled;
        disco(P, cx, cy, Rr, (dx, dy2, r) => {
          if (r > Rr - 4) {
            const c_ = -(dx + dy2) / (r * Math.SQRT2);
            if (off) {   // desligado: o latao fosco, sem o ambar aceso
              if (r > Rr - 1 && c_ < -.3) return cor(120, 96, 58);
              if (r <= Rr - 3 && c_ > .62) return cor(232, 216, 182);
              return c_ > .5 ? cor(218, 196, 150) : c_ > -.05 ? cor(200, 176, 128) : c_ > -.55 ? cor(172, 146, 98) : cor(150, 124, 80);
            }
            if (r > Rr - 1 && c_ < -.3) return AMBAR[2];                               // a borda de fora escura embaixo
            if (r <= Rr - 3 && c_ > .62) return cor(255, 238, 178);                    // o filete aceso por dentro, em cima
            return c_ > .5 ? AMBAR[0] : c_ > -.05 ? cor(250, 194, 84) : c_ > -.55 ? AMBAR[1] : cor(214, 140, 42);
          }
          if (r > Rr - 5) return O;
          return face(dx, dy2);
        }, aperta ? [0, 1] : [1, 2]);
        icone(P, tocando ? 'pausar' : 'tocar', cx + (tocando ? 0 : 1), cy, b.disabled ? cor(140, 126, 108) : TINTA, 1);   // apagado, mas legivel (3,4:1 no creme)
      } else {
        const x0 = R.x0, x1 = R.x1, y0 = R.y0 + (aperta ? 2 : 0), y1 = R.y1;
        sombraCaixa(P, x0, y0, x1, y1, 1, 2, 2);   // (r07) 2 celulas embaixo, como o play e as placas; (r06) o corte da sombra no do botao (2): com 1 sobrava um furo de fundo na quina
        const yf = y1;
        caixa(P, x0, y0, x1, yf, cor(124, 62, 33), cor(196, 124, 78), cor(92, 44, 22), 2);
        for (let x = x0 + 4; x < x1 - 4; x++) { px(P, x, y0 + 3, cor(146, 76, 42)); px(P, x, yf - 4, cor(146, 76, 42)); }
        for (let y = y0 + 4; y < yf - 4; y++) { px(P, x0 + 3, y, cor(146, 76, 42)); px(P, x1 - 4, y, cor(146, 76, 42)); }
        const nome = /ant/.test(b.id) ? 'ant' : 'prox';
        icone(P, nome, (x0 + x1) / 2, (y0 + y1) / 2, b.disabled ? cor(200, 156, 126) : cor(247, 235, 214));   // apagado, mas legivel (3,3:1 na face)
      }
    }
    P.dim = 1;
    return P;
  }
  function ang0x(el) { const m = getComputedStyle(el).transform; if (!m || m === 'none') return 0; const v = m.match(/-?[\d.e]+/g).map(Number); return v[4] || 0; }

  // ---- o rotulo: a capa recortada no quadrado do meio, reduzida em 2 passos e, quando a imagem deixa ler (CORS), com a
  // paleta curta (10 cores por k-medias, contraste e saturacao levantados antes)
  function rotulo(d, Dm) {
    const img = d.rotulo && d.rotulo.querySelector('img');
    const src = img && img.complete && img.naturalWidth ? img.currentSrc || img.src : '';
    const chave = src + '|' + Dm + '|' + (d.corsOk ? 1 : 0);
    if (d.labChave === chave) return d.lab;
    if (img && !src) img.addEventListener('load', () => { d.chaveC = ''; }, { once: true });
    const c = document.createElement('canvas'); c.width = Dm; c.height = Dm;
    const x = c.getContext('2d', { willReadFrequently: true });
    if (src) {
      if (d.corsSrc !== src) {                          // a mesma capa com CORS, para poder ler os pixels
        d.corsSrc = src; d.corsOk = null;
        const im = new Image(); im.crossOrigin = 'anonymous';
        im.onload = () => { d.corsImg = im; d.corsOk = true; d.chaveC = ''; d.labChave = ''; };
        im.onerror = () => { d.corsOk = false; };
        im.src = src;
      }
      const fonte = d.corsOk ? d.corsImg : img;
      const iw = fonte.naturalWidth, ih = fonte.naturalHeight, l = Math.min(iw, ih) * .7;
      const t = document.createElement('canvas'); t.width = 4 * Dm; t.height = 4 * Dm;
      const tx = t.getContext('2d'); tx.imageSmoothingQuality = 'high';
      tx.drawImage(fonte, (iw - l) / 2, (ih - l) / 2, l, l, 0, 0, 4 * Dm, 4 * Dm);
      const m = document.createElement('canvas'); m.width = 2 * Dm; m.height = 2 * Dm;
      const mx = m.getContext('2d'); mx.imageSmoothingQuality = 'high'; mx.drawImage(t, 0, 0, 2 * Dm, 2 * Dm);
      x.imageSmoothingQuality = 'high'; x.filter = 'contrast(1.2) saturate(1.3)'; x.drawImage(m, 0, 0, Dm, Dm); x.filter = 'none';
      if (d.corsOk) {
        const im = x.getImageData(0, 0, Dm, Dm), p = im.data, n = Dm * Dm, K = 10;
        const cen = [];
        for (let k = 0; k < K; k++) { const i = Math.floor((k + .5) / K * n) * 4; cen.push([p[i], p[i + 1], p[i + 2]]); }
        const lab = new Uint8Array(n);
        for (let it = 0; it < 8; it++) {
          const s = cen.map(() => [0, 0, 0, 0]);
          for (let i = 0; i < n; i++) {
            let b = 0, bd = 1e9;
            for (let k = 0; k < K; k++) { const dr = p[4 * i] - cen[k][0], dg = p[4 * i + 1] - cen[k][1], db = p[4 * i + 2] - cen[k][2], dd = dr * dr * .3 + dg * dg * .59 + db * db * .11; if (dd < bd) { bd = dd; b = k; } }
            lab[i] = b; s[b][0] += p[4 * i]; s[b][1] += p[4 * i + 1]; s[b][2] += p[4 * i + 2]; s[b][3]++;
          }
          s.forEach((v, k) => { if (v[3]) cen[k] = [v[0] / v[3], v[1] / v[3], v[2] / v[3]]; });
        }
        // a celula sozinha (nenhum vizinho de 4 com a mesma cor) toma a cor que mais aparece em volta
        const lb2 = lab.slice();
        for (let yy = 1; yy < Dm - 1; yy++) for (let xx = 1; xx < Dm - 1; xx++) {
          const i = yy * Dm + xx, v = [];
          for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) if (a || b) v.push(lab[i + a * Dm + b]);
          if (v.filter(q => q === lab[i]).length >= 2) continue;
          const cnt = {}; let best = v[0];
          for (const q of v) { cnt[q] = (cnt[q] || 0) + 1; if (cnt[q] > cnt[best]) best = q; }
          lb2[i] = best;
        }
        lab.set(lb2);
        for (const c_ of cen) for (let q = 0; q < 3; q++) c_[q] = c_[q] * .8 + [198, 186, 166][q] * .2;
        for (let i = 0; i < n; i++) { const k = lab[i]; p[4 * i] = cen[k][0]; p[4 * i + 1] = cen[k][1]; p[4 * i + 2] = cen[k][2]; p[4 * i + 3] = 255; }
        x.putImageData(im, 0, 0);
        c._hi = t; c._pal = cen;
      }
    } else { x.fillStyle = '#5E1C25'; x.fillRect(0, 0, Dm, Dm); }
    d.lab = c; d.labChave = chave;
    return c;
  }

  function quadroRot(lab, k, NQ) {
    const fr = lab._fr || (lab._fr = []);
    if (fr[k]) return fr[k];
    if (lab._hi && lab._pal) {
      const Dm = lab.width, out = document.createElement('canvas'); out.width = out.height = Dm;
      const ox = out.getContext('2d', { willReadFrequently: true });
      ox.imageSmoothingEnabled = true; ox.imageSmoothingQuality = 'high'; ox.filter = 'contrast(1.35) saturate(1.3)';
      ox.translate(Dm / 2, Dm / 2); ox.rotate(k * 2 * Math.PI / NQ); ox.drawImage(lab._hi, -Dm / 2, -Dm / 2, Dm, Dm);
      ox.setTransform(1, 0, 0, 1, 0, 0); ox.filter = 'none';
      const im = ox.getImageData(0, 0, Dm, Dm), p = im.data, n = Dm * Dm, pal = lab._pal, lb = new Uint8Array(n);
      for (let i = 0; i < n; i++) {
        let b = 0, bd = 1e9;
        for (let q = 0; q < pal.length; q++) { const dr = p[4 * i] - pal[q][0], dg = p[4 * i + 1] - pal[q][1], db = p[4 * i + 2] - pal[q][2], dd = dr * dr * .3 + dg * dg * .59 + db * db * .11; if (dd < bd) { bd = dd; b = q; } }
        lb[i] = b;
      }
      const l2 = lb.slice();
      for (let y = 1; y < Dm - 1; y++) for (let x = 1; x < Dm - 1; x++) {
        const i = y * Dm + x, v = [];
        for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) if (a || b) v.push(lb[i + a * Dm + b]);
        if (v.filter(q => q === lb[i]).length >= 2) continue;
        const cnt = {}; let best = v[0];
        for (const q of v) { cnt[q] = (cnt[q] || 0) + 1; if (cnt[q] > cnt[best]) best = q; }
        l2[i] = best;
      }
      const md = [0, 0, 0];
      for (let i = 0; i < n; i++) { const c = pal[l2[i]]; p[4 * i] = c[0]; p[4 * i + 1] = c[1]; p[4 * i + 2] = c[2]; p[4 * i + 3] = 255; md[0] += c[0]; md[1] += c[1]; md[2] += c[2]; }
      const Ri_ = lab._Ri || (Dm - 2) / 2, an = md.map(v => v / n * .6);
      for (let y = 0; y < Dm; y++) for (let x = 0; x < Dm; x++) {
        const r = Math.hypot(x + .5 - Dm / 2, y + .5 - Dm / 2);
        if (r > Ri_ - 1 && r <= Ri_) { const i = y * Dm + x; p[4 * i] = an[0]; p[4 * i + 1] = an[1]; p[4 * i + 2] = an[2]; }
      }
      ox.putImageData(im, 0, 0); fr[k] = out;
      return out;
    }
    const Dm = lab.width, S = 4, B = Dm * S;
    if (!lab._big) {
      const b = document.createElement('canvas'); b.width = b.height = B;
      const bx = b.getContext('2d'); bx.imageSmoothingEnabled = false; bx.drawImage(lab, 0, 0, B, B); lab._big = b;
    }
    const rc = document.createElement('canvas'); rc.width = rc.height = B;
    const rx = rc.getContext('2d', { willReadFrequently: true }); rx.imageSmoothingEnabled = false;
    rx.translate(B / 2, B / 2); rx.rotate(k * 2 * Math.PI / NQ); rx.drawImage(lab._big, -B / 2, -B / 2);
    const s32 = new Uint32Array(rx.getImageData(0, 0, B, B).data.buffer);
    const out = document.createElement('canvas'); out.width = out.height = Dm;
    const ox = out.getContext('2d'), od = ox.createImageData(Dm, Dm), o = new Uint32Array(od.data.buffer);
    for (let y = 0; y < Dm; y++) for (let x = 0; x < Dm; x++) {
      const cnt = new Map(); let best = 0, bn = 0;
      for (let j = 0; j < S; j++) for (let i = 0; i < S; i++) {
        const v = s32[(y * S + j) * B + x * S + i];
        if ((v >>> 24) < 128) continue;
        const n = (cnt.get(v) || 0) + 1; cnt.set(v, n); if (n > bn) { bn = n; best = v; }
      }
      o[y * Dm + x] = bn ? (best | 0xff000000) >>> 0 : 0;
    }
    const o2 = o.slice();
    for (let y = 1; y < Dm - 1; y++) for (let x = 1; x < Dm - 1; x++) {
      const i = y * Dm + x, v = [o[i - 1], o[i + 1], o[i - Dm], o[i + Dm]];
      if (!o[i] || v.includes(o[i])) continue;
      const cnt = new Map(); let best = v[0], bn = 0;
      for (const q of v) { if (!q) continue; const n = (cnt.get(q) || 0) + 1; cnt.set(q, n); if (n > bn) { bn = n; best = q; } }
      if (bn >= 2) o2[i] = best;
    }
    o.set(o2);
    ox.putImageData(od, 0, 0); fr[k] = out;
    return out;
  }

  // ---- o braco no nosso angulo: as pecas por celula; o tubo com 3 celulas por linha (ou coluna): brilho, meio e sombra
  function braco(d, W, H, g, th) {
    const P = d.armP; P.u.fill(0); P.dim = g.dim;
    const { Px, Py, L, cx: pcx, cy: pcy, Rp } = g, dx = -Math.sin(th), dy = Math.cos(th), ex = Math.cos(th), ey = Math.sin(th);
    const vert = Math.abs(dy) >= Math.abs(dx), hl = CAB_HL, rb = 5.5, cw1 = g.Rb + 1, cw0 = cw1 + 11, cwh = 4.5;
    // a cabeca no referencial dela (u atravessado, v ao longo), comecando no fim do tubo e girada para o eixo do prato
    const { H0x, H0y, hdx, hdy } = cabecaDeck(g, th), hex = hdy, hey = -hdx;
    const litS = -(Math.sign(hex + hey) || 1), outS = -(Math.sign((pcx - H0x) * hex + (pcy - H0y) * hey) || 1);
    const HK = { J: cor(34, 30, 30), L: cor(150, 153, 160), M: cor(96, 98, 106), D: cor(60, 62, 68), C: cor(78, 80, 88), E: cor(122, 125, 132),
                 K: cor(40, 42, 48), T: cor(226, 218, 200), U: cor(244, 238, 224) };
    const pontaAcesa = hdx + hdy < 0;
    const parteH = (u, v) => {
      if (v < 0 || v >= hl) return '';
      const ul = u * litS, uo = u * outS;
      if (v >= hl - 8 && v < hl - 6 && uo > 3.5 && uo <= 8.5) return (pontaAcesa ? v < hl - 7 : v >= hl - 7) ? 'U' : 'T';
      if (Math.abs(u) > 3.5) return '';
      if (v < 1) return 'J';
      if (ul > 2.5) return 'L';
      if (v >= hl - 1) return pontaAcesa ? 'L' : 'D';
      if (v < 2 && !pontaAcesa) return 'L';
      if (ul < -2.5) return 'D';
      return 'M';
    };
    const cabeca = (x, y) => {
      const cnt = {}; let best = '', bn = 0, tot = 0;
      for (let j = 0; j < 8; j++) for (let i = 0; i < 8; i++) {
        const ax = x + (i + .5) / 8 - H0x, ay = y + (j + .5) / 8 - H0y;
        const ch = parteH(ax * hex + ay * hey, ax * hdx + ay * hdy);
        if (!ch) continue;
        tot++; cnt[ch] = (cnt[ch] || 0) + 1; if (cnt[ch] > bn) { bn = cnt[ch]; best = ch; }
      }
      return tot >= 32 ? best : '';
    };
    const hc = [], wc = [];
    const WK = { J: O, P: cor(70, 72, 78), X: cor(42, 44, 50), B: cor(176, 179, 186), b: cor(140, 143, 150), L: cor(140, 143, 150),
                 S: cor(56, 58, 64), D: cor(76, 78, 84), M: cor(92, 94, 100) };
    const parteW = (t, s) => {
      const rc = Math.abs(t) > cwh - 1 ? 1 : 0;
      if (s < -cw0 + rc || s > -cw1 || Math.abs(t) > cwh) return '';
      if (s > -cw1 - 1) return 'J';
      if (s < -cw0 + 2 + rc) return 'P';
      if (s < -cw0 + 3 + rc) return 'X';
      if (Math.abs(s + (cw0 + cw1) / 2) < .5) return t < 0 ? 'B' : 'b';
      return t < -cwh + 1.5 ? 'L' : t > cwh - 1.5 ? 'S' : t > cwh - 3 ? 'D' : 'M';
    };
    const peso = (x, y) => {
      const cnt = {}; let best = '', bn = 0, tot = 0;
      for (let j = 0; j < 8; j++) for (let i = 0; i < 8; i++) {
        const ax = x + (i + .5) / 8 - Px, ay = y + (j + .5) / 8 - Py;
        const ch = parteW(ax * ex + ay * ey, ax * dx + ay * dy);
        if (!ch) continue;
        tot++; cnt[ch] = (cnt[ch] || 0) + 1; if (cnt[ch] > bn) { bn = cnt[ch]; best = ch; }
      }
      return tot >= 32 ? best : '';
    };
    const nT = Math.min(4, Math.max(3, Math.round(3.2 / Math.max(Math.abs(dx), Math.abs(dy))))), hT = nT / 2;
    const ext = 22, x0 = Math.max(0, Math.floor(Math.min(Px, Px + dx * L, Px - dx * cw0) - ext)), x1 = Math.min(W - 1, Math.ceil(Math.max(Px, Px + dx * L, Px - dx * cw0) + ext));
    const y0 = Math.max(0, Math.floor(Math.min(Py, Py + dy * L, Py - dy * cw0) - ext)), y1 = Math.min(H - 1, Math.ceil(Math.max(Py, Py + dy * L, Py - dy * cw0) + ext));
    const bw = x1 - x0 + 1, parte = new Uint8Array(bw * (y1 - y0 + 1)), lado = new Int8Array(bw * (y1 - y0 + 1));
    const tubo = (cx, cy, s, sa, sb) => {
      if (s < sa || s > sb) return 0;
      const q = vert ? cx - (Px + (cy - Py) * dx / dy) : cy - (Py + (cx - Px) * dy / dx);
      return q > -hT && q <= hT ? (q <= -hT + 1 ? 1 : q > hT - 1 ? 3 : 2) : 0;
    };
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const cx = x + .5, cy = y + .5, qx = cx - Px, qy = cy - Py, s = qx * dx + qy * dy, t = qx * ex + qy * ey, i = (y - y0) * bw + (x - x0);
      let p = 0, l = 0;
      const tb = tubo(cx, cy, s, -cw1, L - hl);
      if (tb) { p = 4; l = tb; }
      if (s >= -cw0 - 1 && s <= -cw1 + 1 && Math.abs(t) <= cwh + 1) { const ch = peso(x, y); if (ch) { p = 5; wc[i] = ch; } }   // contrapeso
      if (Math.abs(x + .5 - H0x) < 20 && Math.abs(y + .5 - H0y) < 20) { const ch = cabeca(x, y); if (ch) { p = 2; hc[i] = ch; } }   // a cabeca
      if (qx * qx + qy * qy <= rb * rb) p = 1;                                         // bola
      parte[i] = p; lado[i] = l;
    }
    const em = (x, y) => (x < x0 || y < y0 || x > x1 || y > y1) ? 0 : parte[(y - y0) * bw + (x - x0)];
    // a sombra dura (1 a direita, 2 para baixo; 2 e 3 sob a cabeca), escura de verdade em cima do vinil
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      if (em(x, y)) continue;
      if (em(x - 1, y) || em(x + 1, y) || em(x, y - 1) || em(x, y + 1)) continue;
      const cab = em(x - 2, y - 3) === 2 || em(x - 2, y - 3) === 3;
      if (em(x - 1, y - 2) || em(x - 2, y - 2) || cab) {
        const r = Math.hypot(x + .5 - pcx, y + .5 - pcy);
        px(P, x, y, r < g.Rr ? cor(6, 5, 4) : r <= Rp + 1 ? cor(0, 0, 0, 97) : SOMBRA_F);
      }
    }
    const CORES = { 1: [cor(234, 227, 212), cor(255, 251, 242), cor(160, 150, 134)], 2: [cor(150, 154, 162), cor(212, 216, 224), cor(92, 96, 104)],
                    3: [cor(196, 200, 206), cor(246, 248, 250), cor(130, 134, 140)], 4: [cor(226, 218, 200), cor(250, 244, 230), cor(168, 156, 136)],
                    5: [cor(92, 94, 100), cor(140, 143, 150), cor(56, 58, 64)] };
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      const p = em(x, y), i = (y - y0) * bw + (x - x0);
      if (!p) { if (em(x - 1, y) || em(x + 1, y) || em(x, y - 1) || em(x, y + 1)) px(P, x, y, O); continue; }
      const [c, luz, somb] = CORES[p];
      const qx = x + .5 - Px, qy = y + .5 - Py, s = qx * dx + qy * dy, t = qx * ex + qy * ey;
      let v = c;
      if (p === 1) {
        const r = Math.hypot(qx, qy);
        const rr = Math.hypot(qx, qy);
        v = Math.hypot(qx + 2.2, qy + 2.2) < 1.4 ? luz : (rr > rb - 2.2 && (qx + qy) > .3 * rr) || (qx + qy) / rb > 1 ? somb : c;
      } else if (p === 4) v = lado[i] === 1 ? luz : lado[i] === 3 ? somb : c;
      else if (p === 2) {
        v = HK[hc[i]] || c;
      } else if (p === 5) {
        v = WK[wc[i]] || c;
      } else if (p === 3) v = cor(226, 230, 238);
      px(P, x, y, v);
    }
    // a linha escura entre a bola e o resto (a bola se destaca da base e do tubo)
    for (let y = Math.floor(Py - rb - 1); y <= Math.ceil(Py + rb + 1); y++) for (let x = Math.floor(Px - rb - 1); x <= Math.ceil(Px + rb + 1); x++) {
      const r = Math.hypot(x + .5 - Px, y + .5 - Py);
      if (r > rb && r <= rb + 1 && em(x, y) !== 1) px(P, x, y, O);
    }
  }

  function snap(el) {
    const r = rectP(el), v = (el.dataset.dkSnap || '0 0').split(' ').map(Number);
    const bx = r.left - v[0], by = r.top - v[1];
    const nx = Math.round(bx / 2) * 2 - bx, ny = Math.round(by / 2) * 2 - by;
    if (Math.abs(nx - v[0]) > .01 || Math.abs(ny - v[1]) > .01) { el.style.translate = `${nx}px ${ny}px`; el.dataset.dkSnap = nx + ' ' + ny; }
  }

  function desenha(d) {
    const D = rectP(d.deck), tR = rectP(d.tampo);
    if (!D.width || !tR.width) return;
    const W = Math.ceil(D.width / 2), H = Math.floor(D.height / 2), uc = tR.width / 200;   // a altura impar (405) desce: o vao ate a pedaleira fica 12
    const tx0 = (tR.left - D.left) / 2, ty0 = (tR.top - D.top) / 2;
    const com = d.prato.classList.contains('com-disco');
    const dim = 1;   // o deck da deixa com a cor cheia (decisao do dono): o estado vai na etiqueta de cima da tela
    const lt = getComputedStyle(d.letra, '::before').content.replace(/["']/g, '');
    const fx = rel(d.faixa, D), cmd = d.deck.querySelector('.comandos'), cmdY1 = cmd ? rel(cmd, D).y1 : H - 30;
    const chaveE = [W, H, Math.round(tx0), Math.round(ty0), Math.round(uc * 100), com, dim, lt, fx.x0, fx.x1, cmdY1, fontesOk].join('|');
    if (chaveE !== d.chaveE) {
      d.cv.width = W; d.cv.height = H; d.cv.style.width = 2 * W + 'px'; d.cv.style.height = 2 * H + 'px';
      // a sombra dura de 2 celulas a direita e embaixo, a mesma do visor, do mixer e das pedaleiras, num canvas por baixo
      // do desenho (os toca-discos eram as unicas pecas sem ela, r03)
      if (!d.sv) {
        d.sv = document.createElement('canvas'); d.sv.className = 'dk-sombra'; d.sv.setAttribute('aria-hidden', 'true');
        d.cv.before(d.sv);
      }
      const PS = pincel(W + 2, H + 2);
      sombraCaixa(PS, 0, 0, W, H, 2, 2, 4);
      d.sv.width = W + 2; d.sv.height = H + 2; d.sv.style.width = 2 * (W + 2) + 'px'; d.sv.style.height = 2 * (H + 2) + 'px';
      d.sv.style.left = d.cv.style.left; d.sv.style.top = d.cv.style.top;
      const imS = d.sv.getContext('2d').createImageData(W + 2, H + 2);
      new Uint32Array(imS.data.buffer).set(PS.u);
      d.sv.getContext('2d').putImageData(imS, 0, 0);
      const Rp = 38.25 * uc + 2, Rr = Rp - 9, Rl = Rr * .40;
      d.g = { cx: Math.round(tx0 + 40 * uc + 6), cy: Math.round(ty0 + 40 * uc), Rp, Rr, Rf: Rp * .935, Rl, Ri: Rl - 2, Re: Math.max(1.6, 1.1 * uc), com, dim,
              Px: Math.round(tx0 + 88 * uc + 5) + .5, Py: Math.round(ty0 + 12 * uc) + .5, L: 62.8 * uc, Rb: Math.round(7.1 * uc) - .5, Rm: 4.1 * uc, Dy: ty0 + 58 * uc, faixa: fx, cmdY1 };
      d.letraTxt = lt;
      d.est = estatico(d, W, H, D, d.g);
      d.base = document.createElement('canvas'); d.base.width = W; d.base.height = H;
      d.bctx = d.base.getContext('2d'); d.bimg = d.bctx.createImageData(W, H); d.bU = new Uint32Array(d.bimg.data.buffer);
      d.arm = document.createElement('canvas'); d.arm.width = W; d.arm.height = H;
      d.actx = d.arm.getContext('2d'); d.aimg = d.actx.createImageData(W, H);
      d.armP = pincel(W, H, new Uint32Array(d.aimg.data.buffer));
      d.chaveE = chaveE; d.chaveC = ''; d.th = NaN; d.rot = NaN;
      // o nosso angulo para cada raio do sulco: pelo ponto no eixo do tubo (o de antes do #50) e pela ponta da cabeca
      const gg = d.g, eixo = th => Math.hypot(gg.Px - gg.L * Math.sin(th) - gg.cx, gg.Py + gg.L * Math.cos(th) - gg.cy);
      const ponta = th => { const c = cabecaDeck(gg, th); return Math.hypot(c.H0x + CAB_HL * c.hdx - gg.cx, c.H0y + CAB_HL * c.hdy - gg.cy); };
      const resolve = dc => {
        let tmin = 0, dmin = 1e9;
        for (let k = 0; k <= 160; k++) { const t = k / 160 * 1.6; const v = dc(t); if (v < dmin) { dmin = v; tmin = t; } }
        return rho => { let a = 0, b = tmin; for (let i = 0; i < 40; i++) { const m = (a + b) / 2; if (dc(m) > rho) a = m; else b = m; } return (a + b) / 2; };
      };
      gg.solve = resolve(eixo);
      gg.thEdge = gg.solve(gg.Rr - 3);
      gg.thIni = resolve(ponta)(BRACO_INICIO * (gg.Rr - 3));   // (#50) a ponta da nossa cabeca na borda: o comeco da faixa
    }
    // os controles mudam com o texto, o estado, o lugar e o letreiro
    // o letreiro proprio: parado 2 s, depois 12 celulas por segundo, volta inteira
    const mi = d.mqInfo;
    if (mi && mi.rola) {
      if (d.mqTt !== mi.tt) { d.mqTt = mi.tt; d.mqT0 = performance.now(); }
      const vel = 12, ciclo = 2 + mi.per / vel, t = ((performance.now() - d.mqT0) / 1000) % ciclo;
      d.mqOff = t < 2 ? 0 : -Math.floor((t - 2) * vel) % mi.per;
    } else d.mqOff = 0;
    const sig = [d.titulo.textContent, d.mqOff, d.canal ? d.canal.textContent : '',
                 d.salvar ? d.salvar.hidden + d.salvar.className + d.salvar.style.getPropertyValue('--pr') : '',
                 d.bpm ? d.bpm.textContent : '', d.luz ? d.luz.textContent + d.lamp.className + ((Date.now() / 450 | 0) % 2) : '',
                 d.tempos.map(t => t.textContent).join(), d.seek ? d.seek.value + '/' + d.seek.max + d.seek.disabled : '',
                 d.botoes.map(b => b.disabled + '' + b.matches(':active') + b.className + visivel(b)).join(), document.body.dataset.status,
                 document.body.hasAttribute('data-sobre'), fontesOk,
                 [d.titulo, d.bpm, d.luz, d.seek, ...d.tempos, ...d.botoes].map(e => e && visivel(e) ? Object.values(rel(e, D)).slice(0, 4).join(',') : '').join(';')].join('|');
    let mudouC = false;
    if (sig !== d.chaveC) { d.ctl = controles(d, W, H, D, d.g, d.est); d.chaveC = sig; mudouC = true; }
    const rot = ang(d.gira), thP = ang(d.braco), gg = d.g;
    const antes = t => t >= borda() ? gg.solve(Math.min(1, fPagina(t)) * (gg.Rr - 3)) : t * (gg.thEdge / borda());
    // (#50) do descanso ao comeco da faixa, em proporcao; na faixa, o de antes mais a diferenca do comeco, que vai a zero
    // com ela (p, o quanto da faixa ja tocou, pela ponta da cabeca da pagina)
    const thP0 = BRACO_INICIO_ANG * Math.PI / 180;
    let th;
    if (thP <= thP0) th = thP * (gg.thIni / thP0);
    else {
      const p = Math.min(1, (BRACO_INICIO - pontaNoDisco(thP)) / (BRACO_INICIO - BRACO_FIM));
      th = antes(thP) + (1 - p) * (gg.thIni - antes(thP0));
    }
    const novoRot = Math.abs(rot - d.rot) > 1e-4, novoTh = Math.abs(th - d.th) > 1e-4;
    if (!mudouC && !novoRot && !novoTh) return;
    const Rl = gg.Ri, Dm = Math.ceil(2 * Rl) + 2, lab = gg.com ? rotulo(d, Dm) : null;
    if (lab) lab._Ri = Rl;
    if (mudouC || novoRot) {
      d.bU.set(d.ctl.u);
      d.bctx.putImageData(d.bimg, 0, 0);
    }
    if (novoTh || mudouC) { braco(d, W, H, gg, th); d.actx.putImageData(d.aimg, 0, 0); }
    const c = d.ctx;
    c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, W, H); c.imageSmoothingEnabled = false;
    if (lab) {
      const NQ = 64, kq = ((Math.round(rot / (2 * Math.PI / NQ)) % NQ) + NQ) % NQ;
      if (d.corsOk) c.drawImage(quadroRot(lab, kq, NQ), Math.round(gg.cx - Dm / 2), Math.round(gg.cy - Dm / 2));
      else { c.translate(gg.cx, gg.cy); c.rotate(rot); c.drawImage(lab, -Dm / 2, -Dm / 2); c.setTransform(1, 0, 0, 1, 0, 0); }
      if (gg.dim !== 1) { c.fillStyle = `rgba(0,0,0,${1 - gg.dim})`; c.fillRect(Math.floor(gg.cx - Dm / 2), Math.floor(gg.cy - Dm / 2), Dm + 1, Dm + 1); }
    }
    c.drawImage(d.base, 0, 0);
    c.drawImage(d.arm, 0, 0);
    d.rot = rot; d.th = th;
  }

  function quadro() {
    if (document.body.classList.contains('mesa-dj')) {
      for (const deck of document.querySelectorAll('.palco .deck')) {
        if (deck.hidden || !deck.offsetParent) continue;
        const d = prepara(deck);
        snap(deck);
        try { desenha(d); } catch (e) { console.error('dk2', e); }
      }
    }
    requestAnimationFrame(quadro);
  }
  // (#119) o canvas devolvido em branco (repintarCanvas): a chave do desenho parado (o chaveE, que tambem pinta a
  // sombra e refaz a base e o braco fora da tela) e a do rotulo zeradas, o proximo quadro pinta o deck inteiro
  document.addEventListener('repinta-canvas', () => {
    for (const d of decks.values()) { d.chaveE = ''; d.labChave = ''; }
  });
  fontesProntas.then(() => { fontesOk = true; document.dispatchEvent(new Event('px-letra')); });
  const liga = () => requestAnimationFrame(quadro);
  document.addEventListener('DOMContentLoaded', liga);
})();
/* DECK-JS-FIM */
