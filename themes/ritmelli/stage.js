/* STAGE-JS-INICIO */
'use strict';
/* ---------- palco (celular): o toca-discos abre por cima da prateleira pela barra de baixo;
   o voltar do Android fecha ele em vez de sair da pagina ---------- */
/* cada carga da pagina marca as entradas que poe na historia: o Chrome recarrega a aba que
   descartou em segundo plano (e o puxar para atualizar recarrega) com as entradas de antes
   ainda na pilha, que dizem aberto o que a pagina nova nao abriu */
const VIDA = Math.random().toString(36).slice(2);
const nossa = st => !!(st && (st.busca || st.palco || st.folha));
history.replaceState({ vida: VIDA }, '');
let palcoNaHistoria = false;
let animaPalco = 0, inertDepois = 0;
function animarPalco() {
  const p = $('#palco');
  p.classList.add('anima');
  clearTimeout(animaPalco);
  animaPalco = setTimeout(() => p.classList.remove('anima'), 450);
}
function abrirPalco(on) {
  on = !!on && celular();
  if (on === S.palco) return;
  S.palco = on;
  animarPalco();
  document.body.classList.toggle('com-palco', on);
  const p = $('#palco');
  if (on) { p.setAttribute('role', 'dialog'); p.setAttribute('aria-modal', 'true'); p.setAttribute('aria-label', I18N.t('nav.deck')); }
  else { p.removeAttribute('role'); p.removeAttribute('aria-modal'); p.removeAttribute('aria-label'); }
  p.classList.remove('puxando'); p.style.transform = ''; $('#mini').style.opacity = '';
  for (const x of [$('.topo'), $('#mini')]) x.inert = on;
  // o que fica a vista quando a animacao para destrava ja no toque: a parte de cima do palco ao abrir,
  // a prateleira ao fechar. Com a troca so no fim, o primeiro toque logo depois de abrir caia no fundo
  // do palco e nao apertava nada (19/10). Sao uns 350 e 560 elementos (3 a 5 ms com a CPU 4x
  // mais lenta); a gaveta de pedais (1850, abaixo da dobra) e o que sai de vista trocam so com a
  // animacao terminada: o inert recalcula o estilo de cada descendente, e no quadro do toque os 2900
  // juntos davam 20 a 40 ms no celular de teste segurando o comeco da subida e da descida (medido, 18/10)
  if (on) inertPalco(x => x.id !== 'gaveta'); else $('.parede').inert = false;
  clearTimeout(inertDepois);
  inertDepois = setTimeout(() => { $('.parede').inert = S.palco; inertPalco(); }, 460);
  $('#mini-abrir').setAttribute('aria-expanded', on ? 'true' : 'false');
  // o foco entra no palco (sem anel; o Tab segue para o fechar) e volta para a barra ao sair
  if (on) p.focus({ preventScroll: true });
  else if (!toque()) $('#mini-abrir').focus();
}
function fecharPalco() {
  // desce ja, de onde estiver; o resto (foco, inert) vem no popstate
  animarPalco();
  document.body.classList.remove('com-palco');
  $('#palco').classList.remove('puxando'); $('#palco').style.transform = ''; $('#mini').style.opacity = '';
  if (palcoNaHistoria) history.back(); else abrirPalco(false);
}
/* recolhido no celular, so a barra do palco responde (o resto esta fora da tela); `so` escolhe os filhos */
function inertPalco(so = () => true) {
  const fora = celular() && !S.palco;
  for (const x of $('#palco').children) if (x.id !== 'mini' && so(x)) x.inert = fora;
}
function abrirPalcoComHistoria() {
  if (!S.palco) $('#palco').scrollTop = 0;
  abrirPalco(true);
  if (S.palco && !palcoNaHistoria) { history.pushState({ palco: true, vida: VIDA }, ''); palcoNaHistoria = true; }
}
function bindStage() {
  $('#mini-tocar').addEventListener('click', alternar);
  $('#mini-cortar').addEventListener('click', mutarComAviso);
  $('#palco-cortar').addEventListener('click', mutarComAviso);
  $('#mini-abrir').addEventListener('click', () => celular() ? abrirPalcoComHistoria() : abrirDisco(!S.disco));
  $('#mini-seta').addEventListener('click', () => abrirDisco(!S.disco));
  $('#mini-ant').addEventListener('click', () => cmd('/api/prev'));
  $('#mini-prox').addEventListener('click', () => cmd('/api/next'));
  $('#b-fechar-palco').addEventListener('click', fecharPalco);
  /* gestos do Spotify, com o palco preso ao dedo: a barra e a beirada do palco recolhido;
     puxar a barra para cima sobe o palco inteiro, e a barra se apaga no primeiro terco da
     subida (a madeira do palco aparece por baixo); puxar o palco aberto para baixo (com ele no
     topo) faz o caminho de volta. No topo os aparelhos tem touch-action pan-down, entao o dedo
     descendo nao vira rolagem e o ponteiro chega a cada quadro */
  (() => {
    const p = $('#palco'), mini = $('#mini');
    /* o touchmove cancelado diz ao Chrome que o gesto e da pagina: sem ele, a puxada rapida vira um fling
       mesmo sem nada para rolar, e o primeiro toque do 1 a 2 s seguintes so freia o fling, sem virar
       clique (19/10, medido no celular de teste: abrindo pela barra e fechando pelo palco). O
       ouvinte que bloqueia fica so onde o gesto comeca: a barra (inert com o palco aberto, fora do toque)
       e os aparelhos do topo enquanto o palco esta no topo; rolando, a rolagem nao espera por ele */
    const engolir = e => { if (g && g.ativo && e.cancelable) e.preventDefault(); };
    mini.addEventListener('touchmove', engolir, { passive: false });
    const doTopo = [...p.querySelectorAll('.palco-topo, .deck, .receptor')];
    let ouvindo = false;
    const noTopo = () => {
      const topo = p.scrollTop <= 0;
      p.classList.toggle('no-topo', topo);
      if (topo === ouvindo) return;
      ouvindo = topo;
      for (const x of doTopo) x[topo ? 'addEventListener' : 'removeEventListener']('touchmove', engolir, { passive: false });
    };
    p.addEventListener('scroll', noTopo, { passive: true });
    // posicao do palco: 0 = aberto, curso() = recolhido (so a barra aparece)
    const curso = () => p.offsetHeight - mini.offsetHeight;
    const cabeca = [...p.querySelector('.palco-topo').children];
    function por(y) {
      const c = curso(), yy = clamp(y, 0, c), o = clamp(3 * yy / c - 2, 0, 1);
      p.style.transform = `translateY(${yy}px)`;
      mini.style.opacity = String(o);
      for (const x of cabeca) x.style.opacity = String(clamp(1 - 2 * o, 0, 1));
    }
    const limpar = () => { p.style.transform = ''; mini.style.opacity = ''; for (const x of cabeca) x.style.opacity = ''; };
    let g = null;   // gesto em curso
    noTopo();
    function comecar(e, de) {
      if (e.pointerType !== 'touch' || !celular()) return;
      g = { de, id: e.pointerId, y0: e.clientY, x0: e.clientX, d: 0, v: 0, yAnt: e.clientY, tAnt: e.timeStamp, ativo: false };
    }
    function andar(e) {
      if (!g || e.pointerId !== g.id) return;
      const d = e.clientY - g.y0, dx = e.clientX - g.x0;
      if (!g.ativo) {
        if (Math.abs(d) < 6 && Math.abs(dx) < 6) return;   // ainda nao da para saber o gesto
        const certo = g.de === 'palco' ? d > 0 && p.scrollTop <= 0 : d < 0;
        if (!certo || Math.abs(dx) > Math.abs(d)) { g = null; return; }   // rolagem ou gesto de lado
        g.ativo = true;
        p.classList.add('puxando');
        if (g.de === 'barra') { p.scrollTop = 0; noTopo(); }   // recolhido, o pulo nao aparece
      }
      if (e.timeStamp > g.tAnt) { g.v = (e.clientY - g.yAnt) / (e.timeStamp - g.tAnt); g.yAnt = e.clientY; g.tAnt = e.timeStamp; }
      g.d = d;
      por(g.de === 'palco' ? d : curso() + d);
    }
    function soltar(e) {
      if (!g || e.pointerId !== g.id) return;
      const { ativo, de, d, v } = g;
      g = null;
      if (!ativo) return;
      p.classList.remove('puxando');
      animarPalco();
      limpar();   // a transicao do CSS segue de onde o dedo deixou
      if (de === 'palco') {
        // longe o bastante, ou um puxao rapido: desce e fecha; perto: volta
        if (d > Math.min(160, innerHeight * .22) || (d > 40 && v > .5)) fecharPalco();
      } else if (-d > innerHeight * .2 || v < -.5) abrirPalcoComHistoria();
      // da barra sem subir o bastante: sem a classe, o palco volta a ser so a barra
    }
    p.addEventListener('pointerdown', e => {
      if (!S.palco ? e.target.closest('#mini') : p.scrollTop <= 0 && !e.target.closest('input[type=range], .fila')) comecar(e, S.palco ? 'palco' : 'barra');
    });
    p.addEventListener('pointermove', andar);
    p.addEventListener('pointerup', soltar);
    p.addEventListener('pointercancel', soltar);
  })();
}
/* STAGE-JS-FIM */
