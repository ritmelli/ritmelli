/* PRATELEIRA-JS-INICIO: o titulo e a contagem da plaqueta em letra de pixel (canvas de 1 px por celula, mostrado a 2x) e as
   teclas das capas marcadas com o algarismo (o CSS poe o sprite); gerado por integra_prat.py, v18 */
(() => {
  const { negrita: N, regular: G, desce: D } = LETRA_PLACA, TALT = 9;
  const COR = 'rgb(246,227,194)', SOMBRA = 'rgb(14,7,3)';
  // o titulo da placa na negrita e a contagem na regular, num canvas so (a placa e so a moldura); a letra que falta
  // numa das duas leva o titulo e a contagem para o HTML
  function desenhaConta() {
    const cab = document.getElementById('cab-prat'), conta = document.getElementById('conta');
    if (!cab || !conta) return;
    const t = [...[...I18N.t('nav.shelf')].map(ch => [ch, N]), ...[...(' \u00b7 ' + conta.textContent.trim())].map(ch => [ch, G])];
    let cv = cab.querySelector('canvas.conta-px');
    if (t.some(([ch, F]) => !F[ch] && ch !== ' ')) { cab.classList.remove('conta-px'); if (cv) cv.remove(); return; }
    if (!cv) { cv = document.createElement('canvas'); cv.className = 'conta-px'; cv.setAttribute('aria-hidden', 'true'); cab.appendChild(cv); }
    const larg = ([ch, F]) => F[ch] ? F[ch][0].length : 3;   // o espaco da negrita tem 3
    const desce = ([ch, F]) => F === N ? D[ch] || 0 : 0;
    const w = t.reduce((s, p, i) => s + larg(p) + (i < t.length - 1 ? 1 : 0), 0), h = TALT + 1 + Math.max(...t.map(desce));
    cv.width = w; cv.height = h; cv.style.width = (2 * w) + 'px'; cv.style.height = (2 * h) + 'px';
    const c = cv.getContext('2d');
    c.clearRect(0, 0, w, h);
    for (const [cor, dy] of [[SOMBRA, 1], [COR, 0]]) {
      c.fillStyle = cor;
      let x = 0;
      for (const p of t) {
        const g = p[1][p[0]];
        if (g) { const y0 = TALT - g.length + desce(p); g.forEach((linha, j) => { [...linha].forEach((q, k) => { if (q === '#') c.fillRect(x + k, y0 + j + dy, 1, 1); }); }); }
        x += larg(p) + 1;
      }
    }
    cab.classList.add('conta-px');
  }
  const FONTE = '18.667px "Jersey 10"', LINHA = 16, RECUO = 18;
  const SO_SEP = /^[\-|\u2013\u2014:]+$/;
  const BRANCO = [255, 248, 236], SOMBRA_N = [14, 7, 3];
  // cada letra em x inteiro, com 1 px entre elas: o limiar nao cola uma na outra
  // (r05) kana e kanji na reserva do sistema em negrito de 12 px (a Jersey nao tem; a reserva fina a 18,667 saia mais
  // alta que a caixa-alta e falhada no corte do alfa): a fonte por letra e o corte mais baixo so nelas
  const CJK = /[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ가-힯]/, FONTE_CJK = 'bold 12px "MS PGothic", "MS Gothic", "Yu Gothic UI", "Meiryo", sans-serif';   /* (r11) a MS Gothic tem bitmap de 12 px: kana nitido (na Yu Gothic o na virava borrao); (r12) a P, proporcional, com os mesmos bitmaps: na de largura fixa o kana ficava solto */
  const avanco = (c, ch) => { if (!CJK.test(ch)) return Math.round(c.measureText(ch).width) + 1;
    c.font = FONTE_CJK; const v = Math.round(c.measureText(ch).width) + 1; c.font = FONTE; return v; };
  const largura = (c, s) => [...s].reduce((t, ch) => t + avanco(c, ch), 0) - (s ? 1 : 0);
  const SEPARA = /[\s\-|\u2013\u2014:,;]+$/;
  function quebra(c, texto, largs) {
    const cabe = (s, w) => largura(c, s) <= w;
    const pal = texto.split(/\s+/).filter(Boolean), linhas = ['', ''];
    let li = 0;
    for (let i = 0; i < pal.length; i++) {
      const w = pal[i], cand = linhas[li] ? linhas[li] + ' ' + w : w;
      if (li === 1 && !linhas[1] && SO_SEP.test(w)) continue;     // o traco nao abre a 2a linha
      if (cabe(cand, largs[li])) { linhas[li] = cand; continue; }
      if (li === 0 && linhas[0]) { li = 1; linhas[0] = linhas[0].replace(SEPARA, ''); i--; continue; }   // so quebra no espaco
      if (li === 0) {                                                // a 1a palavra nao cabe ao lado da tecla: corta com hifen
        let k = w.length - 1;
        while (k > 1 && !cabe(w.slice(0, k) + '-', largs[0])) k--;
        // o corte numa silaba: a 2a linha abre com consoante e vogal (ANAVI- / TORIA, nao ANAVIT- / ORIA)
        const VOG = /[aeiouáéíóúâêôãõàAEIOUÁÉÍÓÚÂÊÔÃÕÀ]/;
        for (let q = k; q >= 2; q--) if (!VOG.test(w[q]) && VOG.test(w[q + 1] || '') && VOG.test(w[q - 1])) { k = q; break; }
        linhas[0] = w.slice(0, k) + '-'; li = 1; pal.splice(i + 1, 0, w.slice(k)); continue;
      }
      if (li === 0) { li = 1; i--; continue; }
      let s = linhas[1] ? linhas[1] + ' ' + w : w;
      while (s.length > 1 && largura(c, s.replace(SEPARA, '')) + 12 > largs[1]) s = s.slice(0, -1);   // (r08) a reticencia de passo 4
      // sem toco de menos de 3 letras antes da reticencia ("ORIA - Tr...")
      // (r08) contando so letras: o parentese e o traco nao fazem o toco ("(Au...", "Luz e...")
      const toco = s.replace(SEPARA, '').split(' ').pop();
      if ((toco.match(/\p{L}/gu) || []).length < 3 && s.includes(' ')) s = s.slice(0, s.lastIndexOf(' '));
      const lig = s.replace(SEPARA, '').split(' ').pop();   // a ligacao minuscula de 1 ou 2 letras que sobrou ("e", "de")
      if (/^\p{Ll}{1,2}$/u.test(lig) && s.includes(' ')) s = s.slice(0, s.lastIndexOf(' '));
      linhas[1] = s.replace(SEPARA, '') + '\u2026';
      return linhas;
    }
    return linhas;
  }
  function escreve(c, s, x, y) {
    for (const ch of s) {
      const a = avanco(c, ch);
      if (CJK.test(ch)) { c.font = FONTE_CJK; c.fillText(ch, x, y); c.font = FONTE; c.cjk.push([x, x + a, y]); }   // (r13) em duas passadas o laco do na fechava: o kana fica no traco do bitmap
      else c.fillText(ch, x, y);
      x += a;
    }
    return x;
  }
  function desenhaNome(ficha) {
    const nome = ficha.querySelector('.nome');
    if (!nome) return;
    // sem emoji: o do sistema sai em degrade liso, fora da paleta, e deixava um vao duplo no rotulo
    const texto = [...nome.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('')
      .replace(/[\p{Extended_Pictographic}\ufe0f\u200d]/gu, '').replace(/\s+/g, ' ').trim();
    let cv = ficha.querySelector('canvas.nome-px');
    if (cv && cv.dataset.t === texto) return;
    const w = ficha.clientWidth - 10, h = ficha.clientHeight - 2;
    if (w <= 0 || h <= 0) return;
    if (!cv) { cv = document.createElement('canvas'); cv.className = 'nome-px'; cv.setAttribute('aria-hidden', 'true'); ficha.appendChild(cv); }
    cv.width = w; cv.height = h; cv.dataset.t = texto;
    const c = cv.getContext('2d');
    c.font = FONTE; c.textBaseline = 'alphabetic'; c.fillStyle = '#fff'; c.cjk = [];
    const [l1, l2] = quebra(c, texto, [w - RECUO, w]);
    const reti = l2.endsWith('\u2026'), t2 = reti ? l2.slice(0, -1) : l2;
    escreve(c, l1, RECUO, 16);
    const xf = escreve(c, t2, 0, 16 + LINHA);
    // (r08) os pontos com passo de 1 celula a partir de x par (o passo 3 dava vaos de 2 e 1)
    if (reti) { const x0 = xf + 1 + ((xf + 1) & 1); for (let k = 0; k < 3; k++) c.fillRect(x0 + 4 * k, 14 + LINHA, 2, 2); }
    const img = c.getImageData(0, 0, w, h), d = img.data, cheio = new Uint8Array(w * h), corte = new Uint8Array(w * h).fill(128);
    for (const [x0, x1, yb] of c.cjk) for (let y = Math.max(0, yb - 13); y < Math.min(h, yb + 3); y++) for (let x = x0; x < Math.min(w, x1); x++) corte[y * w + x] = 100;
    for (let i = 0; i < w * h; i++) {
      const a = d[4 * i + 3];
      if (a < corte[i]) { d[4 * i + 3] = 0; continue; }
      cheio[i] = 1; d[4 * i + 3] = 255;
      const r = d[4 * i], g = d[4 * i + 1], b = d[4 * i + 2];
      if (Math.min(r, g, b) > 150 && Math.max(r, g, b) - Math.min(r, g, b) < 40) { d[4 * i] = BRANCO[0]; d[4 * i + 1] = BRANCO[1]; d[4 * i + 2] = BRANCO[2]; }
    }
    for (let y = h - 1; y >= 2; y--) for (let x = 0; x < w; x++) {
      const i = y * w + x;
      if (!cheio[i] && cheio[i - 2 * w]) { d[4 * i] = SOMBRA_N[0]; d[4 * i + 1] = SOMBRA_N[1]; d[4 * i + 2] = SOMBRA_N[2]; d[4 * i + 3] = 255; }
    }
    c.putImageData(img, 0, 0);
    ficha.classList.add('nome-px');
  }
  function desenhaNomes() {
    if (!document.body.classList.contains('mesa-dj')) return;
    document.querySelectorAll('#estante .disco-item .ficha').forEach(desenhaNome);
  }
  // a miniatura a 2 px: a foto reduzida (em 2 passos, media) num canvas de metade do tamanho, mostrado a 2x
  function pixelaCapa(img) {
    const capa = img.closest('.capa');
    if (!capa) return;
    if (!img.complete || !img.naturalWidth) { img.addEventListener('load', () => pixelaCapa(img), { once: true }); return; }
    const W = Math.round(capa.clientWidth / 2), H = Math.round(capa.clientHeight / 2);
    if (!W || !H) return;
    let cv = capa.querySelector('canvas.foto-px');
    const chave = img.currentSrc + '|' + W + 'x' + H;
    if (cv && cv.dataset.s === chave) return;
    if (!cv) { cv = document.createElement('canvas'); cv.className = 'foto-px'; cv.setAttribute('aria-hidden', 'true'); img.after(cv); }
    const iw = img.naturalWidth, ih = img.naturalHeight, e = Math.max(W / iw, H / ih);
    const sw = W / e, sh = H / e;
    const t = document.createElement('canvas'); t.width = 4 * W; t.height = 4 * H;
    const tc = t.getContext('2d'); tc.imageSmoothingQuality = 'high';
    tc.drawImage(img, (iw - sw) / 2, (ih - sh) / 2, sw, sh, 0, 0, 4 * W, 4 * H);
    const m = document.createElement('canvas'); m.width = 2 * W; m.height = 2 * H;
    const mc = m.getContext('2d'); mc.imageSmoothingQuality = 'high'; mc.drawImage(t, 0, 0, 2 * W, 2 * H);
    cv.width = W; cv.height = H; cv.dataset.s = chave;
    const c = cv.getContext('2d'); c.imageSmoothingQuality = 'high'; c.filter = 'contrast(1.12) saturate(1.1)'; c.drawImage(m, 0, 0, W, H);
    capa.classList.add('foto-px');
  }
  function marcaTeclas() {
    // (07/11, pedido do dono) a capa lisa e o nome em letra normal, como na maleta: sem o pixelaCapa e o desenhaNomes
    document.querySelectorAll('#estante kbd:not([data-k])').forEach(k => { k.dataset.k = k.textContent.trim(); });
  }
  function liga() {
    const conta = document.getElementById('conta'), est = document.getElementById('estante');
    if (conta) new MutationObserver(desenhaConta).observe(conta, { childList: true, characterData: true, subtree: true });
    if (est) new MutationObserver(marcaTeclas).observe(est, { childList: true, subtree: true });
    document.addEventListener('repinta-canvas', desenhaConta);   // (#119) o canvas devolvido em branco (repintarCanvas)
    desenhaConta(); marcaTeclas();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', liga); else liga();
})();
/* PRATELEIRA-JS-FIM */
