/* OPTIONS-JS-INICIO */
'use strict';
/* ---------- opcoes de um disco ou resultado (o ...) ---------- */
/* ctx = {tipo: 'disco', id} da prateleira ou {tipo: 'resultado', r} da busca; no computador abre
   ao lado do botao, no celular sobe de baixo com o disco no alto */
let menuCtx = null, menuBotao = null, folhaNaHistoria = false, larguraMenu = 0;
function itensMenu(ctx) {
  const fila = temFila(), out = [];
  if (fila) out.push(['seguir', I18N.t('menu.playNext'), IC.aSeguir], ['fila', I18N.t('menu.addToQueue'), IC.fila]);
  if (ctx.tipo === 'disco') {
    const it = ctx.it;
    if ((it.last_pos || 0) > 5) out.unshift(['continuar', I18N.t('shelf.resumeFrom', { time: fmt(it.last_pos) }), IC.continuar]);
    // os de ate 15 s ja estao nos Sons rapidos sozinhos
    if (!curto(it)) {
      out.push(it.rapido ? ['semRapido', I18N.t('menu.removeQuick'), IC.semRapido]
        : ['rapido', I18N.t('menu.addQuick'), IC.rapido]);
    }
    out.push(['renomear', I18N.t('menu.rename'), IC.renomear]);
    if (it.youtube_id) out.push(['youtube', I18N.t('menu.openYoutube'), IC.youtube]);
    out.push(['apagar', I18N.t('menu.delete'), IC.apagar, 'perigo']);
  } else {
    const r = ctx.r, jb = jobDe(r.youtube_id) || jobDe(r.link);
    if (!naPrateleira(r.youtube_id) && !(jb && jb.status === 'running')) out.push(['salvar', I18N.t('shelf.save'), IC.salvar]);
    out.push(['youtube', I18N.t('menu.openYoutube'), IC.youtube]);
  }
  return out;
}
function abrirMenu(botao, ctx) {
  if (ctx.tipo === 'disco') { ctx.it = S.lib.find(x => x.id === ctx.id); if (!ctx.it) return; }
  menuCtx = ctx; menuBotao = botao;
  $('#aviso').hidden = true;   // o aviso de antes nao fica por cima das opcoes
  const m = $('#menu'), info = ctx.tipo === 'disco' ? ctx.it : ctx.r;
  const titulo = ctx.tipo === 'disco' ? info.title : tituloRes(info);
  const capa = el('span', 'capinha');
  capa.append(arte({ thumb: info.thumb || (info.youtube_id ? `https://i.ytimg.com/vi/${info.youtube_id}/mqdefault.jpg` : null), id: info.id || info.youtube_id || titulo, title: titulo }, true));
  const txt = el('span'); txt.append(el('span', 't', titulo), el('span', 's', [info.channel, info.duration ? fmt(info.duration) : null].filter(Boolean).join(' · ')));
  $('#menu-cab').replaceChildren(capa, txt);
  const lista = $('#menu-itens');
  lista.setAttribute('aria-label', I18N.t('menu.options', { title: titulo }));
  // na folha do celular a contracapa do LP: o LADO A antes da primeira faixa e o Apagar sozinho no LADO B (os dois
  // letreiros so desenho: o leitor de tela le as acoes)
  const folha = celular();
  const lado = (txt, cls) => { const x = el('div', cls, txt); x.setAttribute('aria-hidden', 'true'); return x; };
  lista.replaceChildren(...itensMenu(ctx).flatMap(([acao, rot, ic, cls], i) => {
    const b = el('button', cls); b.type = 'button'; b.setAttribute('role', 'menuitem'); b.dataset.acao = acao;
    b.innerHTML = IC_PX[acao] || ic; b.append(el('span', null, rot));
    if (!folha) return [b];
    if (cls === 'perigo') return [lado(I18N.t('menu.sideB'), 'lado lado-b'), b];
    return i === 0 ? [lado(I18N.t('menu.sideA'), 'lado'), b] : [b];
  }));
  m.hidden = false;
  larguraMenu = innerWidth;
  if (celular()) {
    m.classList.add('folha'); m.style.left = m.style.top = '';
    $('#menu-fundo').hidden = false;
    // o voltar do Android fecha as opcoes (a entrada leva junto o estado de baixo: busca, palco)
    if (!folhaNaHistoria) { history.pushState({ ...(history.state || {}), folha: true }, ''); folhaNaHistoria = true; }
  } else {
    m.classList.remove('folha');
    const r = botao.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight;
    let x = r.right - mw, y = r.bottom + 6;
    if (y + mh > innerHeight - 8) y = r.top - mh - 6;
    m.style.left = clamp(x, 8, innerWidth - mw - 8) + 'px';
    m.style.top = clamp(y, 8, innerHeight - mh - 8) + 'px';
  }
  botao.setAttribute('aria-expanded', 'true');
  lista.querySelector('button').focus({ preventScroll: true });
}
function fecharMenu(voltarFoco) {
  const m = $('#menu'); if (m.hidden) return;
  m.hidden = true; $('#menu-fundo').hidden = true;
  if (menuBotao) { menuBotao.setAttribute('aria-expanded', 'false'); if (voltarFoco && document.contains(menuBotao)) menuBotao.focus(); }
  menuBotao = null;
  if (folhaNaHistoria) { folhaNaHistoria = false; history.back(); }
}
function executar(acao, ctx) {
  if (ctx.tipo === 'disco') {
    const it = ctx.it;
    if (acao === 'continuar') tocar(it.id, { resume: true });
    else if (acao === 'renomear') renomear(it);
    else if (acao === 'rapido' || acao === 'semRapido') marcarRapido(it, acao === 'rapido');
    else if (acao === 'apagar') apagar(it);
    else if (acao === 'seguir' || acao === 'fila') enfileirar({ id: it.id }, acao === 'seguir', it.title, null);
    else if (acao === 'youtube') abrirYoutube(it.youtube_id);
    return;
  }
  const r = ctx.r;
  if (acao === 'seguir' || acao === 'fila') enfileirar(corpoDe(r), acao === 'seguir', tituloRes(r), r.link || r.youtube_id);
  else if (acao === 'salvar') salvarResultado(r);
  else if (acao === 'youtube') abrirYoutube(r.youtube_id, r.link);
}
function abrirYoutube(yid, link) {
  const url = link || (yid ? `https://www.youtube.com/watch?v=${yid}` : null);
  if (url) window.open(url, '_blank', 'noopener');
}
/* depois de um dialogo aberto pelo menu, o foco volta para o disco (o item do menu ja sumiu) */
function focarDisco(id) {
  const li = id && [...document.querySelectorAll('#estante li[data-id]')].find(l => l.dataset.id === id);
  const b = li ? li.querySelector('[data-role="mais"]') : document.querySelector('#estante .capa');
  (b || $('#q')).focus();
}
function vizinhoDe(id) {
  const li = [...document.querySelectorAll('#estante li[data-id]')].find(l => l.dataset.id === id);
  const v = li && (li.nextElementSibling && li.nextElementSibling.dataset.id ? li.nextElementSibling : li.previousElementSibling);
  return v ? v.dataset.id : null;
}
$('#menu').addEventListener('click', e => {
  const b = e.target.closest('button[data-acao]'); if (!b || !menuCtx) return;
  const ctx = menuCtx; fecharMenu(false);
  executar(b.dataset.acao, ctx);
});
$('#menu').addEventListener('keydown', e => {
  const itens = [...$('#menu').querySelectorAll('button:not([hidden])')];
  const i = itens.indexOf(document.activeElement);
  if (e.key === 'ArrowDown') { e.preventDefault(); itens[(i + 1) % itens.length].focus(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); itens[(i - 1 + itens.length) % itens.length].focus(); }
  else if (e.key === 'Tab') fecharMenu(false);
});
// no celular o toque fora cai no fundo escuro, que fecha no click: sem isso o toque fecharia as
// opcoes no pointerdown e o click ainda tocaria a linha que estava embaixo
$('#menu-fundo').addEventListener('click', () => fecharMenu(false));
document.addEventListener('pointerdown', e => {
  if (!$('#menu').hidden && !e.target.closest('#menu, #menu-fundo, [data-role="mais"]')) fecharMenu(false);
});
/* celular: puxar as opcoes para baixo fecha (longe o bastante ou num puxao rapido); perto, voltam */
(() => {
  const m = $('#menu');
  const noTopo = () => m.classList.toggle('no-topo', m.scrollTop <= 0);
  m.addEventListener('scroll', noTopo, { passive: true });
  let g = null, arrastouEm = 0;
  m.addEventListener('pointerdown', e => {
    noTopo();
    if (e.pointerType !== 'touch' || !m.classList.contains('folha') || m.scrollTop > 0) return;
    g = { id: e.pointerId, y0: e.clientY, x0: e.clientX, d: 0, v: 0, yAnt: e.clientY, tAnt: e.timeStamp, ativo: false };
  });
  m.addEventListener('pointermove', e => {
    if (!g || e.pointerId !== g.id) return;
    const d = e.clientY - g.y0, dx = e.clientX - g.x0;
    if (!g.ativo) {
      if (Math.abs(d) < 6 && Math.abs(dx) < 6) return;   // ainda nao da para saber o gesto
      if (d <= 0 || Math.abs(dx) > Math.abs(d)) { g = null; return; }
      g.ativo = true; m.classList.add('puxando');
    }
    if (e.timeStamp > g.tAnt) { g.v = (e.clientY - g.yAnt) / (e.timeStamp - g.tAnt); g.yAnt = e.clientY; g.tAnt = e.timeStamp; }
    g.d = Math.max(0, d);
    m.style.transform = `translateY(${g.d}px)`;
  });
  const soltar = e => {
    if (!g || e.pointerId !== g.id) return;
    const { ativo, d, v } = g;
    g = null;
    if (!ativo) return;
    arrastouEm = Date.now();
    m.classList.remove('puxando');
    if (d > Math.min(120, m.offsetHeight * .3) || (d > 30 && v > .5)) {
      m.style.transform = 'translateY(100%)';   // desce o resto e fecha
      setTimeout(() => { fecharMenu(false); m.style.transform = ''; }, 190);
    } else m.style.transform = '';
  };
  m.addEventListener('pointerup', soltar);
  m.addEventListener('pointercancel', soltar);
  // como no palco: a puxada rapida sem o touchmove cancelado vira fling e engole o primeiro toque depois
  m.addEventListener('touchmove', e => { if (g && g.ativo && e.cancelable) e.preventDefault(); }, { passive: false });
  // soltar depois de puxar nao aperta a opcao que estava embaixo do dedo
  m.addEventListener('click', e => { if (Date.now() - arrastouEm < 400) { e.stopImmediatePropagation(); e.preventDefault(); } }, true);
})();
// o teclado do celular sumindo muda so a altura: as opcoes ficam
addEventListener('resize', () => { if (innerWidth !== larguraMenu) fecharMenu(false); });
/* OPTIONS-JS-FIM */
