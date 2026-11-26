/* I18N-JS-INICIO */
const I18N = (() => {
  const d = window.I18N_DADOS || { lingua: 'pt_BR', textos: {}, reserva: {} };
  const lang = d.lingua.replace('_', '-');
  const tem = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const existe = k => tem(d.textos, k) || tem(d.reserva, k);
  const avisadas = new Set();
  function bruto(chave) {
    if (tem(d.textos, chave)) return d.textos[chave];
    if (tem(d.reserva, chave)) return d.reserva[chave];
    // a chave que falta nas duas linguas aparece na tela como a propria chave: o erro fica a vista
    if (!avisadas.has(chave)) { avisadas.add(chave); console.warn(`i18n: missing key "${chave}"`); }
    return chave;
  }
  function t(chave, params) {
    const s = bruto(chave);
    return params ? s.replace(/\{(\w+)\}/g, (m, k) => (tem(params, k) ? String(params[k]) : m)) : s;
  }
  // o singular so para 1, nas duas linguas que temos: o Intl.PluralRules poe o 0 no singular em portugues, e o Ritmelli
  // sempre escreveu "0 discos". Uma lingua com outras regras pede o plural.select aqui
  function tp(chave, n, params) {
    const k = `${chave}.${n === 1 ? 'one' : 'other'}`;
    return t(existe(k) ? k : `${chave}.other`, { n: n.toLocaleString(lang), ...params });
  }
  // numero com as casas e a virgula (ou o ponto) da lingua
  const num = (v, casas) => v.toLocaleString(lang, { minimumFractionDigits: casas, maximumFractionDigits: casas });
  // so <b> e <code> viram elemento, e sempre com textContent: nada dos arquivos passa por innerHTML. Um param que e
  // um elemento (Node) entra inteiro no lugar do {param}
  function rico(e, chave, params = {}) {
    const troca = s => s.replace(/\{(\w+)\}/g, (m, k) => (tem(params, k) && !(params[k] instanceof Node) ? String(params[k]) : m));
    e.replaceChildren(...bruto(chave).split(/(<(?:b|code)>[\s\S]*?<\/(?:b|code)>|\{\w+\})/).filter(Boolean).map(p => {
      const tag = p.match(/^<(b|code)>([\s\S]*)<\/\1>$/);
      if (tag) { const x = document.createElement(tag[1]); x.textContent = troca(tag[2]); return x; }
      const k = (p.match(/^\{(\w+)\}$/) || [])[1];
      return k && tem(params, k) && params[k] instanceof Node ? params[k] : document.createTextNode(troca(p));
    }));
  }
  const ATRIBUTOS = ['title', 'aria-label', 'placeholder'];
  function aplica(raiz = document) {
    for (const e of raiz.querySelectorAll('[data-i18n]')) {
      const lugares = {};
      for (const f of e.querySelectorAll('[data-i18n-lugar]')) lugares[f.dataset.i18nLugar] = f;
      rico(e, e.dataset.i18n, lugares);
    }
    for (const a of ATRIBUTOS) {
      for (const e of raiz.querySelectorAll(`[data-i18n-${a}]`)) e.setAttribute(a, t(e.getAttribute(`data-i18n-${a}`)));
    }
  }
  document.documentElement.lang = lang;
  // o texto da lingua de reserva (o ingles): a reserva do que tem um desenho por palavra (os botoes do Locutor)
  const reserva = k => (tem(d.reserva, k) ? d.reserva[k] : undefined);
  return { lingua: d.lingua, lang, tem: existe, t, tp, num, rico, aplica, reserva };
})();
/* I18N-JS-FIM */
