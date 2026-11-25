/* SCRIPT-FAILED-JS-INICIO */
'use strict';
const scriptsFailed = [], firstAddress = location.href;
function scriptFailed(s) { scriptsFailed.push(s.getAttribute('src')); }
const scriptsMissing = () => scriptsFailed.filter(f => f !== 'transporte.js');
document.addEventListener('DOMContentLoaded', () => {
  const missing = scriptsMissing();
  if (!missing.length) return;
  document.querySelectorAll('dialog[open]').forEach(d => d.close());
  document.getElementById('tela-parear').hidden = true;
  document.getElementById('fora').hidden = false;
  for (const e of document.body.children) e.inert = e.id !== 'fora';
  document.activeElement.blur();
  const loadAgainWhenItAnswers = () => {
    const l = document.createElement('link');
    l.rel = 'preload'; l.as = 'script'; l.href = `${missing[0]}?retry=${Date.now()}`;
    l.onload = () => { if (location.href === firstAddress) location.reload(); else location.replace(firstAddress); };
    l.onerror = () => { l.remove(); setTimeout(loadAgainWhenItAnswers, 3000); };
    document.head.append(l);
  };
  setTimeout(loadAgainWhenItAnswers, 3000);
});
/* SCRIPT-FAILED-JS-FIM */
