/* SHARED-JS-INICIO */
'use strict';
/* ---------- what every script of the theme shares: the page state (S), the DJ desk's (MESA) and the general helpers.
   The index.html loads this file before all the others, so what it declares is in sight of each of them ---------- */
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const reduz = matchMedia('(prefers-reduced-motion: reduce)');
const celular = () => matchMedia('(max-width: 899.98px)').matches;
const toque = () => matchMedia('(pointer: coarse)').matches;

const S = {
  state: null, lib: [], jobs: [], pos: 0, levels: { mic: 0, track: 0, out: 0 },
  online: null, jaConectou: false, desligado: false,
  pareando: false,        // celular sem pareamento: o #tela-parear pede o codigo do PC
  caps: null,             // o que esta pagina pode, pelo servidor ({papel, rotas}); null ate ele dizer
  atualizando: null,      // a versao que o instalador esta pondo: a pagina recarrega quando o Ritmelli voltar
  busca: null,            // null = prateleira; {q, link, itens, carregando, erro}
  buscaSeq: 0,
  jobAlvo: {},            // id do job -> youtube_id
  jobCorpo: {},           // id do job -> corpo do POST, para tentar de novo
  vistoFora: new Set(),   // (#53) os discos (id do YouTube ou link) que o prato ou a fila mostrou fora da prateleira
  libOk: false,           // (#53) a prateleira ja chegou do servidor
  chegou: new Map(),      // (#53) o que cada download desta pagina trouxe: alvo -> id do item na prateleira
  segurando: {},          // slider sendo mexido: chave -> instante
  arrastandoSeek: false,
  rotuloId: undefined,
  efeitos: null,          // lista de /api/effects, na ordem de exibicao
  erroEfeitos: null,
  gaveta: false,          // gaveta de efeitos aberta (so conta no computador)
  palco: false,           // toca-discos aberto por cima da prateleira (so no celular)
};
const SEM_EFEITO = 'nenhum';
/* a mesa de DJ (computador largo): lado = onde esta o deck no ar ('a' na esquerda, 'b' na direita); o deck da deixa
   fica com a proxima da fila; antes = o disco que saiu na ultima troca de lado (ele segue no deck dele enquanto soa
   na passagem); bpm = o andamento medido de cada disco que passou pela fila */
const MESA = { montada: null, lado: 'a', idAr: null, trAr: null, antes: null, deixa: null, bpm: new Map(), trocaT: 0 };

/* a maleta do A seguir no celular comeca fechada, so com o proximo, e so a tecla abre e fecha; a
   lista fechada nao pega toque nem foco */
function abrirMaleta(on) {
  const sec = $(celular() ? '.fila-palco' : '.fila-parede'), b = sec.querySelector('.abre-fila'), rot = on ? I18N.t('queue.close') : I18N.t('queue.open');
  sec.classList.toggle('aberta', on);
  b.setAttribute('aria-expanded', on ? 'true' : 'false');
  b.setAttribute('aria-label', rot); b.title = rot;
  sec.querySelector('.lista-fila').inert = !on;
}
/* rolos da parede (so no computador): esmaecem a borda de cima quando ainda ha disco escondido la */
function sombrear(r) {
  const fim = r.scrollHeight - r.clientHeight;
  r.classList.toggle('mais-cima', fim > 1 && r.scrollTop > 2);
}
/* SHARED-JS-FIM */
