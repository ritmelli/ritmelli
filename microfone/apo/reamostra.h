// reamostra.h: leitura do anel (48 kHz) na taxa do microfone.
//
// 48 kHz no microfone = copia direta (bit a bit). Outra taxa = polifasico de sinc janelado (Kaiser): a razao vira
// L/M reduzida (44,1 kHz = 147/160) e cada fase tem a sua fileira de coeficientes calculada no Prepara, entao no
// tempo real nao ha interpolacao de fase nem conta transcendental, so produto escalar. Corte em 96,7% da menor
// Nyquist, largura de 128 amostras na taxa de saida (mais na entrada quando desce de taxa), Kaiser beta 11,2:
// tom de 1 kHz com THD+N perto de -140 dB, resposta plana ate 20 kHz e o que passa da Nyquist entra a -118 dB.
// Taxa sem razao pequena (L > 1024) cai no linear.
#pragma once
#include <cmath>
#include <cstdint>
#include <vector>

struct Reamostra {
    static constexpr uint32_t TAXA_ANEL = 48000;
    static constexpr uint32_t MAX_FASES = 1024;
    static constexpr double BETA = 11.2;
    static constexpr double CORTE = 0.967;
    static constexpr uint32_t BASE = 128;

    enum Modo { DIRETO, SINC, LINEAR };
    Modo modo = DIRETO;
    uint32_t L = 1, M = 1, taps = 0;
    std::vector<float> h;  // L fases x taps
    double passo = 1.0;    // so no LINEAR

    // estado da leitura
    int64_t pos = 0;     // indice inteiro da entrada (anel) da proxima saida
    uint32_t fase = 0;   // fracao da posicao, em 1/L
    double fracao = 0.0; // fracao no LINEAR
    int64_t inicio = 0;  // o que veio antes de pegar a vaga conta como silencio

    static uint32_t Mdc(uint32_t a, uint32_t b) {
        while (b) {
            uint32_t t = a % b;
            a = b;
            b = t;
        }
        return a;
    }

    static double I0(double x) {  // Bessel modificada de ordem 0 (serie), so no Prepara
        double soma = 1.0, termo = 1.0, q = x * x / 4.0;
        for (int k = 1; k < 64; k++) {
            termo *= q / ((double)k * (double)k);
            soma += termo;
            if (termo < soma * 1e-17) {
                break;
            }
        }
        return soma;
    }

    // Fora do tempo real (aloca)
    void Prepara(uint32_t taxa_saida) {
        h.clear();
        taps = 0;
        if (taxa_saida == 0 || taxa_saida == TAXA_ANEL) {
            modo = DIRETO;
            L = M = 1;
            return;
        }
        const uint32_t g = Mdc(taxa_saida, TAXA_ANEL);
        L = taxa_saida / g;
        M = TAXA_ANEL / g;
        if (L > MAX_FASES) {
            modo = LINEAR;
            passo = (double)TAXA_ANEL / (double)taxa_saida;
            return;
        }
        modo = SINC;
        const double razao = (double)L / (double)M;
        const double desce = razao < 1.0 ? razao : 1.0;
        const double fc = 0.5 * desce * CORTE;  // ciclos por amostra de entrada
        taps = (uint32_t)std::ceil((double)BASE / desce / 4.0) * 4;
        h.resize((size_t)L * taps);
        const double meio = taps / 2.0, i0b = I0(BETA), pi = 3.14159265358979323846;
        for (uint32_t r = 0; r < L; r++) {
            for (uint32_t k = 0; k < taps; k++) {
                const double t = (double)r / L + meio - 1.0 - (double)k;  // distancia da amostra ate a saida
                const double u = t / meio;
                const double w = u * u < 1.0 ? I0(BETA * std::sqrt(1.0 - u * u)) / i0b : 0.0;
                const double x = 2.0 * fc * t;
                const double sinc = x == 0.0 ? 1.0 : std::sin(pi * x) / (pi * x);
                h[(size_t)r * taps + k] = (float)(2.0 * fc * sinc * w);
            }
        }
    }

    void Comeca(int64_t escrito) {
        pos = escrito;
        fase = 0;
        fracao = 0.0;
        inicio = escrito;
    }

    // O indice mais velho que ainda vai ser lido (o escritor nao pode passar por cima dele)
    int64_t MaisVelho() const {
        return modo == SINC ? pos - (int64_t)taps / 2 + 1 : pos;
    }

    // O mais novo que a proxima saida precisa
    int64_t Precisa() const {
        return modo == SINC ? pos + (int64_t)taps / 2 : (modo == LINEAR ? pos + 1 : pos);
    }

    // Tempo real. Gera ate n quadros do anel (dados estereo, mascara = quadros do anel - 1) e entrega cada um em
    // poe(i, esq, dir). Devolve quantos gerou: para quando a proxima saida precisa de amostra que ainda nao chegou.
    template <typename Poe>
    uint32_t Gera(const float* dados, uint32_t mascara, int64_t escrito, uint32_t n, Poe poe) {
        uint32_t i = 0;
        if (modo == DIRETO) {
            for (; i < n && pos < escrito; i++, pos++) {
                const float* a = &dados[(pos & mascara) * 2];
                poe(i, a[0], a[1]);
            }
            return i;
        }
        if (modo == LINEAR) {
            for (; i < n && pos + 1 < escrito; i++) {
                const float t = (float)fracao;
                const float* a0 = &dados[(pos & mascara) * 2];
                const float* a1 = &dados[((pos + 1) & mascara) * 2];
                poe(i, a0[0] + (a1[0] - a0[0]) * t, a0[1] + (a1[1] - a0[1]) * t);
                fracao += passo;
                const double inteiro = std::floor(fracao);
                pos += (int64_t)inteiro;
                fracao -= inteiro;
            }
            return i;
        }
        const int64_t meia = (int64_t)taps / 2;
        for (; i < n && pos + meia < escrito; i++) {
            const float* c = &h[(size_t)fase * taps];
            const int64_t j0 = pos - meia + 1;
            double esq = 0.0, dir = 0.0;
            if (j0 >= inicio) {
                for (uint32_t k = 0; k < taps; k++) {
                    const float* a = &dados[((j0 + k) & mascara) * 2];
                    esq += (double)a[0] * c[k];
                    dir += (double)a[1] * c[k];
                }
            } else {  // comeco: o que e anterior a vaga vale zero
                for (uint32_t k = 0; k < taps; k++) {
                    if (j0 + (int64_t)k < inicio) {
                        continue;
                    }
                    const float* a = &dados[((j0 + k) & mascara) * 2];
                    esq += (double)a[0] * c[k];
                    dir += (double)a[1] * c[k];
                }
            }
            poe(i, (float)esq, (float)dir);
            fase += M;
            pos += fase / L;
            fase %= L;
        }
        return i;
    }
};
