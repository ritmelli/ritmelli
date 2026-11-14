// voz.dll: o motor de efeitos do filtro (voz.h) fora do audiodg, para o app conferir e medir por ctypes
// (microfone/voz.py; dev/testa_voz.py compara cada efeito com a cadeia do fx.py).
#include <new>
#include <stdlib.h>
#include "voz.h"

struct Instancia {
    voz::Cadeia c;
    uint8_t* mem;
};

// cria a cadeia do preset na taxa; erro recebe o codigo (voz::Erro); nullptr se nao montou
extern "C" __declspec(dllexport) void* voz_cria(const uint8_t* preset, uint32_t n, double taxa, uint32_t* erro) {
    auto* in = new (std::nothrow) Instancia();
    const size_t bytes = voz::ArenaBytes(taxa);
    if (!in || !(in->mem = static_cast<uint8_t*>(malloc(bytes)))) {
        delete in;
        if (erro) {
            *erro = voz::SEM_MEMORIA;
        }
        return nullptr;
    }
    const uint32_t e = in->c.Carrega(preset, n, taxa, in->mem, bytes);
    if (erro) {
        *erro = e;
    }
    if (e != voz::OK) {
        free(in->mem);
        delete in;
        return nullptr;
    }
    return in;
}

// passa n amostras mono pela cadeia, no lugar; 0 se saiu algo nao finito (o bloco volta em silencio)
extern "C" __declspec(dllexport) int voz_processa(void* h, float* x, uint32_t n) {
    return static_cast<Instancia*>(h)->c.Processa(x, n) ? 1 : 0;
}

extern "C" __declspec(dllexport) unsigned long long voz_usado(void* h) {
    return static_cast<Instancia*>(h)->c.Usado();
}

extern "C" __declspec(dllexport) unsigned long long voz_arena(double taxa) { return voz::ArenaBytes(taxa); }

extern "C" __declspec(dllexport) void voz_destroi(void* h) {
    auto* in = static_cast<Instancia*>(h);
    if (in) {
        free(in->mem);
        delete in;
    }
}
