// O anel de audio entre o app e o filtro do microfone (micfx.dll, dentro do audiodg.exe).
//
// Quem cria a memoria e o filtro: ele roda como LocalService, que pode criar objeto Global\, e a permissao deixa o
// usuario logado ler e escrever. O app abre a memoria pelo nome; sem nenhum microfone com o filtro vivo, ela nao
// existe. Nada de mutex: os indices sao contadores de quadros que so crescem (int64), escritos depois dos dados.
//
// O filtro fica em todos os microfones (o instalador pendura), e so o microfone alvo age: o app grava em "alvo" o
// hash do id do microfone escolhido (MicFxHash), e a instancia do filtro de qualquer outro microfone deixa o som
// passar como veio, sem pegar vaga. No alvo, dois sentidos:
// - musica (app -> filtro): um produtor (o app) e ate MICFX_LEITORES leitores; o produtor so escreve onde o leitor
//   mais atrasado ja leu, e cada leitor anda no proprio ritmo. O filtro soma em cima da voz, ou, com sem_voz (e o
//   app vivo), poe so o que veio do app: a voz cortada, ou a voz com efeito que o app devolveu (o efeito que o
//   filtro nao roda).
// - voz crua (filtro -> app): o filtro do alvo escreve a voz do microfone, mono e na taxa dele, antes de somar
//   qualquer coisa; o app le dali (o que ele mesmo le do microfone pelo Windows ja leva a musica).
// - efeito de voz (app -> filtro -> app): o app escreve o preset do efeito (voz.h) com um seqlock (preset_seq impar =
//   escrevendo; par = pronto); o filtro do alvo copia, monta a cadeia e responde em preset_feito (o seq que leu) e
//   preset_erro (voz::Erro). Com a cadeia montada e o app vivo, o filtro poe a voz com efeito no lugar da crua, no
//   proprio bloco, e devolve ao app em voz_fx (ouvir a propria voz). preset_n 0 = sem efeito. No microfone com o
//   hospedeiro do MFX, o efeito (e o corte da voz, quando ele esta montado) roda no hospedeiro, depois do processamento
//   do fabricante: o redutor de ruido dele apagava partes do efeito (#78). O EFX ali so escreve a voz crua.
// - um dono de cada papel: com o microfone aberto por dois programas o Windows pode montar duas cadeias, cada uma com
//   as suas instancias do filtro. Todas agem no proprio som, mas so uma escreve a voz crua (voz_dono, com batida em
//   voz_batida) e so uma escreve a voz com efeito e responde ao preset (fx_dono, fx_batida); sem o hospedeiro e a
//   mesma instancia, com ele o EFX tem a voz e o hospedeiro o efeito. A outra assume quando a dona solta (fechou, ou
//   o microfone saiu do alvo) ou para de bater por MICFX_BATIDA_MS (#70).
// - a pista da voz (app -> filtro): a voz convertida fora do filtro, por um processo do app que le a voz crua e devolve
//   outra (o que o filtro nao tem como rodar no bloco dele). Tem escritor proprio e folga propria, separados da musica:
//   a voz nao paga a folga que o misturador da musica precisa. Com pista_ligada e o escritor batendo (pista_batida, ate
//   MICFX_PISTA_MS), o filtro tira a voz do microfone e poe a da pista, no mesmo ponto em que soma a musica (no microfone
//   com o hospedeiro do MFX, depois do fabricante); o que faltar no bloco sai em silencio, e nao na voz do microfone.
//   Escritor que para de bater = a voz do microfone volta. O leitor que ficar para tras pula para o mais novo: o
//   escritor nunca espera (voz e ao vivo). Ao ligar, o escritor marca em pista_inicio de onde a leitura comeca: a
//   folga que ele escreve logo em seguida (um pouco de silencio antes da voz) toca inteira, mesmo que o filtro so
//   perceba a pista um bloco depois. pista_lido diz ate onde cada leitor leu (-1 = nao esta lendo a pista): o
//   escritor mede a folga por ele, e a cadeia que chega depois (#70) comeca junto da que ja le.
//
// O layout e fixo e o microfone/injeta.py tem o espelho dele em ctypes: mudou aqui, muda la (e sobe MICFX_VERSAO e o
// nome do mapa, que a versao velha pode estar viva no audiodg durante a troca).
#pragma once
#include <stddef.h>
#include <stdint.h>

#ifndef MICFX_MAPA  // a banca de teste (teste/banca_filtro.cpp) usa um nome so dela
#define MICFX_MAPA L"Global\\RitmelliMicFx5"
#endif
#define MICFX_MAGIA 0x58464D52u  // "RMFX"
#define MICFX_VERSAO 5u
#define MICFX_PRESET_BYTES 65536u  // o maior preset (o Locutor, com o FIR de 1023) tem ~10 KB
#define MICFX_TAXA 48000u        // o app escreve sempre a 48 kHz
#define MICFX_CANAIS 2u          // estereo intercalado, float32
#define MICFX_QUADROS 32768u     // potencia de 2: ~0,68 s
#define MICFX_VOZ_QUADROS 16384u // potencia de 2: ~0,34 s da voz crua a 48 kHz
#define MICFX_LEITORES 8u
#define MICFX_BATIDA_MS 500u     // leitor sem batida ha mais que isso e dado como morto
#define MICFX_APP_MS 1000u       // app sem escrever ha mais que isso: a voz volta (o app caiu com a voz cortada)
#define MICFX_PISTA_QUADROS 16384u // potencia de 2: ~0,34 s da pista da voz (48 kHz, estereo como os dados)
#define MICFX_PISTA_MS 1000u     // escritor da pista sem bater ha mais que isso: a voz do microfone volta

typedef struct MicFxLeitor {
    volatile int64_t lido;      // quadros que este leitor ja consumiu
    volatile int64_t batida;    // GetTickCount64 do ultimo APOProcess
    volatile uint32_t dono;     // id da instancia que ocupa a vaga (0 = livre)
    volatile uint32_t taxa;     // taxa do microfone desse leitor (so informativo)
    volatile uint32_t ep;       // hash do microfone desse leitor (0 = nao deu para saber)
    uint32_t reservado;
} MicFxLeitor;

typedef struct MicFxAnel {
    uint32_t magia;
    uint32_t versao;
    uint32_t taxa;
    uint32_t canais;
    uint32_t quadros;
    uint32_t leitores;
    volatile int64_t escrito;     // quadros publicados pelo app
    volatile float ganho;         // ganho do som injetado (1.0 = como veio)
    volatile uint32_t sem_voz;    // 1 = so o que veio do app, a voz do microfone fica de fora (vale com o app vivo)
    volatile int64_t batida_app;  // GetTickCount64 da ultima escrita do app: o sem_voz so vale ate MICFX_APP_MS depois
    volatile uint32_t alvo;       // hash do microfone escolhido no app (0 = nenhum: nenhum filtro mexe no som)
    volatile uint32_t voz_taxa;   // taxa da voz crua (a do microfone alvo)
    volatile int64_t voz_escrito; // quadros de voz crua publicados pelo filtro do alvo
    MicFxLeitor leitor[MICFX_LEITORES];
    float dados[MICFX_QUADROS * MICFX_CANAIS];
    float voz[MICFX_VOZ_QUADROS];
    // o efeito de voz no filtro (v3)
    volatile int64_t fx_escrito;     // quadros de voz com efeito publicados pelo filtro do alvo (taxa da voz crua)
    volatile uint32_t preset_seq;    // seqlock do app: soma 1 antes de escrever e 1 depois (impar = escrevendo)
    volatile uint32_t preset_n;      // bytes do preset (0 = sem efeito no filtro)
    volatile uint32_t preset_feito;  // o preset_seq que o filtro do alvo leu por ultimo
    volatile uint32_t preset_erro;   // o que deu ao montar (voz::Erro; 0 = a voz com efeito sai do filtro)
    float voz_fx[MICFX_VOZ_QUADROS];
    uint8_t preset[MICFX_PRESET_BYTES];
    // os donos (v4): a instancia que escreve a voz crua e a que escreve voz_fx e responde ao preset; 0 = ninguem
    volatile uint32_t voz_dono;
    volatile uint32_t fx_dono;
    volatile int64_t voz_batida;  // GetTickCount64 da ultima escrita da dona da voz crua
    volatile int64_t fx_batida;   // e da dona do efeito
    // a pista da voz (v5): a voz convertida fora do filtro entra no lugar da voz do microfone
    volatile uint32_t pista_ligada;   // 1 = a voz do microfone sai e entra a da pista (vale com o escritor batendo)
    uint32_t pista_reservado;
    volatile int64_t pista_escrito;   // quadros publicados pelo escritor da pista
    volatile int64_t pista_batida;    // GetTickCount64 da ultima escrita (ou pulso) dele
    volatile int64_t pista_inicio;    // o pista_escrito de quando ele ligou: a leitura comeca dali
    volatile int64_t pista_lido[MICFX_LEITORES];  // ate onde o leitor de cada vaga ja leu; -1 = nao le a pista
    float pista[MICFX_PISTA_QUADROS * MICFX_CANAIS];
} MicFxAnel;

// O hash do id do microfone (o GUID do endpoint, "{a1b2c3d4-...}", que e tambem o nome da chave dele no registro):
// FNV-1a de 32 bits sobre os caracteres em minusculo; nunca 0. O app tem o mesmo (injeta.hash_microfone).
static inline uint32_t MicFxHash(const wchar_t* s) {
    uint32_t h = 2166136261u;
    for (; s && *s; s++) {
        wchar_t c = *s;
        if (c >= L'A' && c <= L'Z') {
            c = (wchar_t)(c - L'A' + L'a');
        }
        h ^= (uint32_t)(c & 0xFF);
        h *= 16777619u;
    }
    return h ? h : 1u;
}

#ifdef __cplusplus
static_assert(sizeof(MicFxLeitor) == 32, "MicFxLeitor");
static_assert(offsetof(MicFxAnel, escrito) == 24, "escrito");
static_assert(offsetof(MicFxAnel, batida_app) == 40, "batida_app");
static_assert(offsetof(MicFxAnel, alvo) == 48, "alvo");
static_assert(offsetof(MicFxAnel, voz_escrito) == 56, "voz_escrito");
static_assert(offsetof(MicFxAnel, leitor) == 64, "leitor");
static_assert(offsetof(MicFxAnel, dados) == 320, "dados");
static_assert(offsetof(MicFxAnel, voz) == 320 + MICFX_QUADROS * MICFX_CANAIS * 4, "voz");
static_assert(offsetof(MicFxAnel, fx_escrito) == 328000, "fx_escrito");
static_assert(offsetof(MicFxAnel, preset_seq) == 328008, "preset_seq");
static_assert(offsetof(MicFxAnel, voz_fx) == 328024, "voz_fx");
static_assert(offsetof(MicFxAnel, preset) == 328024 + MICFX_VOZ_QUADROS * 4, "preset");
static_assert(offsetof(MicFxAnel, voz_dono) == 459096, "voz_dono");
static_assert(offsetof(MicFxAnel, fx_dono) == 459100, "fx_dono");
static_assert(offsetof(MicFxAnel, voz_batida) == 459104, "voz_batida");
static_assert(offsetof(MicFxAnel, fx_batida) == 459112, "fx_batida");
static_assert(offsetof(MicFxAnel, pista_ligada) == 459120, "pista_ligada");
static_assert(offsetof(MicFxAnel, pista_escrito) == 459128, "pista_escrito");
static_assert(offsetof(MicFxAnel, pista_batida) == 459136, "pista_batida");
static_assert(offsetof(MicFxAnel, pista_inicio) == 459144, "pista_inicio");
static_assert(offsetof(MicFxAnel, pista_lido) == 459152, "pista_lido");
static_assert(offsetof(MicFxAnel, pista) == 459216, "pista");
static_assert(sizeof(MicFxAnel) == 459216 + MICFX_PISTA_QUADROS * MICFX_CANAIS * 4, "MicFxAnel");
#endif
