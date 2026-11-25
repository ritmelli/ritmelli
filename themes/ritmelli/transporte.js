/* O transporte do tema: toda conversa com o servidor passa por aqui (os pedidos da API e o fluxo de eventos do SSE),
   e o resto do tema nao sabe como ela chega. Hoje e o HTTP do mesmo servidor que serviu a pagina. O que o tema mostra
   nao sai do endereco da pagina: sai do caps que o servidor manda (no /api/state, no 401 do pareamento e no primeiro
   evento do SSE). O endereco so serve aqui para o "local", o palpite de quem nunca recebeu um caps (a pagina guardada
   que o navegador reabre com o Ritmelli fechado), e so escolhe o texto do aviso de fora do ar */
const TRANSPORTE = (() => {
  /* um pedido da API: {status, ok, json} (o json e null sem corpo); sem resposta nenhuma, o erro com status 0 */
  async function pedir(metodo, caminho, dados) {
    let r;
    try {
      r = await fetch(caminho, {
        method: metodo,
        headers: dados ? { 'Content-Type': 'application/json' } : undefined,
        body: dados ? JSON.stringify(dados) : undefined,
      });
    } catch (e) {
      const x = new Error('no response'); x.status = 0;
      throw x;
    }
    let json = null;
    try { json = await r.json(); } catch (e) { /* corpo vazio */ }
    return { status: r.status, ok: r.ok, json };
  }

  /* o fluxo de eventos: ao(nome, fn) chama fn com os dados do evento ja lidos (o "open" sem nenhum); aoFalhar(fn), a
     conexao que caiu ou foi recusada; fechada(), se ela desistiu de vez (a recusa de cara, que o navegador nao tenta de
     novo); fechar(). Sem como abrir, o erro sai na hora, para quem chamou tentar de novo */
  function eventos(caminho) {
    const fonte = new EventSource(caminho);
    return {
      ao(nome, fn) { fonte.addEventListener(nome, e => fn(e.data === undefined ? undefined : JSON.parse(e.data))); },
      aoFalhar(fn) { fonte.onerror = fn; },
      fechada: () => fonte.readyState === EventSource.CLOSED,
      fechar: () => fonte.close(),
    };
  }

  const local = ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname);
  return { pedir, eventos, local };
})();
