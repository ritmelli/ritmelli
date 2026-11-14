// Banca do filtro inteiro fora do audiodg: o micfx.cpp de verdade (o mesmo APOProcess, Soma e Efeito), com o anel num
// nome so do teste (Local\, sem administrador). O teste em Python (dev/testa_filtro.py) cria a instancia na taxa e nos
// canais do microfone, passa blocos como o audiodg passaria e confere o que sai, escrevendo o anel pelo
// microfone/injeta.py como o app.
static wchar_t g_banca_mapa[128] = L"Local\\RitmelliBancaFiltro";
#define MICFX_MAPA g_banca_mapa
#include "../micfx.cpp"

#include <audiomediatype.h>
#include <ksmedia.h>

struct Banca {
    CMicFx* apo;
    IAudioMediaType* fmt;
    UINT32 canais;
};

// mapa: o nome do anel (Local\...); devolve nullptr se o motor recusar o formato
extern "C" __declspec(dllexport) void* banca_cria(const wchar_t* mapa, float taxa, unsigned canais, unsigned max_quadros) {
    wcsncpy_s(g_banca_mapa, mapa, _TRUNCATE);
    WAVEFORMATEXTENSIBLE w = {};
    w.Format.wFormatTag = WAVE_FORMAT_EXTENSIBLE;
    w.Format.nChannels = (WORD)canais;
    w.Format.nSamplesPerSec = (DWORD)taxa;
    w.Format.wBitsPerSample = 32;
    w.Format.nBlockAlign = (WORD)(4 * canais);
    w.Format.nAvgBytesPerSec = w.Format.nSamplesPerSec * w.Format.nBlockAlign;
    w.Format.cbSize = sizeof(WAVEFORMATEXTENSIBLE) - sizeof(WAVEFORMATEX);
    w.Samples.wValidBitsPerSample = 32;
    w.dwChannelMask = canais == 1 ? SPEAKER_FRONT_CENTER : (SPEAKER_FRONT_LEFT | SPEAKER_FRONT_RIGHT);
    w.SubFormat = KSDATAFORMAT_SUBTYPE_IEEE_FLOAT;
    IAudioMediaType* fmt = nullptr;
    if (FAILED(CreateAudioMediaType(&w.Format, sizeof(w), &fmt))) {
        return nullptr;
    }
    auto* apo = new CMicFx(nullptr);
    APOInitBaseStruct ini = {sizeof(APOInitBaseStruct), CLSID_MicFx};  // sem o endpoint: age como o alvo
    APO_CONNECTION_DESCRIPTOR ent = {}, sai = {};
    for (APO_CONNECTION_DESCRIPTOR* d : {&ent, &sai}) {
        d->Type = APO_CONNECTION_BUFFER_TYPE_EXTERNAL;
        d->pBuffer = 0;
        d->u32MaxFrameCount = max_quadros;
        d->pFormat = fmt;
        d->u32Signature = APO_CONNECTION_DESCRIPTOR_SIGNATURE;
    }
    APO_CONNECTION_DESCRIPTOR* pe = &ent;
    APO_CONNECTION_DESCRIPTOR* ps = &sai;
    if (FAILED(apo->Initialize(sizeof(ini), reinterpret_cast<BYTE*>(&ini))) || FAILED(apo->LockForProcess(1, &pe, 1, &ps))) {
        apo->m_interno.Release();
        fmt->Release();
        return nullptr;
    }
    return new Banca{apo, fmt, canais};
}

// um bloco do audiodg: entrada e saida intercaladas (quadros x canais); silencio = a entrada marcada BUFFER_SILENT
extern "C" __declspec(dllexport) void banca_bloco(void* h, float* entrada, float* saida, unsigned quadros, int silencio) {
    auto* b = static_cast<Banca*>(h);
    APO_CONNECTION_PROPERTY ent = {reinterpret_cast<UINT_PTR>(entrada), quadros,
                                   silencio ? BUFFER_SILENT : BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    APO_CONNECTION_PROPERTY sai = {reinterpret_cast<UINT_PTR>(saida), 0, BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    APO_CONNECTION_PROPERTY* pe = &ent;
    APO_CONNECTION_PROPERTY* ps = &sai;
    b->apo->APOProcess(1, &pe, 1, &ps);
}

extern "C" __declspec(dllexport) void banca_destroi(void* h) {
    auto* b = static_cast<Banca*>(h);
    b->apo->UnlockForProcess();
    b->apo->m_interno.Release();
    b->fmt->Release();
    delete b;
}
