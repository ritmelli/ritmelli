/* TONEARM-JS-INICIO */
'use strict';
/* ---------- braco: o angulo segue o raio do sulco ---------- */
// o prato e 4% menor que o lugar dele, em volta do mesmo centro (a moldura grossa do toca-discos, 19/10): o sulco tambem.
// (#50) A agulha e a ponta da cabeca, e nao um ponto no eixo do tubo: no dev/pecas.py a cabeca (8,8 cqw) dobra 24 graus
// a 53,5 cqw do pivo, entao a ponta fica a 61,6 cqw dele (L) e 3,3 graus a frente do tubo (desvio). Com o ponto no eixo,
// a 62 cqw, a agulha comecava a faixa em 84% do raio, para dentro do disco
const CABECA = { dobra: 53.5, comp: 8.8, ang: 24 * Math.PI / 180 };
const G = { cx: 40, cy: 40, R: (36 - 2.6) * .96, px: 88, py: 12,
            L: Math.hypot(CABECA.comp * Math.sin(CABECA.ang), CABECA.dobra + CABECA.comp * Math.cos(CABECA.ang)),
            desvio: Math.atan2(CABECA.comp * Math.sin(CABECA.ang), CABECA.dobra + CABECA.comp * Math.cos(CABECA.ang)) };
// onde a ponta esta no disco com o braco no angulo th (radianos), em fracao do raio
const pontaNoDisco = th => Math.hypot(G.px - G.L * Math.sin(th + G.desvio) - G.cx, G.py + G.L * Math.cos(th + G.desvio) - G.cy) / G.R;
// (#50) a faixa comeca com a agulha na borda, onde ela entra num disco de verdade (a ponta a 95% do raio: com a largura
// da cabeca, rente a borda)
const BRACO_INICIO = 0.95;
// o ponto no eixo do tubo, a 62 cqw do pivo: a conta do sulco ate o #50. O fim do curso segue nela
const EIXO_L = 62;
const eixoNoDisco = th => Math.hypot(G.px - EIXO_L * Math.sin(th) - G.cx, G.py + EIXO_L * Math.cos(th) - G.cy) / G.R;
// (07/11, pedido do dono) o fim do curso na ultima ranhura: o angulo em que o ponto no eixo fica a 50% do raio (com 41% a
// cabeca do braco parava em cima do selo). (#50) O mesmo angulo de antes, pela mesma busca: so o comeco mudou
function anguloDoEixo(f) {
  const alvo = G.R * f;
  let a = 10, b = 70;
  for (let i = 0; i < 26; i++) {
    const m = (a + b) / 2, r = m * Math.PI / 180;
    if (Math.hypot(G.px - EIXO_L * Math.sin(r) - G.cx, G.py + EIXO_L * Math.cos(r) - G.cy) > alvo) a = m; else b = m;
  }
  return (a + b) / 2;
}
const BRACO_FIM_ANG = anguloDoEixo(0.50);
const BRACO_FIM = pontaNoDisco(BRACO_FIM_ANG * Math.PI / 180);   // a ponta, no fim, a uns 40% do raio
function anguloPara(p) {
  if (p >= 1) return BRACO_FIM_ANG;
  const alvo = BRACO_INICIO - p * (BRACO_INICIO - BRACO_FIM);
  // ate 55 graus a ponta so entra no disco (ela passa mais perto do centro a uns 57 e sai de novo)
  let a = 10, b = 55;
  for (let i = 0; i < 26; i++) {
    const m = (a + b) / 2;
    if (pontaNoDisco(m * Math.PI / 180) > alvo) a = m; else b = m;
  }
  return (a + b) / 2;
}
const BRACO_INICIO_ANG = anguloPara(0);
// o desenho do braco para o angulo (as ANGULOS do dev/pecas.py): o descanso e seis no curso do disco, de 28 a 48 graus,
// de 4 em 4, e o tema gira no maximo 2 graus em cima do desenho. O de 28 (#50) e o do comeco da faixa, a uns 27 graus
const desenhoDoBraco = ang => ang < 15 ? 'repouso' : ang < 30 ? 'inicio' : ang < 34 ? 'a' : ang < 38 ? 'b' : ang < 42 ? 'c' : ang < 46 ? 'd' : 'e';
function posAtual() { return S.pos; }
function moverBraco() {
  const s = S.state;
  // o braco de pixel descansa reto: a 3 graus o degrau do tubo vira dente solto (o descanso anda junto)
  let ang = 0;
  if (s && s.track && s.status !== 'ended' && s.status !== 'idle') {
    const dur = s.duration || s.track.duration;
    const p = dur ? clamp(posAtual() / dur, 0, 1) : 0;
    ang = anguloPara(p);
  }
  mudar($('#braco'), '--ang', ang.toFixed(1) + 'deg');
  desenhoBraco(ang);
}
/* o braco e um desenho em pixel ja inclinado (dev/pecas.py), um por faixa de angulo (o desenhoDoBraco()). Na troca de
   faixa o braco esta andando (o tema gira em 1 s): o desenho novo espera ele cobrir uns 45% do caminho, para nenhum dos
   dois girar longe do seu angulo */
let faixaBraco = null, trocaBraco = 0;
function desenhoBraco(ang) {
  const f = desenhoDoBraco(ang);
  if (f === faixaBraco) return;
  const imediato = faixaBraco === null || matchMedia('(prefers-reduced-motion: reduce)').matches;
  faixaBraco = f;
  clearTimeout(trocaBraco);
  if (imediato) $('#braco').dataset.desenho = f;
  else trocaBraco = setTimeout(() => { $('#braco').dataset.desenho = f; }, 200);
}
/* TONEARM-JS-FIM */
