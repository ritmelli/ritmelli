/* PHONE-JS-INICIO */
'use strict';
/* ---------- celular (no PC): o QR, o codigo e os conectados. Aberto, confere a cada 2 s: o celular que acabou de
   parear aparece na lista, e o codigo vencido ou usado da lugar a outro ---------- */
let celT = 0, celQR = '', celIds = null, celLista = '';
async function abrirCelular() {
  const msg = $('#dcel-msg');
  celIds = null;
  msg.className = 'msg-dlg'; msg.textContent = I18N.t('phone.generating');
  $('#dlg-cel').showModal();
  if (await atualizarCelular()) msg.textContent = '';
  conferirCelular();
}
/* a proxima conferencia so sai depois da resposta: com o setInterval, uma resposta lenta podia chegar depois da
   seguinte e mostrar o codigo de antes */
function conferirCelular() {
  clearTimeout(celT);
  if ($('#dlg-cel').open) celT = setTimeout(async () => { await atualizarCelular(); conferirCelular(); }, 2000);
}
$('#dlg-cel').addEventListener('close', () => { clearTimeout(celT); celQR = ''; });
async function atualizarCelular() {
  const msg = $('#dcel-msg');
  let r;
  try { r = await api('GET', `/api/pareamento?caminho=${encodeURIComponent(location.pathname)}`); }
  catch (e) { msg.className = 'msg-dlg erro'; msg.textContent = e.message; return false; }
  $('#dcel-semrede').hidden = !!r.url;
  $('#dcel-par').hidden = !r.url;
  $('#dcel-par').classList.toggle('queimado', r.queimado);
  $('#dcel-url').textContent = r.url || '';
  $('#dcel-cod').textContent = r.codigo ? r.codigo.replace(/^(\d{3})(\d{3})$/, '$1 $2') : '';
  const vale = $('#dcel-vale');
  vale.classList.toggle('erro', r.queimado);
  vale.textContent = r.queimado
    ? I18N.t('phone.blocked')
    : I18N.t('phone.valid', { n: Math.max(1, Math.ceil(r.vale_s / 60)) });
  const chaveQR = r.qr ? r.qr.join('') : '';
  if (chaveQR !== celQR) {
    celQR = chaveQR; $('#dcel-qr').innerHTML = r.qr ? desenharQR(r.qr) : '';
    const svg = $('#dcel-qr svg'); if (svg) svg.setAttribute('aria-label', I18N.t('phone.qrLabel'));   // texto fora do innerHTML
  }
  desenharCelulares(r.celulares || []);
  return true;
}
/* o QR em pixels inteiros da tela (com a escala do Windows tambem): modulo borrado a camera le pior */
function desenharQR(linhas) {
  const n = linhas.length, borda = 4, lado = n + 2 * borda;
  const dpr = devicePixelRatio || 1, px = Math.max(3, Math.floor(220 * dpr / lado)) / dpr;
  let d = '';
  linhas.forEach((l, y) => {
    for (let x = 0; x < n;) {
      if (l[x] !== '1') { x++; continue; }
      let f = x; while (f < n && l[f] === '1') f++;
      d += `M${x + borda} ${y + borda}h${f - x}v1h${x - f}z`;
      x = f;
    }
  });
  return `<svg width="${lado * px}" height="${lado * px}" viewBox="0 0 ${lado} ${lado}" shape-rendering="crispEdges" role="img"><rect width="${lado}" height="${lado}" fill="#F4EFE6"/><path fill="#2A1812" d="${d}"/></svg>`;
}
function quando(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return '';
  if (d.toDateString() === new Date().toDateString()) return I18N.t('phone.today', { time: d.toLocaleTimeString(I18N.lang, { hour: '2-digit', minute: '2-digit' }) });
  return I18N.t('phone.onDate', { date: d.toLocaleDateString(I18N.lang, { day: '2-digit', month: '2-digit' }) });
}
function desenharCelulares(lista) {
  const ids = lista.map(c => c.id);
  const novo = celIds && lista.find(c => !celIds.includes(c.id));
  if (novo) { const m = $('#dcel-msg'); m.className = 'msg-dlg'; m.textContent = I18N.t('phone.connectedOk', { name: novo.nome }); }
  celIds = ids;
  const ul = $('#dcel-lista'), v = JSON.stringify(lista);
  if (v === celLista) return;   // a cada 2 s: so redesenha quando muda (o foco num Desconectar nao pula)
  celLista = v;
  ul.replaceChildren();
  if (!lista.length) { ul.append(el('li', 'cel-vazio', I18N.t('phone.noDevices'))); return; }
  for (const c of lista) {
    const li = el('li'), quem = el('span', 'cel-quem');
    quem.append(el('span', 'cel-nome', c.nome), el('span', 'cel-quando', I18N.t('phone.since', { when: quando(c.desde), seen: quando(c.visto) })));
    const b = el('button', 'btn', I18N.t('phone.disconnect')); b.type = 'button'; b.dataset.id = c.id;
    b.setAttribute('aria-label', I18N.t('phone.disconnectLabel', { name: c.nome, when: quando(c.desde) }));
    li.append(quem, b);
    ul.append(li);
  }
}
$('#dcel-lista').addEventListener('click', async e => {
  const b = e.target.closest('button[data-id]'); if (!b) return;
  const msg = $('#dcel-msg');
  b.disabled = true;
  try {
    await api('DELETE', `/api/pareamento/${encodeURIComponent(b.dataset.id)}`);
    msg.className = 'msg-dlg'; msg.textContent = I18N.t('phone.disconnected');
    await atualizarCelular();
  } catch (err) { msg.className = 'msg-dlg erro'; msg.textContent = err.message; b.disabled = false; }
});
$('#dcel-outro').addEventListener('click', async () => {
  const msg = $('#dcel-msg');
  try { await api('POST', '/api/pareamento/codigo'); msg.textContent = ''; await atualizarCelular(); }
  catch (e) { msg.className = 'msg-dlg erro'; msg.textContent = e.message; }
});
function bindPhoneButton() {
  $('#b-cel').addEventListener('click', abrirCelular);
}
/* PHONE-JS-FIM */
