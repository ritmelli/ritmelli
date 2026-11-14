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
//   app vivo), poe so o que veio do app: a voz cortada, ou a voz com efeito que o app devolveu.
// - voz crua (filtro -> app): o filtro do alvo escreve a voz do microfone, mono e na taxa dele, antes de somar
//   qualquer coisa; o app le dali (o que ele mesmo le do microfone pelo Windows ja leva a musica).
//
// O layout e fixo e o microfone/injeta.py tem o espelho dele em ctypes: mudou aqui, muda la (e sobe MICFX_VERSAO e o
// nome do mapa, que a versao velha pode estar viva no audiodg durante a troca).
#pragma once
#include <stddef.h>
#include <stdint.h>

#define MICFX_MAPA L"Global\\RitmelliMicFx2"
#define MICFX_MAGIA 0x58464D52u  // "RMFX"
#define MICFX_VERSAO 2u
#define MICFX_TAXA 48000u        // o app escreve sempre a 48 kHz
#define MICFX_CANAIS 2u          // estereo intercalado, float32
#define MICFX_QUADROS 32768u     // potencia de 2: ~0,68 s
#define MICFX_VOZ_QUADROS 16384u // potencia de 2: ~0,34 s da voz crua a 48 kHz
#define MICFX_LEITORES 8u
#define MICFX_BATIDA_MS 500u     // leitor sem batida ha mais que isso e dado como morto
#define MICFX_APP_MS 1000u       // app sem escrever ha mais que isso: a voz volta (o app caiu com a voz cortada)

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
#endif
