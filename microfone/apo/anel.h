// O anel de audio entre o app e o filtro do microfone (micfx.dll, dentro do audiodg.exe).
//
// Quem cria a memoria e o filtro: ele roda como LocalService, que pode criar objeto Global\, e a permissao deixa o
// usuario logado ler e escrever. O app abre a memoria pelo nome; sem nenhum microfone com o filtro vivo, ela nao
// existe. Um produtor (o app) e ate MICFX_LEITORES leitores (cada instancia viva do filtro, uma por microfone ou
// stream): o produtor so escreve onde o leitor mais atrasado ja leu, e cada leitor anda no proprio ritmo. Nada de
// mutex: os indices sao contadores de quadros que so crescem (int64), escritos depois dos dados.
//
// O layout e fixo e o microfone/injeta.py tem o espelho dele em ctypes: mudou aqui, muda la (e sobe MICFX_VERSAO).
#pragma once
#include <stddef.h>
#include <stdint.h>

#define MICFX_MAPA L"Global\\RitmelliMicFx1"
#define MICFX_MAGIA 0x58464D52u  // "RMFX"
#define MICFX_VERSAO 1u
#define MICFX_TAXA 48000u        // o app escreve sempre a 48 kHz
#define MICFX_CANAIS 2u          // estereo intercalado, float32
#define MICFX_QUADROS 32768u     // potencia de 2: ~0,68 s
#define MICFX_LEITORES 8u
#define MICFX_BATIDA_MS 500u     // leitor sem batida ha mais que isso e dado como morto

typedef struct MicFxLeitor {
    volatile int64_t lido;      // quadros que este leitor ja consumiu
    volatile int64_t batida;    // GetTickCount64 do ultimo APOProcess
    volatile uint32_t dono;     // id da instancia que ocupa a vaga (0 = livre)
    volatile uint32_t taxa;     // taxa do microfone desse leitor (so informativo)
} MicFxLeitor;

typedef struct MicFxAnel {
    uint32_t magia;
    uint32_t versao;
    uint32_t taxa;
    uint32_t canais;
    uint32_t quadros;
    uint32_t leitores;
    volatile int64_t escrito;   // quadros publicados pelo app
    volatile float ganho;       // ganho do som injetado (1.0 = como veio)
    volatile uint32_t sem_voz;  // 1 = so o som injetado, a voz do microfone fica de fora
    uint32_t reservado[6];
    MicFxLeitor leitor[MICFX_LEITORES];
    float dados[MICFX_QUADROS * MICFX_CANAIS];
} MicFxAnel;

#ifdef __cplusplus
static_assert(sizeof(MicFxLeitor) == 24, "MicFxLeitor");
static_assert(offsetof(MicFxAnel, escrito) == 24, "escrito");
static_assert(offsetof(MicFxAnel, leitor) == 64, "leitor");
static_assert(offsetof(MicFxAnel, dados) == 256, "dados");
#endif
