/* BROWSER-CHECK-JS-INICIO */
'use strict';
if (!(HTMLScriptElement.supports && HTMLScriptElement.supports('importmap'))) {
  window.stop();
  const notice = document.createElement('body');
  notice.textContent = I18N.t('app.noImportMap');
  document.documentElement.classList.add('i18n-ok');
  document.documentElement.append(notice);
}
/* BROWSER-CHECK-JS-FIM */
