// Banca do filtro inteiro fora do audiodg: o micfx.cpp de verdade (o mesmo APOProcess, Soma e Efeito), com o anel num
// nome so do teste (Local\, sem administrador). O teste em Python (dev/testa_filtro.py) cria a instancia na taxa e nos
// canais do microfone, passa blocos como o audiodg passaria e confere o que sai, escrevendo o anel pelo
// microfone/injeta.py como o app. A segunda metade e a banca do hospedeiro do MFX (#49): ele carrega um "fabricante"
// falso (um APO com cancelamento de eco que corta a entrada pela metade, como um redutor) e soma a musica no que sai.
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

// um bloco do audiodg: entrada e saida intercaladas (quadros x canais); silencio = a entrada marcada BUFFER_SILENT.
// Devolve a marca da saida (1 = BUFFER_SILENT: quem vem depois trata o bloco como silencio)
extern "C" __declspec(dllexport) int banca_bloco(void* h, float* entrada, float* saida, unsigned quadros, int silencio) {
    auto* b = static_cast<Banca*>(h);
    APO_CONNECTION_PROPERTY ent = {reinterpret_cast<UINT_PTR>(entrada), quadros,
                                   silencio ? BUFFER_SILENT : BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    APO_CONNECTION_PROPERTY sai = {reinterpret_cast<UINT_PTR>(saida), 0, BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    APO_CONNECTION_PROPERTY* pe = &ent;
    APO_CONNECTION_PROPERTY* ps = &sai;
    b->apo->APOProcess(1, &pe, 1, &ps);
    return sai.u32BufferFlags == BUFFER_SILENT ? 1 : 0;
}

extern "C" __declspec(dllexport) void banca_destroi(void* h) {
    auto* b = static_cast<Banca*>(h);
    b->apo->UnlockForProcess();
    b->apo->m_interno.Release();
    b->fmt->Release();
    delete b;
}

// ---- o hospedeiro do MFX ----

// o CLSID do fabricante falso
static const CLSID CLSID_FabricanteFalso = {0x6b0c1f2e, 0x3d4a, 0x4b5c, {0x8d, 0x9e, 0x0f, 0x1a, 0x2b, 0x3c, 0x4d, 0x5e}};

class CFabricanteFalso : public IAudioProcessingObject,
                         public IAudioProcessingObjectRT,
                         public IAudioProcessingObjectConfiguration,
                         public IApoAcousticEchoCancellation {
public:
    LONG m_ref = 1;
    CLSID m_init_clsid = {};  // o CLSID que o Initialize recebeu
    UINT32 m_canais = 1;
    int m_travas = 0;
    int m_processos = 0;

    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (!ppv) {
            return E_POINTER;
        }
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IAudioProcessingObject)) {
            *ppv = static_cast<IAudioProcessingObject*>(this);
        } else if (riid == __uuidof(IAudioProcessingObjectRT)) {
            *ppv = static_cast<IAudioProcessingObjectRT*>(this);
        } else if (riid == __uuidof(IAudioProcessingObjectConfiguration)) {
            *ppv = static_cast<IAudioProcessingObjectConfiguration*>(this);
        } else if (riid == __uuidof(IApoAcousticEchoCancellation)) {
            *ppv = static_cast<IApoAcousticEchoCancellation*>(this);
        } else {
            *ppv = nullptr;
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return (ULONG)InterlockedIncrement(&m_ref); }
    STDMETHODIMP_(ULONG) Release() override {
        const LONG r = InterlockedDecrement(&m_ref);
        if (!r) {
            delete this;
        }
        return (ULONG)r;
    }

    STDMETHODIMP Reset() override { return S_OK; }
    STDMETHODIMP GetLatency(HNSTIME* t) override {
        *t = 0;
        return S_OK;
    }
    STDMETHODIMP GetRegistrationProperties(APO_REG_PROPERTIES** pp) override {
        auto* r = static_cast<APO_REG_PROPERTIES*>(CoTaskMemAlloc(sizeof(APO_REG_PROPERTIES)));
        if (!r) {
            return E_OUTOFMEMORY;
        }
        *r = {};
        r->clsid = CLSID_FabricanteFalso;
        r->Flags = APO_FLAG_DEFAULT;
        wcscpy_s(r->szFriendlyName, L"Fabricante falso");
        r->u32MinInputConnections = r->u32MaxInputConnections = 1;
        r->u32MinOutputConnections = r->u32MaxOutputConnections = 1;
        r->u32MaxInstances = 0xffffffff;
        r->u32NumAPOInterfaces = 1;
        r->iidAPOInterfaceList[0] = __uuidof(IAudioProcessingObject);
        *pp = r;
        return S_OK;
    }
    STDMETHODIMP Initialize(UINT32 n, BYTE* d) override {
        if (n < sizeof(APOInitBaseStruct) || !d) {
            return E_INVALIDARG;
        }
        m_init_clsid = reinterpret_cast<APOInitBaseStruct*>(d)->clsid;
        return S_OK;
    }
    STDMETHODIMP IsInputFormatSupported(IAudioMediaType*, IAudioMediaType* pedido, IAudioMediaType** ok) override {
        pedido->AddRef();
        *ok = pedido;
        return S_OK;
    }
    STDMETHODIMP IsOutputFormatSupported(IAudioMediaType*, IAudioMediaType* pedido, IAudioMediaType** ok) override {
        pedido->AddRef();
        *ok = pedido;
        return S_OK;
    }
    STDMETHODIMP GetInputChannelCount(UINT32* n) override {
        *n = m_canais;
        return S_OK;
    }

    STDMETHODIMP LockForProcess(UINT32 nIn, APO_CONNECTION_DESCRIPTOR** ppIn, UINT32, APO_CONNECTION_DESCRIPTOR**) override {
        UNCOMPRESSEDAUDIOFORMAT f = {};
        if (nIn && SUCCEEDED(ppIn[0]->pFormat->GetUncompressedAudioFormat(&f))) {
            m_canais = f.dwSamplesPerFrame;
        }
        m_travas++;
        return S_OK;
    }
    STDMETHODIMP UnlockForProcess() override {
        m_travas--;
        return S_OK;
    }

    // o "redutor": a saida e a entrada pela metade (silencio segue silencio)
    STDMETHODIMP_(void) APOProcess(UINT32, APO_CONNECTION_PROPERTY** ppIn, UINT32, APO_CONNECTION_PROPERTY** ppOut) override {
        const float* e = reinterpret_cast<const float*>(ppIn[0]->pBuffer);
        float* s = reinterpret_cast<float*>(ppOut[0]->pBuffer);
        const UINT32 q = ppIn[0]->u32ValidFrameCount;
        for (UINT32 i = 0; i < q * m_canais; i++) {
            s[i] = ppIn[0]->u32BufferFlags == BUFFER_SILENT ? 0.0f : 0.5f * e[i];
        }
        ppOut[0]->u32ValidFrameCount = q;
        ppOut[0]->u32BufferFlags = ppIn[0]->u32BufferFlags;
        m_processos++;
    }
    STDMETHODIMP_(UINT32) CalcInputFrames(UINT32 n) override { return n; }
    STDMETHODIMP_(UINT32) CalcOutputFrames(UINT32 n) override { return n; }
};

static CFabricanteFalso* g_falso = nullptr;

static HRESULT CriaFalso(int, CLSID* clsid, IUnknown** obj) {
    *clsid = CLSID_FabricanteFalso;
    g_falso = new CFabricanteFalso();  // nasce com 1: a referencia da banca, para conferir
    g_falso->AddRef();                 // e a do hospedeiro
    *obj = static_cast<IAudioProcessingObject*>(g_falso);
    return S_OK;
}

struct BancaHospede {
    IUnknown* obj;  // o IUnknown interno do hospedeiro, como o motor recebe da fabrica
    IAudioProcessingObjectRT* rt;
    IAudioProcessingObjectConfiguration* cfg;
    CFabricanteFalso* falso;
    IAudioMediaType* fmt;
};

// O hospedeiro pela fabrica de verdade (vaga 0), com o fabricante falso por dentro
extern "C" __declspec(dllexport) void* banca_hospede_cria(const wchar_t* mapa, float taxa, unsigned canais,
                                                          unsigned max_quadros) {
    wcsncpy_s(g_banca_mapa, mapa, _TRUNCATE);
    g_cria_hospedado = CriaFalso;
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
    IUnknown* obj = nullptr;
    if (FAILED(g_fabricas_hospede[0].CreateInstance(nullptr, __uuidof(IUnknown), reinterpret_cast<void**>(&obj)))) {
        fmt->Release();
        return nullptr;
    }
    auto* b = new BancaHospede{obj, nullptr, nullptr, g_falso, fmt};
    obj->QueryInterface(IID_PPV_ARGS(&b->rt));
    obj->QueryInterface(IID_PPV_ARGS(&b->cfg));
    IAudioProcessingObject* apo = nullptr;
    obj->QueryInterface(IID_PPV_ARGS(&apo));
    APOInitBaseStruct ini = {sizeof(APOInitBaseStruct), CLSID_Hospede[0]};  // sem o endpoint: age como o alvo
    APO_CONNECTION_DESCRIPTOR ent = {}, sai = {};
    for (APO_CONNECTION_DESCRIPTOR* d : {&ent, &sai}) {
        d->Type = APO_CONNECTION_BUFFER_TYPE_EXTERNAL;
        d->u32MaxFrameCount = max_quadros;
        d->pFormat = fmt;
        d->u32Signature = APO_CONNECTION_DESCRIPTOR_SIGNATURE;
    }
    APO_CONNECTION_DESCRIPTOR* pe = &ent;
    APO_CONNECTION_DESCRIPTOR* ps = &sai;
    const bool ok = apo && b->rt && b->cfg && SUCCEEDED(apo->Initialize(sizeof(ini), reinterpret_cast<BYTE*>(&ini))) &&
                    SUCCEEDED(b->cfg->LockForProcess(1, &pe, 1, &ps));
    if (apo) {
        apo->Release();
    }
    return ok ? b : nullptr;
}

// O que o hospedeiro mostra: [0] o Initialize do fabricante recebeu o CLSID dele; [1] o registro sai com o CLSID do
// hospedeiro; [2] tem o cancelamento de eco (o fabricante tem); [3] tem o IAudioSystemEffects3 (o fabricante nao tem);
// [4] o fabricante esta travado; [5] blocos que o fabricante processou
extern "C" __declspec(dllexport) void banca_hospede_info(void* h, int* r) {
    auto* b = static_cast<BancaHospede*>(h);
    r[0] = b->falso->m_init_clsid == CLSID_FabricanteFalso;
    IAudioProcessingObject* apo = nullptr;
    APO_REG_PROPERTIES* reg = nullptr;
    r[1] = SUCCEEDED(b->obj->QueryInterface(IID_PPV_ARGS(&apo))) && SUCCEEDED(apo->GetRegistrationProperties(&reg)) &&
           reg->clsid == CLSID_Hospede[0];
    if (reg) {
        CoTaskMemFree(reg);
    }
    if (apo) {
        apo->Release();
    }
    IUnknown* x = nullptr;
    r[2] = SUCCEEDED(b->obj->QueryInterface(__uuidof(IApoAcousticEchoCancellation), reinterpret_cast<void**>(&x)));
    if (x) {
        x->Release();
        x = nullptr;
    }
    r[3] = SUCCEEDED(b->obj->QueryInterface(__uuidof(IAudioSystemEffects3), reinterpret_cast<void**>(&x)));
    if (x) {
        x->Release();
    }
    r[4] = b->falso->m_travas;
    r[5] = b->falso->m_processos;
}

extern "C" __declspec(dllexport) void banca_hospede_bloco(void* h, float* entrada, float* saida, unsigned quadros,
                                                          int silencio) {
    auto* b = static_cast<BancaHospede*>(h);
    APO_CONNECTION_PROPERTY ent = {reinterpret_cast<UINT_PTR>(entrada), quadros,
                                   silencio ? BUFFER_SILENT : BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    APO_CONNECTION_PROPERTY sai = {reinterpret_cast<UINT_PTR>(saida), 0, BUFFER_VALID, APO_CONNECTION_PROPERTY_SIGNATURE};
    APO_CONNECTION_PROPERTY* pe = &ent;
    APO_CONNECTION_PROPERTY* ps = &sai;
    b->rt->APOProcess(1, &pe, 1, &ps);
}

// devolve as referencias que sobraram no fabricante falso depois de soltar tudo (1 = so a da banca: nada vazou)
extern "C" __declspec(dllexport) int banca_hospede_destroi(void* h) {
    auto* b = static_cast<BancaHospede*>(h);
    b->cfg->UnlockForProcess();
    b->rt->Release();
    b->cfg->Release();
    b->obj->Release();
    const int sobra = (int)b->falso->m_ref;
    b->falso->Release();
    b->fmt->Release();
    g_cria_hospedado = nullptr;
    delete b;
    return sobra;
}
