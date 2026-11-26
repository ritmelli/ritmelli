/* MIX-JS-INICIO */
/* o mixer da mesa inteiro em pixel art (1 celula = 2 px), num canvas por cima do receptor: o painel
   de metal escovado com os parafusos, os tres VUs (a janela ambar, o arco, os numeros e a agulha do medidor da
   pagina), os volumes em pe com as marcas e o pino creme, as chaves do set, o crossfader e a placa da transicao
   automatica. Os elementos de verdade seguem ali, transparentes: o clique, o estado e o lugar vem deles. */
import { glyphs, ruido, fontesProntas, cor, O, O2, SOMBRA, SOMBRA_F, TINTA, CREME_L, F57, ACENTO, pincel, px, recorte, solto, caixa, sombraCaixa, stamp } from "pixel.js";
(() => {
  const { gl, larg, texto } = glyphs();
  const AMBAR = [cor(255, 214, 110), cor(252, 186, 72), cor(224, 148, 46)];   // (r06) a canaleta do crossfader no ambar dos volumes (a de baixo lia marrom)


  // ================= o mixer: painel de metal escovado com os VUs, os volumes em pe, as chaves do set, o crossfader e a
  // placa da transicao automatica
  const F35 = {
    A: [".#.", "#.#", "###", "#.#", "#.#"], B: ["##.", "#.#", "##.", "#.#", "##."], C: [".##", "#..", "#..", "#..", ".##"],
    D: ["##.", "#.#", "#.#", "#.#", "##."], E: ["###", "#..", "##.", "#..", "###"], F: ["###", "#..", "##.", "#..", "#.."],
    G: [".##", "#..", "#.#", "#.#", ".##"], H: ["#.#", "#.#", "###", "#.#", "#.#"], I: ["###", ".#.", ".#.", ".#.", "###"],
    J: ["..#", "..#", "..#", "#.#", ".#."], K: ["#.#", "#.#", "##.", "#.#", "#.#"], L: ["#..", "#..", "#..", "#..", "###"],
    M: ["#...#", "##.##", "#.#.#", "#...#", "#...#"], N: ["#..#", "##.#", "#.##", "#..#", "#..#"], O: [".#.", "#.#", "#.#", "#.#", ".#."],
    P: ["##.", "#.#", "##.", "#..", "#.."], Q: [".#.", "#.#", "#.#", "##.", ".##"], R: ["##.", "#.#", "##.", "#.#", "#.#"],
    S: [".##", "#..", ".#.", "..#", "##."], T: ["###", ".#.", ".#.", ".#.", ".#."], U: ["#.#", "#.#", "#.#", "#.#", "###"],
    V: ["#...#", "#...#", ".#.#.", ".#.#.", "..#.."], W: ["#...#", "#...#", "#.#.#", "##.##", "#...#"], X: ["#.#", "#.#", ".#.", "#.#", "#.#"],
    Y: ["#.#", "#.#", ".#.", ".#.", ".#."], Z: ["###", "..#", ".#.", "#..", "###"],
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#.", "##.", ".#.", ".#.", "###"], "2": ["##.", "..#", ".#.", "#..", "###"],
    "3": ["##.", "..#", ".#.", "..#", "##."], "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "##.", "..#", "##."],
    "6": [".##", "#..", "###", "#.#", "###"], "7": ["###", "..#", ".#.", ".#.", ".#."], "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "##."], "-": ["..", "..", "##", "..", ".."], "%": ["#.#", "..#", ".#.", "#..", "#.#"], " ": ["..", "..", "..", "..", ".."],
  };
  // as marcas dos acentos em 2 linhas, com 1 de folga acima da letra
  const ACE35 = { "Á": ["A", "..#", ".#."], "Ó": ["O", "..#", ".#."], "Í": ["I", "..#", ".#."], "É": ["E", "..#", ".#."], "Ú": ["U", "..#", ".#."],
                  "Ã": ["A", ".#.#", "#.#."], "Õ": ["O", ".#.#", "#.#."], "Â": ["A", ".#.", "#.#"], "Ê": ["E", ".#.", "#.#"], "Ô": ["O", ".#.", "#.#"] };
  const g35 = ch => { const a = ACE35[ch], b = a ? a[0] : ch === 'Ç' ? 'C' : ch, rows = F35[b] || F35[' ']; return { w: rows[0].length, rows, mark: a ? a.slice(1) : null, ced: ch === 'Ç' }; };
  const larg35 = s => [...s.toUpperCase()].reduce((t, ch, i) => t + g35(ch).w + (i ? 1 : 0), 0);
  function texto35(P, s, x, y, c) {   // y = a linha de cima das maiusculas
    for (const ch of s.toUpperCase()) {
      const g = g35(ch);
      g.rows.forEach((l, j) => [...l].forEach((q, i) => { if (q === '#') px(P, x + i, y + j, c); }));
      if (g.mark) { const o = Math.floor((g.mark[0].length - g.w) / 2); g.mark.forEach((l, j) => [...l].forEach((q, i) => { if (q === '#') px(P, x + i - o, y - 3 + j, c); })); }
      if (g.ced) { px(P, x + 1, y + 5, c); px(P, x, y + 6, c); }
      x += g.w + 1;
    }
    return x;
  }
  const ICM = {
    aleatorio: ["........#..", ".........#.", "###...#####", "...#.#...#.", "....#......", "...#.#...#.", "###...#####", ".........#.", "........#.."],
    repetir: [".......#...", ".########..", "#......#...", "#.........#", "...#......#", "..########.", "...#......."],
    parecidas: [".###...###.", "#...#.#...#", "#....#....#", "#...#.#...#", ".###...###."],
  };
  const iconeM = (P, nome, cx, cy, c) => stamp(P, ICM[nome], cx, cy, c);

  const MET = { a: cor(207, 203, 195), b: cor(211, 207, 199), c: cor(215, 211, 203), luz2: cor(224, 221, 214), luz: cor(246, 244, 239), somb: cor(160, 154, 146), somb2: cor(186, 181, 172), sulco: cor(110, 104, 96) };
  const VUC = { face: cor(252, 186, 72), faceS: cor(224, 148, 46), tinta: cor(36, 22, 14), zona: cor(222, 44, 28), banda: cor(60, 32, 20),
                bandaL: cor(124, 82, 56), bandaS: cor(38, 18, 10), nome: cor(246, 230, 200), nomeOff: cor(242, 115, 94), escala: cor(60, 32, 20), agulha: cor(26, 11, 4), faceL: cor(255, 200, 98), faceE: cor(232, 168, 60), faceB: cor(255, 212, 124), arco: cor(110, 62, 28), zonaE: cor(176, 28, 18), zonaB: cor(150, 22, 14) };
  const TINTA_M = cor(52, 40, 34), CINZA_M = cor(78, 68, 60);
  const parafusoM = (P, x, y) => {
    const f = [".###.", "#hhx#", "#hxm#", "#xmd#", ".###."];
    const k = { "#": cor(52, 40, 34), h: cor(250, 248, 242), m: cor(204, 200, 192), s: cor(156, 150, 142), d: cor(120, 112, 104), x: cor(96, 90, 84) };
    f.forEach((l, j) => [...l].forEach((q, i) => { if (q !== '.') px(P, x + i, y + j, k[q]); }));
    f.forEach((l, j) => [...l].forEach((q, i) => {
      if (q === '.') return;
      const l2 = f[j + 1], q2 = l2 ? l2[i + 1] : undefined;
      if ((!q2 || q2 === '.') && !(i === f[0].length - 2 && j === f.length - 2)) px(P, x + i + 1, y + j + 1, SOMBRA_F);
    }));
  };
  // o segmento de um raio no angulo a (graus, 0 = em pe), as celulas a ate meia do eixo
  function raio(P, pcx, pcy, a, r0, r1, meia, c) {
    const t = a * Math.PI / 180, dx = Math.sin(t), dy = -Math.cos(t);
    const xs = [pcx + dx * r0, pcx + dx * r1], ys = [pcy + dy * r0, pcy + dy * r1];
    for (let y = Math.floor(Math.min(...ys) - 1); y <= Math.ceil(Math.max(...ys) + 1); y++)
      for (let x = Math.floor(Math.min(...xs) - 1); x <= Math.ceil(Math.max(...xs) + 1); x++) {
        const cx = x + .5 - pcx, cy = y + .5 - pcy, ao = cx * dx + cy * dy;
        if (ao >= r0 && ao <= r1 && Math.abs(cx * dy - cy * dx) <= meia) px(P, x, y, c);
      }
  }
  const ESC = [[-50, -34.1], [-45, -34.1], [-40, -34.1], [-30, -13.3], [-20, 0], [-15, 13.3], [-10, 34.1], [-7, 36.5], [-5, 39.6], [-3, 43], [0, 50]];   // (r15) o 40 e o 10 1 celula para fora (a escala com sinal de menos pedia vao entre os grupos)
  const escAng = db => {
    if (db <= ESC[0][0]) return ESC[0][1];
    for (let i = 1; i < ESC.length; i++) if (db <= ESC[i][0]) { const [a, b] = [ESC[i - 1], ESC[i]]; return a[1] + (b[1] - a[1]) * (db - a[0]) / (b[0] - a[0]); }
    return ESC[ESC.length - 1][1];
  };
  const angDb = a => -50 + 50 * Math.pow(Math.min(1, Math.max(0, (a + 50) / 100)), 1 / 1.6);
  // as celulas de um caminho amostrado, sem as quinas dobradas (o pixel perfeito)
  function caminho(pts) {
    const c = [];
    for (const [x, y] of pts) { const q = [Math.floor(x), Math.floor(y)]; const u = c[c.length - 1]; if (!u || u[0] !== q[0] || u[1] !== q[1]) c.push(q); }
    const o = [];
    for (let i = 0; i < c.length; i++) {
      const a = o[o.length - 1], b = c[i + 1], p = c[i];
      if (a && b && Math.abs(a[0] - b[0]) === 1 && Math.abs(a[1] - b[1]) === 1 && (p[0] === a[0] || p[1] === a[1])) continue;
      o.push(p);
    }
    return o;
  }
  const ponto = (g, a, r) => [g.pcx + r * Math.sin(a * Math.PI / 180), g.pcy - r * Math.cos(a * Math.PI / 180)];
  const arcoC = (g, a0, a1, r) => { const p = []; for (let a = a0; a <= a1 + 1e-9; a += .1) p.push(ponto(g, a, r)); return caminho(p); };
  const raioC = (g, a, r0, r1) => { const p = []; for (let r = r0; r <= r1 + 1e-9; r += .1) p.push(ponto(g, a, r)); return caminho(p); };
  const NOMEV = {
    V: ["##.##", "##.##", "##.##", "##.##", ".###.", "..#.."], O: [".###.", "##.##", "##.##", "##.##", "##.##", ".###."],
    Z: ["#####", "...##", "..##.", ".##..", "##...", "#####"], D: ["####.", "##.##", "##.##", "##.##", "##.##", "####."],
    I: ["##", "##", "##", "##", "##", "##"], S: [".####", "##...", ".###.", "...##", "...##", "####."],
    C: [".####", "##...", "##...", "##...", "##...", ".####"], J: ["...##", "...##", "...##", "...##", "##.##", ".###."],
    G: [".####", "##...", "##.##", "##.##", "##.##", ".####"],
    // as do ingles (VOICE, MUSIC, GAME); a letra que nao esta aqui some do nome, e o dev/testa_i18n.py confere as duas linguas
    E: ["#####", "##...", "####.", "##...", "##...", "#####"], R: ["####.", "##.##", "##.##", "####.", "##.##", "##.##"],
    A: [".###.", "##.##", "##.##", "#####", "##.##", "##.##"], M: ["##...##", "###.###", "#######", "##.#.##", "##...##", "##...##"],
    U: ["##.##", "##.##", "##.##", "##.##", "##.##", ".###."],
  };
  const ARCOS = { 9: [1, 1, 1, 1, 1, 1, 1], 10: [2, 1, 1, 1, 1, 1, 1], 11: [2, 2, 1, 1, 1, 1, 1], 12: [2, 2, 2, 1, 1, 1, 1],
                  13: [2, 2, 2, 2, 1, 1, 1], 14: [3, 2, 2, 2, 1, 1, 1], 15: [3, 3, 2, 2, 1, 1, 1] };
  function vuFace(P, x0, y0, x1, y1, nome, apagado) {
    sombraCaixa(P, x0, y0, x1, y1, 1, 1, 2);
    caixa(P, x0, y0, x1, y1, VUC.banda, VUC.bandaL, VUC.bandaS, 2);
    const fx0 = x0 + 2, fx1 = x1 - 2, fy0 = y0 + 2, fy1 = y0 + 22, FW = fx1 - fx0, cx = Math.floor(FW / 2), top = 11, PY = 31.1;   // (r15) a escala 1 celula abaixo: o -20 colava no reflexo do topo
    const h = Math.max(9, Math.min(15, FW - 3 - cx)), ARCO = ARCOS[h], sx = h / 15;
    const g = { fx0, fx1, fy0, fy1, cx, acx: fx0 + cx + .5, acy: fy0 + PY, ar: 19.6, sx, hx: fx0 + cx + .5, hy: fy0 + 18.5 };
    if (apagado) P.dim = .55;
    for (let y = fy0; y < fy1; y++) for (let x = fx0; x < fx1; x++) {
      const ex = Math.min(x - fx0, fx1 - 1 - x), ey = Math.min(y - fy0, fy1 - 1 - y);
      if (ex + ey < 1) continue;
      px(P, x, y, (y === fy0 || x === fx0) ? VUC.faceS : (y === fy1 - 1 || x === fx1 - 1) ? VUC.faceB : y <= fy0 + 1 ? VUC.faceL : VUC.face);   // (r07) o reflexo com 1 fileira: o 20 da escala entrava na 2a
    }
    const ay = {};
    for (let x = cx - 2; x <= cx + 2; x++) ay[x] = top;
    let l = cx - 2, r = cx + 2;
    ARCO.forEach((n, i) => { for (let k = 0; k < n; k++) { ay[l - 1 - k] = top + 1 + i; ay[r + 1 + k] = top + 1 + i; } l -= n; r += n; });
    const z0 = r - 4;
    for (const x in ay) px(P, fx0 + +x, fy0 + ay[x], +x < z0 ? VUC.arco : VUC.zona);
    g.arcoCel = new Set(Object.keys(ay).map(x => (fx0 + +x) + ',' + (fy0 + ay[x])));   // (r19) a agulha para 1 celula antes dele
    for (let x = z0; x < r; x++) px(P, fx0 + x, fy0 + ay[x] + 1, VUC.zonaE);
    const pk = ay[r] - 4, rk = r + 1;   // (r15) a lampada de pico 1 celula a direita e 1 abaixo: colada no 0 do -10 lia como -10 com ponto
    px(P, fx0 + rk, fy0 + pk, cor(255, 150, 120)); px(P, fx0 + rk + 1, fy0 + pk, VUC.zona); px(P, fx0 + rk, fy0 + pk + 1, VUC.zona); px(P, fx0 + rk + 1, fy0 + pk + 1, VUC.zonaE);
    const marca = (x, n, c, txt) => {
      const y = ay[x], dx = x - cx, dy = y + .5 - PY, d = Math.hypot(dx, dy), ux = dx / d, uy = dy / d;
      let tx = x, ty = y;
      for (let k = 1; k <= n; k++) { tx = k === 1 ? x : x + (Math.abs(ux) > .3 ? Math.sign(ux) : 0); ty = y - k; px(P, fx0 + tx, fy0 + ty, c); }
      // (r13) o sinal de menos da escala em dB (o numero fica no lugar, o traco de 2 celulas 1 celula antes dele)
      if (txt) { const tw = larg35(txt), nx = fx0 + Math.round(tx + .5 - tw / 2); texto35(P, txt, nx, fy0 + ty - 6, VUC.escala); px(P, nx - 3, fy0 + ty - 4, VUC.escala); px(P, nx - 2, fy0 + ty - 4, VUC.escala); }
    };
    const tres = Math.round(10 * sx) >= 8, off = Math.round(10 * sx) + (tres ? 1 : 0);   // (r15) 2 celulas entre os grupos -40 -20 -10, 1 dentro de cada
    marca(cx - off, 2, VUC.arco, '40'); marca(cx, 2, VUC.arco, tres ? '20' : ''); marca(cx + off, 2, VUC.arco, '10');
    if (tres) for (const x of [cx - 4, cx + 4]) px(P, fx0 + x, fy0 + ay[x] - 1, VUC.arco);   // (r16) as marcas sem numero com 1 celula (eram 2, mais altas que as do -40 e do -10)
    P.dim = 1;
    const nm = nome.toUpperCase(), gl_ = [...nm].map(ch => NOMEV[ch]).filter(Boolean);
    const tw = gl_.reduce((a, q) => a + q[0].length + 1, -1);
    let nx = Math.round((x0 + x1 - tw) / 2);
    const ny = fy1 + Math.ceil((y1 - 2 - fy1 - 6) / 2);
    for (const q of gl_) { q.forEach((l_, j) => [...l_].forEach((c, i) => { if (c === '#') px(P, nx + i, ny + j, apagado ? VUC.nomeOff : VUC.nome); })); nx += q[0].length + 1; }
    return g;
  }
  function vuAgulha(P, g, aPag, apagado) {
    recorte(P, g.fx0, g.fy0 + 1, g.fx1, g.fy1);
    if (apagado) P.dim = .55;
    const db = angDb(aPag), alvo = d_ => { const t = escAng(d_) * Math.PI / 180; return [g.acx + g.sx * g.ar * Math.sin(t), g.acy - g.ar * Math.cos(t)]; };
    let [tx, ty] = alvo(Math.max(-40, db)), vx = tx - g.hx, vy = ty - g.hy, L = Math.hypot(vx, vy) + 1.2;
    let a = Math.atan2(vx, -vy);
    // parada: deitada em degraus de 2 e 3 (1 para 2,5), logo alem do 40
    if (db < -41) { a = -Math.atan(2.5); L -= 1.5; }
    const pts = [];
    for (let q = 0; q <= L + 1e-9; q += .1) pts.push([g.hx + q * Math.sin(a), g.hy - q * Math.cos(a)]);
    // (r20) a ponta cruza o arco em 1 celula, como no mock (parada antes dele a agulha virava toco); so em repouso, deitada
    // quase tangente ao arco perto do -40, ela para 1 celula antes (r19: ali a ponta pousava no arco e fazia um no)
    const cel = caminho(pts), perto = ([x, y]) => g.arcoCel && [-1, 0, 1].some(dx => [-1, 0, 1].some(dy => g.arcoCel.has((x + dx) + ',' + (y + dy))));
    while (db < -41 && cel.length > 2 && perto(cel[cel.length - 1])) cel.pop();
    for (const [x, y] of cel) px(P, x, y, VUC.agulha);
    // o pivo: a cupula de 7, 5 e 3 na cor da faixa, o brilho de 1 em cima a esquerda
    const bx = g.fx0 + g.cx, by = g.fy1 - 1;
    for (let k = 0; k < 2; k++) for (let x = bx - 2 + k; x <= bx + 2 - k; x++) px(P, x, by - k, x === bx - 2 + k ? VUC.bandaL : VUC.banda);
    P.dim = 1;
    solto(P);
  }

  // ---- um volume em pe: o rotulo em cima, as marcas dos dois lados, a canaleta escura com o ambar subindo do pe, o pino
  // creme com o sulco no meio e o valor embaixo
  function faderEst(P, F) {
    const { cx, sy0 } = F, sy1 = F.sy1 - 1;   // (r26) o trilho 1 celula mais curto embaixo: o curso de 75 celulas, o da regua de 16 tracos (era 76 e o 0% caia 1 celula abaixo do ultimo)
    const curso = sy1 - sy0 - 11, nk = Math.max(2, Math.floor(curso / 5) + 1), k0 = sy0 + 5 + Math.floor((curso - (nk - 1) * 5) / 2);
    for (let k = 0; k < nk; k++) {
      const y = k0 + 5 * k;
      for (const [a, b] of [[cx - 16, cx - 11], [cx + 12, cx + 17]]) for (let x = a; x < b; x++) { px(P, x, y, cor(80, 74, 68)); px(P, x, y + 1, cor(226, 223, 216)); }
    }
    // a canaleta: contorno de 1 com as pontas arredondadas, 3 de miolo (a parede da esquerda na sombra)
    for (let y = sy0; y < sy1; y++) for (let x = cx - 2; x <= cx + 2; x++) {
      const ey = Math.min(y - sy0, sy1 - 1 - y), ex = Math.min(x - (cx - 2), cx + 2 - x);
      if (ex + ey < 1) continue;
      px(P, x, y, ex === 0 || ey === 0 ? O : x === cx - 1 ? cor(40, 28, 22) : x === cx ? cor(48, 34, 26) : cor(58, 42, 34));
    }
  }
  // um tom so, sem degrade (o app nao tem degrade em lugar nenhum; ordem dele, 06/11)
  const SOMBRA_A = cor(30, 12, 4, 110);   // a das outras sombras do painel (185 lia como base preta embaixo do pino)
  function sombraAlta(P, x0, y0, x1, y1) {
    for (let y = y0 + 2; y < y1; y++) px(P, x1, y, SOMBRA_A);
    px(P, x1 - 1, y1 - 1, SOMBRA_A);
    for (let d = 0; d < 3; d++) { const ins = d === 2 ? 1 : 0; for (let x = x0 + 1 + ins; x <= x1 - ins; x++) px(P, x, y1 + d, SOMBRA_A); }
  }
  function faderDin(P, F, f, valor, apag, foco) {
    const { cx, sy0, L } = F, sy1 = F.sy1 - 1;   // (r26) o fim do trilho encurtado (faderEst); o % fica onde estava (F.sy1 + 3)
    const yc = Math.round(sy0 + 5 + (1 - f) * (sy1 - sy0 - 11));
    if (apag) P.dim = .7;
    for (let y = yc + 6; y < sy1 - 1; y++) {
      px(P, cx - 1, y, apag ? cor(176, 166, 152) : cor(255, 214, 110)); px(P, cx, y, apag ? cor(160, 150, 136) : cor(252, 186, 72)); px(P, cx + 1, y, apag ? cor(140, 130, 118) : cor(224, 148, 46));
    }
    const x0 = cx - 9, x1 = cx + 10, y0 = yc - 5, y1 = yc + 6;
    sombraAlta(P, x0, y0, x1, y1);
    caixa(P, x0, y0, x1, y1, cor(240, 233, 220), cor(252, 249, 242), cor(188, 178, 162), 1);
    for (let x = x0 + 3; x < x1 - 3; x++) for (const gy of [y0 + 2, yc]) { px(P, x, gy, cor(184, 172, 154)); px(P, x, gy + 1, cor(252, 249, 242)); }
    for (let x = x0 + 1; x < x1 - 2; x++) { px(P, x, y0 + 7, cor(248, 238, 220)); px(P, x, y0 + 8, cor(214, 198, 172)); px(P, x, y0 + 9, cor(184, 166, 140)); }
    px(P, x1 - 2, y0 + 7, cor(188, 178, 162)); px(P, x1 - 2, y0 + 8, cor(172, 162, 144)); px(P, x1 - 2, y0 + 9, cor(156, 146, 127));
    if (foco) for (let x = x0 - 1; x <= x1; x++) for (let y = y0 - 1; y <= y1; y++) if (x === x0 - 1 || x === x1 || y === y0 - 1 || y === y1) px(P, x, y, cor(143, 74, 12));
    P.dim = 1;
    texto35(P, valor, Math.round(F.col + .5 - larg35(valor) / 2), F.sy1 + 3, CINZA_M);   // (r17) 1 celula acima: com os faders descidos o % ficava mais perto do sulco que do trilho
  }

  // ---- as chaves do set: teclas de madeira com o icone creme (ambar ligadas), a luz no canto e o nome miudo embaixo
  function tecla(P, T, nome, rotulo, liga, aperta, luz, foco) {
    const tcx = T.col, kx0 = tcx - 12, kx1 = tcx + 13, ky0 = T.y0 + (aperta ? 1 : 0), ky1 = T.y0 + 14;
    sombraCaixa(P, kx0, ky0, kx1, ky1, 1, 1, 2);
    caixa(P, kx0, ky0, kx1, ky1, cor(106, 70, 50), cor(166, 122, 92), cor(78, 50, 34), 2);
    const veio = cor(90, 56, 38);
    for (const [a, b, y] of [[2, 6, 3], [15, 21, 10]]) for (let x = kx0 + a; x < kx0 + b; x++) px(P, x, ky0 + y, veio);
    iconeM(P, nome, kx0 + 9.5, (ky0 + ky1) / 2, liga ? cor(255, 206, 96) : cor(247, 235, 214));
    if (luz) led(P, kx1 - 7, ky0 + 3, cor(255, 240, 200), cor(255, 170, 60), cor(232, 140, 40), cor(40, 20, 10), cor(176, 130, 100));
    else led(P, kx1 - 7, ky0 + 3, cor(170, 60, 50), cor(96, 26, 24), cor(72, 18, 18), cor(40, 20, 10), cor(176, 130, 100));
    if (foco) for (let x = kx0 - 1; x <= kx1; x++) for (let y = ky0 - 1; y <= ky1; y++) if (x === kx0 - 1 || x === kx1 || y === ky0 - 1 || y === ky1) px(P, x, y, cor(143, 74, 12));
    texto35(P, rotulo, Math.round(tcx + .5 - larg35(rotulo) / 2), T.y0 + 20, TINTA_M);
  }

  // ---- o crossfader: o A e o B nas pontas (aceso o lado no ar), a canaleta ambar e o pino creme com as estrias
  function crossEst(P, X) {
    const cy = X.cy, tx0 = X.x0 + 17, tx1 = X.x1 - 17;
    const dentro = (x, y) => x >= tx0 && x < tx1 && y >= cy - 2 && y <= cy + 2 && Math.min(x - tx0, tx1 - 1 - x) + Math.min(y - (cy - 2), cy + 2 - y) >= 1;
    // (r08) a canaleta sem sombra, como as dos volumes (dois modelos de luz para a mesma peca; e somava com a do pino)
    for (let x = tx0; x < tx1; x++) for (let y = cy - 2; y <= cy + 2; y++) {
      if (!dentro(x, y)) continue;
      const ex = Math.min(x - tx0, tx1 - 1 - x), ey = Math.min(y - (cy - 2), cy + 2 - y);
      px(P, x, y, ex === 0 || ey === 0 ? O : y === cy - 1 ? AMBAR[0] : y === cy ? AMBAR[1] : AMBAR[2]);
    }
  }
  function crossDin(P, X, xv, lado) {
    const cy = X.cy;
    for (const [lt, x0] of [['A', X.x0], ['B', X.x1 - 14]]) {
      const aceso = (lt === 'A') === (lado !== 'b');
      sombraCaixa(P, x0, cy - 6, x0 + 14, cy + 7, 1, 1, 1);
      if (aceso) caixa(P, x0, cy - 6, x0 + 14, cy + 7, cor(252, 204, 130), cor(255, 238, 206), cor(222, 160, 84), 1);
      else caixa(P, x0, cy - 6, x0 + 14, cy + 7, cor(236, 230, 218), cor(252, 250, 244), cor(196, 188, 174), 1);
      texto(P, 'fb', lt, x0 + Math.floor((14 - gl('fb', lt).w) / 2), cy + 4, TINTA);
    }
    const tx0 = X.x0 + 17, tx1 = X.x1 - 17, w = 12, xc0 = Math.round(tx0 + xv * (tx1 - tx0 - w)), y0 = cy - 7, y1 = cy + 8;
    sombraAlta(P, xc0, y0, xc0 + w, y1);
    caixa(P, xc0, y0, xc0 + w, y1, cor(240, 233, 220), cor(252, 249, 242), cor(188, 178, 162), 1);
    for (let y = y0 + 3; y < y1 - 4; y++) for (const gx of [3, 5, 7]) { px(P, xc0 + gx, y, cor(170, 158, 140)); px(P, xc0 + gx + 1, y, cor(252, 249, 242)); }
    // (r08) a face da frente em 3 fileiras, como a dos volumes (com 1 so o pino parecia uma pastilha chapada)
    for (let x = xc0 + 1; x < xc0 + w - 2; x++) { px(P, x, y1 - 4, cor(248, 238, 220)); px(P, x, y1 - 3, cor(214, 198, 172)); px(P, x, y1 - 2, cor(184, 166, 140)); }
    px(P, xc0 + w - 2, y1 - 4, cor(188, 178, 162)); px(P, xc0 + w - 2, y1 - 3, cor(172, 162, 144)); px(P, xc0 + w - 2, y1 - 2, cor(156, 146, 127));
  }

  // ---- a placa da transicao automatica: a luz dela (verde) e mais seis que acendem com a passagem, e o nome
  function placaEst(P, A) {
    const tTop = 21, rows = Math.ceil((tTop + A.thp) / 2) + 4;
    const w = Math.max(A.tw + 18, 7 * 8 + 19), x0 = Math.round((A.x0 + A.x1 - w) / 2), x1 = x0 + w;   // (r24) 2 celulas a mais de cada lado: os rebites de baixo encostavam nas pontas do texto; as bordas na dos botoes A e B
    let y0 = A.y0 + 3;   // (r18) a placa sobe junto com o crossfader
    if (y0 + rows > A.yMax) y0 = Math.max(A.y0 + 1, A.yMax - rows);
    const y1 = y0 + rows;
    sombraCaixa(P, x0, y0, x1, y1, 1, 1, 2);
    caixa(P, x0, y0, x1, y1, cor(226, 216, 196), cor(246, 240, 228), cor(186, 174, 152), 2);
    const reb = [[x0 + 3, y0 + 3], [x1 - 5, y0 + 3]].concat([[x0 + 3, y1 - 5], [x1 - 5, y1 - 5]]);
    for (const [px_, py_] of reb) {
      px(P, px_, py_, cor(250, 246, 236)); px(P, px_ + 1, py_, cor(170, 158, 136)); px(P, px_, py_ + 1, cor(170, 158, 136)); px(P, px_ + 1, py_ + 1, cor(130, 118, 98));
    }
    A.tcx = (x0 + x1) / 2; A.ttop = 2 * y0 + tTop + 2;
    const l0 = Math.round((x0 + x1 - 53) / 2);
    A.lx = [...Array(7)].map((_, i) => l0 + i * 8);
    A.ly = y0 + 6;
  }
  const LED = [".##.", "#ab%", "#bc%", ".%%."];
  function led(P, x, y, a, b, c, aro = cor(58, 40, 30), aroL = aro) {
    const k = { "#": aro, "%": aroL, a, b, c };
    LED.forEach((l, j) => [...l].forEach((q, i) => { if (q !== '.') px(P, x + i, y + j, k[q]); }));
  }
  const LED5 = [".###.", "#abb%", "#bbc%", "#bcc%", ".%%%."];
  function placaDin(P, A, estado, prog) {
    A.lx.forEach((lx, i) => {
      if (i === 0) {
        const on = estado === 2 || (estado === 3 && (Date.now() / 550 | 0) % 2 === 0);
        const k = on ? { "#": cor(30, 60, 24), "%": cor(30, 60, 24), a: cor(236, 255, 220), b: cor(132, 236, 86), c: cor(100, 210, 62) }
                     : { "#": cor(58, 40, 30), "%": cor(58, 40, 30), a: cor(108, 132, 92), b: cor(62, 92, 48), c: cor(40, 64, 32) };
        LED5.forEach((l, j) => [...l].forEach((q, ii) => { if (q !== '.') px(P, lx + ii, A.ly - 1 + j, k[q]); }));
      } else {
        const on = estado === 3 && prog * 6 >= i - .5;
        const k = on ? { "#": cor(58, 40, 30), "%": cor(58, 40, 30), a: cor(255, 236, 180), b: cor(250, 160, 50), c: cor(206, 108, 30) }
                     : { "#": cor(58, 40, 30), "%": cor(58, 40, 30), a: cor(176, 98, 52), b: cor(150, 72, 28), c: cor(120, 54, 20) };
        LED5.forEach((l, j) => [...l].forEach((q, ii) => { if (q !== '.') px(P, lx + ii, A.ly - 1 + j, k[q]); }));
      }
    });
  }

  // ---------------- o mixer na pagina
  let mx = null, fontesMx = false;
  // ---- o negrito de 8 desenhado a mao para o nome da placa (1 px de tela por pixel): hastes de 2, tracos deitados de 1,
  // acentos 1 acima da letra e o cedilha embaixo
  const G8 = {
    T: ["######", "..##..", "..##..", "..##..", "..##..", "..##..", "..##..", "..##.."],
    R: ["#####.", "##..##", "##..##", "#####.", "##.##.", "##..##", "##..##", "##..##"],
    A: [".####.", "##..##", "##..##", "##..##", "######", "##..##", "##..##", "##..##"],
    N: ["##..##", "###.##", "###.##", "######", "##.###", "##.###", "##..##", "##..##"],
    S: [".####.", "##..##", "##....", ".####.", "....##", "....##", "##..##", ".####."],
    I: ["##", "##", "##", "##", "##", "##", "##", "##"],
    C: [".####.", "##..##", "##....", "##....", "##....", "##....", "##..##", ".####."],
    O: [".####.", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", ".####."],
    U: ["##..##", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", ".####."],
    M: ["##...##", "###.###", "#######", "##.#.##", "##...##", "##...##", "##...##", "##...##"],
    D: ["#####.", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##", "#####."],
    J: ["....##", "....##", "....##", "....##", "....##", "##..##", "##..##", ".####."],
    G: [".####.", "##..##", "##....", "##.###", "##..##", "##..##", "##..##", ".#####"],
    F: ["######", "##....", "##....", "#####.", "##....", "##....", "##....", "##...."],
    E: ["######", "##....", "##....", "#####.", "##....", "##....", "##....", "######"],
    V: ["##..##", "##..##", "##..##", "##..##", "##..##", ".####.", ".####.", "..##.."],
    Z: ["######", "....##", "...###", "..###.", ".###..", "###...", "##....", "######"],
    H: ["##..##", "##..##", "##..##", "######", "##..##", "##..##", "##..##", "##..##"],
    P: ["#####.", "##..##", "##..##", "#####.", "##....", "##....", "##....", "##...."],
    " ": ["...", "...", "...", "...", "...", "...", "...", "..."],
  };
  const A8 = { "Ã": ["A", [".##..#", "#..##."]], "Á": ["A", ["...##.", "..##.."]], "Ó": ["O", ["...##.", "..##.."]], "É": ["E", ["...##.", "..##.."]], "Õ": ["O", [".##..#", "#..##."]] };
  const F8 = { G: G8, A: A8, h: 8 };
  const gB = (F, ch) => { const a = F.A[ch], b = a ? a[0] : ch === 'Ç' ? 'C' : ch; return { rows: F.G[b] || F.G[' '], mark: a ? a[1] : null, ced: ch === 'Ç' }; };
  const largB = (t, F = F8, esp = 1) => [...t].reduce((s_, ch, i) => s_ + gB(F, ch).rows[0].length + (i ? esp : 0), 0);
  const larg8 = t => largB(t);
  function textoB(im, t, x, y, rgb, F = F8, esp = 1) {
    const put = (X, Y) => { if (X < 0 || Y < 0 || X >= im.width || Y >= im.height) return; const i = 4 * (Y * im.width + X); im.data[i] = rgb[0]; im.data[i + 1] = rgb[1]; im.data[i + 2] = rgb[2]; im.data[i + 3] = 255; };
    for (const ch of t) {
      const g = gB(F, ch), w = g.rows[0].length;
      g.rows.forEach((l, j) => [...l].forEach((q, i) => { if (q === '#') put(x + i, y + j); }));
      if (g.mark) g.mark.forEach((l, j) => [...l].forEach((q, i) => { if (q === '#') put(x + i, y - 3 + j); }));
      if (g.ced) { put(x + 2, y + F.h); put(x + 3, y + F.h); put(x + 1, y + F.h + 1); put(x + 2, y + F.h + 1); }
      x += w + esp;
    }
  }
  const texto8 = (im, t, x, y, rgb) => textoB(im, t, x, y, rgb);
  // o rotulo desenhado tem largura fixa (cada palavra numa linha cabe em 46 pixels da letra, com o pixel da letra em 2 do
  // palco, o Windows a 125%): o do fone tem um texto curto so para ele, e o do label segue para o resto
  const TEXTO_DESENHADO = { 'f-mon': I18N.t('mixer.recordInHeadphonesShort') };
  const relM = (el, D) => { const r = rectP(el); return { x0: Math.round((r.left - D.left) / 2), y0: Math.round((r.top - D.top) / 2), x1: Math.round((r.right - D.left) / 2), y1: Math.round((r.bottom - D.top) / 2), h: r.height, w: r.width }; };
  const vis = el => el && !el.hidden && el.offsetParent !== null && getComputedStyle(el).display !== 'none';
  function preparaMx(rec) {
    if (mx && mx.rec === rec) return mx;
    const cv = document.createElement('canvas');
    cv.className = 'mx-px'; cv.setAttribute('aria-hidden', 'true');
    rec.appendChild(cv);
    const q = s => rec.querySelector(s);
    mx = { rec, cv, ctx: cv.getContext('2d'), janela: q('.janela'), metros: [...rec.querySelectorAll('.mostrador')],
           faders: [...rec.querySelectorAll('.fader')], teclas: [...rec.querySelectorAll('.tecla-set')], xf: q('.xfader'), pino: q('.xf-pino'),
           auto: q('.auto-luz'), lamp: q('#lamp-auto'), chaveE: '', chaveD: '' };
    rec.classList.add('mx-ok');
    return mx;
  }
  const NOMES_T = { 'm-aleatorio': 'aleatorio', 'm-repetir': 'repetir', 'm-parecidas': 'parecidas' };
  function quebra(t, max) {
    const ps = t.split(/\s+/), out = [];
    let cur = '';
    for (const p of ps) { const n = cur ? cur + ' ' + p : p; if (cur && larg35(n) > max) { out.push(cur); cur = p; } else cur = n; }
    if (cur) out.push(cur);
    return out;
  }
  function desenhaMx(m) {
    const D = rectP(m.rec);
    if (!D.width) return;
    // o pixel das letras dos rotulos e da placa: 1 px do palco no desenho, mas nunca menos de 1 px CSS e sempre um numero
    // inteiro de pixels da tela (no notebook dele, palco a 0,75: 2 px de tela por pixel da letra, nao 1,5, pedido dele)
    const dT = (devicePixelRatio || 1) * PALCO.k, LS = Math.max(Math.round(dT), Math.ceil((devicePixelRatio || 1) - 1e-6)) / dT;
    const gx = v => Math.round((D.left + v) * dT) / dT - D.left, gy = v => Math.round((D.top + v) * dT) / dT - D.top;
    const W = Math.round(D.width / 2), H = Math.floor(D.height / 2), M_ = 3;   // a altura impar (439) desce para a celula de baixo: a base na das pedaleiras
    const J = relM(m.janela, D);
    const fs = m.faders.filter(vis).map(f => {
      const lab = f.querySelector('label'), inp = f.querySelector('input'), out = f.querySelector('output'), sm = lab.querySelector('small');
      const C = relM(f, D), I = relM(inp, D), Ou = relM(out, D);
      const txt = (TEXTO_DESENHADO[inp.id] || [...lab.childNodes].filter(n => n.nodeType === 3 || n.nodeName === 'SPAN').map(n => n.textContent).join('')).trim();
      return { el: f, inp, out, C, cx: Math.round((I.x0 + I.x1) / 2), sy0: I.y0, sy1: I.y1, L: I.h, oy: Ou.y1 - 2, txt, apag: !f.classList.contains('fader-voz') && !!(sm && sm.textContent.trim()) };
    });
    const ts = m.teclas.filter(vis).map(t => ({ el: t, T: relM(t, D), rot: t.querySelector('.rot-set').textContent.trim() }));
    const X = vis(m.xf) ? relM(m.xf, D) : null, A = vis(m.auto) ? relM(m.auto, D) : null;
    if (X) X.cy = X.y0 + 13;   // (r18) a linha do crossfader 1 celula acima (o sulco fica no X.y0, na base dos Sons rapidos): o rodape ficava com 2 celulas
    const apag = m.metros.map(e => e.classList.contains('apagado'));
    const JM = MESA.montada && $('#pads') && $('#pads').offsetWidth ? jacksMesa() : null;
    const geo = [JM ? [JM.a, JM.a2, JM.v, JM.b, JM.p, JM.p2].join(',') : '', W, H, J.x0, J.y0, J.x1, J.y1, fs.map(f => [f.C.x0, f.C.y0, f.C.x1, f.C.y1, f.sy0, f.sy1, f.cx, f.txt, f.apag].join(',')).join(';'),
                 ts.map(t => [t.T.x0, t.T.y0, t.T.x1, t.rot].join(',')).join(';'), X ? [X.x0, X.y0, X.x1].join(',') : '', A ? [A.x0, A.y0, A.x1].join(',') : '',
                 apag.join(), fontesMx, LS].join('|');
    if (geo !== m.chaveE) {
      m.cv.width = W + M_; m.cv.height = H + M_; m.cv.style.width = 2 * (W + M_) + 'px'; m.cv.style.height = 2 * (H + M_) + 'px';
      const P = pincel(W + M_, H + M_);
      // a sombra do painel na parede
      for (let y = 2; y < H + 2; y++) for (let x = 2; x < W + 2; x++) {
        const ex = Math.min(x - 2, W + 1 - x), ey = Math.min(y - 2, H + 1 - y);
        // (r07) tambem dentro da caixa onde o chanfro do painel tira o canto (sobrava um L de madeira na quina de baixo)
        const fora = x >= W || y >= H || Math.min(x, W - 1 - x) + Math.min(y, H - 1 - y) < 2;
        if (ex + ey >= 2 && fora) px(P, x, y, SOMBRA);
      }
      const nm = m.metros.length || 3, gap = 4, mw = Math.floor((J.x1 - J.x0 - gap * (nm - 1)) / nm), sobra = (J.x1 - J.x0) - (mw * nm + gap * (nm - 1));
      const vx0 = i => J.x0 + Math.floor(sobra / 2) + i * (mw + gap);
      const cols = m.metros.map((_, i) => vx0(i) + Math.floor(mw / 2));
      fs.forEach((f, i) => { f.col = fs.length === cols.length ? cols[i] : Math.floor((f.C.x0 + f.C.x1) / 2); f.cx = f.col; f.linhas = quebra(f.txt, mw - 2); });
      ts.forEach((t, i) => { t.T.col = ts.length === cols.length ? cols[i] : Math.round((t.T.x0 + t.T.x1) / 2); });
      // onde fica liso: atras dos rotulos, dos valores e dos nomes das teclas
      // os textos em HTML: um por volume e o da placa; a largura medida vira o liso atras deles e a largura da placa
      const span = (k, cls) => {
        m.txt = m.txt || {};
        let e = m.txt[k];
        if (!e) { e = document.createElement('span'); e.className = 'mx-txt ' + cls; e.setAttribute('aria-hidden', 'true'); m.rec.appendChild(e); m.txt[k] = e; }
        e.style.display = ''; return e;
      };
      for (const e of Object.values(m.txt || {})) e.style.display = 'none';
      // as linhas de cada rotulo antes, para todos ficarem com o meio na mesma altura (o de uma linha no meio do de duas)
      const lg = t => largB(t, F8, 2), AL = F8.h;
      let LSr = LS, LH = AL + 4;   // o pixel da letra e a distancia entre as linhas dos rotulos (a placa segue no LS)
      const quebra8 = t => {
        const ps = t.toUpperCase().split(/\s+/), out = [];
        let cur = '';
        for (const p_ of ps) { const n_ = cur ? cur + ' ' + p_ : p_; if (cur && lg(n_) * LSr > 2 * mw - 6) { out.push(cur); cur = p_; } else cur = n_; }
        if (cur) out.push(cur);
        return out;
      };
      // (r19) o rotulo cabe entre o mostrador e o trilho: com o Windows a 125% a letra vai a 2 px de tela, o DISCO NO JOGO
      // quebrava em 3 linhas e subia por cima das placas (a 150%, o RECORD IN PHONES). Sem espaco, primeiro as linhas mais
      // juntas, depois a letra 1 px de tela menor (abaixo de 1 px CSS, so ai), ate caber; com espaco, fica como era
      const teto = 2 * J.y1 + 2, base0 = Math.min(...fs.map(f => 2 * f.C.y0 + 34));
      cabe: for (let n = Math.round(LS * dT); n >= 1; n--) {
        for (const lh of [AL + 4, AL + 3, AL + 2]) {
          LSr = n / dT; LH = lh;
          fs.forEach(f => { f.l8 = quebra8(f.txt); });
          if (base0 - LSr * ((Math.max(1, ...fs.map(f => f.l8.length)) - 1) * LH + AL) >= teto) break cabe;
        }
      }
      const NL = Math.max(1, ...fs.map(f => f.l8.length));
      fs.forEach((f, i) => {
        m.txt = m.txt || {};
        let cv = m.txt['v' + i];
        if (!cv || cv.tagName !== 'CANVAS') {
          if (cv) cv.remove();
          cv = document.createElement('canvas'); cv.className = 'mx-txt mx-rot-px'; cv.setAttribute('aria-hidden', 'true'); m.rec.appendChild(cv); m.txt['v' + i] = cv;
        }
        cv.style.display = '';
        const linhas = f.l8;
        const w = Math.max(...linhas.map(lg)), h = 3 + (linhas.length - 1) * LH + AL + 3;
        cv.width = w; cv.height = h; cv.style.width = w * LSr + 'px'; cv.style.height = h * LSr + 'px';
        const c = cv.getContext('2d'), im = c.createImageData(w, h);
        linhas.forEach((l, j) => textoB(im, l, Math.floor((w - lg(l)) / 2), 4 + j * LH, [250, 248, 242], F8, 2));
        linhas.forEach((l, j) => textoB(im, l, Math.floor((w - lg(l)) / 2), 3 + j * LH, [46, 33, 26], F8, 2));
        c.putImageData(im, 0, 0);
        // (r05) a linha de base 1 celula acima: o rotulo colava no topo do trilho (e no cursor em 100%); o vao para o VU
        // e para o trilho fica igual
        const base = 2 * f.C.y0 + 34, left = gx(2 * f.col + 1 - w * LSr / 2), top = gy(base - LSr * (3 + (NL - 1) * LH + AL) + LSr * (NL - linhas.length) * LH);
        cv.style.left = left + 'px'; cv.style.top = top + 'px';
        f.cal = [Math.floor(left / 2) - 2, Math.floor(top / 2), Math.ceil((left + w * LSr) / 2) + 2, Math.ceil((top + h * LSr) / 2)];
      });
      if (A) {
        // o nome da placa sem suavizar (ordem dele, 06/11): a mesma letra desenhada num canvas de 1 px, cada pixel cheio ou
        // vazio pelo meio do alfa
        let cv = m.placaCv;
        if (!cv) { cv = document.createElement('canvas'); cv.className = 'mx-txt mx-placa-px'; cv.setAttribute('aria-hidden', 'true'); m.rec.appendChild(cv); m.placaCv = cv; }
        const t = (m.auto.textContent || '').trim().toUpperCase();
        // (r09) 1 fileira vazia em cima (h0 + 1, o canvas 1 pixel acima): o top cai em 1/64 de px do layout, fora da
        // tela, e o Chrome estica a fileira 0 em 1 px de tela; com ela vazia, o acento do A e do til deixa de engordar
        const w = largB(t, F8, 2), h0 = 3 + F8.h + 3, h = h0 + 1;
        cv.width = w; cv.height = h; cv.style.width = w * LS + 'px'; cv.style.height = h * LS + 'px';
        const c = cv.getContext('2d'), im = c.createImageData(w, h);
        textoB(im, t, 0, 4, [15, 8, 5], F8, 2);
        c.putImageData(im, 0, 0);
        A.tw = Math.ceil(w * LS / 2); A.thp = h0 * LS; A.el = cv; A.yMax = H - 5;
      }
      const calmos = [];
      for (const f of fs) {
        calmos.push(f.cal);
        calmos.push([f.col - 9, f.sy1 + 3, f.col + 10, f.sy1 + 10]);
      }
      for (const t of ts) { const w = larg35(t.rot), x0 = Math.round(t.T.col + .5 - w / 2); calmos.push([x0 - 2, t.T.y0 + 15, x0 + w + 2, t.T.y0 + 26]); }
      const calmo = (x, y) => calmos.some(q => x >= q[0] && x < q[2] && y >= q[1] && y < q[3]);
      const ySplit = X ? X.y0 : H - 30;   // (r13) o sulco no meio da faixa livre entre os rotulos e o knob do crossfader (4 celulas de cada lado); a base dos Sons rapidos vem para a linha dele
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
        const ex = Math.min(x, W - 1 - x), ey = Math.min(y, H - 1 - y);
        if (ex + ey < 2) continue;
        let c;
        if (ex + ey === 2 || ex === 0 || ey === 0) c = O;
        else if (y === 1 || x === 1 || (ex + ey === 3 && x < W / 2 && y < H / 2)) c = MET.luz;
        else if (y === H - 2 || x === W - 2 || ex + ey === 3) c = MET.somb;
        else if (y === H - 3 || x === W - 3) c = MET.somb2;
        else if (y === 2 || x === 2) c = MET.luz2;
        else if (calmo(x, y)) c = MET.b;
        else {
          const sec = y > ySplit ? 7 : 0, L = 4 + Math.floor(ruido(x, 5 + sec) * 11), sg = Math.floor((y + ruido(x, 1 + sec) * 30) / L), h = ruido(x, sg, 2 + sec);
          c = h < .2 ? (x % 2 ? MET.a : MET.c) : MET.b;
        }
        px(P, x, y, c);
      }
      for (let x = 2; x < W - 2; x++) { px(P, x, ySplit + 1, MET.sulco); px(P, x, ySplit + 2, MET.luz); }
      for (const [x, y] of [[3, 3], [W - 8, 3], [3, H - 8], [W - 8, H - 8]]) parafusoM(P, x, y);   // (r25) os da direita e os de baixo no espelho dos outros pelo corpo (como VUs, A/B e rebites), a sombra no chanfro   // (r13) 1 celula para dentro: a sombra pintava por cima do chanfro   // os da direita fora do chanfro claro; (r06) os de baixo a 1 celula do contorno, como os outros
      // (c1) as tomadas de aco nos lados, onde os cabos entram (jacksMesa): as duas da pedaleira da esquerda no lado
      // esquerdo, as do par dos Sons rapidos e as duas da pedaleira da direita no direito; as faixas na rampa quente dos parafusos (o brilho em
      // cima, a base escura), 1 celula a mais que a porca do plugue em cima e embaixo, com a sombra de 1 celula embaixo
      if (JM) for (const [y, dir] of [[JM.a, false], [JM.a2, false], [JM.v, true], [JM.b, true], [JM.p, true], [JM.p2, true]]) {
        const cyJ = Math.round((y - D.top) / 2), xa = dir ? W - 5 : 0;
        for (let yy = cyJ - 4; yy <= cyJ + 4; yy++) for (let x = xa; x <= xa + 4; x++) {
          const borda = x === xa || x === xa + 4 || yy === cyJ - 4 || yy === cyJ + 4;
          px(P, x, yy, borda ? O : yy === cyJ - 3 ? cor(224, 221, 214) : yy === cyJ + 3 ? cor(96, 90, 84) : cor(154, 145, 137));
        }
        for (let x = xa + 1; x <= xa + 3; x++) px(P, x, cyJ + 5, cor(154, 145, 137));
      }
      m.vg = m.metros.map((e, i) => ({ k: e.dataset.k, apag: apag[i], g: vuFace(P, vx0(i), J.y0, vx0(i) + mw, J.y1, e.dataset.nome || '', apag[i]) }));
      for (const f of fs) faderEst(P, f);
      if (X) crossEst(P, X);
      if (A) { placaEst(P, A); A.el.style.left = gx(2 * A.tcx - A.el.width * LS / 2) + 'px'; A.el.style.top = gy(A.ttop) - LS + 'px'; }
      m.est = P; m.fs = fs; m.ts = ts; m.X = X; m.A = A; m.chaveE = geo; m.chaveD = '';
      m.dyn = pincel(W + M_, H + M_); m.img = m.ctx.createImageData(W + M_, H + M_); m.imgU = new Uint32Array(m.img.data.buffer);
    }
    // o que anda: as agulhas, os pinos, as teclas, o crossfader e as luzes
    const angs = m.vg.map(v => Math.round(((typeof angPixel === 'object' && angPixel[v.k] != null) ? angPixel[v.k] : -50) * 2) / 2);
    const foco = document.activeElement && m.rec.contains(document.activeElement) && document.activeElement.matches(':focus-visible') ? document.activeElement : null;
    const fv = m.fs.map(f => [f.inp.value, f.inp.max, f.out.textContent].join('/'));
    const tv = m.ts.map(t => [t.el.getAttribute('aria-pressed'), t.el.matches(':active') || t.el.classList.contains('apertado'), (t.el.querySelector('.lampada') || {}).className].join('/'));
    const xv = m.pino ? parseFloat(getComputedStyle(m.pino).getPropertyValue('--x')) || 0 : 0, lado = document.body.dataset.lado || 'a';
    const lc = m.lamp ? m.lamp.className : '', est = /piscando/.test(lc) ? 3 : /acesa/.test(lc) ? 2 : 0;
    const blink = est === 3 ? (Date.now() / 550 | 0) % 2 : 0;
    const sig = [angs.join(), fv.join(), tv.join(), xv.toFixed(3), lado, est, blink, foco ? foco.id : ''].join('|');
    if (sig === m.chaveD) return;
    m.chaveD = sig;
    const P = m.dyn;
    P.u.set(m.est.u);
    m.vg.forEach((v, i) => vuAgulha(P, v.g, angs[i], v.apag));
    m.fs.forEach(f => faderDin(P, f, (+f.inp.value - +f.inp.min) / ((+f.inp.max - +f.inp.min) || 1), f.out.textContent.trim(), f.apag, foco === f.inp));
    m.ts.forEach(t => tecla(P, t.T, NOMES_T[t.el.id] || 'parecidas', t.rot, t.el.getAttribute('aria-pressed') === 'true',
                            t.el.matches(':active') || t.el.classList.contains('apertado'), /acesa/.test((t.el.querySelector('.lampada') || {}).className || ''), foco === t.el));
    if (m.X) crossDin(P, m.X, xv, lado);
    if (m.A) {
      // o quanto da passagem ja foi: o crossfader saindo do lado de onde partiu
      const prog = est === 3 ? (lado === 'b' ? xv : 1 - xv) : 0;
      placaDin(P, m.A, est, prog);
    }
    m.imgU.set(P.u);
    m.ctx.putImageData(m.img, 0, 0);
  }
  function snapM(el) {
    const r = rectP(el), v = (el.dataset.mxSnap || '0 0').split(' ').map(Number);
    const bx = r.left - v[0], by = r.top - v[1];
    const nx = Math.round(bx / 2) * 2 - bx, ny = Math.round(by / 2) * 2 - by;
    if (Math.abs(nx - v[0]) > .01 || Math.abs(ny - v[1]) > .01) { el.style.translate = `${nx}px ${ny}px`; el.dataset.mxSnap = nx + ' ' + ny; }
  }

  // ---------------- os Sons rapidos: a caixa de madeira com a costura e as cantoneiras de latao, o fundo escuro, o titulo
  // e os pads de controladora com a plaquinha creme do nome
  let pd = null;
  const hexCor = h => cor(parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16));
  const mistura = (c, d, k) => cor(((c & 255) * (1 - k) + (d & 255) * k) | 0, (((c >> 8) & 255) * (1 - k) + ((d >> 8) & 255) * k) | 0,
                                   (((c >> 16) & 255) * (1 - k) + ((d >> 16) & 255) * k) | 0);
  const BRANCO = cor(255, 255, 255);
  // a cor em HSL, para as rampas que viram o matiz: o claro puxa para o amarelo, o escuro para o outro lado
  function paraHsl(c) {
    const r = (c & 255) / 255, g = ((c >> 8) & 255) / 255, b = ((c >> 16) & 255) / 255, mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
    let h = 0, s_ = 0;
    if (mx !== mn) {
      const d = mx - mn; s_ = l > .5 ? d / (2 - mx - mn) : d / (mx + mn);
      h = 60 * (mx === r ? (g - b) / d + (g < b ? 6 : 0) : mx === g ? (b - r) / d + 2 : (r - g) / d + 4);
    }
    return [h, s_, l];
  }
  function deHsl(h, s_, l) {
    h = ((h % 360) + 360) % 360; s_ = Math.min(1, Math.max(0, s_)); l = Math.min(1, Math.max(0, l));
    const a = s_ * Math.min(l, 1 - l), f = n => { const k = (n + h / 30) % 12; return Math.round(255 * (l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)))); };
    return cor(f(0), f(8), f(4));
  }
  const lEstrela = c => {
    const lin = v => { v /= 255; return v <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
    const Y = .2126 * lin(c & 255) + .7152 * lin((c >> 8) & 255) + .0722 * lin((c >> 16) & 255);
    return Y > .008856 ? 116 * Math.cbrt(Y) - 16 : 903.3 * Y;
  };
  const rumo = (h, alvo, g) => { const d = ((alvo - h + 540) % 360) - 180; return h + Math.sign(d) * Math.min(Math.abs(d), g); };
  function rampa(base, aceso) {
    const [h, s_, l] = paraHsl(base), a = aceso ? .12 : 0, cl = (dh, ds, dl) => deHsl(rumo(h, dh >= 0 ? 60 : 240, Math.abs(dh)), s_ + ds, l + dl + a);
    // o brilho parado: o menor passo de luz que sobe 6 de L* (e o anel da borda dele, 3), igual em todas as cores
    const L0 = lEstrela(cl(0, 0, 0)), passo = alvo => { let k = 0; while (k < .4 && lEstrela(cl(4, .06, k)) - L0 < alvo) k += .005; return cl(4, .06, k); };
    const claraDemais = L0 > 75;
    return { sulco: cl(-14, -.04, -.17), sombra: cl(-8, 0, -.07), base: cl(0, 0, 0), meio: passo(claraDemais ? 11 : 6), anel: passo(claraDemais ? 6 : 3), claro: aceso ? cl(10, .12, .13) : null,
             aro: cl(12, .1, .27), aro2: cl(8, .08, .15), aroB: cl(-8, 0, -.07), aroM2: cl(5, .05, .07), especular: aceso ? BRANCO : cl(14, .1, .36) };
  }
  const LATAO = { l: cor(255, 234, 150), m: cor(222, 170, 70), s: cor(166, 108, 34), d: cor(116, 72, 22) };
  const PAINEL = { b: cor(71, 35, 26), e: cor(63, 30, 22), somb: cor(34, 20, 12), somb2: cor(50, 25, 18), luz: cor(94, 52, 32) };
  const MAD = { realce: cor(232, 160, 100), escuro: cor(92, 42, 18), face: cor(150, 74, 38), faceS: cor(124, 58, 30), rebaixo: cor(104, 48, 24),
                veio: cor(134, 65, 33), veioS: cor(110, 51, 26) };
  const COSTURA = cor(236, 212, 168), FURO = cor(92, 42, 18), PLACA = { face: cor(239, 229, 208), luz: cor(250, 243, 228), somb: cor(204, 168, 116), dir: cor(224, 206, 174) };
  function preparaPads(sec) {
    if (pd && pd.sec === sec) return pd;
    const cv = document.createElement('canvas');
    cv.className = 'pads-px'; cv.setAttribute('aria-hidden', 'true'); sec.prepend(cv);
    pd = { sec, cv, ctx: cv.getContext('2d'), chave: '' };
    sec.classList.add('px-ok');
    return pd;
  }
  // a moldura de E: contorno, 1 de luz (em cima e a esquerda) ou de sombra, 4 de madeira com veios longos e raros, a costura
  // na 3a celula da madeira e o contorno de dentro
  function moldura(P, W, H, E, L) {
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const ex = Math.min(x, W - 1 - x), ey = Math.min(y, H - 1 - y), d = Math.min(ex, ey);
      if (ex + ey < 2 || d >= E) continue;
      const ao = ey <= ex, al = ao ? x : y, fundo = ao ? y > H / 2 : x > W / 2;
      let c;
      if (ex + ey === 2 || d === 0) c = O;
      else if (d === E - 1) c = O2;
      else if (d === 1) c = fundo ? MAD.escuro : MAD.realce;
      else if (d === E - 2 || d === E - 3) {
        c = d === E - 2 ? (fundo ? MAD.faceS : MAD.rebaixo) : (fundo ? MAD.faceS : MAD.face);
        // os veios escuros: so na faixa do rebaixo, de 3 a 8 celulas, um a cada 15 a 30 (o comeco de cada um sorteado)
        const lado = (ao ? 1 : 2) + (fundo ? 2 : 0), comp = ao ? W : H;
        let ini = L + 2 + Math.floor(ruido(lado, 0, 31) * 8), achou = false;
        for (let n = 1; ini < comp - L - 2 && !achou; n++) {
          const len = 3 + Math.floor(ruido(lado, n, 32) * 6);
          if (d === E - 2 && al >= ini && al < Math.min(ini + len, comp - L - 2)) achou = true;
          ini += len + 15 + Math.floor(ruido(lado, n, 33) * 16);
        }
        if (achou) c = fundo ? cor(100, 46, 24) : cor(82, 36, 18);
      }
      else {
        c = fundo ? MAD.faceS : MAD.face;
        // os veios: tracos de 1 de 4 a 8 ao longo da travessa, um a cada 13, em tracos alternados
        const seg = Math.floor((al + d * 11) / 23), pos = (al + d * 11 + Math.floor(ruido(d, Math.floor((al + d * 11) / 23), 7) * 9)) % 23,
              len = 3 + Math.floor(ruido(d, seg, 6) * 4);
        const comp = ao ? W : H;
        if (d === 2 && al > L + 1 && al < comp - L - 2 && ruido(d, seg, ao ? 3 : 4) < .45 && pos >= 3 && pos < 3 + len) c = fundo ? MAD.veioS : cor(166, 86, 46);
      }
      px(P, x, y, c);
    }
    // a costura: pontos de 3 com 2 de folga na 3a celula, o furo escuro na saida de cada ponto, parando antes das cantoneiras
    const k = 3, a0 = L + 1;
    const lado = (n, f) => {
      const k_ = Math.floor((n + 1) / 5), o = Math.floor((n - (5 * k_ - 1)) / 2);
      for (let i = 0; i < k_; i++) { for (let t = 0; t < 3; t++) f(o + 5 * i + t, COSTURA, true); f(o + 5 * i + 3, FURO, false); }
    };
    lado(W - 2 * a0, (t, c, sb) => { t += 1; px(P, a0 + t, k, c); px(P, a0 + t, H - 1 - k, c); if (sb) { px(P, a0 + t, k + 1, MAD.rebaixo); px(P, a0 + t, H - k, MAD.escuro); } });
    // (r15) a lateral 1 celula abaixo: com a base encurtada (r13) ela ficava a 1 celula da cantoneira de cima e a 3 da de baixo
    lado(H - 2 * a0, (t, c, sb) => { t += 1; px(P, k, a0 + t, c); px(P, W - 1 - k, a0 + t, c); if (sb) { px(P, k + 1, a0 + t, MAD.rebaixo); px(P, W - k, a0 + t, MAD.escuro); } });
  }
  // a cantoneira de latao em L com a borda de dentro na diagonal (pernas de L, largura w, chanfro de 2 na quina) e dois
  // rebites; a luz e de cima e da esquerda em qualquer canto, e a sombra de contato cai na madeira
  function cantoneira(P, W, H, sx, sy, L, w) {
    const X = i => sx < 0 ? i : W - 1 - i, Y = j => sy < 0 ? j : H - 1 - j;
    const den = (i, j) => i >= 0 && j >= 0 && i < L && j < L && i + j >= 2 && i + j <= L - 1 + w;
    const tela = new Map();
    for (let j = 0; j < L; j++) for (let i = 0; i < L; i++) if (den(i, j)) tela.set(X(i) + ',' + Y(j), 1);
    const tem = (x, y) => tela.has(x + ',' + y);
    for (let j = -1; j <= L; j++) for (let i = -1; i <= L; i++) {
      const x = X(i), y = Y(j);
      if (!tem(x, y) && tem(x - 1, y - 1)) px(P, x, y, SOMBRA_F);
    }
    for (const key of tela.keys()) {
      const [x, y] = key.split(',').map(Number);
      const borda = !tem(x - 1, y) || !tem(x + 1, y) || !tem(x, y - 1) || !tem(x, y + 1);
      let c = LATAO.m;
      const luz = !tem(x, y - 2) || !tem(x - 2, y), somb = !tem(x, y + 2) || !tem(x + 2, y);
      if (borda) c = O;
      else if (luz && !somb) c = LATAO.l;
      else if (luz && somb) c = cor(246, 212, 120);
      else if (somb) c = LATAO.s;
      px(P, x, y, c);
    }
    const rebite = (i, j) => {   // a cupula de 3x3 na tela, com a luz de cima e da esquerda em qualquer canto
      const x = Math.min(X(i), X(i + 2)), y = Math.min(Y(j), Y(j + 2));
      const k = { H: cor(255, 234, 150), W: cor(255, 250, 205), A: cor(246, 212, 120), m: LATAO.m, s: LATAO.s, D: LATAO.d };
      ["mWm", "HAs", "msD"].forEach((l, b) => [...l].forEach((q, a) => px(P, x + a, y + b, k[q])));
    };
    rebite(3, 6); rebite(6, 3);
  }
  // o pad de S: contorno com chanfro de 2, aro de 1 (claro em cima e a esquerda, meio-tom embaixo e a direita), o filete
  // escuro de 1 com chanfro de 1 e a face: o brilho redondo no meio e a sombra em L na coluna e na fileira de fora
  function pad(P, x0, y0, S, base, aceso, apagado) {
    const t = apagado ? { sulco: cor(34, 26, 22), sombra: cor(44, 35, 30), base: cor(50, 40, 34), meio: cor(50, 40, 34), claro: null,
                          aro: cor(104, 90, 80), aro2: cor(80, 68, 60), aroB: cor(44, 35, 30), aroM2: cor(62, 51, 44), especular: cor(138, 124, 114) } : rampa(base, aceso);
    const cx = Math.floor((S - 1) / 2) - 1;
    for (let j = 0; j < S; j++) for (let i = 0; i < S; i++) {
      const dx = Math.min(i, S - 1 - i), dy = Math.min(j, S - 1 - j), d = Math.min(dx, dy), tl = i + j < S - 1;
      if (dx + dy < 3) continue;
      let c;
      if (dx + dy === 3 || d === 0) c = O;
      else if (d === 1 || dx + dy === 4) c = tl ? t.aro : t.aroB;                 // o aro de 2: a celula de fora...
      else if (d === 2 || dx + dy === 5) c = tl ? (t.aro2 || t.aro) : (t.aroM2 || t.aroM);   // ... e a de dentro, um degrau abaixo
      else if (d === 3 || dx + dy === 6) c = tl ? t.sombra : t.sulco;            // o sulco nos quatro lados
      else if (i === S - 5 || j === S - 5) c = t.sombra;                         // a sombra de 1 embaixo e a direita
      else {
        const q = Math.pow(Math.pow(Math.abs(i - cx), 3) + Math.pow(Math.abs(j - cx), 3), 1 / 3);
        c = t.claro && q <= 2.6 ? t.claro : q <= 4.8 ? t.meio : q <= 5.8 ? (t.anel || t.meio) : t.base;
      }
      px(P, x0 + i, y0 + j, c);
    }
    // o traco de brilho no aro de cima (6) e no da esquerda (3), e o reflexo de dentro
    for (let i = 4; i <= 8; i++) px(P, x0 + i, y0 + 1, t.especular);
    for (let j = 4; j <= 6; j++) px(P, x0 + 1, y0 + j, t.especular);
    px(P, x0 + 4, y0 + 5, t.especular); px(P, x0 + 5, y0 + 4, t.especular);
  }
  // o titulo em negrito de 9 (a 5x7 com as linhas 3 e 5 dobradas, hastes de 2), 1 celula entre as letras, o acento de 2x2
  // separado da letra por 1 linha, a sombra embaixo e a direita
  function glifoTit(ch) {
    let b = ch, marca = null;
    if (ACENTO[ch]) { b = ACENTO[ch][0]; marca = ACENTO[ch][1]; }
    if (TIT9[b]) {
      const rows = TIT9[b].map(l => [...l].map(q => q === '#' ? 1 : 0));
      return { w: rows[0].length, rows, marca, maius: b === b.toUpperCase() && b !== b.toLowerCase() };
    }
    const rows = b === 'r' ? ["....", "....", "#.##", "#...", "#...", "#...", "#..."] : (F57[b] || F57[' ']), w0 = rows[0].length, out = [],
          baixa = b === b.toLowerCase() && b !== b.toUpperCase();
    const dobra = baixa ? [3, 5] : [1, 5];
    rows.forEach((l, j) => {
      const r = new Array(w0 + 1).fill(0);
      [...l].forEach((q, i) => { if (q === '#') { r[i] = 1; r[i + 1] = 1; } });
      out.push(r); if (dobra.includes(j)) out.push(r.slice());
    });
    let x0 = w0 + 1, x1 = -1;
    out.forEach(r => r.forEach((v, i) => { if (v) { x0 = Math.min(x0, i); x1 = Math.max(x1, i); } }));
    if (x1 < 0) return { w: 3, rows: [], marca: null };
    return { w: x1 - x0 + 1, rows: out.map(r => r.slice(x0, x1 + 1)), marca, maius: b === b.toUpperCase() && b !== b.toLowerCase() };
  }
  const TIT9 = {   // linhas 0 a 8 (caixa alta 9, x de 7 a partir da 2), pernas em 9 e 10
    S: [".######", "##.....", "##.....", "##.....", ".#####.", ".....##", ".....##", ".....##", "######."],
    o: ["......", "......", ".####.", "##..##", "##..##", "##..##", "##..##", "##..##", ".####."],
    n: ["......", "......", "#####.", "##..##", "##..##", "##..##", "##..##", "##..##", "##..##"],
    s: ["......", "......", ".#####", "##....", "##....", ".####.", "....##", "....##", "#####."],
    r: ["......", "......", "##.###", "###...", "##....", "##....", "##....", "##....", "##...."],
    a: ["......", "......", ".####.", "....##", ".#####", "##..##", "##..##", "##..##", ".#####"],
    p: ["......", "......", "#####.", "##..##", "##..##", "##..##", "##..##", "##..##", "#####.", "##....", "##...."],
    i: ["##", "..", "##", "##", "##", "##", "##", "##", "##"],
    d: ["....##", "....##", ".#####", "##..##", "##..##", "##..##", "##..##", "##..##", ".#####"],
  };
  const MARCA_T = { "́": ["..##", ".##."], "̀": ["##..", ".##."], "̂": [".##.", "#..#"], "̃": [".#.#", "#.#."] };
  function larguraTit(s) { return [...s].reduce((t, ch, i) => t + (ch === ' ' ? 4 : glifoTit(ch).w) + (i ? 1 : 0), 0); }
  function titulo(P, s, x, yb, c) {
    const passa = (k, ox, oy) => {
      let pen = x;
      for (const ch of s) {
        if (ch === ' ') { pen += 5; continue; }
        const g = glifoTit(ch), top = yb - 9;
        g.rows.forEach((r, j) => r.forEach((v, i) => { if (v) px(P, pen + i + ox, top + j + oy, k); }));
        const m = g.marca && MARCA_T[g.marca];
        if (m) {
          const mx = pen + Math.ceil((g.w - m[0].length) / 2), my = g.maius ? top - 3 : top - 1;
          m.forEach((l, j) => [...l].forEach((q, i) => { if (q === '#') px(P, mx + i + ox, my + j + oy, k); }));
        }
        pen += g.w + 1;
      }
    };
    for (const [ox, oy] of [[1, 1], [2, 1], [1, 2], [2, 2]]) passa(cor(34, 20, 12), ox, oy);
    for (const [ox, oy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) passa(O, ox, oy);
    passa(c, 0, 0);
    // o segundo tom: as 4 linhas de baixo da caixa alta e do x, so dentro das letras
    const meio = cor(232, 210, 172);
    for (let y = yb - 4; y < yb + 3; y++) for (let xx = x; xx < x + larguraTit(s) + 1; xx++) {
      const i = y * P.W + xx;
      if (xx >= 0 && y >= 0 && xx < P.W && y < P.H && P.u[i] === c) P.u[i] = meio;
    }
  }
  function placa(P, x0, y0, x1, y1, k) {
    const dentro = (x, y) => { if (x < x0 || x >= x1 || y < y0 || y >= y1) return false; return Math.min(x - x0, x1 - 1 - x) + Math.min(y - y0, y1 - 1 - y) >= 2; };
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) if (!dentro(x, y) && dentro(x - 1, y - 1)) px(P, x, y, cor(34, 20, 12));
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const dx = Math.min(x - x0, x1 - 1 - x), dy = Math.min(y - y0, y1 - 1 - y);
      if (dx + dy < 2) continue;
      const luz = y === y0 + 1 || x === x0 + 1 || (dx + dy === 3 && x < (x0 + x1) / 2 && y < (y0 + y1) / 2);
      const somb = y === y1 - 2 || (dx + dy === 3 && y > (y0 + y1) / 2);
      px(P, x, y, dx + dy === 2 || dx === 0 || dy === 0 ? O : somb ? k.somb : luz ? k.luz : x === x1 - 2 ? k.dir : k.face);
    }
  }
  function desenhaPads(p) {
    const D = rectP(p.sec);
    if (!D.width) return;
    const W = Math.floor(D.width / 2), H = Math.floor(D.height / 2), M_ = 2;
    const faces = [...p.sec.querySelectorAll('.pad')].map(b => {
      const f = b.querySelector('.pad-face'), n = b.querySelector('.pad-nome');
      const F_ = relM(f, D), N_ = n ? relM(n, D) : null;
      return { b, F: F_, N: N_, nome: n ? n.textContent.trim() : '', cor: b.style.getPropertyValue('--pad').trim(),
               aceso: b.classList.contains('tocando'), aperta: b.matches(':active') || b.classList.contains('apertado'), vazio: b.classList.contains('sem-som') };
    });
    const tit = ((p.sec.querySelector('h2') || {}).textContent || I18N.t('pads.title')).trim();
    // (r05) o nome que nao cabe corta na palavra, sem reticencia ("Buzina", nao "Buzina ..."): o texto do elemento fica
    // inteiro (leitor de tela e o title do botao), o curto vai no data-curto e o CSS mostra so ele
    for (const n of p.sec.querySelectorAll('.pad-nome')) {
      const cheio = n.textContent, chave = cheio + '|' + n.clientWidth;
      if (!n.clientWidth || n.dataset.medido === chave) continue;
      n.dataset.medido = chave; delete n.dataset.curto;
      const pal = cheio.trim().split(/\s+/);
      if (pal.length < 2 || n.scrollWidth <= n.clientWidth) continue;   // a palavra unica fica como estava
      let k = pal.length - 1;
      for (; k > 1; k--) { n.textContent = pal.slice(0, k).join(' '); if (n.scrollWidth <= n.clientWidth) break; }
      n.textContent = cheio;
      n.dataset.curto = pal.slice(0, Math.max(1, k)).join(' ');
    }
    const altN = Math.round(((faces.find(f => f.N) || {}).N || { h: 20 }).h / 2);
    const chave = [altN, W, H, tit, fontesMx, faces.map(f => [f.F.x0, f.F.y0, f.F.x1, f.N ? f.N.y0 : '', f.nome, f.cor, f.aceso, f.aperta, f.vazio].join(',')).join(';')].join('|');
    if (chave === p.chave) return;
    p.chave = chave;
    const P = pincel(W + M_, H + M_);
    sombraCaixa(P, 0, 0, W, H, 2, 2, 2);   // a sombra da caixa na parede
    const E = 7, L = 13;
    moldura(P, W, H, E, L);
    // o titulo: o de 9 se cabe, senao o negrito de 7
    const tw = larguraTit(tit), yb = E + 15;
    const ocupado = [];
    if (tw <= W - 2 * (E + 3)) { ocupado.push([Math.floor((W - tw) / 2) - 1, yb - 12, Math.floor((W - tw) / 2) + tw + 2, yb + 3]); }
    else { const t2 = larg('fb', tit) - 1; ocupado.push([Math.floor((W - t2) / 2) - 1, yb - 9, Math.floor((W - t2) / 2) + t2 + 2, yb + 3]); }
    for (const f of faces) {
      const S = f.F.x1 - f.F.x0;
      ocupado.push([f.F.x0 - 1, f.F.y0 - 1, f.F.x0 + S + 2, f.F.y0 + S + 2]);
      const ny = f.N ? f.N.y0 : f.F.y0 + S + 2;
      ocupado.push([f.F.x0 - 1, ny - 1, f.F.x0 + S + 2, ny + 12]);
    }
    const livre = (x, y) => !ocupado.some(q => x >= q[0] && x < q[2] && y >= q[1] && y < q[3]);
    // o fundo escuro rebaixado: a sombra da moldura em cima e a esquerda, o filete claro embaixo e a direita, e so manchas
    // escuras deitadas de 2 a 3, raras, longe dos contornos
    for (let y = E; y < H - E; y++) for (let x = E; x < W - E; x++) {
      let c = PAINEL.b;
      if (y === E || x === E) c = PAINEL.somb;
      else if ((y === E + 1 && x > E) || (x === E + 1 && y > E)) c = PAINEL.somb2;
      else if (y === H - E - 1 || x === W - E - 1) c = PAINEL.luz;
      px(P, x, y, c);
    }
    // o couro liso: as manchas so cabiam na faixa de baixo e liam como uma fileira solta (r02)
    for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) cantoneira(P, W, H, sx, sy, L, 5);
    if (tw <= W - 2 * (E + 3)) titulo(P, tit, Math.floor((W - tw) / 2), yb, cor(252, 242, 220));
    else { const t2 = larg('fb', tit) - 1; texto(P, 'fb', tit, Math.round((W - t2) / 2), yb, CREME_L, { sombra: O }); }
    // os pads e as plaquinhas
    for (const f of faces) {
      const S = f.F.x1 - f.F.x0, dy = f.aperta && !f.vazio ? 1 : 0;
      if (!dy) for (let j = 1; j <= S; j++) for (let i = 1; i <= S; i++) {
        const den = (a, b) => a >= 0 && b >= 0 && a < S && b < S && Math.min(a, S - 1 - a) + Math.min(b, S - 1 - b) >= 3;
        if (!den(i, j) && den(i - 1, j - 1)) px(P, f.F.x0 + i, f.F.y0 + j, cor(34, 20, 12));
      }
      pad(P, f.F.x0, f.F.y0 + dy, S, f.vazio ? 0 : hexCor(f.cor || '#888888'), f.aceso, f.vazio);
      const ny0 = f.N ? f.N.y0 : f.F.y0 + S + 2, nx0 = f.F.x0, nx1 = f.F.x0 + S, ny1 = ny0 + altN;
      placa(P, nx0, ny0, nx1, ny1, f.vazio ? { face: cor(76, 64, 52), luz: cor(90, 78, 64), somb: cor(62, 51, 44), dir: cor(68, 57, 46) } : PLACA);
    }
    p.cv.width = W + M_; p.cv.height = H + M_; p.cv.style.width = 2 * (W + M_) + 'px'; p.cv.style.height = 2 * (H + M_) + 'px';
    const img = p.ctx.createImageData(W + M_, H + M_);
    new Uint32Array(img.data.buffer).set(P.u);
    p.ctx.putImageData(img, 0, 0);
  }
  // ---------------- o visor de DJ: o gabinete de madeira com as cantoneiras de latao, a moldura escura do tubo em volta do
  // vidro, e no painel da direita a luz vermelha, os dois botoes e a grade do alto-falante. O vidro e o que ele mostra
  // seguem os de antes (pedido dele, 06/11: so o de fora muda); a geometria sai da tela e das leituras de dentro
  let tvp = null;
  function preparaTv(sec) {
    if (tvp && tvp.sec === sec) return tvp;
    const cv = document.createElement('canvas');
    cv.className = 'tv-px'; cv.setAttribute('aria-hidden', 'true'); sec.prepend(cv);
    tvp = { sec, cv, ctx: cv.getContext('2d'), chave: '' };
    sec.classList.add('px-ok');
    return tvp;
  }
  const VIDRO = cor(11, 8, 7), CARVAO = cor(22, 20, 19);
  // a madeira do gabinete, puxada para o marrom do mock; tudo opaco (a sombra de contato e a propria lateral escura)
  const MT = { face: cor(152, 84, 52), luz: cor(222, 152, 112), escuro: cor(96, 48, 26), lado: cor(116, 60, 34), dir: cor(130, 70, 42),
               veio: cor(134, 72, 44), veioM: cor(116, 60, 34), veioP: cor(143, 78, 48), veioC: cor(172, 102, 66), friso: cor(186, 116, 78) };
  const LAT = { face: cor(222, 170, 70), luz: cor(246, 212, 120), dobra: cor(166, 108, 34), escuro: cor(116, 72, 22), brilho: cor(255, 250, 205) };
  // a moldura do tubo: as faixas de fora (1) para dentro (4) depois do contorno, com a luz (L, e LL no primeiro terco do
  // topo e da esquerda), o meio (M, nas quinas que viram) e a sombra (S); o recesso entre o chanfro da abertura e o arco
  const TK = cor(28, 18, 13), TD = cor(26, 16, 10), TM = cor(54, 32, 20), TS = cor(40, 24, 15);
  const TUBO = { L: [TM, TM, TM, TD], LL: cor(90, 58, 36), LM: cor(72, 44, 26), M: [TM, TM, cor(33, 20, 12), TD], S: [cor(33, 20, 12), cor(33, 20, 12), TS, cor(72, 44, 26)] };
  void TK;
  const ARCO = [5, 3, 2, 1, 1];   // o arco de fora da moldura (o recorte por linha a partir da quina): degraus 2-1-1-2
  const QVIDRO = { t: [5, 3, 2, 1, 1], b: [5, 3, 2, 1, 1] };   // a quina do vidro, em cima e embaixo (o selo A embaixo a esquerda)
  // dentro do retangulo R = [x0, y0, x1, y1) com as quinas recortadas pela tabela T (T[j] celulas na linha j de cada quina)
  function dentroT(x, y, R, T) {
    if (x < R[0] || y < R[1] || x >= R[2] || y >= R[3]) return false;
    const i = Math.min(x - R[0], R[2] - 1 - x), j = Math.min(y - R[1], R[3] - 1 - y);
    const t = Array.isArray(T) ? T : (y - R[1] <= R[3] - 1 - y ? T.t : T.b);
    return !(j < t.length && i < t[j]);
  }
  // dentro do retangulo redondo de raio r (o gabinete), crescido de k (k negativo encolhe)
  function arred(x, y, R, r, k = 0) {
    const x0 = R[0] - k, y0 = R[1] - k, x1 = R[2] + k, y1 = R[3] + k, rr = Math.max(0, r + k);
    if (x < x0 || y < y0 || x >= x1 || y >= y1) return false;
    const cx = x < x0 + rr ? x0 + rr : x > x1 - 1 - rr ? x1 - 1 - rr : x, cy = y < y0 + rr ? y0 + rr : y > y1 - 1 - rr ? y1 - 1 - rr : y;
    return Math.hypot(x - cx, y - cy) <= rr + .4;
  }
  // o lado da borda mais perto: 't' em cima, 'b' embaixo, 'l' a esquerda, 'r' a direita
  const lado = (x, y, R) => {
    const ex = Math.min(x - R[0], R[2] - 1 - x), ey = Math.min(y - R[1], R[3] - 1 - y);
    return ey <= ex ? (y < (R[1] + R[3]) / 2 ? 't' : 'b') : (x < (R[0] + R[2]) / 2 ? 'l' : 'r');
  };
  const daLuz = l => l === 't' || l === 'l';
  // para onde a borda de R olha (pela quina de raio r): 1 para a luz de cima e da esquerda, -1 para o outro lado, 0 de lado
  const luzD = (x, y, R, r) => {
    const cx = Math.min(Math.max(x, R[0] + r), R[2] - 1 - r), cy = Math.min(Math.max(y, R[1] + r), R[3] - 1 - r), nx = x - cx, ny = y - cy;
    return nx || ny ? -(nx + ny) / (Math.hypot(nx, ny) * Math.SQRT2) : 0;
  };
  const olhaLuz = (x, y, R, r) => {
    const cx = Math.min(Math.max(x, R[0] + r), R[2] - 1 - r), cy = Math.min(Math.max(y, R[1] + r), R[3] - 1 - r);
    let nx = x - cx, ny = y - cy;
    if (!nx && !ny) { const l = lado(x, y, R); nx = l === 'l' ? -1 : l === 'r' ? 1 : 0; ny = l === 't' ? -1 : l === 'b' ? 1 : 0; }
    const d = -(nx + ny) / (Math.hypot(nx, ny) * Math.SQRT2);
    return d > .35 ? 1 : d < -.35 ? -1 : 0;
  };
  // um sprite redondo de diametro n (impar), em camadas de fora para dentro: corDe(camada, dx, dy) por celula, com a sombra
  // de contato de 1 celula embaixo e a direita
  function redondo(P, x0, y0, n, corDe, perfil = null) {
    const c = (n - 1) / 2, r2 = (c + .5) * (c + .5);
    const den = (i, j) => i >= 0 && j >= 0 && i < n && j < n && (perfil ? Math.abs(i - c) <= (perfil[j] - 1) / 2 : (i - c) ** 2 + (j - c) ** 2 <= r2);
    const cam = new Int8Array(n * n).fill(-1);
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) if (den(i, j)) cam[j * n + i] = 99;
    for (let k = 0; k < n; k++) for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      if (cam[j * n + i] !== 99) continue;
      const v = (a, b) => (a < 0 || b < 0 || a >= n || b >= n) ? -1 : cam[b * n + a];
      if ([v(i - 1, j), v(i + 1, j), v(i, j - 1), v(i, j + 1)].some(q => q !== 99 && q < k)) cam[j * n + i] = k;
    }
    for (let j = 0; j <= n; j++) for (let i = 0; i <= n; i++) if (!den(i, j) && den(i - 1, j - 1)) px(P, x0 + i, y0 + j, MT.lado);
    for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
      const k = cam[j * n + i];
      if (k < 0) continue;
      const cc = corDe(k, i - c, j - c);
      if (cc) px(P, x0 + i, y0 + j, cc);
    }
  }
  // o gabinete: contorno, a luz de 1 em cima e a esquerda, a espessura escura de 2 embaixo e de 1 a direita, a face, e a
  // borda da abertura (o mesmo arco da moldura): 1 celula de sombra em cima e a esquerda, de luz embaixo e a direita
  function gabinete(P, W, H, B) {
    const R = [0, 0, W, H], naB = (x, y) => dentroT(x, y, B, ARCO);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      if (!arred(x, y, R, 3) || naB(x, y)) continue;
      const l = lado(x, y, R);
      let c = MT.face;
      if (!arred(x, y, R, 3, -1)) c = O;
      else if (!arred(x, y, R, 3, -2)) c = daLuz(l) ? MT.luz : MT.escuro;
      else if (!arred(x, y, R, 3, -3) && !daLuz(l)) c = MT.lado;
      if (c === MT.face && [[0, -1], [-1, 0], [1, 0], [0, 1]].some(([a, b]) => naB(x + a, y + b))) {
        const o = olhaLuz(x, y, B, 5);
        c = o > 0 ? MT.escuro : o < 0 ? MT.luz : luzD(x, y, B, 5) < 0 ? MT.friso : MT.veio;
      }
      px(P, x, y, c);
    }
  }
  // os veios: fibras de 1 a 3 tracos de 8 a 24 celulas com quebras de 2 a 4, o miolo mais escuro de 1 a 2 numa ponta e as
  // vezes um fio claro do lado, nas linhas (deitadas) e colunas (em pe) dadas; so em celula de face, sem encostar de lado
  // em contorno ou em sombra de controle
  function veios(P, linhas, colunas) {
    const hsM = (a, b, c = 0) => {
      let h = Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263) + Math.imul(c | 0, 1274126177);
      h = Math.imul(h ^ (h >>> 13), 1274126177);
      return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
    };
    const f0 = (a, b) => a >= 0 && b >= 0 && a < P.W && b < P.H && P.u[b * P.W + a] === MT.face;
    const duro = new Set([O, CARVAO, MT.lado, MT.escuro, MT.friso, LAT.face, LAT.luz]);
    const livre = (a, b) => !(a >= 0 && b >= 0 && a < P.W && b < P.H) || !duro.has(P.u[b * P.W + a]);
    const VEIO = new Set([MT.veio, MT.veioM, MT.veioP]);
    const ve = (a, b) => a >= 0 && b >= 0 && a < P.W && b < P.H && VEIO.has(P.u[b * P.W + a]);
    const sob = (a, b) => ve(a, b - 1) || ve(a, b + 1);
    const fibra = (ini, fim, fixo, deitado, semente, loose) => {
      let p = ini + Math.floor(hsM(semente, 0, 91) * 14), n = 0;
      while (p < fim) {
        const tracos = 2 + Math.floor(hsM(semente, n, 92) * 3);
        for (let t = 0; t < tracos && p < fim; t++, n++) {
          const len = 3 + Math.floor(hsM(semente, n, 93) * (deitado ? 12 : 4)), cel = [];
          for (let u = 0; u < len && p + u < fim; u++) cel.push(deitado ? [p + u, fixo] : [fixo, p + u]);
          // o traco aparece so nos trechos livres de 3 ou mais (entre os controles, ele some e volta)
          const deg = deitado && len >= 8 && hsM(semente, n, 88) < .3 ? (hsM(semente, n, 87) < .5 ? -1 : 1) : 0;
          if (deg) for (let u = Math.floor(cel.length / 2); u < cel.length; u++) cel[u] = [cel[u][0], cel[u][1] + deg];
          const bom = ([a, b]) => f0(a, b) && (loose || (deitado ? livre(a, b - 1) && livre(a, b + 1) : livre(a - 1, b) && livre(a + 1, b)))
            && !(deitado && sob(a, b) && sob(a - 1, b) && sob(a + 1, b));
          const trechos = [];
          let cur = [];
          for (const q of cel) { if (bom(q)) cur.push(q); else { if (cur.length) trechos.push(cur); cur = []; } }
          if (cur.length) trechos.push(cur);
          trechos.filter(tr => tr.length >= 3).forEach((tr, m) => {
            const sorte = hsM(semente, n + m, 85), tom = sorte < .3 && deitado ? MT.veioM : sorte < .75 ? MT.veio : MT.veioP;
            tr.forEach(([a, b], u) => px(P, a, b, tr.length >= 5 && (u === 0 || u === tr.length - 1) ? MT.veioP : tom));
            if (deitado && tom === MT.veio && hsM(semente, n + m, 86) < .25) for (const [a, b] of tr.slice(0, 2)) if (f0(a, b + 1)) px(P, a, b + 1, MT.veioC);
            if (tr.length >= 8 && hsM(semente, n + m, 96) < .35) {
              const [a, b] = tr[Math.floor(tr.length / 2)], [la, lb] = deitado ? [a, b - 1] : [a - 1, b];
              for (let u = -2; u <= 2; u++) { const qa = deitado ? la + u : la, qb = deitado ? lb : lb + u; if (f0(qa, qb)) px(P, qa, qb, MT.veioC); }
            }
          });
          p += len + (deitado ? 1 : 3 + Math.floor(hsM(semente, n, 94) * 3));
        }
        p += 20 + Math.floor(hsM(semente, n, 98) * 26);
      }
    };
    linhas.forEach(([y, x0, x1], i) => fibra(x0, x1, y, true, 300 + i * 7 + y, false));
    colunas.forEach(([x, y0, y1, loose], i) => fibra(y0, y1, x, false, 700 + i * 11 + x, !!loose));
  }
  // a moldura do tubo: o arco de fora (ARCO) em contorno e 4 faixas contadas por erosao de 8 vizinhos a partir dele (cada
  // faixa repete o arco, sem chanfro); o vidro com a quina QVIDRO manda. O brilho da faixa 2 so num arco de ~12 celulas em
  // volta da quina de cima a esquerda, com 2 celulas de meio-tom
  function moldTubo(P, B, G) {
    const W_ = B[2] - B[0], H_ = B[3] - B[1], cam = new Int8Array(W_ * H_).fill(-1), crista = new Set();
    for (let y = 0; y < H_; y++) for (let x = 0; x < W_; x++) if (dentroT(B[0] + x, B[1] + y, B, ARCO)) cam[y * W_ + x] = 99;
    const v = (x, y) => (x < 0 || y < 0 || x >= W_ || y >= H_) ? -1 : cam[y * W_ + x];
    for (let y = 0; y < H_; y++) for (let x = 0; x < W_; x++)
      if (cam[y * W_ + x] === 99 && [v(x - 1, y), v(x + 1, y), v(x, y - 1), v(x, y + 1)].some(q => q < 0)) cam[y * W_ + x] = 0;
    for (let k = 1; k < 5; k++) for (let y = 0; y < H_; y++) for (let x = 0; x < W_; x++) {
      if (cam[y * W_ + x] !== 99) continue;
      let borda = false;
      for (let b = -1; b <= 1 && !borda; b++) for (let a = -1; a <= 1; a++) { const q = v(x + a, y + b); if (q !== 99 && q < k) { borda = true; break; } }
      if (borda) cam[y * W_ + x] = k;
    }
    for (let y = B[1]; y < B[3]; y++) for (let x = B[0]; x < B[2]; x++) {
      const k = cam[(y - B[1]) * W_ + (x - B[0])];
      if (k < 0) continue;
      let c;
      if (dentroT(x, y, G, QVIDRO)) c = VIDRO;
      else if (k === 0) c = O;
      else {
        const colaVidro = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([a, b]) => dentroT(x + a, y + b, G, QVIDRO));
        const f = colaVidro ? 4 : Math.min(4, k), o = olhaLuz(x, y, G, 3), l = lado(x, y, G);
        c = (o > 0 ? TUBO.L : o < 0 ? TUBO.S : TUBO.M)[f - 1];
        const bx = x - B[0], by = y - B[1];
        if (o >= 0 && f === 2 && [v(bx - 1, by), v(bx + 1, by), v(bx, by - 1), v(bx, by + 1)].some(q => q === 1)) {
          c = l === 't' || l === 'l' ? TUBO.LL : TUBO.LM;   // a crista inteira no claro, o meio-tom na quina que vira
          crista.add(x + ',' + y);
        }
      }
      px(P, x, y, c);
    }
    for (let y = B[1]; y < B[3]; y++) for (let x = B[0]; x < B[2]; x++) {
      if (P.u[y * P.W + x] !== TD) continue;
      const vz = [[1, 0], [-1, 0], [0, 1], [0, -1]].filter(([a, b]) => P.u[(y + b) * P.W + x + a] === TD).length;
      if (!vz) P.u[y * P.W + x] = TS;
    }
    for (let y = B[1]; y < B[3]; y++) for (let x = B[0]; x < B[2]; x++) {
      const c = P.u[y * P.W + x], e = P.u[y * P.W + x - 1], d = P.u[y * P.W + x + 1], u = P.u[(y - 1) * P.W + x], b = P.u[(y + 1) * P.W + x];
      if (c === TM && ((e === TD && d === TD) || (u === TD && b === TD))) P.u[y * P.W + x] = TS;
      else if (c === TD && [e, d, u, b].every(q => q === TM || q === TS)) P.u[y * P.W + x] = TM;
    }
    for (let y = B[1]; y < B[3]; y++) for (let x = B[0]; x < B[2]; x++) {
      if (P.u[y * P.W + x] !== TUBO.S[3] || crista.has(x + ',' + y)) continue;
      if (![[1, 0], [-1, 0], [0, 1], [0, -1]].some(([a, b]) => P.u[(y + b) * P.W + x + a] === VIDRO)) { P.u[y * P.W + x] = TS; continue; }
      if ([[1, 0], [-1, 0], [0, 1], [0, -1]].some(([a, b]) => P.u[(y + b) * P.W + x + a] === TD)) P.u[y * P.W + x] = TM;
    }
    const acerto = (ox, oy, lista, c) => lista.forEach(([a, b]) => { P.u[(oy + b) * P.W + ox + a] = c; });
    const quinas = () => {
      const TR = [B[2] - 1, B[1]], BL = [B[0], B[3] - 1], TL = [B[0], B[1]];
      acerto(...TR, [[-6, 4], [-5, 4]], TM);
      acerto(...TR, [[-5, 5], [-4, 5], [-4, 6], [-3, 6], [-2, 5], [-4, 8], [-4, 9]], TS);
      acerto(...BL, [[4, -5], [5, -5]], TM);
      acerto(...BL, [[5, -4], [6, -4], [6, -3]], TS);
      acerto(...BL, [[7, -5]], TD);
      acerto(...TL, [[6, 7]], TD);
      acerto(...TR, [[-6, 7]], TD);
      acerto(...TL, [[8, 4], [9, 4], [6, 5], [7, 5], [5, 6], [4, 7], [4, 8], [4, 9]], TM);
      acerto(...TR, [[-9, 4], [-8, 4], [-3, 4]], TM);
      acerto(...TR, [[-7, 5], [-6, 5], [-5, 6]], TS);
      acerto(...TR, [[-5, 7]], TUBO.S[3]);
      acerto(...BL, [[4, -7]], TD);
      acerto(...BL, [[4, -6]], TM);
    };
    // as pontas da crista (as celulas com um vizinho so) apagam em 2 celulas de meio-tom escuro
    const viz8 = (x, y) => [[-1, -1], [0, -1], [1, -1], [-1, 0], [1, 0], [-1, 1], [0, 1], [1, 1]].map(([a, b]) => [x + a, y + b]).filter(([a, b]) => crista.has(a + ',' + b));
    for (const key of crista) {
      const [x, y] = key.split(',').map(Number), vz = viz8(x, y);
      if (vz.length !== 1) continue;
      P.u[y * P.W + x] = TS;
      const [a, b] = vz[0];
      P.u[b * P.W + a] = TS;
    }
    quinas();
  }
  // a cantoneira de latao: o pentagono de pernas de 11 que abraca a quina do gabinete (2 celulas para fora dele), a diagonal
  // de dentro longe da abertura e as pontas retas; contorno, a luz de 1 nas bordas que olham para cima e para a esquerda, a
  // dobra escura nas que olham para baixo e para a direita; a sombra de contato na madeira (sem encostar no labio) e, fora
  // do gabinete, na mesa; o rebite em cupula com a sombra em latao. Desenha no pincel com a margem M (o gabinete em M, M)
  function cantoneiraTv(P, W, H, sx, sy, M) {
    const X = i => sx < 0 ? M - 1 + i : M + W - i, Y = j => sy < 0 ? M - 1 + j : M + H - j;
    const den = (i, j) => i >= 0 && j >= 0 && i <= 10 && j <= 10 && i + j >= 2 && i + j <= 13;
    const tela = new Set();
    for (let j = 0; j <= 10; j++) for (let i = 0; i <= 10; i++) if (den(i, j)) tela.add(X(i) + ',' + Y(j));
    const tem = (x, y) => tela.has(x + ',' + y);
    const madeira = new Set([MT.face, MT.veio, MT.veioM, MT.veioC, MT.veioP]);
    for (const key of tela) {
      const [x, y] = key.split(',').map(Number), a = x + 1, b = y + 1;
      if (tem(a, b) || a >= P.W || b >= P.H) continue;
      const q = P.u[b * P.W + a], viz = [[0, -1], [-1, 0], [1, 0], [0, 1]].map(([p, r]) => P.u[(b + r) * P.W + a + p]);
      if (madeira.has(q) || q === MT.luz) { if ((tem(a - 1, b) || tem(a, b - 1)) && !viz.includes(MT.escuro)) px(P, a, b, MT.lado); }
      else if (!(q >>> 24) || q === SOMBRA) px(P, a, b, SOMBRA);
      const a2 = x + 2, b2 = y + 2;
      if (!tem(a2, b2) && a2 < P.W && b2 < P.H) { const q2 = P.u[b2 * P.W + a2]; if (!(q2 >>> 24)) px(P, a2, b2, SOMBRA); }
    }
    for (const key of tela) {
      const [x, y] = key.split(',').map(Number);
      let c = LAT.face;
      if (!tem(x - 1, y) || !tem(x + 1, y) || !tem(x, y - 1) || !tem(x, y + 1)) c = O;
      else {
        const luz = !tem(x, y - 2) || !tem(x - 2, y) || !tem(x - 1, y - 1), somb = !tem(x, y + 2) || !tem(x + 2, y) || !tem(x + 1, y + 1);
        if (luz && !somb) c = LAT.luz;
        else if (somb && !luz) c = LAT.dobra;
      }
      P.u[y * P.W + x] = c;
    }
    const x0 = Math.min(X(3), X(6)), y0 = Math.min(Y(3), Y(6)), kr = { W: LAT.brilho, L: LAT.luz, a: LAT.dobra, m: LAT.face, d: cor(116, 72, 15) };
    [".aa.", "aWLd", "aLmd", ".dd."].forEach((ln, b) => [...ln].forEach((q, a) => { if (q !== '.') P.u[(y0 + b) * P.W + x0 + a] = kr[q]; }));
  }
  // a luz: o aro de metal continuo com o contorno carvao e a lente redonda (borda vinho, o brilho de 2 no alto a esquerda, a
  // sombra de dentro embaixo a direita); acesa, o brilho em volta
  function luzTv(P, x0, y0, acesa) {
    if (acesa) for (let j = -2; j < 11; j++) for (let i = -2; i < 11; i++) {
      const r = Math.hypot(i - 4, j - 4);
      if (r > 4.6 && r <= 6.2) px(P, x0 + i, y0 + j, cor(255, 70, 50, r <= 5.4 ? 100 : 50));
    }
    const L = acesa ? { borda: cor(176, 32, 22), base: cor(236, 58, 40), meio: cor(255, 130, 100), brilho: cor(255, 236, 226) }
                    : { borda: cor(74, 18, 14), base: cor(118, 30, 24), meio: cor(168, 58, 48), brilho: cor(204, 128, 116) };
    redondo(P, x0, y0, 9, (k, dx, dy) => {
      if (k === 0) return CARVAO;
      if (k === 1) {
        if (dx === -1 && dy === -3) return cor(212, 206, 196);   // o reflexo do aro
        return dx + dy < -2 ? cor(176, 170, 162) : dx + dy > 2 ? cor(96, 90, 84) : cor(138, 132, 126);
      }
      if (dx === -1 && dy === -1) return L.brilho;
      if ((dx === -2 && dy === -1) || (dx === -1 && dy === -2)) return L.meio;
      if (k === 2) return dx + dy >= 0 ? L.borda : L.base;   // a borda da lente escurece embaixo a direita
      if (dx + dy >= 2) return L.borda;   // o crescente de sombra
      return L.base;
    }, [3, 7, 7, 9, 9, 9, 7, 7, 3]);
  }
  // o botao preto: o bisel claro em cima e a esquerda, a lateral escura embaixo e a direita, o quadrante de cima um tom acima,
  // o brilho de 1 (com 2 de meio-tom) no alto a esquerda, o crescente de sombra, o ponteiro claro do centro para a borda e
  // tres marcas de 2 em arco
  function botaoTv(P, x0, y0, ang = -60) {
    const n = 11, c = 5;
    for (const [dx, dy] of [[0, -8], [0, -7], [-5, -5], [5, -5]]) px(P, x0 + c + dx, y0 + c + dy, LAT.face);
    redondo(P, x0, y0, n, (k, dx, dy) => {
      const s = dx + dy;
      if (k === 0) return cor(18, 17, 16);
      if (k === 1) return s < -1 ? cor(150, 146, 142) : s > 1 ? cor(36, 34, 33) : cor(95, 92, 89);   // o anel de metal
      const q = dx + ',' + dy;
      if (q === '-2,-2') return cor(150, 146, 142);   // o brilho de cupula, longe do ponteiro
      if (q === '-3,-2' || q === '-3,-1' || q === '-3,0' || q === '-2,0' || q === '-2,-1') return cor(95, 92, 89);
      const fundo = s >= 2 ? Math.floor((s - 2) / 2) : -1;   // a espessura do crescente cresce com a diagonal
      if (k - 2 <= fundo) return cor(36, 34, 33);   // o crescente de sombra
      if (s >= 1 && k - 2 <= fundo + 1) return cor(47, 45, 43);
      return cor(62, 59, 57);
    });
    // o ponteiro, do centro para a marca: em pe (-90) ou para a de 1h (-60)
    const rastro = ang === -90 ? [[0, 0], [0, -1], [0, -2]] : [[0, 0], [1, -1], [2, -2]];
    rastro.forEach(([a, b], r) => px(P, x0 + c + a, y0 + c + b, r === rastro.length - 1 ? cor(212, 206, 196) : cor(248, 244, 236)));   // o ponteiro, do centro para a borda
  }
  // a grade: fendas em capsula (o miolo quase preto de 2 com o contorno nas pontas) e o labio claro de 9 embaixo
  function gradeTv(P, x0, y0, n) {
    for (let s = 0; s < n; s++) {
      const y = y0 + s * 5;
      for (let x = x0 + 1; x < x0 + 10; x++) px(P, x, y, O);
      for (let x = x0; x < x0 + 11; x++) px(P, x, y + 1, x === x0 || x === x0 + 10 ? O : cor(40, 17, 7));
      for (let x = x0 + 1; x < x0 + 10; x++) px(P, x, y + 2, x === x0 + 1 || x === x0 + 9 ? O : cor(56, 25, 11));
      for (let x = x0 + 1; x < x0 + 10; x++) px(P, x, y + 3, MT.friso);
    }
  }
  // o painel rebaixado da coluna: o friso escuro em cima e a esquerda, o claro embaixo e a direita
  function painelTv(P, x0, y0, x1, y1) {
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const dTL = (x - x0) + (y - y0), dTR = (x1 - 1 - x) + (y - y0), dBL = (x - x0) + (y1 - 1 - y), dBR = (x1 - 1 - x) + (y1 - 1 - y);
      if (dTL < 3 || dTR < 3 || dBL < 3 || dBR < 3) continue;   // a madeira fica
      if (dBR === 3 || (dTR === 3 && x === x1 - 1) || (dBL === 3 && y === y1 - 1)) px(P, x, y, MT.friso);
      else if (dTL === 3 || dTR === 3 || dBL === 3) px(P, x, y, MT.escuro);
      else if (y === y0 || x === x0) px(P, x, y, MT.escuro);
      else if (y === y1 - 1 || x === x1 - 1) px(P, x, y, MT.friso);
    }
  }
  function desenhaTv(t) {
    const D0 = rectP(t.sec);
    if (!D0.width) return;
    const EX = 0, D = { left: D0.left - 2 * EX, top: D0.top, width: D0.width + 2 * EX, height: D0.height };   // no prumo do mixer e dos pads (EX = 1 passava 1 celula na esquerda)
    const W = Math.ceil(D.width / 2 - .05), H = Math.ceil(D.height / 2 - .05), M_ = 2;   // a caixa toda, sem a fresta da parede
    const q = s => t.sec.querySelector(s);
    const tl = q('#tv-tela'), le = q('#tv-leituras'), luz = q('#tv-luz');
    if (!tl || !le || !luz) return;
    const T = relM(tl, D), Lt = relM(le, D);
    const acesa = /alerta|acesa/.test(luz.className);
    const chave = [W, H, T.x0, T.y0, T.x1, Lt.y1, acesa].join('|');
    if (chave === t.chave) return;
    t.chave = chave;
    // o vidro (1 celula alem da tela e das leituras, 2 em cima), a moldura de 5 em volta e a abertura na madeira, que e a
    // moldura com as quinas chanfradas
    const G = [Math.min(T.x0, Lt.x0) - 1, T.y0 - 2, Math.max(T.x1, Lt.x1) + 1, Lt.y1 + 1], B = [G[0] - 5, G[1] - 5, G[2] + 5, G[3] + 5];
    // o painel da direita, alinhado com a borda da abertura em cima e embaixo, e a pilha centrada nele
    const Pn = [B[2] + 3, B[1] + 2, W - 4, B[3] - 1], cx = Math.floor((Pn[0] + Pn[2]) / 2);
    // de cima para baixo: a luz (11 e 1 de sombra), as marcas (3) e o botao (13 e 1), as marcas e o outro botao, as fendas;
    // os cinco vaos iguais
    const nG = 6, conteudo = 10 + 3 + 12 + 3 + 12 + (5 * nG - 1), vao = Math.max(2, Math.floor((Pn[3] - Pn[1] - 2 - conteudo) / 5));
    const sobra = Pn[3] - Pn[1] - 2 - conteudo - 5 * vao;
    const yL = Pn[1] + 1 + vao + Math.floor(sobra / 2), yK1 = yL + 10 + vao + 3, yK2 = yK1 + 12 + vao + 3, yG = yK2 + 12 + vao;
    const P = pincel(W + M_, H + M_);
    sombraCaixa(P, 0, 0, W, H, 2, 2, 2);
    gabinete(P, W, H, B);
    painelTv(P, Pn[0], Pn[1], Pn[2], Pn[3]);
    moldTubo(P, B, G);
    luzTv(P, cx - 4, yL, acesa);
    botaoTv(P, cx - 5, yK1);
    botaoTv(P, cx - 5, yK2, -90);
    gradeTv(P, cx - 5, yG, nG);
    // um no de 2 por regua, no sentido do veio
    for (const [a, b, dx, dy] of [[Math.round(W * .63), H - 5, 1, 0], [Math.round(W * .3), 3, 1, 0], [2, Math.round(H * .55), 0, 1], [W - 5, Math.round(H * .4), 0, 1]])
      if (P.u[b * P.W + a] === MT.face && P.u[(b + dy) * P.W + a + dx] === MT.face) { px(P, a, b, MT.veioM); px(P, a + dx, b + dy, MT.veioM); }
    veios(P, [[2, 30, W - 8], [3, 8, W - 8], [4, 14, W - 8], [H - 6, 8, W - 8], [H - 5, 20, W - 8], [H - 4, 8, W - 8]],
          [[2, 9, H - 9], [3, 16, H - 16, true], [W - 3, 12, H - 12, true], [B[2] + 1, B[1] + 4, B[3] - 4, true]]);
    const okP = new Set([MT.face, MT.escuro, MT.friso, MT.veio, MT.veioP]);
    for (const [x, sem] of [[Pn[0] + 1, 41], [Pn[2] - 2, 43]]) {
      let y = Pn[1] + 3 + Math.floor(ruido(sem, 0, 81) * 6), n = 0;
      while (y < Pn[3] - 3) {
        const len = 3 + Math.floor(ruido(sem, n, 82) * 3), tr = [];
        for (let u = 0; u < len && y + u < Pn[3] - 3; u++) {
          const yy = y + u;
          let ok = P.u[yy * P.W + x] === MT.face;
          for (let b = -1; b <= 1 && ok; b++) for (let a = -1; a <= 1; a++) if (!okP.has(P.u[(yy + b) * P.W + x + a])) { ok = false; break; }
          if (ok) tr.push(yy);
        }
        tr.forEach(yy => px(P, x, yy, MT.veio));
        y += len + 2 + Math.floor(ruido(sem, n, 83) * 4); n++;
      }
    }
    // as cantoneiras passam 2 celulas para fora do gabinete: o canvas ganha a margem MG em volta
    const MG = 2, Q = pincel(W + M_ + 2 * MG, H + M_ + 2 * MG);
    for (let y = 0; y < P.H; y++) Q.u.set(P.u.subarray(y * P.W, (y + 1) * P.W), (y + MG) * Q.W + MG);
    for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) cantoneiraTv(Q, W, H, sx, sy, MG);
    t.cv.width = Q.W; t.cv.height = Q.H; t.cv.style.width = 2 * Q.W + 'px'; t.cv.style.height = 2 * Q.H + 'px';
    t.cv.style.left = -2 * (MG + EX) + 'px'; t.cv.style.top = -2 * MG + 'px';
    const img = t.ctx.createImageData(Q.W, Q.H);
    new Uint32Array(img.data.buffer).set(Q.u);
    t.ctx.putImageData(img, 0, 0);
  }
  // ---------------- as pedaleiras: o painel de feltro marrom escuro pendurado (mock de 20/11), so em volta da fileira
  // de pedais (o banco), com o vao dos lados e em cima para os cabos (os do medirCabosBanco): o contorno com o canto em
  // degrau, o bisel de 1 (claro em cima e a esquerda, escuro embaixo e a direita), a beira do feltro afundada mais 1, o
  // feltro em manchas largas com o grao escuro e o claro soltos, e a sombra dura das outras pecas
  const GAV = { o: O, luz: cor(88, 78, 68), esc: cor(22, 18, 15), luz2: cor(60, 52, 45), esc2: cor(29, 24, 21),
                t: cor(42, 35, 30), t2: cor(48, 40, 34), t3: cor(37, 31, 26), tE: cor(29, 24, 20), tL: cor(64, 55, 47) };
  const gavs = new Map();
  function desenhaGav(g) {
    let q = gavs.get(g);
    if (!q) {
      const cv = document.createElement('canvas');
      cv.className = 'gav-px'; cv.setAttribute('aria-hidden', 'true'); g.prepend(cv);
      q = { cv, ctx: cv.getContext('2d') };
      gavs.set(g, q); g.classList.add('gav-ok');
    }
    const D = rectP(g), bc = g.querySelector('.banco'), B = bc && bc.offsetWidth ? rectP(bc) : D;
    const W = Math.round(D.width / 2), H = Math.round(D.height / 2), M_ = 2;
    if (W < 20 || H < 20) return;
    // o painel do banco: de 8 celulas abaixo do topo (em cima correm os cabos dos pedais; revisao da r09, a pedaleira 8
    // px mais baixa) ate o fundoDoFeltro, 16 px embaixo do Troca de voz (que desce 18 px alem dos outros) ou 20 embaixo
    // dos comuns, passando do pe da gaveta se precisar: o mesmo fundo nas duas. A chave fica no canvas: o repintarCanvas
    // a zera
    const x0 = clamp(Math.round((B.left - D.left) / 2), 0, W - 20), x1 = clamp(Math.round((B.right - D.left) / 2), x0 + 20, W);
    const y0 = 8, y1 = Math.round((fundoDoFeltro(g) - D.top) / 2), HH = Math.max(H, y1), w = x1 - x0, h = y1 - y0;
    const chave = [W, H, x0, x1, y1].join('x');
    if (chave === q.cv._geo) return;
    q.cv._geo = chave;
    const P = pincel(W + M_, HH + M_);
    sombraCaixa(P, x0, y0, x1, y1, 2, 2, 3);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const ex = Math.min(x, w - 1 - x), ey = Math.min(y, h - 1 - y), d = Math.min(ex, ey), s = ex + ey;
      if (s < 3) continue;
      const cimaEsq = ey <= ex ? y < h / 2 : x < w / 2;
      let c;
      if (s === 3 || d === 0) c = GAV.o;
      else if (d === 1 || s === 4) c = cimaEsq ? GAV.luz : GAV.esc;
      else if (d === 2 || s === 5) c = cimaEsq ? GAV.esc2 : GAV.luz2;
      else {
        const hh = ruido(x, y, 61), m = ruido(x >> 3, y >> 3, 17) + .5 * ruido(x >> 2, (y + 1) >> 2, 29);
        c = hh < .06 ? GAV.tE : hh > .96 ? GAV.tL : m > 1.05 ? GAV.t2 : m < .4 ? GAV.t3 : GAV.t;
      }
      px(P, x0 + x, y0 + y, c);
    }
    q.cv.width = W + M_; q.cv.height = HH + M_; q.cv.style.width = 2 * (W + M_) + 'px'; q.cv.style.height = 2 * (HH + M_) + 'px';
    const img = q.ctx.createImageData(W + M_, HH + M_);
    new Uint32Array(img.data.buffer).set(P.u);
    q.ctx.putImageData(img, 0, 0);
  }
  function quadroMx() {
    if (document.body.classList.contains('mesa-dj')) {
      for (const g of document.querySelectorAll('.palco .gaveta')) if (g.offsetParent) try { desenhaGav(g); } catch (e) { console.error('gav', e); }
      const rec = document.querySelector('.palco .receptor');
      if (rec && rec.offsetParent) {
        const m = preparaMx(rec);
        snapM(rec);
        try { desenhaMx(m); } catch (e) { console.error('mx', e); }
      }
      const tv = document.getElementById('tv');
      if (tv && !tv.hidden && tv.offsetParent) {
        const t = preparaTv(tv);
        snapM(tv);
        try { desenhaTv(t); } catch (e) { console.error('tv', e); }
      }
      const sp = document.getElementById('pads');
      if (sp && !sp.hidden && sp.offsetParent) {
        const p = preparaPads(sp);
        snapM(sp);
        try { desenhaPads(p); } catch (e) { console.error('pads', e); }
      }
    }
    requestAnimationFrame(quadroMx);
  }
  // (#119) o canvas devolvido em branco (repintarCanvas): as chaves do mixer (o chaveE pinta tambem os rotulos e a
  // placa), do monitor e dos Sons rapidos zeradas, o proximo quadro pinta os tres de novo. As
  // maletas dos pedais (desenhaGav) guardam a chave no _geo do canvas, que o repintarCanvas zera
  document.addEventListener('repinta-canvas', () => {
    if (mx) mx.chaveE = '';
    if (tvp) tvp.chave = '';
    if (pd) pd.chave = '';
  });
  Promise.all([fontesProntas, document.fonts.load('700 12px "Archivo"')]).then(() => { fontesMx = true; });
  const ligaMx = () => requestAnimationFrame(quadroMx);
  document.addEventListener('DOMContentLoaded', ligaMx);
})();
/* MIX-JS-FIM */
