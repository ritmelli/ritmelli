/* TURNTABLE-JS-INICIO */
'use strict';
/* ---------- prato e faixa ---------- */
const IC_TOCAR = '<path d="M7 4.5v15l12.5-7.5z" fill="currentColor"/>';
const IC_PAUSAR = '<rect x="6" y="5" width="4.2" height="14" rx="1" fill="currentColor"/><rect x="13.8" y="5" width="4.2" height="14" rx="1" fill="currentColor"/>';
const MIC_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>';
const IC_MIC = MIC_SVG + '</svg>';
const IC_MIC_CORTADO = MIC_SVG + '<path d="M4 4l16 16" stroke-width="2.2"/></svg>';

function desenharFaixa() {
  const s = S.state; if (!s) return;
  const tr = s.track, st = s.status;
  document.body.dataset.status = st;
  $('#prato').classList.toggle('com-disco', !!tr);
  const id = tr ? tr.id + '|' + (tr.thumb || '') : null;
  if (id !== S.rotuloId) {
    S.rotuloId = id;
    $('#rotulo').replaceChildren(tr ? arte(tr, true) : '');
    $('#mini-rotulo').replaceChildren(tr ? arte(tr, true) : '');
  }
  porTitulo(tr ? tr.title : I18N.t('deck.noDisc'), !!tr);
  $('#canal-faixa').textContent = tr ? (tr.channel || I18N.t('deck.noChannel')) : dicaPrato();
  // com error o leitor para e o servidor marca ended: nao e "chegou ao fim"
  $('#situacao').textContent = s.error && st !== 'playing' ? I18N.t('deck.status.error') : (SITUACAO[st] || st);
  const lf = $('#lamp-faixa');
  lf.className = 'lampada' + (s.error && st !== 'playing' ? ' alerta' : st === 'playing' ? ' acesa' : st === 'buffering' ? ' acesa piscando' : '');

  const dur = s.duration || (tr && tr.duration) || 0;
  const sk = $('#seek');
  sk.disabled = !tr || !dur;
  sk.max = dur || 0;
  $('#t-dur').textContent = fmt(dur);

  // som rapido tocando por cima: o botao e Pausar mesmo sem disco no prato ou com ele parado, e cala os sons
  // (sem disco no prato o pausar ficava apagado e nao dava para parar o som rapido)
  const sobre = !!(s.por_cima && s.por_cima.length);
  document.body.toggleAttribute('data-sobre', sobre);   // o pixel do pausar no celular sai do CSS
  let rot = I18N.t('deck.play'), ic = IC_TOCAR;
  if (st === 'playing' || st === 'buffering' || sobre) { rot = I18N.t('deck.pause'); ic = IC_PAUSAR; }
  else if (st === 'paused') rot = I18N.t('deck.resume');
  else if (st === 'ended') rot = I18N.t('deck.playAgain');
  // o botao grande do transporte e o da barra de baixo do celular fazem o mesmo
  for (const [b, i] of [['#b-tocar', '#ic-tocar'], ['#mini-tocar', '#ic-mini']]) {
    $(b).disabled = !tr && !sobre; $(b).setAttribute('aria-label', rot); $(b).title = b === '#b-tocar' ? I18N.t('deck.withSpaceKey', { action: rot }) : rot; $(i).innerHTML = ic;
  }
  $('#mini-tit').textContent = tr ? tr.title : I18N.t('deck.noDisc');
  $('#mini-sub').textContent = !tr ? dicaMini()
    : s.error && st !== 'playing' ? I18N.t('deck.status.error') : (tr.channel || I18N.t('deck.noChannel'));
  rotularMini();
  desenharRapidos();

  // Anterior, Proxima e Aleatorio precisam do servidor que guarda historico e embaralha
  const transp = 'shuffle' in s;
  for (const b of ['#b-aleatorio', '#b-anterior', '#b-proxima']) $(b).classList.toggle('ausente', !transp);
  ligarChave($('#b-aleatorio'), transp && s.shuffle);
  $('#b-anterior').disabled = !transp || (!tr && !s.history);
  // fila vazia: o Proxima fica apagado e nao responde, como no YouTube Music
  $('#b-proxima').disabled = !transp || !(s.queue && s.queue.length);
  // a barra de baixo do computador tem os mesmos pulos
  for (const [m, b] of [['#mini-ant', '#b-anterior'], ['#mini-prox', '#b-proxima']]) { $(m).disabled = $(b).disabled; $(m).classList.toggle('ausente', !transp); }
  ligarChave($('#b-repetir'), s.loop);

  const ef = $('#erro-faixa');
  if (s.error) {
    $('#erro-faixa-txt').textContent = textoMsg(s.error);
    ef.hidden = false;
  } else ef.hidden = true;

  marcarPrateleira();
  desenharTempo();
  desenharMesa();
}

/* titulo do disco numa linha: se nao cabe, uma copia vem atras e o par desliza para a esquerda
   sem parar, com uma pausa no comeco de cada volta, como no YouTube Music */
const LETREIRO_PX_S = 36, LETREIRO_PAUSA_S = 2, LETREIRO_VAO = 48;
function porTitulo(txt, comDisco) {
  const h = $('#titulo-faixa');
  if (h._txt === txt) return;
  h._txt = txt;
  h.title = comDisco ? txt : '';
  const l = el('span', 'letreiro'); l.append(el('span', null, txt));
  h.replaceChildren(l);
  medirTitulo();
}
function medirTitulo() {
  const h = $('#titulo-faixa'), l = h.firstElementChild; if (!l) return;
  if (l._anim) { l._anim.cancel(); l._anim = null; }
  while (l.children.length > 1) l.lastChild.remove();
  h.classList.remove('rolando');
  if (reduz.matches || h.scrollWidth - h.clientWidth <= 1) return;
  const copia = l.firstElementChild.cloneNode(true); copia.setAttribute('aria-hidden', 'true');
  l.append(copia);
  h.classList.add('rolando');
  const passo = l.firstElementChild.offsetWidth + LETREIRO_VAO;
  const anda = passo / LETREIRO_PX_S, total = anda + LETREIRO_PAUSA_S;
  l._anim = l.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(0)', offset: LETREIRO_PAUSA_S / total },
    { transform: `translateX(${-passo}px)` }], { duration: total * 1000, iterations: Infinity, easing: 'linear' });
}
let medindoTitulo = 0;
new ResizeObserver(() => { cancelAnimationFrame(medindoTitulo); medindoTitulo = requestAnimationFrame(medirTitulo); }).observe($('#titulo-faixa'));
reduz.addEventListener('change', medirTitulo);
if (document.fonts) document.fonts.ready.then(medirTitulo);

/* texto sob "Nenhum disco no prato": com a prateleira vazia, aponta a busca */
function dicaPrato() {
  return S.lib.length ? I18N.t('deck.hint') : I18N.t('deck.hintEmpty');
}
/* o mesmo na barra de baixo, curto: com a prateleira vazia nao ha capa para tocar */
function dicaMini() { return S.lib.length ? I18N.t('deck.hintMini') : I18N.t('deck.hintMiniEmpty'); }
function rotularMini() {
  const rot = S.disco ? I18N.t('nav.backToShelf') : I18N.t('nav.openDeck');
  $('#mini-abrir').setAttribute('aria-label', `${rot}: ${$('#mini-tit').textContent}, ${$('#mini-sub').textContent}`);
  $('#mini-abrir').setAttribute('aria-expanded', S.disco || S.palco ? 'true' : 'false');
}

function desenharTempo() {
  const s = S.state; if (!s) return;
  const dur = s.duration || (s.track && s.track.duration) || 0;
  const sk = $('#seek');
  if (!S.arrastandoSeek) {
    const p = s.track ? clamp(S.pos, 0, dur || 0) : 0;
    sk.value = p;
    // so escreve o que mudou: o tick chega 15 vezes por segundo e cada escrita repinta
    mudar($('#t-pos'), 'textContent', fmt(p));
    mudar(sk, '--p', dur ? (p / dur * 100).toFixed(1) + '%' : '0%');
    mudar(sk, '--f', dur ? (p / dur).toFixed(4) : '0');   // a fracao: o ambar ate o centro do cursor de pixel
    mudar(sk, 'aria-valuetext', I18N.t('deck.timeOf', { pos: fmt(p), total: fmt(dur) }));
    mudar($('#mini-prog'), '--prog', dur ? (p / dur).toFixed(3) : '0');
    mudar($('#mini-tempo'), 'textContent', `${fmt(p)} / ${fmt(dur)}`);
  }
  moverBraco();
  tempoMesa();
}
const escritos = new WeakMap();
function mudar(el, chave, v) {
  let m = escritos.get(el); if (!m) escritos.set(el, m = {});
  if (m[chave] === v) return;
  m[chave] = v;
  if (chave === 'textContent') el.textContent = v;
  else if (chave.startsWith('--')) el.style.setProperty(chave, v);
  else el.setAttribute(chave, v);
}

function ligarChave(b, on) {
  b.setAttribute('aria-pressed', on ? 'true' : 'false');
  const l = b.querySelector('.lampada');
  if (l) l.className = 'lampada' + (on ? (b.id === 'b-cortar' ? ' alerta' : ' acesa') : '');
}
function bindTurntable() {
  $('#b-anterior').addEventListener('click', () => cmd('/api/prev'));
  $('#b-proxima').addEventListener('click', () => cmd('/api/next'));
  $('#b-aleatorio').addEventListener('click', () => { const v = !(S.state && S.state.shuffle); ligarChave($('#b-aleatorio'), v); ajustar('shuffle', v); });
  $('#b-repetir').addEventListener('click', () => { const v = !(S.state && S.state.loop); ligarChave($('#b-repetir'), v); ajustar('loop', v); });
  $('#b-tocar').addEventListener('click', alternar);
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
}
/* TURNTABLE-JS-FIM */
