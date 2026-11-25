/* UI-EVENTS-JS-INICIO */
'use strict';
/* ---------- eventos da interface ---------- */
$('#estante').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  const li = b.closest('li');
  const id = li && li.dataset.id;
  if (b.dataset.role === 'capa' && id) {
    if (Date.now() - seguradaEm > 900) {   // soltar depois de segurar nao toca
      tocar(id);
      // (07/11, pedido do dono) na mesa o disco clicado da uma subidinha e volta ao lugar (o que toca nao fica mais levantado)
      if (MESA.montada && !reduz.matches && li.animate)
        li.animate([{ transform: 'translateY(0)' }, { transform: 'translateY(-6px)', offset: .35 }, { transform: 'translateY(0)' }], { duration: 300, easing: 'ease-out' });
    }
  }
  else if (b.dataset.role === 'mais' && id) { if (menuBotao === b) fecharMenu(true); else { fecharMenu(false); abrirMenu(b, { tipo: 'disco', id }); } }
  else if (b.dataset.role === 'retentar') { const c = S.jobCorpo[b.dataset.job]; if (c) baixar(c, S.jobAlvo[b.dataset.job]); }
});
$('#b-anterior').addEventListener('click', () => cmd('/api/prev'));
$('#b-proxima').addEventListener('click', () => cmd('/api/next'));
$('#b-aleatorio').addEventListener('click', () => { const v = !(S.state && S.state.shuffle); ligarChave($('#b-aleatorio'), v); ajustar('shuffle', v); });
$('#b-repetir').addEventListener('click', () => { const v = !(S.state && S.state.loop); ligarChave($('#b-repetir'), v); ajustar('loop', v); });
function alternarVoz() { const v = !(S.state && S.state.mic_mute); ligarChave($('#b-cortar'), v); ajustar('mic_mute', v); desenharReceptor(); }
$('#b-cortar').addEventListener('click', alternarVoz);
$('#b-nivelar').addEventListener('click', () => { const v = !(S.state && S.state.volume_auto); ligarChave($('#b-nivelar'), v); ajustar('volume_auto', v); });
$('#b-ouvir').addEventListener('click', () => {
  const v = !(S.state && S.state.voice_monitor);
  ligarChave($('#b-ouvir'), v); ajustar('voice_monitor', v);
  // sem volume proprio: o teste toca em 100%, o mesmo nivel que vai para o jogo
  if (v && S.state && S.state.voice_mon_vol !== 1) ajustar('voice_mon_vol', 1);
  desenharEfeito();
});
bindEffectsDrawer();
textoBusca();
matchMedia('(max-width: 899.98px)').addEventListener('change', () => {
  abrirGaveta(S.gaveta); if (!celular()) abrirPalco(false); else abrirDisco(false); inertPalco(); textoBusca();
});
$('#b-tocar').addEventListener('click', alternar);
$('#mini-tocar').addEventListener('click', alternar);
function mutarComAviso() {
  alternarVoz();
  avisar(S.state && S.state.mic_mute ? I18N.t('voice.mutedToast') : I18N.t('voice.backToast'));
}
$('#mini-cortar').addEventListener('click', mutarComAviso);
$('#b-mudo-topo').addEventListener('click', mutarComAviso);
$('#b-pagina').addEventListener('click', () => abrirDisco(!S.disco));
mqUnica.addEventListener('change', () => { if (paginaUnica()) abrirDisco(true); });
if (paginaUnica()) abrirDisco(true);
/* na mesa a prateleira, os pedais e a maleta correm de lado: a rodinha do mouse, que rola em pe, corre os tres. O
   ouvinte so existe com a mesa montada (montarMesa): o wheel que bloqueia a rolagem, preso na pedaleira em toda tela,
   mudava o desenho do feltro no celular (um a seis pontos de cor, no compara) */
const rodaDeLado = e => {
  if (!paginaUnica() || e.ctrlKey || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
  const ul = e.currentTarget;
  if (ul.scrollWidth <= ul.clientWidth + 1) return;
  e.preventDefault();
  ul.scrollLeft += e.deltaY * (e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? ul.clientWidth : 1);
};
function rodinhas(on) {
  for (const rolo of [$('#estante'), $('#gaveta'), $('#gaveta-dir'), $('.fila-parede .lista-fila')])
    rolo[on ? 'addEventListener' : 'removeEventListener']('wheel', rodaDeLado, { passive: false });
}
$('#palco-cortar').addEventListener('click', mutarComAviso);
$('#mini-abrir').addEventListener('click', () => celular() ? abrirPalcoComHistoria() : abrirDisco(!S.disco));
$('#mini-seta').addEventListener('click', () => abrirDisco(!S.disco));
$('#mini-ant').addEventListener('click', () => cmd('/api/prev'));
$('#mini-prox').addEventListener('click', () => cmd('/api/next'));
$('#mini-ef').addEventListener('click', desligarEfeito);
$('#b-fechar-palco').addEventListener('click', fecharPalco);
/* a pilha e [pagina, busca, palco, opcoes]: cada voltar fecha o que esta por cima. Entrada
   morta (de antes de a pagina recarregar, ou que diz aberto o que ja fechou) o voltar pula:
   senao um voltar nao fazia nada, e a busca so fechava no segundo (18/10) */
addEventListener('popstate', e => {
  // so a mesma pagina chega aqui pelo popstate: marca de outra carga e entrada de uma vida que
  // ja acabou (com ela, a base dessa vida: o voltar dali e para sair)
  const alheia = !!e.state && (e.state.vida ? e.state.vida !== VIDA : nossa(e.state));
  const st = alheia ? {} : e.state || {};
  if (folhaNaHistoria && !st.folha) { folhaNaHistoria = false; fecharMenu(false); }
  if (!st.palco) { palcoNaHistoria = false; abrirPalco(false); }
  if (!st.palco && !st.busca) { buscaNaHistoria = false; if (S.busca) { fecharBusca(); $('#q').value = ''; } }
  if (alheia || (st.folha && $('#menu').hidden) || (st.palco && !S.palco) || (st.busca && !st.palco && !S.busca)) {
    if (st.busca && !S.busca) buscaNaHistoria = false;
    history.back();
  }
});
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
$('#chips').addEventListener('click', e => {
  const b = e.target.closest('.compacto');
  if (b && Date.now() - seguradaEm > 900) tocar(b.dataset.id, { por_cima: true });   // soltar depois de segurar nao toca
});
/* segurar a capa no celular, ou o botao direito no computador, abre o menu do disco (como no YouTube Music); num
   compacto dos Sons rapidos, que nao tem os tres pontos, abre o mesmo menu (25/10) */
let seguradaEm = 0;
$('#estante').addEventListener('contextmenu', e => {
  const b = e.target.closest('.capa'), li = b && b.closest('li[data-id]');
  if (!li) return;
  e.preventDefault(); seguradaEm = Date.now();
  fecharMenu(false); abrirMenu(b, { tipo: 'disco', id: li.dataset.id });
});
$('#chips').addEventListener('contextmenu', e => {
  const b = e.target.closest('.compacto');
  if (!b) return;
  e.preventDefault(); seguradaEm = Date.now();
  fecharMenu(false); abrirMenu(b, { tipo: 'disco', id: b.dataset.id });
});
/* (#52) arrastar um disco da prateleira ate um toca-discos, so na mesa, a unica tela com a prateleira e os dois
   toca-discos juntos: soltar no deck no ar toca agora, como o clique; no da deixa toca a seguir, como o "Tocar a
   seguir" do menu (o disco que ja esta na deixa fica como esta). No mouse, andar uns pixels com o botao apertado ja
   arrasta: o clique segue tocando, e o botao direito e o "..." seguem abrindo o menu. No dedo, segurar meio segundo
   levanta o disco (o celular vibra): andando, arrasta; soltando sem andar, abre o menu, que e o que o segurar fazia (o
   segurar do proprio navegador fica de fora na mesa, para nao abrir o menu no meio do arrasto). Fora da mesa nada
   muda. Soltar longe dos toca-discos, o Esc, o gesto cancelado ou a mesa desmontando devolvem o disco a prateleira */
(() => {
  const est = $('#estante'), SEGURAR_MS = 450, FOLGA_DEDO = 8, FOLGA_MOUSE = 6;
  let g = null;          // o gesto em curso
  let dedoEm = 0;        // o fim do ultimo gesto de dedo: o menu do segurar do navegador que chega depois fica de fora
  let engolir = null;    // o ponteiro do arrasto cancelado pelo Esc: o soltar dele nao vira clique
  // o toca-discos que aparece no ponto: o que estiver por cima dele (a gaveta da busca, um aviso) tapa o alvo. A capa
  // solta e a placa do alvo nao pegam o ponteiro, entao nao contam
  function alvoEm(x, y) {
    const e = document.elementFromPoint(x, y), d = e && e.closest('.palco .deck');
    return d ? { d, acao: d.classList.contains('deck-deixa') ? 'seguir' : 'agora' } : null;
  }
  function apagarAlvo(d) { d.classList.remove('alvo-disco'); delete d.dataset.alvo; }
  function acender(alvo) {
    const d = alvo ? alvo.d : null;
    if (g.alvo && g.alvo !== d) apagarAlvo(g.alvo);
    if (d) { d.dataset.alvo = I18N.t(alvo.acao === 'agora' ? 'cue.playNow' : 'menu.playNext'); d.classList.add('alvo-disco'); }
    g.alvo = d;
  }
  const posicionar = () => { g.voa.style.transform = `translate(${g.x - g.dx}px, ${g.y - g.dy}px)`; };
  // a capa sai da prateleira: uma copia solta, presa ao ponteiro no ponto onde ele pegou
  function levantar() {
    clearTimeout(g.timer);
    if (!MESA.montada || !g.li.isConnected) { acabar(); return; }
    const r = g.capa.getBoundingClientRect();
    g.fase = 'levantado'; g.xl = g.x; g.yl = g.y; g.dx = g.x0 - r.left; g.dy = g.y0 - r.top;
    const v = el('div', 'disco-voando'), c = el('div', 'dv-capa'), arteNo = g.capa.querySelector('img, .capa-gerada');
    c.append(arteNo ? arteNo.cloneNode(true) : arte(g.it, false));
    v.append(c); v.setAttribute('aria-hidden', 'true');
    v.style.width = r.width + 'px'; v.style.height = r.height + 'px';
    document.body.append(v);
    g.voa = v; posicionar();
    g.li.classList.add('levantado');
    document.body.classList.add('arrastando-disco');
    getSelection().removeAllRanges();
    // preso a prateleira (que nunca e redesenhada): o soltar chega mesmo fora da janela ou com o disco redesenhado
    try { est.setPointerCapture(g.id); } catch (e) { /* o ponteiro ja saiu */ }
    if (g.dedo && navigator.vibrate) navigator.vibrate(12);
  }
  function acabar() {
    if (!g) return;
    clearTimeout(g.timer);
    if (g.alvo) apagarAlvo(g.alvo);
    if (g.voa) g.voa.remove();
    g.li.classList.remove('levantado');
    document.body.classList.remove('arrastando-disco');
    if (g.dedo) dedoEm = Date.now();
    g = null;
  }
  // a capa volta voando para o lugar do disco na prateleira (achado pelo id: ele pode ter sido redesenhado no caminho)
  function devolver() {
    const voa = g.voa, id = g.it.id;
    g.voa = null;
    acabar();
    if (!voa) return;
    const li = [...est.querySelectorAll('li[data-id]')].find(l => l.dataset.id === id), capa = li && li.querySelector('.capa');
    if (!capa || !MESA.montada || reduz.matches) { voa.remove(); return; }
    const r = capa.getBoundingClientRect();
    voa.classList.add('voltando');
    voa.style.transform = `translate(${r.left}px, ${r.top}px)`;
    setTimeout(() => voa.remove(), 200);
  }
  est.addEventListener('pointerdown', e => {
    if (g || !MESA.montada || e.button !== 0 || !e.isPrimary) return;
    const capa = e.target.closest('.capa'), li = capa && capa.closest('li[data-id]');
    const it = li && S.lib.find(x => x.id === li.dataset.id);
    if (!it) return;
    g = { id: e.pointerId, dedo: e.pointerType !== 'mouse', li, capa, it, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY,
          fase: 'espera', alvo: null, voa: null };
    if (g.dedo) g.timer = setTimeout(levantar, SEGURAR_MS);
  });
  addEventListener('pointermove', e => {
    if (!g || e.pointerId !== g.id) return;
    g.x = e.clientX; g.y = e.clientY;
    if (!g.dedo && !(e.buttons & 1)) { if (g.fase === 'espera') acabar(); else devolver(); return; }   // soltou fora da janela
    if (g.fase === 'espera') {
      const andou = Math.hypot(g.x - g.x0, g.y - g.y0);
      if (g.dedo) { if (andou > FOLGA_DEDO) acabar(); return; }   // o dedo andou antes do tempo: e a rolagem da prateleira
      if (andou < FOLGA_MOUSE) return;
      levantar();
      if (!g) return;
      g.fase = 'arrastando';
    } else if (g.fase === 'levantado') {
      if (Math.hypot(g.x - g.xl, g.y - g.yl) < FOLGA_DEDO) return;
      g.fase = 'arrastando';
    }
    if (!MESA.montada) { devolver(); return; }
    posicionar();
    acender(alvoEm(g.x, g.y));
  });
  addEventListener('pointerup', e => {
    if (engolir === e.pointerId) { engolir = null; seguradaEm = Date.now(); return; }
    if (!g || e.pointerId !== g.id) return;
    if (g.fase === 'espera') { acabar(); return; }   // o clique, ou o toque curto, de sempre: o click toca o disco
    seguradaEm = Date.now();   // o click que vem depois do soltar nao toca o disco
    if (g.fase === 'levantado') {   // segurou e soltou sem andar: o menu, como o segurar abria
      const { capa, it } = g;
      acabar();
      fecharMenu(false); abrirMenu(capa, { tipo: 'disco', id: it.id });
      return;
    }
    const alvo = MESA.montada ? alvoEm(g.x, g.y) : null, it = g.it;
    if (!alvo) { devolver(); return; }
    acabar();
    if (alvo.acao === 'agora') tocar(it.id);
    else if (!mesmoDisco(MESA.deixa, it)) executar('seguir', { tipo: 'disco', it });
  });
  addEventListener('pointercancel', e => {
    if (engolir === e.pointerId) engolir = null;
    if (!g || e.pointerId !== g.id) return;
    if (g.fase === 'espera') acabar(); else devolver();
  });
  document.addEventListener('keydown', e => {   // antes do Esc da pagina, que pararia a musica
    if (!g || g.fase === 'espera' || e.key !== 'Escape') return;
    e.preventDefault(); e.stopImmediatePropagation();
    engolir = g.id;
    devolver();
  }, true);
  // o menu do segurar do proprio navegador: na mesa, o dedo ja abre o menu ao soltar
  est.addEventListener('contextmenu', e => {
    if (!MESA.montada || !e.target.closest('.capa')) return;
    if ((g && g.dedo) || Date.now() - dedoEm < 800) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  est.addEventListener('dragstart', e => { if (MESA.montada && e.target.closest && e.target.closest('.capa')) e.preventDefault(); });
  // com o disco levantado, o dedo nao rola a prateleira: o touchmove que bloqueia so existe na mesa (fora dela a
  // rolagem segue sem esperar por ele)
  const prende = e => { if (g && g.dedo && g.fase !== 'espera' && e.cancelable) e.preventDefault(); };
  const ligar = () => est[paginaUnica() ? 'addEventListener' : 'removeEventListener']('touchmove', prende, { passive: false });
  ligar();
  mqUnica.addEventListener('change', () => { ligar(); if (g && !paginaUnica()) acabar(); });
})();
$('#estante').addEventListener('scroll', () => requestAnimationFrame(marcarPonto), { passive: true });
$('#cartoes').addEventListener('click', e => { const li = e.target.closest('li[data-id]'); if (li) tocar(li.dataset.id, { resume: true }); });
/* no toque a barra so muda arrastando o cursor: encostar em outro ponto da canaleta (sem
   querer, rolando a pagina) pulava o volume ou a faixa para la; o mouse
   e o teclado seguem como antes */
const CURSOR_PX = 16, DEDO_PX = 24;
document.querySelectorAll('input[type=range]').forEach(r => {
  let vale = true, antes = r.value;
  r.addEventListener('pointerdown', e => {
    antes = r.value;
    if (e.pointerType !== 'touch') { vale = true; return; }
    const b = r.getBoundingClientRect(), min = +r.min, max = +r.max;
    const cw = PALCO.k * (parseFloat(getComputedStyle(r).getPropertyValue('--cursor-w')) || CURSOR_PX);   // o pino do palco tem 24 px
    const x = b.left + cw / 2 + (max > min ? (r.value - min) / (max - min) : 0) * (b.width - cw);
    vale = Math.abs(e.clientX - x) <= DEDO_PX;
  }, { capture: true, passive: true });
  // o change do toque chega depois do pointerup: so o proximo gesto ou tecla destrava
  r.addEventListener('keydown', () => { vale = true; }, true);
  const barrar = e => { if (!vale) { e.stopImmediatePropagation(); r.value = antes; } };
  r.addEventListener('input', barrar, true);
  r.addEventListener('change', barrar, true);
});
for (const [fi, oi, k, curva] of FADERS) {
  const f = $(fi);
  f.addEventListener('input', () => {
    const g = curva ? ganhoDaPos(+f.value) : f.value / 100;
    pintarFader(f); rotularFader(f, $(oi), curva, g); ajustar(k, g);
    // fone desligado (de antes, quando havia a chave): subir o volume do fone religa
    if (k === 'mon_vol' && S.state && !S.state.monitor_on && +f.value > 0) ajustar('monitor_on', true);
  });
}
const sk = $('#seek');
sk.addEventListener('input', () => {
  S.arrastandoSeek = true;
  const dur = +sk.max || 0, v = +sk.value;
  mudar($('#t-pos'), 'textContent', fmt(v));
  mudar(sk, '--p', dur ? (v / dur * 100).toFixed(1) + '%' : '0%');
  mudar(sk, '--f', dur ? (v / dur).toFixed(4) : '0');
  mudar(sk, 'aria-valuetext', I18N.t('deck.timeOf', { pos: fmt(v), total: fmt(dur) }));
});
sk.addEventListener('change', async () => {
  const t = +sk.value;
  S.pos = t;
  try { await api('POST', '/api/seek', { t }); } catch (e) { avisar(e.message, true); }
  setTimeout(() => { S.arrastandoSeek = false; }, 350);
});
/* teclado: o passo nativo (0,1 s) nao anda nada numa faixa de 41 min */
const PASSOS = { ArrowRight: 5, ArrowUp: 5, ArrowLeft: -5, ArrowDown: -5, PageUp: 30, PageDown: -30 };
sk.addEventListener('keydown', e => {
  const dur = +sk.max || 0;
  if (sk.disabled || !dur || e.altKey || e.ctrlKey || e.metaKey) return;
  let t;
  if (e.key in PASSOS) t = S.pos + PASSOS[e.key];
  else if (e.key === 'Home') t = 0;
  else if (e.key === 'End') t = dur - 3;
  else return;
  e.preventDefault();
  t = clamp(t, 0, Math.max(0, dur - 0.5));
  S.pos = t; desenharTempo();
  api('POST', '/api/seek', { t }).catch(err => avisar(err.message, true));
});
bindSearch();
$('#b-cel').addEventListener('click', abrirCelular);
$('#b-disp').addEventListener('click', abrirDispositivos);
$('#dica-ouvir').addEventListener('click', e => { if (e.target.closest('.ir-disp')) abrirDispositivos(); });
$('#b-desligar').addEventListener('click', desligar);

function campoDeTexto(t) {
  if (!t || !t.closest) return false;
  if (t.closest('textarea, select, [contenteditable="true"]')) return true;
  const i = t.closest('input');
  return !!i && !['range', 'checkbox', 'radio', 'button', 'submit'].includes(i.type);
}
document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (!$('#menu').hidden) { if (e.key === 'Escape') { e.preventDefault(); fecharMenu(true); } return; }
  if (S.palco && e.key === 'Escape' && !dialogoAberto()) { e.preventDefault(); fecharPalco(); return; }
  if (S.disco && !paginaUnica() && e.key === 'Escape' && !dialogoAberto() && !campoDeTexto(e.target)) { e.preventDefault(); abrirDisco(false); return; }
  // (#114) a busca aberta tambem esta por cima: o Esc fecha ela, como no campo, e a musica segue (antes ele chegava ao
  // fim e parava a musica). O foco que estava nos resultados, que somem, vai para o campo, como no voltar
  if (S.busca && e.key === 'Escape' && !dialogoAberto() && !campoDeTexto(e.target)) {
    e.preventDefault();
    const nosResultados = $('#vista-busca').contains(document.activeElement);
    fecharBusca();
    if (nosResultados && !toque()) $('#q').focus();
    return;
  }
  if (dialogoAberto() || campoDeTexto(e.target)) return;
  if (e.code === 'Space' || e.key === ' ') { e.preventDefault(); if (!e.repeat) alternar(); }
  else if (/^[1-9]$/.test(e.key)) { const it = S.lib[+e.key - 1]; if (it) { e.preventDefault(); tocar(it.id); } }
  else if (e.key === '0') {
    e.preventDefault();
    if (!e.repeat && S.state && S.state.effect !== SEM_EFEITO) escolherEfeito(SEM_EFEITO);
  }
  else if (e.key === 'Escape') { e.preventDefault(); if (S.state && S.state.track) cmd('/api/stop'); }
});
document.addEventListener('keyup', e => {
  if ((e.code === 'Space' || e.key === ' ') && !dialogoAberto() && !campoDeTexto(e.target) && $('#menu').hidden) e.preventDefault();
});
/* UI-EVENTS-JS-FIM */
