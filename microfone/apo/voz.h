// voz.h: os efeitos de voz do Ritmelli rodando dentro do filtro do microfone (micfx.dll), sem a ida e volta pelo app.
//
// O app (microfone/preset.py) le o efeito do fx.py e monta o PRESET: a lista de etapas com os parametros e os
// coeficientes ja projetados na taxa do microfone (o scipy projeta, aqui so se roda). O filtro copia o preset do anel
// (anel.h), carrega a cadeia numa memoria propria (Arena, separada no LockForProcess) e passa a voz por ela no bloco
// do audiodg. O mesmo cabecalho compila no voz.dll, que os testes do app carregam por ctypes (microfone/voz.py) para
// conferir cada etapa contra a cadeia do fx.py.
//
// Tempo real: nada de alocacao, trava ou chamada que espera. O preset vem de uma memoria que o usuario escreve, e o
// filtro roda como LocalService: toda contagem e todo parametro se conferem antes de usar (Leitor), e a memoria de
// cada etapa sai da Arena com limite. Preset que nao passa = sem efeito (a voz crua segue).
//
// As etapas que imitam a pedalboard (filtros RBJ, Compressor e Limiter, Distortion, Bitcrush, Delay, Chorus, Phaser,
// Reverb) foram escritas a partir das formulas publicas de cada algoritmo e conferidas contra a saida dela (caixa
// preta, dev/testa_voz.py). As etapas do fx.py (PitchShifter, PortaoRuido, AGC, Multibanda, CambioRadio, Fdn,
// Distorcao...) sao a mesma conta, em blocos: o que no fx.py conta blocos de 10 ms aqui conta tempo, e da o mesmo
// resultado com o bloco de 10 ms do audiodg.
#pragma once
#include <math.h>
#include <cmath>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace voz {

static const uint32_t MAGIA = 0x315A5652u;  // "RVZ1"
static const uint32_t VERSAO = 1u;
static const uint32_t MAX_ETAPAS = 32u;
static const uint32_t MAX_BLOCO = 8192u;  // amostras por passada; o que vier maior se fatia
static const double PI = 3.14159265358979323846;
static const double BLOCO_REF = 0.01;  // o bloco do fx.py (10 ms): os coeficientes "por bloco" valem para ele

// o que o filtro devolve no anel (preset_erro)
enum Erro : uint32_t { OK = 0, INVALIDO = 1, SEM_MEMORIA = 2, TAXA = 3 };

enum Tipo : uint32_t {
    T_SOS = 1,         // secoes de segunda ordem (b0 b1 b2 a1 a2), DF2 transposta em double, como o sosfilt
    T_FIR = 2,         // FIR direto (o QuestComoSM58)
    T_GANHO = 3,       // ganho linear
    T_PITCH = 4,       // PitchShifter do fx.py
    T_RINGMOD = 5,     // RingMod do fx.py
    T_PORTAO = 6,      // PortaoRuido do fx.py
    T_DECIMA = 7,      // Decimador do fx.py (amostra e segura)
    T_AGC = 8,         // AGC do fx.py
    T_MULTIBANDA = 9,  // Multibanda + CompBanda do fx.py
    T_COMPRESSOR = 10, // o Compressor da pedalboard
    T_LIMITER = 11,    // o Limiter da pedalboard
    T_DISTORCAO = 12,  // o Distortion da pedalboard (tanh)
    T_BITCRUSH = 13,   // o Bitcrush da pedalboard
    T_DELAY = 14,      // o Delay da pedalboard
    T_CHORUS = 15,     // o Chorus da pedalboard
    T_PHASER = 16,     // o Phaser da pedalboard
    T_FREEVERB = 17,   // o Reverb da pedalboard (Freeverb)
    T_RADIO = 18,      // CambioRadio.detecta do fx.py (o som do canal sai pelo gerador do extra)
    T_FDN = 19,        // Fdn do fx.py (reverb de rede de atraso com realimentacao)
    T_DISTORCAO_OS = 20,  // a Distorcao do fx.py (o tanh com oversampling)
};

enum Gerador : uint32_t { G_NENHUM = 0, G_RADIO = 1 };

// ---------------------------------------------------------------------------------------------------------------
// Memoria: tudo que uma cadeia usa sai daqui, zerado

struct Arena {
    uint8_t* base = nullptr;
    size_t cap = 0;
    size_t usado = 0;
    bool faltou = false;  // algum pedido nao coube

    template <class T>
    T* Pega(size_t n) {
        const size_t al = 16;
        const size_t ini = (usado + al - 1) & ~(al - 1);
        if (n == 0) {
            return nullptr;
        }
        if (n > cap / sizeof(T) || ini > cap || cap - ini < n * sizeof(T)) {
            faltou = true;
            return nullptr;
        }
        usado = ini + n * sizeof(T);
        T* p = reinterpret_cast<T*>(base + ini);
        memset(p, 0, n * sizeof(T));
        return p;
    }
};

// O tamanho da memoria de uma cadeia na taxa: sobra para todo efeito do fx.py (o maior, o Radio, usa ~350 KB a
// 48 kHz e ~530 KB a 96 kHz; a Catedral, com as linhas da Fdn, ~450 KB a 48 kHz e ~740 KB a 96 kHz; o
// dev/testa_voz.py confere que cada um cabe em 3/4). Uma por instancia do filtro.
static inline size_t ArenaBytes(double taxa) {
    const double k = taxa > 48000.0 ? taxa / 48000.0 : 1.0;
    return (size_t)(768.0 * 1024.0 * k) + 256 * 1024;
}

// Os parametros de uma etapa: doubles em sequencia, lidos com conferencia (fora do intervalo, NaN ou falta = invalido)
struct Leitor {
    const uint8_t* p;
    uint32_t n;
    uint32_t i = 0;
    bool ok = true;

    Leitor(const uint8_t* dados, uint32_t quantos) : p(dados), n(quantos) {}

    double Le(double lo, double hi) {
        if (i >= n) {
            ok = false;
            return lo;
        }
        double v;
        memcpy(&v, p + (size_t)i * 8, 8);
        i++;
        if (!(v >= lo && v <= hi)) {  // NaN cai aqui
            ok = false;
            return lo;
        }
        return v;
    }
    uint32_t Conta(uint32_t max) {
        const double v = Le(0.0, (double)max);
        const uint32_t c = (uint32_t)v;
        if ((double)c != v) {
            ok = false;
        }
        return c;
    }
};

struct Ctx {
    double taxa;
    double dt;  // duracao do bloco (s)
    float* tmp[3];  // MAX_BLOCO cada, para quem precisa (Multibanda)
};

static inline double Pot(double base, double expoente) { return pow(base, expoente); }

// coeficiente "por bloco de 10 ms" do fx.py levado a um bloco de dt
static inline double PorBloco(double c, double dt) { return 1.0 - Pot(1.0 - c, dt / BLOCO_REF); }

static inline double Rms(const float* x, uint32_t n) {
    double s = 0.0;
    for (uint32_t i = 0; i < n; i++) {
        s += (double)x[i] * (double)x[i];
    }
    return n ? s / n : 0.0;  // a media do quadrado
}

// ---------------------------------------------------------------------------------------------------------------
// Etapas

struct Sos {
    uint32_t k;
    double* c;  // k x (b0 b1 b2 a1 a2)
    double* z;  // k x 2
    bool Prepara(Leitor& l, Arena& a) {
        k = l.Conta(16);
        if (!l.ok || !k || !(c = a.Pega<double>(k * 5)) || !(z = a.Pega<double>(k * 2))) {
            return false;
        }
        for (uint32_t s = 0; s < k; s++) {
            for (uint32_t j = 0; j < 5; j++) {
                c[s * 5 + j] = l.Le(-1e6, 1e6);
            }
            const double a1 = c[s * 5 + 3], a2 = c[s * 5 + 4];
            if (!(fabs(a2) < 1.0 && fabs(a1) < 1.0 + a2)) {  // polos fora do circulo: instavel
                return false;
            }
        }
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            double v = x[i];
            for (uint32_t s = 0; s < k; s++) {
                const double* q = &c[s * 5];
                double* zz = &z[s * 2];
                const double y = q[0] * v + zz[0];
                zz[0] = q[1] * v - q[3] * y + zz[1];
                zz[1] = q[2] * v - q[4] * y;
                v = y;
            }
            x[i] = (float)v;
        }
    }
};

struct Fir {
    uint32_t n;
    uint32_t p;
    double* h;
    float* hist;  // 2n: cada amostra vai em p e p + n, o produto le n seguidas
    bool Prepara(Leitor& l, Arena& a) {
        n = l.Conta(4096);
        if (!l.ok || !n || !(h = a.Pega<double>(n)) || !(hist = a.Pega<float>(2 * (size_t)n))) {
            return false;
        }
        for (uint32_t j = 0; j < n; j++) {
            h[j] = l.Le(-1e3, 1e3);
        }
        p = 0;
        return l.ok;
    }
    void Processa(float* x, uint32_t m) {
        for (uint32_t i = 0; i < m; i++) {
            p = p ? p - 1 : n - 1;
            hist[p] = hist[p + n] = x[i];
            const float* q = &hist[p];
            double s = 0.0;
            for (uint32_t j = 0; j < n; j++) {
                s += h[j] * (double)q[j];
            }
            x[i] = (float)s;
        }
    }
};

struct Ganho {
    double g;
    bool Prepara(Leitor& l) {
        g = l.Le(0.0, 1e4);
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            x[i] = (float)(x[i] * g);
        }
    }
};

struct Pitch {
    double inc, w, xf, d;
    float* hist;
    uint64_t mask, t;
    bool Prepara(Leitor& l, Arena& a) {
        inc = l.Le(-64.0, 1.0);
        w = l.Le(16.0, 65536.0);
        xf = l.Le(1.0, 65536.0);
        if (!l.ok) {
            return false;
        }
        uint64_t tam = 1;
        while (tam < (uint64_t)(2.0 * w + 4.0)) {
            tam <<= 1;
        }
        if (!(hist = a.Pega<float>((size_t)tam))) {
            return false;
        }
        mask = tam - 1;
        t = 0;
        d = inc >= 0.0 ? 0.0 : w - 1e-3;
        return true;
    }
    float Tap(double atraso) const {
        const double pos = (double)t - atraso;
        const double f0 = floor(pos);
        const double fr = pos - f0;
        const int64_t i0 = (int64_t)f0;
        const int64_t i1 = i0 + 1 <= (int64_t)t ? i0 + 1 : (int64_t)t;
        const double a = hist[(uint64_t)i0 & mask], b = hist[(uint64_t)i1 & mask];
        return (float)(a * (1.0 - fr) + b * fr);
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            hist[t & mask] = x[i];
            d += inc;
            d -= floor(d / w) * w;
            const double g = d / xf < 1.0 ? d / xf : 1.0;
            x[i] = (float)(Tap(d) * g + Tap(d + w) * (1.0 - g));
            t++;
        }
    }
};

struct RingMod {
    double passo, mix, fase;
    bool Prepara(Leitor& l, double taxa) {
        passo = 2.0 * PI * l.Le(0.0, 20000.0) / taxa;
        mix = l.Le(0.0, 1.0);
        fase = 0.0;
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            fase += passo;
            x[i] = (float)(x[i] * (1.0 - mix + mix * sin(fase)));
        }
        fase = fmod(fase, 2.0 * PI);
    }
};

struct Portao {
    double piso, abre_fundo, fecha, sem_voz, abre_voz, segura_s, fecha_s, memoria, aprende_s, sobe_db_s, abre_s;
    double fundo, voz_db, tempo, g, resta;
    bool tem_fundo, tem_voz, aberto;
    bool Prepara(Leitor& l) {
        piso = l.Le(1e-6, 1.0);
        abre_fundo = l.Le(1.0, 1e4);
        fecha = l.Le(1.0, 1e4);
        sem_voz = l.Le(1.0, 1e4);
        abre_voz = l.Le(1e-6, 1.0);
        segura_s = l.Le(0.0, 10.0);
        fecha_s = l.Le(1e-3, 10.0);
        memoria = l.Le(0.0, 1.0);
        aprende_s = l.Le(0.0, 10.0);
        sobe_db_s = l.Le(0.0, 100.0);
        abre_s = l.Le(0.0, 0.1);
        g = piso;
        tem_fundo = tem_voz = aberto = false;
        tempo = resta = fundo = voz_db = 0.0;
        return l.ok;
    }
    void Processa(float* x, uint32_t n, const Ctx& c) {
        const double rms = sqrt(Rms(x, n)) + 1e-9;
        tempo += c.dt;
        if (!tem_fundo || tempo <= aprende_s + 1e-9) {  // o comeco: o menor nivel visto
            fundo = tem_fundo && fundo < rms ? fundo : rms;
            tem_fundo = true;
        } else if (!aberto) {  // desce na hora, sobe devagar so com o portao fechado
            const double sobe = fundo * Pot(10.0, sobe_db_s * c.dt / 20.0);
            fundo = rms < sobe ? rms : sobe;
        }
        double abre;
        if (!tem_voz) {
            abre = fundo * sem_voz;
        } else {
            const double a1 = fundo * abre_fundo, a2 = Pot(10.0, voz_db / 20.0) * abre_voz;
            abre = a1 > a2 ? a1 : a2;
        }
        if (rms > abre) {
            aberto = true;
            resta = segura_s;
        } else if (aberto && rms < fundo * fecha) {
            resta -= c.dt;
            if (resta <= 1e-6) {
                aberto = false;
            }
        }
        if (aberto && rms > fundo * sem_voz) {
            const double db = 20.0 * log10(rms);
            const double m = Pot(memoria, c.dt / BLOCO_REF);
            voz_db = tem_voz ? m * voz_db + (1.0 - m) * db : db;
            tem_voz = true;
        }
        const double alvo = aberto ? 1.0 : piso;
        if (!n) {
            return;
        }
        if (alvo > g) {  // abre rapido: rampa linear ate 1 e depois 1
            uint32_t k = (uint32_t)(abre_s * c.taxa);
            k = k < n ? k : n;
            for (uint32_t i = 0; i < n; i++) {
                double r = 1.0;
                if (i < k) {
                    r = k > 1 ? g + (1.0 - g) * (double)i / (double)(k - 1) : g;
                }
                x[i] = (float)(x[i] * r);
            }
            g = k < n ? 1.0 : (k > 1 ? 1.0 : g);
        } else {  // fecha em escala de dB
            const double passo = g * Pot(piso, c.dt / fecha_s);
            const double fim = alvo > passo ? alvo : passo;
            for (uint32_t i = 0; i < n; i++) {
                const double r = n > 1 ? g * Pot(fim / g, (double)i / (double)(n - 1)) : g;
                x[i] = (float)(x[i] * r);
            }
            g = n > 1 ? fim : g;
        }
    }
};

struct Decima {
    double fator, acc;
    float hold;
    bool Prepara(Leitor& l) {
        fator = l.Le(1.0, 1000.0);
        acc = 0.0;
        hold = 0.0f;
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            if (acc <= 1e-9) {
                hold = x[i];
                acc += fator;
            }
            acc -= 1.0;
            x[i] = hold;
        }
    }
};

struct Agc {
    double alvo, porta, teto, c_nivel, c_desce, c_sobe, nivel, g;
    bool Prepara(Leitor& l) {
        alvo = l.Le(-120.0, 0.0);
        porta = l.Le(-200.0, 0.0);
        teto = l.Le(0.0, 60.0);
        c_nivel = l.Le(0.0, 1.0);
        c_desce = l.Le(0.0, 1.0);
        c_sobe = l.Le(0.0, 1.0);
        nivel = alvo;
        g = 0.0;
        return l.ok;
    }
    void Processa(float* x, uint32_t n, const Ctx& c) {
        const double db = 10.0 * log10(Rms(x, n) + 1e-12);
        if (db > porta) {
            nivel += (db - nivel) * PorBloco(c_nivel, c.dt);
            double a = alvo - nivel;
            a = a < -teto ? -teto : (a > teto ? teto : a);
            g += (a - g) * PorBloco(a < g ? c_desce : c_sobe, c.dt);
        }
        const double k = Pot(10.0, g / 20.0);
        for (uint32_t i = 0; i < n; i++) {
            x[i] = (float)(x[i] * k);
        }
    }
};

struct CompBanda {
    double lim, razao, portao, ataque_ms, solta_ms, ganho, env, red;
    bool Prepara(Leitor& l) {
        lim = l.Le(-200.0, 0.0);
        razao = l.Le(1.0, 1000.0);
        ataque_ms = l.Le(0.01, 10000.0);
        solta_ms = l.Le(0.01, 10000.0);
        ganho = l.Le(-60.0, 60.0);
        portao = lim - 10.0;
        env = lim - 30.0;
        red = 0.0;
        return l.ok;
    }
    // soma em out o bloco b comprimido
    void Soma(const float* b, float* out, uint32_t n, const Ctx& c) {
        const double db = 10.0 * log10(Rms(b, n) + 1e-12);
        const double ant = red;
        if (db > portao) {
            const double k = exp(-c.dt * 1000.0 / (db > env ? ataque_ms : solta_ms));
            env = k * env + (1.0 - k) * db;
            red = (env - lim > 0.0 ? env - lim : 0.0) * (1.0 - 1.0 / razao);
        }
        for (uint32_t i = 0; i < n; i++) {
            const double r = n > 1 ? -ant + (ant - red) * (double)i / (double)(n - 1) : -ant;
            out[i] += (float)(b[i] * Pot(10.0, (r + ganho) / 20.0));
        }
    }
};

struct Multibanda {
    uint32_t k;  // cortes
    Sos lo[4], hi[4];
    CompBanda comp[5];
    bool Prepara(Leitor& l, Arena& a) {
        k = l.Conta(4);
        if (!l.ok || !k) {
            return false;
        }
        for (uint32_t j = 0; j < k; j++) {
            if (!lo[j].Prepara(l, a) || !hi[j].Prepara(l, a)) {
                return false;
            }
        }
        for (uint32_t j = 0; j <= k; j++) {
            if (!comp[j].Prepara(l)) {
                return false;
            }
        }
        return l.ok;
    }
    void Processa(float* x, uint32_t n, const Ctx& c) {
        float* resto = c.tmp[0];
        float* b = c.tmp[1];
        float* out = c.tmp[2];
        memcpy(resto, x, n * sizeof(float));
        memset(out, 0, n * sizeof(float));
        for (uint32_t j = 0; j < k; j++) {
            memcpy(b, resto, n * sizeof(float));
            lo[j].Processa(b, n);
            hi[j].Processa(resto, n);
            comp[j].Soma(b, out, n, c);
        }
        comp[k].Soma(resto, out, n, c);
        memcpy(x, out, n * sizeof(float));
    }
};

// o compressor da pedalboard: envelope de pico com ataque e soltura, ganho (env / limiar)^(1/razao - 1) acima dele
struct Compressor {
    double limiar, inv, ca, cs, env;
    bool Prepara(Leitor& l, double taxa) {
        const double lim_db = l.Le(-200.0, 60.0);
        const double razao = l.Le(1.0, 1e6);
        const double ataque = l.Le(0.0, 10000.0);
        const double solta = l.Le(0.0, 10000.0);
        Monta(lim_db, razao, ataque, solta, taxa);
        return l.ok;
    }
    void Monta(double lim_db, double razao, double ataque, double solta, double taxa) {
        const double ef = -2.0 * PI * 1000.0 / taxa;
        limiar = Pot(10.0, lim_db / 20.0);
        inv = 1.0 / razao - 1.0;
        ca = ataque < 1e-3 ? 0.0 : exp(ef / ataque);
        cs = solta < 1e-3 ? 0.0 : exp(ef / solta);
        env = 0.0;
    }
    inline double Amostra(double v) {
        const double a = fabs(v);
        env = a + (a > env ? ca : cs) * (env - a);
        return env < limiar ? v : v * Pot(env / limiar, inv);
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            x[i] = (float)Amostra(x[i]);
        }
    }
};

// o limiter da pedalboard: dois compressores (o primeiro fixo), ganho de saida e corte em 1
struct Limiter {
    Compressor c1, c2;
    double ganho;
    bool Prepara(Leitor& l, double taxa) {
        const double lim_db = l.Le(-100.0, 0.0);
        const double solta = l.Le(0.0, 10000.0);
        c1.Monta(-10.0, 4.0, 2.0, 200.0, taxa);
        c2.Monta(lim_db, 1000.0, 0.001, solta, taxa);
        ganho = Pot(10.0, (10.0 * (1.0 - 1.0 / 4.0) / 2.0 - lim_db) / 20.0);
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            double v = c2.Amostra(c1.Amostra(x[i])) * ganho;
            x[i] = (float)(v > 1.0 ? 1.0 : (v < -1.0 ? -1.0 : v));
        }
    }
};

struct Distorcao {
    double g;
    bool Prepara(Leitor& l) {
        g = Pot(10.0, l.Le(-60.0, 100.0) / 20.0);
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            x[i] = (float)tanh(x[i] * g);
        }
    }
};

// A Distorcao do fx.py: o mesmo tanh, mas a 2^est vezes a taxa. Cada 2x sobe com zeros no meio e o FIR meia-banda
// (projetado no fx.py) tira as imagens; o tanh roda na taxa alta; cada 2x desce pelo mesmo FIR, que tira o que passa da
// metade da taxa antes de ficar 1 amostra de cada 2. Sem isso as harmonicas acima da metade da taxa dobram para dentro
// da faixa (aliasing). Roda em pedacos de PEDACO amostras, para a memoria da taxa alta ficar pequena.
struct DistorcaoOS {
    static const uint32_t PEDACO = 64u;
    static const uint32_t MAX_EST = 3u;
    static const uint32_t MAX_TAPS = 255u;
    double g;
    uint32_t est, nh, npar, nimpar;
    double* h;
    uint32_t *par, *impar;  // os taps nao nulos de indice par e de indice impar
    double* sobe[MAX_EST];  // de cada estagio: o fim do sinal de antes (nh - 1) e o pedaco novo
    double* desce[MAX_EST];
    double *a, *b;  // o pedaco na taxa alta, ida e volta

    bool Prepara(Leitor& l, Arena& ar) {
        g = Pot(10.0, l.Le(-60.0, 100.0) / 20.0);
        est = l.Conta(MAX_EST);
        nh = l.Conta(MAX_TAPS);
        if (!l.ok || est < 1 || nh < 1 || nh % 2 == 0) {
            return false;
        }
        if (!(h = ar.Pega<double>(nh)) || !(par = ar.Pega<uint32_t>(nh)) || !(impar = ar.Pega<uint32_t>(nh))) {
            return false;
        }
        npar = nimpar = 0;
        for (uint32_t k = 0; k < nh; k++) {
            h[k] = l.Le(-1.0, 1.0);
            if (h[k] != 0.0) {
                if (k & 1u) {
                    impar[nimpar++] = k;
                } else {
                    par[npar++] = k;
                }
            }
        }
        for (uint32_t s = 0; s < est; s++) {
            if (!(sobe[s] = ar.Pega<double>(nh - 1 + (PEDACO << (s + 1)))) ||
                !(desce[s] = ar.Pega<double>(nh - 1 + (PEDACO << (est - s))))) {
                return false;
            }
        }
        return l.ok && (a = ar.Pega<double>(PEDACO << est)) && (b = ar.Pega<double>(PEDACO << est));
    }

    // m amostras viram 2m: o sinal com um zero depois de cada amostra (vezes 2, o ganho que o zero tira) pelo FIR. Com
    // os zeros, a saida par so pega taps pares e a impar so os impares (o resto multiplica zero)
    void Sobe(double* buf, const double* in, uint32_t m, double* out) const {
        double* novo = buf + nh - 1;
        for (uint32_t i = 0; i < m; i++) {
            novo[2 * i] = 2.0 * in[i];
            novo[2 * i + 1] = 0.0;
        }
        for (uint32_t j = 0; j < 2 * m; j++) {
            const uint32_t* t = (j & 1u) ? impar : par;
            const uint32_t q = (j & 1u) ? nimpar : npar;
            double s = 0.0;
            for (uint32_t k = 0; k < q; k++) {
                s += h[t[k]] * novo[(ptrdiff_t)j - (ptrdiff_t)t[k]];
            }
            out[j] = s;
        }
        memmove(buf, buf + 2 * m, (nh - 1) * sizeof(double));
    }

    // m amostras (par) viram m/2: o FIR so nas que ficam
    void Desce(double* buf, const double* in, uint32_t m, double* out) const {
        double* novo = buf + nh - 1;
        memcpy(novo, in, m * sizeof(double));
        for (uint32_t i = 0; i < m / 2; i++) {
            const ptrdiff_t j = (ptrdiff_t)(2 * i);
            double s = 0.0;
            for (uint32_t k = 0; k < npar; k++) {
                s += h[par[k]] * novo[j - (ptrdiff_t)par[k]];
            }
            for (uint32_t k = 0; k < nimpar; k++) {
                s += h[impar[k]] * novo[j - (ptrdiff_t)impar[k]];
            }
            out[i] = s;
        }
        memmove(buf, buf + m, (nh - 1) * sizeof(double));
    }

    void Processa(float* x, uint32_t n) {
        while (n) {
            const uint32_t m = n < PEDACO ? n : PEDACO;
            double *p = a, *q = b, *t;
            for (uint32_t i = 0; i < m; i++) {
                p[i] = x[i];
            }
            uint32_t len = m;
            for (uint32_t s = 0; s < est; s++) {
                Sobe(sobe[s], p, len, q);
                len *= 2;
                t = p; p = q; q = t;
            }
            for (uint32_t i = 0; i < len; i++) {
                p[i] = tanh(p[i] * g);
            }
            for (uint32_t s = 0; s < est; s++) {
                Desce(desce[s], p, len, q);
                len /= 2;
                t = p; p = q; q = t;
            }
            for (uint32_t i = 0; i < m; i++) {
                x[i] = (float)p[i];
            }
            x += m;
            n -= m;
        }
    }
};

struct Bitcrush {
    double s;
    bool Prepara(Leitor& l) {
        s = Pot(2.0, l.Le(1.0, 32.0));
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            x[i] = (float)(nearbyint((double)x[i] * s) / s);  // metade vai pro par, como o np.round
        }
    }
};

struct Delay {
    uint32_t d, i;
    double fb, mix;
    float* buf;
    bool Prepara(Leitor& l, Arena& a, double taxa) {
        const double s = l.Le(1.0 / taxa, 5.0);
        fb = l.Le(0.0, 1.0);
        mix = l.Le(0.0, 1.0);
        d = (uint32_t)floor(s * taxa + 0.5);
        i = 0;
        return l.ok && d && (buf = a.Pega<float>(d)) != nullptr;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t k = 0; k < n; k++) {
            const float o = buf[i];
            buf[i] = (float)(x[k] + fb * o);
            i = i + 1 < d ? i + 1 : 0;
            x[k] = (float)(x[k] * (1.0 - mix) + o * mix);
        }
    }
};

struct Chorus {
    double passo, fase, prof, centro_ms, fb, mix, taxa, ultimo;
    float* buf;
    uint64_t mask, t;
    bool Prepara(Leitor& l, Arena& a, double tx) {
        taxa = tx;
        const double rate = l.Le(0.0, 100.0);
        prof = l.Le(0.0, 1.0);
        centro_ms = l.Le(0.0, 100.0);
        fb = l.Le(-1.0, 1.0);
        mix = l.Le(0.0, 1.0);
        if (!l.ok) {
            return false;
        }
        passo = 2.0 * PI * rate / taxa;
        fase = -passo - PI;  // o oscilador dela comeca uma amostra atras, em sin(-pi)
        const double max_ms = 10.0 * prof + centro_ms + 1.0;
        uint64_t tam = 4;
        while (tam < (uint64_t)(max_ms * taxa / 1000.0) + 4) {
            tam <<= 1;
        }
        if (!(buf = a.Pega<float>((size_t)tam))) {
            return false;
        }
        mask = tam - 1;
        t = 0;
        ultimo = 0.0;
        return true;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            double ms = 20.0 * prof * 0.5 * sin(fase) + centro_ms;
            ms = ms < 1.0 ? 1.0 : ms;
            fase += passo;
            if (fase > PI) {
                fase -= 2.0 * PI;
            }
            buf[t & mask] = (float)(x[i] - ultimo);
            const double pos = (double)t - ms * taxa / 1000.0;
            const double f0 = floor(pos);
            const double fr = pos - f0;
            const int64_t i0 = (int64_t)f0;
            const double y = buf[(uint64_t)i0 & mask] * (1.0 - fr) + buf[(uint64_t)(i0 + 1) & mask] * fr;
            ultimo = y * fb;
            x[i] = (float)((1.0 - mix) * x[i] + mix * y);
            t++;
        }
    }
};

struct Phaser {
    double passo, fase, prof, ncf, fmin, fmax, fb, mix, taxa, g, ultimo;
    double s[6];
    uint64_t t;
    bool Prepara(Leitor& l, double tx) {
        taxa = tx;
        const double rate = l.Le(0.0, 100.0);
        prof = l.Le(0.0, 1.0);
        const double cf = l.Le(20.0, 20000.0);
        fb = l.Le(-1.0, 1.0);
        mix = l.Le(0.0, 1.0);
        fmin = 20.0;
        fmax = 0.49 * taxa < 20000.0 ? 0.49 * taxa : 20000.0;
        ncf = log(cf / fmin) / log(fmax / fmin);
        passo = 2.0 * PI * rate * 4.0 / taxa;  // o oscilador anda a cada 4 amostras
        fase = -PI;
        t = 0;
        g = ultimo = 0.0;
        memset(s, 0, sizeof(s));
        return l.ok;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            if ((t & 3) == 0) {
                double v = sin(fase) * prof * 0.5 + ncf;
                v = v < 0.0 ? 0.0 : (v > 1.0 ? 1.0 : v);
                const double f = fmin * Pot(fmax / fmin, v);
                const double tn = tan(PI * f / taxa);
                g = tn / (1.0 + tn);
                fase += passo;
                if (fase > PI) {
                    fase -= 2.0 * PI;
                }
            }
            double o = x[i] - ultimo;
            for (int j = 0; j < 6; j++) {  // passa-tudo de primeira ordem (TPT)
                const double v = g * (o - s[j]);
                const double lp = v + s[j];
                s[j] = lp + v;
                o = 2.0 * lp - o;
            }
            ultimo = o * fb;
            x[i] = (float)((1.0 - mix) * x[i] + mix * o);
            t++;
        }
    }
};

struct Freeverb {
    static const int NC = 8, NA = 4;
    float* cb[NC];
    float* ab[NA];
    uint32_t cn[NC], an[NA], ci[NC], ai[NA];
    double ultimo[NC];
    double fbk, d1, d2, wet1, seco;
    bool Prepara(Leitor& l, Arena& a, double taxa) {
        static const int combs[NC] = {1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617};
        static const int aps[NA] = {556, 441, 341, 225};
        const double sala = l.Le(0.0, 1.0);
        const double amortece = l.Le(0.0, 1.0);
        const double molhado = l.Le(0.0, 1.0);
        const double dry = l.Le(0.0, 1.0);
        const double largura = l.Le(0.0, 1.0);
        if (!l.ok) {
            return false;
        }
        const double k = taxa / 44100.0;
        for (int j = 0; j < NC; j++) {
            cn[j] = (uint32_t)(combs[j] * k);
            ci[j] = 0;
            ultimo[j] = 0.0;
            if (!cn[j] || !(cb[j] = a.Pega<float>(cn[j]))) {
                return false;
            }
        }
        for (int j = 0; j < NA; j++) {
            an[j] = (uint32_t)(aps[j] * k);
            ai[j] = 0;
            if (!an[j] || !(ab[j] = a.Pega<float>(an[j]))) {
                return false;
            }
        }
        fbk = sala * 0.28 + 0.7;
        d1 = amortece * 0.4;
        d2 = 1.0 - d1;
        wet1 = 0.5 * molhado * 3.0 * (1.0 + largura);
        seco = dry * 2.0;
        return true;
    }
    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            const double ent = x[i] * 0.015;
            double out = 0.0;
            for (int j = 0; j < NC; j++) {
                const double o = cb[j][ci[j]];
                ultimo[j] = o * d2 + ultimo[j] * d1;
                cb[j][ci[j]] = (float)(ent + ultimo[j] * fbk);
                ci[j] = ci[j] + 1 < cn[j] ? ci[j] + 1 : 0;
                out += o;
            }
            for (int j = 0; j < NA; j++) {
                const double b = ab[j][ai[j]];
                ab[j][ai[j]] = (float)(out + b * 0.5);
                ai[j] = ai[j] + 1 < an[j] ? ai[j] + 1 : 0;
                out = b - out;
            }
            x[i] = (float)(out * wet1 + x[i] * seco);
        }
    }
};

// Walsh-Hadamard de 8 (ordem de Sylvester, sem escala), a mesma ordem de somas do _hadamard do fx.py
static inline void Hadamard8(double* v) {
    for (int h = 1; h < 8; h <<= 1) {
        for (int i = 0; i < 8; i += 2 * h) {
            for (int j = i; j < i + h; j++) {
                const double a = v[j], b = v[j + h];
                v[j] = a + b;
                v[j + h] = a - b;
            }
        }
    }
}

// a Fdn do fx.py: pre-atraso, difusor de 8 canais (atraso, sinal e Hadamard a cada passo), 8 linhas de
// realimentacao com leitura modulada (interpolacao linear), o filtro de cada linha (duas prateleiras num biquad, a
// conta do sosfilt) e a Hadamard na volta. As linhas guardam float, como o fx.py (que arredonda o que entra nelas).
struct Fdn {
    static const uint32_t N = 8, PASSOS = 6;
    uint32_t pre, ipre, passos;
    float* bpre;
    uint32_t dd[PASSOS][N], di[PASSOS][N];
    float* db[PASSOS][N];
    double sinal[PASSOS][N];
    uint32_t L[N], cap[N], w[N], per[N], off[N];
    float* lb[N];
    double c[N][5], z[N][2], wf[N], saida[N];
    double meia, cedo, molhado, seco, esc;
    uint64_t t;

    // o ganho da linha |H| em toda a faixa: acima de 1 a realimentacao cresce sem parar
    static bool Contido(const double* q) {
        for (int k = 0; k <= 256; k++) {
            const double om = PI * k / 256.0;
            const double c1 = cos(om), s1 = sin(om), c2 = cos(2.0 * om), s2 = sin(2.0 * om);
            const double nr = q[0] + q[1] * c1 + q[2] * c2, ni = -(q[1] * s1 + q[2] * s2);
            const double dr = 1.0 + q[3] * c1 + q[4] * c2, di_ = -(q[3] * s1 + q[4] * s2);
            if (nr * nr + ni * ni > dr * dr + di_ * di_) {
                return false;
            }
        }
        return true;
    }

    bool Prepara(Leitor& l, Arena& a, double taxa) {
        pre = l.Conta((uint32_t)taxa);
        passos = l.Conta(PASSOS);
        if (!l.ok || !passos || (pre && !(bpre = a.Pega<float>(pre)))) {
            return false;
        }
        for (uint32_t k = 0; k < passos; k++) {
            for (uint32_t j = 0; j < N; j++) {
                dd[k][j] = l.Conta((uint32_t)(taxa * 0.5));
                di[k][j] = 0;
                db[k][j] = nullptr;
                if (l.ok && dd[k][j] && !(db[k][j] = a.Pega<float>(dd[k][j]))) {
                    return false;
                }
            }
            for (uint32_t j = 0; j < N; j++) {
                sinal[k][j] = l.Le(-1.0, 1.0);
            }
        }
        for (uint32_t j = 0; j < N; j++) {
            L[j] = l.Conta((uint32_t)taxa);
            if (!l.ok || L[j] < 2) {
                return false;
            }
        }
        for (uint32_t j = 0; j < N; j++) {
            for (int k = 0; k < 5; k++) {
                c[j][k] = l.Le(-1e6, 1e6);
            }
            const double a1 = c[j][3], a2 = c[j][4];
            if (!l.ok || !(fabs(a2) < 1.0 && fabs(a1) < 1.0 + a2) || !Contido(c[j])) {  // polo fora ou ganho > 1
                return false;
            }
            z[j][0] = z[j][1] = 0.0;
        }
        const double mod = l.Le(0.0, 0.05 * taxa);
        for (uint32_t j = 0; j < N; j++) {
            per[j] = l.Conta((uint32_t)(taxa * 100.0));
            if (!l.ok || !per[j]) {
                return false;
            }
            off[j] = (uint32_t)((uint64_t)per[j] * j / N);
            wf[j] = 2.0 * PI / per[j];
        }
        for (uint32_t j = 0; j < N; j++) {
            saida[j] = l.Le(-8.0, 8.0);
        }
        cedo = l.Le(0.0, 10.0);
        molhado = l.Le(0.0, 10.0);
        seco = l.Le(0.0, 10.0);
        if (!l.ok) {
            return false;
        }
        meia = mod * 0.5;
        esc = 1.0 / sqrt(8.0);
        for (uint32_t j = 0; j < N; j++) {
            cap[j] = L[j] + (uint32_t)ceil(mod) + 2;  // a leitura mais antiga (L + mod + 1) e a escrita
            w[j] = 0;
            if (!(lb[j] = a.Pega<float>(cap[j]))) {
                return false;
            }
        }
        ipre = 0;
        t = 0;
        return true;
    }

    void Processa(float* x, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            const double xin = x[i];
            double xp = xin;
            if (pre) {
                xp = bpre[ipre];
                bpre[ipre] = x[i];
                ipre = ipre + 1 < pre ? ipre + 1 : 0;
            }
            double v[N], f[N];
            for (uint32_t j = 0; j < N; j++) {
                v[j] = xp;
            }
            for (uint32_t k = 0; k < passos; k++) {
                for (uint32_t j = 0; j < N; j++) {
                    double o;
                    if (dd[k][j]) {
                        uint32_t& p = di[k][j];
                        o = db[k][j][p];
                        db[k][j][p] = (float)v[j];
                        p = p + 1 < dd[k][j] ? p + 1 : 0;
                    } else {
                        o = (float)v[j];
                    }
                    v[j] = o * sinal[k][j];
                }
                Hadamard8(v);
                for (uint32_t j = 0; j < N; j++) {
                    v[j] = v[j] * esc;
                }
            }
            for (uint32_t j = 0; j < N; j++) {
                const double fase = (double)((t + off[j]) % per[j]) * wf[j];
                const double at = (double)L[j] + meia * (1.0 + sin(fase));
                const double ia = floor(at);
                const double fr = at - ia;
                const uint32_t i0 = (w[j] + cap[j] - (uint32_t)ia) % cap[j];
                const uint32_t i1 = i0 ? i0 - 1 : cap[j] - 1;
                const double r = (double)lb[j][i0] * (1.0 - fr) + (double)lb[j][i1] * fr;
                const double* q = c[j];
                const double y = q[0] * r + z[j][0];
                z[j][0] = q[1] * r - q[3] * y + z[j][1];
                z[j][1] = q[2] * r - q[4] * y;
                f[j] = y;
            }
            double acc = 0.0;
            for (uint32_t j = 0; j < N; j++) {
                acc = acc + saida[j] * (f[j] + cedo * v[j]);
            }
            Hadamard8(f);
            for (uint32_t j = 0; j < N; j++) {
                lb[j][w[j]] = (float)(f[j] * esc + v[j]);
                w[j] = w[j] + 1 < cap[j] ? w[j] + 1 : 0;
            }
            t++;
            x[i] = (float)(xin * seco + acc * molhado);
        }
    }
};

// Sorteio sem estado global: xorshift64* com Box-Muller
struct Sorteio {
    uint64_t s;
    double guardado;
    bool tem;
    void Semeia(uint64_t semente) {
        s = semente ? semente : 0x9E3779B97F4A7C15ull;
        tem = false;
    }
    double Uniforme() {  // [0, 1)
        s ^= s >> 12;
        s ^= s << 25;
        s ^= s >> 27;
        return (double)((s * 2685821657736338717ull) >> 11) * (1.0 / 9007199254740992.0);
    }
    double Normal() {
        if (tem) {
            tem = false;
            return guardado;
        }
        double u = Uniforme();
        u = u < 1e-300 ? 1e-300 : u;
        const double r = sqrt(-2.0 * log(u)), a = 2.0 * PI * Uniforme();
        guardado = r * sin(a);
        tem = true;
        return r * cos(a);
    }
};

// o radio de policia: detecta a fala na voz crua (etapa da cadeia) e gera chiado, estalo, squelch e bip (o gerador
// do extra, somado depois do nivelador)
struct Radio {
    double liga, desliga, silencio_s, chiado, estalo, bip, rabo, p_estalo, estalo_s, taxa, quieto_s;
    bool falando;
    float* fila;
    uint32_t cap, ini, fim;
    Sorteio rng;
    bool Prepara(Leitor& l, Arena& a, double tx) {
        taxa = tx;
        liga = l.Le(0.0, 1.0);
        desliga = l.Le(0.0, 1.0);
        silencio_s = l.Le(0.0, 60.0);
        chiado = l.Le(0.0, 1.0);
        estalo = l.Le(0.0, 1.0);
        bip = l.Le(0.0, 1.0);
        rabo = l.Le(0.0, 1.0);
        p_estalo = l.Le(0.0, 1.0);
        estalo_s = l.Le(0.0, 0.1);
        const double semente = l.Le(0.0, 4294967295.0);
        if (!l.ok) {
            return false;
        }
        rng.Semeia((uint64_t)semente * 0x9E3779B97F4A7C15ull + 1);
        cap = (uint32_t)(0.6 * taxa);
        ini = fim = 0;
        falando = false;
        quieto_s = 0.0;
        return (fila = a.Pega<float>(cap)) != nullptr;
    }
    // ruido gaussiano de seg segundos no fim da fila; cai = some em rampa linear
    void Ruido(double seg, double nivel, bool cai) {
        const uint32_t n = (uint32_t)(seg * taxa);
        for (uint32_t i = 0; i < n && fim < cap; i++) {
            const double r = cai && n > 1 ? 1.0 - (double)i / (double)(n - 1) : 1.0;
            fila[fim++] = (float)(rng.Normal() * nivel * r);
        }
    }
    void Bip() {
        const uint32_t n = (uint32_t)(0.16 * taxa);
        const double ultimo = n ? (double)(n - 1) / taxa : 0.0;
        for (uint32_t i = 0; i < n && fim < cap; i++) {
            const double t = (double)i / taxa;
            double v = bip * sin(2.0 * PI * (t < 0.08 ? 1200.0 : 1600.0) * t);
            double borda = (t < ultimo - t ? t : ultimo - t) / 0.004;
            v *= borda < 1.0 ? borda : 1.0;
            fila[fim++] = (float)v;
        }
        Ruido(0.14, rabo, true);
    }
    void Compacta() {
        if (ini) {
            memmove(fila, fila + ini, (fim - ini) * sizeof(float));
            fim -= ini;
            ini = 0;
        }
    }
    void Detecta(const float* x, uint32_t n, const Ctx& c) {
        const double rms = sqrt(Rms(x, n));
        if (!falando && rms > liga) {
            falando = true;
            quieto_s = 0.0;
            ini = fim = 0;  // a fila vira o squelch abrindo
            Ruido(0.04, rabo, true);
        } else if (falando) {
            quieto_s = rms < desliga ? quieto_s + c.dt : 0.0;
            if (quieto_s >= silencio_s - 1e-9) {
                falando = false;
                Compacta();
                Bip();
            }
        }
    }
    void Som(float* e, uint32_t n, const Ctx& c) {
        if (falando) {
            for (uint32_t i = 0; i < n; i++) {
                e[i] += (float)(rng.Normal() * chiado);
            }
            const uint32_t m = (uint32_t)(estalo_s * taxa);
            if (n > m + 1 && rng.Uniforme() < PorBloco(p_estalo, c.dt)) {
                const uint32_t k = (uint32_t)(rng.Uniforme() * (double)(n - m));
                for (uint32_t i = 0; i < m; i++) {
                    e[k + i] += (float)(rng.Normal() * estalo);
                }
            }
        }
        const uint32_t m = fim - ini < n ? fim - ini : n;
        for (uint32_t i = 0; i < m; i++) {
            e[i] += fila[ini + i];
        }
        ini += m;
        if (ini == fim) {
            ini = fim = 0;
        }
    }
};

// ---------------------------------------------------------------------------------------------------------------
// O nivelador do Efeito: volume como o ouvido soma (Audibilidade do fx.py), na entrada crua e na saida

struct Audibilidade {
    uint32_t n, bits;
    float* hist;
    double *win, *re, *im, *cs, *sn;
    int8_t* banda;  // banda critica de cada raia do rfft (-1 = fora de 50 a 15000 Hz)
    double expoente;
    bool Prepara(Arena& a, double taxa, double exp_) {
        expoente = exp_;
        n = 256;
        bits = 8;
        while (n < 0.02 * taxa && n < 4096) {
            n <<= 1;
            bits++;
        }
        if (!(hist = a.Pega<float>(n)) || !(win = a.Pega<double>(n)) || !(re = a.Pega<double>(n)) ||
            !(im = a.Pega<double>(n)) || !(cs = a.Pega<double>(n / 2)) || !(sn = a.Pega<double>(n / 2)) ||
            !(banda = a.Pega<int8_t>(n / 2 + 1))) {
            return false;
        }
        for (uint32_t i = 0; i < n; i++) {
            win[i] = 0.5 - 0.5 * cos(2.0 * PI * i / (n - 1));  // np.hanning
        }
        for (uint32_t i = 0; i < n / 2; i++) {
            cs[i] = cos(2.0 * PI * i / n);
            sn[i] = -sin(2.0 * PI * i / n);
        }
        for (uint32_t i = 0; i <= n / 2; i++) {
            const double f = (double)i * taxa / n;
            const double z = 13.0 * atan(0.00076 * f) + 3.5 * atan((f / 7500.0) * (f / 7500.0));
            const int b = (int)floor(z);
            banda[i] = (int8_t)((f >= 50.0 && f <= 15000.0 && b >= 0 && b < 25) ? b : -1);
        }
        return true;
    }
    void Fft() {
        for (uint32_t i = 1, j = 0; i < n; i++) {  // inversao de bits
            uint32_t bit = n >> 1;
            for (; j & bit; bit >>= 1) {
                j ^= bit;
            }
            j ^= bit;
            if (i < j) {
                double t = re[i];
                re[i] = re[j];
                re[j] = t;
                t = im[i];
                im[i] = im[j];
                im[j] = t;
            }
        }
        for (uint32_t len = 2; len <= n; len <<= 1) {
            const uint32_t passo = n / len;
            for (uint32_t i = 0; i < n; i += len) {
                for (uint32_t k = 0; k < len / 2; k++) {
                    const double wr = cs[k * passo], wi = sn[k * passo];
                    const double ur = re[i + k], ui = im[i + k];
                    const double vr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi;
                    const double vi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr;
                    re[i + k] = ur + vr;
                    im[i + k] = ui + vi;
                    re[i + k + len / 2] = ur - vr;
                    im[i + k + len / 2] = ui - vi;
                }
            }
        }
    }
    double Mede(const float* x, uint32_t m) {
        if (m >= n) {
            memcpy(hist, x + (m - n), n * sizeof(float));
        } else {
            memmove(hist, hist + m, (n - m) * sizeof(float));
            memcpy(hist + (n - m), x, m * sizeof(float));
        }
        for (uint32_t i = 0; i < n; i++) {
            re[i] = hist[i] * win[i];
            im[i] = 0.0;
        }
        Fft();
        double e[25] = {0};
        for (uint32_t i = 0; i <= n / 2; i++) {
            if (banda[i] >= 0) {
                e[banda[i]] += re[i] * re[i] + im[i] * im[i];
            }
        }
        double s = 0.0;
        for (int b = 0; b < 25; b++) {
            s += Pot(e[b] + 1e-12, expoente);
        }
        return s;
    }
};

// ---------------------------------------------------------------------------------------------------------------
// A cadeia: o Efeito do fx.py (etapas, ganho, nivelador, extra, corte em 1)

struct Etapa {
    uint32_t tipo;
    void* e;
};

struct Cadeia {
    Etapa etapas[MAX_ETAPAS];
    Etapa extra[MAX_ETAPAS];
    uint32_t n_etapas = 0, n_extra = 0, gerador = G_NENHUM;
    double taxa = 48000.0, ganho = 1.0;
    bool nivelar = false;
    double fala, memoria, passo_n, teto, expoente;
    double m_in = 0.0, m_out = 0.0, g_auto = 1.0;
    Audibilidade *a_in = nullptr, *a_out = nullptr;
    Radio* radio = nullptr;
    float *cru = nullptr, *ext = nullptr, *tmp[3] = {nullptr, nullptr, nullptr};
    Arena arena;
    bool pronta = false;

    template <class T>
    static T* Cria(Arena& a) {
        return a.Pega<T>(1);  // POD: zerado ja e o estado inicial
    }

    bool Monta(Etapa& et, uint32_t tipo, Leitor& l) {
        et.tipo = tipo;
        Arena& a = arena;
        switch (tipo) {
        case T_SOS: { auto* p = Cria<Sos>(a); et.e = p; return p && p->Prepara(l, a); }
        case T_FIR: { auto* p = Cria<Fir>(a); et.e = p; return p && p->Prepara(l, a); }
        case T_GANHO: { auto* p = Cria<Ganho>(a); et.e = p; return p && p->Prepara(l); }
        case T_PITCH: { auto* p = Cria<Pitch>(a); et.e = p; return p && p->Prepara(l, a); }
        case T_RINGMOD: { auto* p = Cria<RingMod>(a); et.e = p; return p && p->Prepara(l, taxa); }
        case T_PORTAO: { auto* p = Cria<Portao>(a); et.e = p; return p && p->Prepara(l); }
        case T_DECIMA: { auto* p = Cria<Decima>(a); et.e = p; return p && p->Prepara(l); }
        case T_AGC: { auto* p = Cria<Agc>(a); et.e = p; return p && p->Prepara(l); }
        case T_MULTIBANDA: { auto* p = Cria<Multibanda>(a); et.e = p; return p && p->Prepara(l, a); }
        case T_COMPRESSOR: { auto* p = Cria<Compressor>(a); et.e = p; return p && p->Prepara(l, taxa); }
        case T_LIMITER: { auto* p = Cria<Limiter>(a); et.e = p; return p && p->Prepara(l, taxa); }
        case T_DISTORCAO: { auto* p = Cria<Distorcao>(a); et.e = p; return p && p->Prepara(l); }
        case T_DISTORCAO_OS: { auto* p = Cria<DistorcaoOS>(a); et.e = p; return p && p->Prepara(l, a); }
        case T_BITCRUSH: { auto* p = Cria<Bitcrush>(a); et.e = p; return p && p->Prepara(l); }
        case T_DELAY: { auto* p = Cria<Delay>(a); et.e = p; return p && p->Prepara(l, a, taxa); }
        case T_CHORUS: { auto* p = Cria<Chorus>(a); et.e = p; return p && p->Prepara(l, a, taxa); }
        case T_PHASER: { auto* p = Cria<Phaser>(a); et.e = p; return p && p->Prepara(l, taxa); }
        case T_FREEVERB: { auto* p = Cria<Freeverb>(a); et.e = p; return p && p->Prepara(l, a, taxa); }
        case T_FDN: { auto* p = Cria<Fdn>(a); et.e = p; return p && p->Prepara(l, a, taxa); }
        case T_RADIO: {
            if (radio) {
                return false;  // um radio por cadeia
            }
            auto* p = Cria<Radio>(a);
            et.e = radio = p;
            return p && p->Prepara(l, a, taxa);
        }
        default:
            return false;
        }
    }

    void Roda(const Etapa& et, float* x, uint32_t n, const Ctx& c) {
        switch (et.tipo) {
        case T_SOS: static_cast<Sos*>(et.e)->Processa(x, n); break;
        case T_FIR: static_cast<Fir*>(et.e)->Processa(x, n); break;
        case T_GANHO: static_cast<Ganho*>(et.e)->Processa(x, n); break;
        case T_PITCH: static_cast<Pitch*>(et.e)->Processa(x, n); break;
        case T_RINGMOD: static_cast<RingMod*>(et.e)->Processa(x, n); break;
        case T_PORTAO: static_cast<Portao*>(et.e)->Processa(x, n, c); break;
        case T_DECIMA: static_cast<Decima*>(et.e)->Processa(x, n); break;
        case T_AGC: static_cast<Agc*>(et.e)->Processa(x, n, c); break;
        case T_MULTIBANDA: static_cast<Multibanda*>(et.e)->Processa(x, n, c); break;
        case T_COMPRESSOR: static_cast<Compressor*>(et.e)->Processa(x, n); break;
        case T_LIMITER: static_cast<Limiter*>(et.e)->Processa(x, n); break;
        case T_DISTORCAO: static_cast<Distorcao*>(et.e)->Processa(x, n); break;
        case T_DISTORCAO_OS: static_cast<DistorcaoOS*>(et.e)->Processa(x, n); break;
        case T_BITCRUSH: static_cast<Bitcrush*>(et.e)->Processa(x, n); break;
        case T_DELAY: static_cast<Delay*>(et.e)->Processa(x, n); break;
        case T_CHORUS: static_cast<Chorus*>(et.e)->Processa(x, n); break;
        case T_PHASER: static_cast<Phaser*>(et.e)->Processa(x, n); break;
        case T_FREEVERB: static_cast<Freeverb*>(et.e)->Processa(x, n); break;
        case T_FDN: static_cast<Fdn*>(et.e)->Processa(x, n); break;
        case T_RADIO: static_cast<Radio*>(et.e)->Detecta(x, n, c); break;
        default: break;
        }
    }

    // Le o preset (cabecalho + etapas) e monta a cadeia na memoria dada; OK ou o erro. Zera todo o estado.
    uint32_t Carrega(const uint8_t* p, size_t n, double taxa_mic, uint8_t* mem, size_t mem_bytes) {
        pronta = false;
        n_etapas = n_extra = 0;
        radio = nullptr;
        a_in = a_out = nullptr;
        arena.base = mem;
        arena.cap = mem_bytes;
        arena.usado = 0;
        arena.faltou = false;
        // cabecalho (80 bytes): magia, versao, taxa, ganho, nivelar, etapas, extra, gerador e os 5 do nivelador
        // (fala, memoria, passo, teto, expoente); depois cada etapa: tipo, quantos doubles, os doubles
        if (!p || n < 80 || !mem) {
            return INVALIDO;
        }
        uint32_t magia, versao, niv, ne, nx, ger;
        double tx, gn;
        memcpy(&magia, p, 4);
        memcpy(&versao, p + 4, 4);
        memcpy(&tx, p + 8, 8);
        memcpy(&gn, p + 16, 8);
        memcpy(&niv, p + 24, 4);
        memcpy(&ne, p + 28, 4);
        memcpy(&nx, p + 32, 4);
        memcpy(&ger, p + 36, 4);
        if (magia != MAGIA || versao != VERSAO || ne > MAX_ETAPAS || nx > MAX_ETAPAS || ger > G_RADIO) {
            return INVALIDO;
        }
        if (!(tx >= 8000.0 && tx <= 384000.0) || !(gn >= 0.0 && gn <= 1e4)) {
            return INVALIDO;
        }
        if (fabs(tx - taxa_mic) > 0.5) {
            return TAXA;
        }
        Leitor cab(p + 40, 5);
        fala = cab.Le(0.0, 1.0);
        memoria = cab.Le(0.0, 1.0);
        passo_n = cab.Le(0.0, 1.0);
        teto = cab.Le(1.0, 1e6);
        expoente = cab.Le(0.01, 1.0);
        if (!cab.ok) {
            return INVALIDO;
        }
        size_t pos = 80;
        taxa = tx;
        ganho = gn;
        nivelar = niv != 0;
        gerador = ger;
        if (!(cru = arena.Pega<float>(MAX_BLOCO)) || !(ext = arena.Pega<float>(MAX_BLOCO))) {
            return SEM_MEMORIA;
        }
        for (int j = 0; j < 3; j++) {
            if (!(tmp[j] = arena.Pega<float>(MAX_BLOCO))) {
                return SEM_MEMORIA;
            }
        }
        if (nivelar) {
            if (!(a_in = arena.Pega<Audibilidade>(1)) || !(a_out = arena.Pega<Audibilidade>(1)) ||
                !a_in->Prepara(arena, taxa, expoente) || !a_out->Prepara(arena, taxa, expoente)) {
                return SEM_MEMORIA;
            }
        }
        for (uint32_t k = 0; k < ne + nx; k++) {
            if (n - pos < 8) {
                return INVALIDO;
            }
            uint32_t tipo, qtd;
            memcpy(&tipo, p + pos, 4);
            memcpy(&qtd, p + pos + 4, 4);
            pos += 8;
            if (qtd > (n - pos) / 8) {
                return INVALIDO;
            }
            Leitor l(p + pos, qtd);
            Etapa& et = k < ne ? etapas[k] : extra[k - ne];
            if (!Monta(et, tipo, l) || !l.ok || l.i != qtd) {
                return arena.faltou ? SEM_MEMORIA : INVALIDO;
            }
            pos += (size_t)qtd * 8;
        }
        if (pos != n || (gerador == G_RADIO && !radio)) {
            return INVALIDO;
        }
        n_etapas = ne;
        n_extra = nx;
        m_in = m_out = 0.0;
        g_auto = 1.0;
        pronta = true;
        return OK;
    }

    // Passa a voz (mono) pela cadeia no lugar; false se saiu algo nao finito (o bloco vira silencio e quem chama
    // recarrega o preset, zerando o estado)
    bool Processa(float* x, uint32_t n) {
        if (!pronta) {
            return true;
        }
        bool ok = true;
        while (n) {
            const uint32_t m = n < MAX_BLOCO ? n : MAX_BLOCO;
            ok = Bloco(x, m) && ok;
            x += m;
            n -= m;
        }
        return ok;
    }

    size_t Usado() const { return arena.usado; }

private:
    bool Bloco(float* x, uint32_t n) {
        Ctx c;
        c.taxa = taxa;
        c.dt = (double)n / taxa;
        c.tmp[0] = tmp[0];
        c.tmp[1] = tmp[1];
        c.tmp[2] = tmp[2];
        if (nivelar) {
            memcpy(cru, x, n * sizeof(float));
        }
        for (uint32_t k = 0; k < n_etapas; k++) {
            Roda(etapas[k], x, n, c);
        }
        for (uint32_t i = 0; i < n; i++) {
            x[i] = (float)(x[i] * ganho);
        }
        if (nivelar) {
            const double ni = a_in->Mede(cru, n), no = a_out->Mede(x, n);
            if (Rms(cru, n) > fala) {
                const double m = Pot(memoria, c.dt / BLOCO_REF);
                m_in = m * m_in + (1.0 - m) * ni;
                m_out = m * m_out + (1.0 - m) * no;
            }
            if (m_in > 0.0 && m_out > 0.0) {
                double alvo = Pot(m_in / m_out, 1.0 / (2.0 * expoente));
                alvo = alvo < 1.0 / teto ? 1.0 / teto : (alvo > teto ? teto : alvo);
                g_auto += (alvo - g_auto) * PorBloco(passo_n, c.dt);
            }
            for (uint32_t i = 0; i < n; i++) {
                x[i] = (float)(x[i] * g_auto);
            }
        }
        if (gerador == G_RADIO && radio) {
            memset(ext, 0, n * sizeof(float));
            radio->Som(ext, n, c);
            for (uint32_t k = 0; k < n_extra; k++) {
                Roda(extra[k], ext, n, c);
            }
            const double k = ganho * (nivelar ? g_auto : 1.0);
            for (uint32_t i = 0; i < n; i++) {
                x[i] = (float)(x[i] + ext[i] * k);
            }
        }
        bool ok = true;
        for (uint32_t i = 0; i < n; i++) {
            float v = x[i];
            if (!std::isfinite(v)) {
                v = 0.0f;
                ok = false;
            }
            x[i] = v > 1.0f ? 1.0f : (v < -1.0f ? -1.0f : v);
        }
        if (!ok) {
            memset(x, 0, n * sizeof(float));
        }
        return ok;
    }
};

}  // namespace voz
