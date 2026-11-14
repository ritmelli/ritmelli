// Banca do reamostra.h fora do audiodg: simula o anel (escritor em blocos, leitor em blocos do tamanho do
// periodo do microfone, com fome e volta do anel) e devolve a saida estereo pro teste_reamostra.py medir.
#include <algorithm>
#include <vector>
#include "../reamostra.h"

extern "C" __declspec(dllexport) int reamostra(const float* entrada, int n_entrada, float* saida, int n_saida,
                                               unsigned taxa, int bloco_leitor, int bloco_escritor,
                                               long long quadros_anel) {
    const int64_t Q = quadros_anel;  // potencia de 2, como no anel.h
    std::vector<float> anel((size_t)Q * 2, 0.0f);
    Reamostra rs;
    rs.Prepara(taxa);
    rs.Comeca(0);
    int64_t escrito = 0, lidos = 0;
    int gerados = 0;
    while (gerados < n_saida) {
        const int64_t livre = Q - (escrito - rs.MaisVelho());
        const int64_t w = std::min<int64_t>({(int64_t)bloco_escritor, livre, (int64_t)n_entrada - lidos});
        for (int64_t k = 0; k < w; k++) {
            anel[(size_t)((escrito + k) & (Q - 1)) * 2] = entrada[(lidos + k) * 2];
            anel[(size_t)((escrito + k) & (Q - 1)) * 2 + 1] = entrada[(lidos + k) * 2 + 1];
        }
        escrito += std::max<int64_t>(w, 0);
        lidos += std::max<int64_t>(w, 0);
        const uint32_t g = rs.Gera(anel.data(), (uint32_t)(Q - 1), escrito,
                                   (uint32_t)std::min(bloco_leitor, n_saida - gerados),
                                   [&](uint32_t i, float esq, float dir) {
            saida[(gerados + i) * 2] = esq;
            saida[(gerados + i) * 2 + 1] = dir;
        });
        gerados += (int)g;
        if (g == 0 && w <= 0) {
            break;
        }
    }
    return gerados;
}

extern "C" __declspec(dllexport) int modo(unsigned taxa, unsigned* L, unsigned* M, unsigned* taps) {
    Reamostra rs;
    rs.Prepara(taxa);
    *L = rs.L;
    *M = rs.M;
    *taps = rs.taps;
    return (int)rs.modo;
}
