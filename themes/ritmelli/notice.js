/* NOTICE-JS-INICIO */
'use strict';
/* ---------- aviso rapido ---------- */
let avisoT = null;
/* acao = {rotulo, fn}: um botao no aviso, como o "Abrir" do Spotify depois de por na fila */
function avisar(txt, erro, acao) {
  const a = $('#aviso');
  a.replaceChildren();
  if (erro) a.append(el('span', 'lampada alerta'));
  a.append(el('span', 'aviso-t', txt));
  a.classList.toggle('com-acao', !!acao);
  if (acao) {
    const b = el('button', 'aviso-acao', acao.rotulo); b.type = 'button';
    b.addEventListener('click', () => { a.hidden = true; acao.fn(); });
    a.append(b);
  }
  a.hidden = false;
  clearTimeout(avisoT);
  avisoT = setTimeout(() => { a.hidden = true; }, erro ? 6000 : acao ? 5000 : 3200);
}
/* NOTICE-JS-FIM */
