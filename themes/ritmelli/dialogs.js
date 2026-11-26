/* DIALOGS-JS-INICIO */
'use strict';
/* ---------- dialogos ---------- */
function confirmar(titulo, texto, sim) {
  return new Promise(res => {
    const d = $('#dlg-confirma');
    $('#dc-t').textContent = titulo; $('#dc-p').textContent = texto; $('#dc-sim').textContent = sim;
    d.returnValue = '';
    d.addEventListener('close', () => res(d.returnValue === 'sim'), { once: true });
    d.showModal();
    $('#dc-nao').focus();
  });
}
async function apagar(it) {
  const ok = await confirmar(I18N.t('delete.title', { title: it.title }), I18N.t('delete.text'), I18N.t('menu.delete'));
  if (!ok) { focarDisco(it.id); return; }
  const vizinho = vizinhoDe(it.id);
  try { await api('DELETE', `/api/library/${encodeURIComponent(it.id)}`); avisar(I18N.t('delete.done')); focarDisco(vizinho); }
  catch (e) { avisar(e.message, true); focarDisco(it.id); }
}
function renomear(it) {
  const d = $('#dlg-nome'), inp = $('#dn-in');
  inp.value = it.title;
  d.returnValue = '';
  d.addEventListener('close', async () => {
    focarDisco(it.id);
    const novo = inp.value.trim();
    if (d.returnValue !== 'sim' || !novo || novo === it.title) return;
    try { await api('PATCH', `/api/library/${encodeURIComponent(it.id)}`, { title: novo }); avisar(I18N.t('rename.done')); }
    catch (e) { avisar(e.message, true); }
  }, { once: true });
  d.showModal();
  inp.select();
}
/* um disco de mais de 15 s entra nos Sons rapidos pela mao (25/10); o servidor guarda no disco ("rapido") */
async function marcarRapido(it, on) {
  try {
    const r = await api('PATCH', `/api/library/${encodeURIComponent(it.id)}`, { rapido: on });
    // servidor de antes desta mudanca responde ok sem guardar
    if (!r.item || !!r.item.rapido !== on) { avisar(I18N.t('pads.needsRestart'), true); return; }
    avisar(on ? I18N.t('pads.added') : I18N.t('pads.removed'));
  } catch (e) { avisar(e.message, true); }
}

// Cancelar fora do submit: Enter no campo salva (o envio implicito usa o primeiro submit)
$('#dn-nao').addEventListener('click', () => $('#dlg-nome').close('nao'));
/* DIALOGS-JS-FIM */
