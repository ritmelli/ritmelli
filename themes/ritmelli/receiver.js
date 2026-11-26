/* RECEIVER-JS-INICIO */
'use strict';
/* ---------- receptor ---------- */
/* o volume do disco anda numa escala perceptiva: o ganho e a posicao ao cubo. Linear, 2% era -34 dB e 3% -30 dB, e
   no volume de lobby cada passo pulava 2,5 a 3,5 dB; ao cubo, do silencio ate 10% do ganho cabem 46 dos 100 passos, e
   perto de 2% cada passo muda ~1 dB. O motor, a API e o config.json seguem com o ganho linear de 0 a 1. A voz fica
   linear: e o nivel do microfone no Windows, com o numero que ele mostra */
const FADERS = [['#f-vol', '#o-vol', 'vol', true], ['#f-mon', '#o-mon', 'mon_vol', true], ['#f-mic', '#o-mic', 'mic_vol', false]];
const ganhoDaPos = p => (p / 100) ** 3;
const posDoGanho = g => Math.round(Math.cbrt(Math.max(0, Math.min(1, g))) * 100);
// o ganho do fader para o leitor de tela, na lingua (a virgula ou o ponto do I18N.num, com o sinal de menos de verdade)
function dbDoGanho(g) { return g > 0 ? I18N.t('mixer.gainDb', { db: I18N.num(20 * Math.log10(g), 1).replace('-', '−') }) : I18N.t('mixer.gainMuted'); }
function rotularFader(f, o, curva, g) {   // g: o ganho que o motor tem (o leitor de tela diz em dB)
  o.textContent = f.value + '%';
  if (curva) f.setAttribute('aria-valuetext', `${f.value}%, ${dbDoGanho(g)}`);
}
function desenharReceptor() {
  const s = S.state; if (!s) return;
  const agora = Date.now();
  for (const [fi, oi, k, curva] of FADERS) {
    if (agora - (S.segurando[k] || 0) < 900) continue;
    // sem a chave "Fone ligado", o fone desligado aparece como volume zero
    const f = $(fi), g = k === 'mon_vol' && !s.monitor_on ? 0 : s[k] || 0;
    f.value = curva ? posDoGanho(g) : Math.round(g * 100); pintarFader(f); rotularFader(f, $(oi), curva, g);
  }
  // fone "Nenhum" no dialogo: o volume do fone nao tem efeito, entao apaga e diz por que
  const semFone = !!s.active_devices && !s.active_devices.monitor;
  $('#f-mon').disabled = semFone;
  $('#f-mon').closest('.fader').title = semFone ? I18N.t('mixer.noHeadphones') : '';
  $('label[for="f-mon"] small').textContent = semFone ? I18N.t('mixer.noHeadphonesShort') : '';
  ligarChave($('#b-cortar'), s.mic_mute);
  // o volume automatico (no Microfone e fone): ligado, a alta desce e a baixa sobe ate o mesmo volume; diz quanto nesta
  $('#b-nivelar').closest('.nivelar').hidden = !('volume_auto' in s);   // servidor antigo: sem a chave
  ligarChave($('#b-nivelar'), !!s.volume_auto);
  const gdb = s.ganho_db || 0;
  $('#dd-nivelar').textContent = !s.volume_auto ? I18N.t('devices.autoVolumeOff')
    : I18N.t('devices.autoVolumeOn') + (Math.abs(gdb) < 0.05 ? ''
      : ' ' + I18N.t(gdb > 0 ? 'devices.autoVolumeUp' : 'devices.autoVolumeDown', { db: I18N.num(Math.abs(gdb), 1) }));
  for (const mc of [$('#mini-cortar'), $('#palco-cortar')]) {   // o da barra e o do cabecalho do palco
    if (mc._cortada === !!s.mic_mute) continue;
    mc._cortada = !!s.mic_mute;
    mc.setAttribute('aria-pressed', s.mic_mute ? 'true' : 'false');
    mc.classList.toggle('cortada', !!s.mic_mute);
    mc.title = s.mic_mute ? I18N.t('voice.mutedTap') : I18N.t('voice.mute');
    mc.innerHTML = s.mic_mute ? IC_MIC_CORTADO : IC_MIC;
  }
  const mt = $('#b-mudo-topo');   // o do topo na pagina do disco (computador): o icone e o nome dizem o estado
  if (mt._cortada !== !!s.mic_mute) {
    mt._cortada = !!s.mic_mute;
    mt.setAttribute('aria-pressed', s.mic_mute ? 'true' : 'false');
    mt.classList.toggle('cortada', !!s.mic_mute);
    mt.title = s.mic_mute ? I18N.t('voice.mutedClick') : I18N.t('voice.mute');
    mt.querySelector('.ic-mic').innerHTML = s.mic_mute ? IC_MIC_CORTADO : IC_MIC;
    mt.querySelector('.rot').textContent = s.mic_mute ? I18N.t('voice.muted') : I18N.t('voice.mute');
  }
  const mic = document.querySelector('.mostrador[data-k="mic"]');
  mic.classList.toggle('apagado', !!s.mic_mute);
  mic.querySelector('.nome-m').textContent = s.mic_mute ? I18N.t('mixer.meter.voiceMuted') : I18N.t('mixer.meter.voice');
  desenharEfeito();
}
function pintarFader(f) { f.style.setProperty('--p', (f.value / f.max * 100).toFixed(1) + '%'); f.style.setProperty('--f', (f.value / f.max).toFixed(4)); }

function alternarVoz() { const v = !(S.state && S.state.mic_mute); ligarChave($('#b-cortar'), v); ajustar('mic_mute', v); desenharReceptor(); }
function mutarComAviso() {
  alternarVoz();
  avisar(S.state && S.state.mic_mute ? I18N.t('voice.mutedToast') : I18N.t('voice.backToast'));
}
function bindReceiver() {
  $('#b-cortar').addEventListener('click', alternarVoz);
  $('#b-nivelar').addEventListener('click', () => { const v = !(S.state && S.state.volume_auto); ligarChave($('#b-nivelar'), v); ajustar('volume_auto', v); });
  for (const [fi, oi, k, curva] of FADERS) {
    const f = $(fi);
    f.addEventListener('input', () => {
      const g = curva ? ganhoDaPos(+f.value) : f.value / 100;
      pintarFader(f); rotularFader(f, $(oi), curva, g); ajustar(k, g);
      // fone desligado (de antes, quando havia a chave): subir o volume do fone religa
      if (k === 'mon_vol' && S.state && !S.state.monitor_on && +f.value > 0) ajustar('monitor_on', true);
    });
  }
}
/* RECEIVER-JS-FIM */
