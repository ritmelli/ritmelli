/* DESK-SCALE-JS-INICIO */
'use strict';
/* o palco da mesa (pedido dele, 06/11): a mesa monta sempre num tamanho fixo, PALCO_W x PALCO_H (a proporcao do mock
   B), e a pagina escala tudo para caber na janela, centrado; o que a janela tem de outra proporcao vira faixa de parede.
   Quando da, a escala cai num numero inteiro de pixels da tela por celula de 2 px (no notebook dele, 3x3), para o
   pixel art ficar nitido e sem costura (o ajustarPalco diz quanto pode passar ou perder). O getBoundingClientRect vem escalado; o rectP devolve a
   caixa no tamanho do palco, com a origem no canto dele */
const PALCO_W = 1920, PALCO_H = 1026, PALCO_PE = 14, PALCO = { k: 1, w: 0, h: 0, x: 0, y: 0 };
// PALCO_PE: a madeira embaixo do pe do feltro (a barra de cima tem 15 no palco; o mock ~22 em 1080). So no encaixe e
// no centramento: a caixa do palco (layout, --palco-h, fonte, cabos com y1 = PALCO_H) segue com PALCO_H
function ajustarPalco() {
  const st = document.documentElement.style;
  if (!document.body.classList.contains('mesa-dj')) {
    PALCO.k = 1; PALCO.x = PALCO.y = 0;
    for (const p of ['--palco-k', '--palco-w', '--palco-h', '--palco-x', '--palco-y']) st.removeProperty(p);
    return;
  }
  const W = innerWidth, H = innerHeight, d = devicePixelRatio || 1, enc = Math.min(W / PALCO_W, H / PALCO_H);
  const encPe = Math.min(W / PALCO_W, H / (PALCO_H + PALCO_PE));
  // a celula num numero inteiro de pixels da tela: o inteiro de cima, se o palco passa no maximo 1,2% da janela (corta
  // so a folga da beira; a janela do notebook dele tem 768 de altura, e 0,7485 punha 2 costuras na onda, pedido dele);
  // senao o de baixo, perdendo no maximo 10% do tamanho; senao o encaixe exato. O de baixo e o encaixe contam a folga
  // do pe (PALCO_PE): na janela maximizada a pedaleira colava no pe da janela (revisao da r12)
  const x2 = 2 * enc * d, cima = Math.ceil(x2 - 1e-6), x2p = 2 * encPe * d, baixo = Math.floor(x2p + 1e-6);
  const k = cima >= 1 && cima / x2 <= 1.012 ? cima / (2 * d) : baixo >= 1 && baixo / x2p >= .9 ? baixo / (2 * d) : encPe;
  // centrado, com a origem num pixel inteiro da tela; (r16) 1 celula para a esquerda: a sombra de 2 celulas das pecas
  // cai a direita e a madeira visivel da beira direita ficava 3 css menor que a da esquerda (a madeira anda junto)
  const px_ = v => Math.round(v * d) / d;
  const pe = Math.max(0, Math.min(PALCO_PE, H / k - PALCO_H));
  PALCO.k = k; PALCO.w = PALCO_W; PALCO.h = PALCO_H; PALCO.x = px_((W - PALCO_W * k) / 2 - 2 * k); PALCO.y = px_((H - (PALCO_H + pe) * k) / 2);
  st.setProperty('--palco-k', String(k)); st.setProperty('--palco-w', PALCO_W + 'px'); st.setProperty('--palco-h', PALCO_H + 'px');
  st.setProperty('--palco-x', PALCO.x + 'px'); st.setProperty('--palco-y', PALCO.y + 'px');
}
addEventListener('resize', ajustarPalco);
function rectP(e) {
  const r = e.getBoundingClientRect(), k = PALCO.k;
  if (k === 1 && !PALCO.x && !PALCO.y) return r;
  const left = (r.left - PALCO.x) / k, top = (r.top - PALCO.y) / k, width = r.width / k, height = r.height / k;
  return { left, top, width, height, right: left + width, bottom: top + height, x: left, y: top };
}
// a largura do palco (ou da janela, sem a mesa), para prender o que abre por cima dentro dele
const larguraPalco = () => PALCO.k === 1 ? innerWidth : PALCO.w;
/* DESK-SCALE-JS-FIM */
