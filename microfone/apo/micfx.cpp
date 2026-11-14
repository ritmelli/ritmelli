// micfx.dll: o filtro de microfone da Vitrola (um APO de efeito do motor de audio do Windows).
//
// O Windows carrega o filtro dentro do audiodg.exe, no caminho do microfone em que ele foi pendurado (o
// microfone.py poe o nosso nas vagas EFX e LFX daquele microfone e guarda o original). A cada bloco de audio do
// microfone (~10 ms), o APOProcess soma o que o app deixou no anel (anel.h): quem ouve aquele microfone (jogo, Discord)
// recebe a voz e a musica juntas.
//
// Escrito a partir da documentacao publica da Microsoft (Audio Processing Objects, CBaseAudioProcessingObject).
#include <windows.h>
#include <sddl.h>
#include <mmreg.h>
#include <audioenginebaseapo.h>
#include <baseaudioprocessingobject.h>
#include <audioengineextensionapo.h>
#include <mmdeviceapi.h>
#include <propidl.h>
#include <new>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include "anel.h"
#include "reamostra.h"

// Nome do modo de processamento de sinal (audiomediatype.h / ksmedia.h) pro log
static const char* NomeDoModo(const GUID& g) {
    static const struct {
        GUID id;
        const char* nome;
    } modos[] = {
        {{0xC18E2F7E, 0x933D, 0x4965, {0xB7, 0xD1, 0x1E, 0xEF, 0x22, 0x8D, 0x2A, 0xF3}}, "DEFAULT"},
        {{0x9E90EA20, 0xB493, 0x4FD1, {0xA1, 0xA8, 0x7E, 0x13, 0x61, 0xA9, 0x56, 0xCF}}, "RAW"},
        {{0x98951333, 0xB9CD, 0x48B1, {0xA0, 0xA3, 0xFF, 0x40, 0x68, 0x2D, 0x73, 0xF7}}, "COMMUNICATIONS"},
        {{0x4780004E, 0x7133, 0x41D8, {0x8C, 0x74, 0x66, 0x0D, 0xAD, 0xD2, 0xC0, 0xEE}}, "SPEECH"},
        {{0xB26FEB0D, 0xEC94, 0x477C, {0x94, 0x94, 0xD1, 0xAB, 0x8E, 0x75, 0x3F, 0x6E}}, "MEDIA"},
        {{0xFC1CFC9B, 0xB9D6, 0x4CFA, {0xB5, 0xE0, 0x4B, 0xB2, 0x16, 0x68, 0x78, 0xB2}}, "MOVIE"},
        {{0x9CF2A70B, 0xF377, 0x403B, {0xBD, 0x6B, 0x36, 0x08, 0x63, 0xE0, 0x35, 0x5C}}, "NOTIFICATION"},
        {{0xB13C2B0F, 0x4F55, 0x4A4F, {0xB2, 0xEE, 0x49, 0xA2, 0x4A, 0x7F, 0x5C, 0x2E}}, "FAR_FIELD"},
    };
    for (const auto& m : modos) {
        if (m.id == g) {
            return m.nome;
        }
    }
    return "outro";
}

// Log fora do tempo real (carregar, negociar formato, Initialize, Lock): log\micfx.log, na pasta da DLL. O
// microfone.py cria a pasta dentro da pasta de programas (so administrador cria ali) e da escrita so pro LocalService,
// quem roda o audiodg.exe; o usuario so le. Passou de LOG_TETO, o log vira micfx.log.1 (um so) e recomeca.
static const LONGLONG LOG_TETO = 1 << 20;
static wchar_t g_log[MAX_PATH];
static wchar_t g_log_velho[MAX_PATH];
static SRWLOCK g_log_trava = SRWLOCK_INIT;

static void PreparaLog(HMODULE modulo) {
    wchar_t pasta[MAX_PATH];
    DWORD n = GetModuleFileNameW(modulo, pasta, MAX_PATH);
    if (!n || n >= MAX_PATH) {
        return;
    }
    wchar_t* barra = wcsrchr(pasta, L'\\');
    if (!barra) {
        return;
    }
    barra[1] = L'\0';
    if (_snwprintf_s(g_log, MAX_PATH, _TRUNCATE, L"%slog\\micfx.log", pasta) < 0 ||
        _snwprintf_s(g_log_velho, MAX_PATH, _TRUNCATE, L"%slog\\micfx.log.1", pasta) < 0) {
        g_log[0] = L'\0';
    }
}

static HANDLE AbreLog() {
    // sem seguir ponto de reparse no proprio arquivo; sem a pasta log, nao cria nada e nao loga
    return CreateFileW(g_log, FILE_APPEND_DATA | FILE_READ_ATTRIBUTES,
                       FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_ALWAYS,
                       FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
}

static void Log(const char* fmt, ...) {
    if (!g_log[0]) {
        return;
    }
    char msg[480];
    va_list va;
    va_start(va, fmt);
    _vsnprintf_s(msg, sizeof(msg), _TRUNCATE, fmt, va);
    va_end(va);
    SYSTEMTIME t;
    GetLocalTime(&t);
    char linha[560];
    int n = _snprintf_s(linha, sizeof(linha), _TRUNCATE, "%02d:%02d:%02d.%03d pid %lu: %s\r\n", t.wHour, t.wMinute,
                        t.wSecond, t.wMilliseconds, GetCurrentProcessId(), msg);
    AcquireSRWLockExclusive(&g_log_trava);
    HANDLE h = AbreLog();
    LARGE_INTEGER tamanho;
    if (h != INVALID_HANDLE_VALUE && GetFileSizeEx(h, &tamanho) && tamanho.QuadPart > LOG_TETO) {
        CloseHandle(h);
        MoveFileExW(g_log, g_log_velho, MOVEFILE_REPLACE_EXISTING);
        h = AbreLog();
    }
    if (h != INVALID_HANDLE_VALUE) {
        DWORD escrito;
        WriteFile(h, linha, (DWORD)(n > 0 ? n : 0), &escrito, nullptr);
        CloseHandle(h);
    }
    ReleaseSRWLockExclusive(&g_log_trava);
}

static void LogFormato(const char* onde, IAudioMediaType* t, HRESULT hr) {
    UNCOMPRESSEDAUDIOFORMAT f = {};
    if (t && SUCCEEDED(t->GetUncompressedAudioFormat(&f))) {
        Log("%s: hr=0x%08lx formato %08lx canais %u bytes %u bits %u taxa %.0f", onde, hr, f.guidFormatType.Data1,
            f.dwSamplesPerFrame, f.dwBytesPerSampleContainer, f.dwValidBitsPerSample, f.fFramesPerSecond);
    } else {
        Log("%s: hr=0x%08lx (sem formato)", onde, hr);
    }
}

// O que sai do filtro vai pro Discord, pro jogo e pros outros efeitos do microfone, e um NaN ali trava o estado de
// filtro deles ate o microfone reabrir. Amostra do anel que nao e numero vira silencio; o ganho fica em
// [0, GANHO_MAX]; e a soma de voz e musica que passa do joelho dobra suave ate 1,0 em vez de estourar (abaixo do
// joelho nada muda: a 48 kHz a musica segue bit a bit).
static const float GANHO_MAX = 4.0f;
static const float JOELHO = 0.9f;

static inline float Finito(float x) {
    return std::isfinite(x) ? x : 0.0f;
}

static inline float Dobra(float x) {
    if (!std::isfinite(x)) {
        return 0.0f;
    }
    const float a = std::fabs(x);
    if (a <= JOELHO) {
        return x;
    }
    const float y = JOELHO + (1.0f - JOELHO) * std::tanh((a - JOELHO) / (1.0f - JOELHO));
    return x < 0.0f ? -y : y;
}

// PKEY_AudioEndpoint_GUID: o GUID do microfone ("{a1b2c3d4-...}"), o mesmo nome da chave dele no registro
static const PROPERTYKEY PKEY_GuidDoMicrofone = {
    {0x1da5d803, 0xd492, 0x4edd, {0x8c, 0x23, 0xe0, 0xc0, 0xff, 0xee, 0x7f, 0x0e}}, 4};

// O hash do microfone em que esta instancia foi pendurada (MicFxHash), e o GUID em texto pro log; 0 se nao deu. Pelas
// propriedades do endpoint (o primeiro ponteiro depois da base em todas as versoes do APOInitSystemEffects); sem
// elas, pelo ultimo aparelho da lista (o endpoint, no APOInitSystemEffects e no 2).
static uint32_t HashDoMicrofone(UINT32 cb, BYTE* dados, char* txt, size_t n) {
    txt[0] = '\0';
    if (cb < sizeof(APOInitSystemEffects)) {
        return 0;
    }
    auto* s1 = reinterpret_cast<APOInitSystemEffects*>(dados);
    uint32_t h = 0;
    if (s1->pAPOEndpointProperties) {
        PROPVARIANT pv;
        PropVariantInit(&pv);
        if (SUCCEEDED(s1->pAPOEndpointProperties->GetValue(PKEY_GuidDoMicrofone, &pv)) && pv.vt == VT_LPWSTR &&
            pv.pwszVal) {
            h = MicFxHash(pv.pwszVal);
            WideCharToMultiByte(CP_ACP, 0, pv.pwszVal, -1, txt, (int)n, nullptr, nullptr);
        }
        PropVariantClear(&pv);
    }
    const bool lista = cb == sizeof(APOInitSystemEffects) || cb == sizeof(APOInitSystemEffects2);
    if (!h && lista && s1->pDeviceCollection) {
        UINT k = 0;
        IMMDevice* d = nullptr;
        if (SUCCEEDED(s1->pDeviceCollection->GetCount(&k)) && k &&
            SUCCEEDED(s1->pDeviceCollection->Item(k - 1, &d)) && d) {
            LPWSTR id = nullptr;
            if (SUCCEEDED(d->GetId(&id)) && id) {  // "{0.0.1.00000000}.{guid}": o guid e o que vem depois do ultimo '.'
                const wchar_t* g = wcsrchr(id, L'.');
                g = g ? g + 1 : id;
                h = MicFxHash(g);
                WideCharToMultiByte(CP_ACP, 0, g, -1, txt, (int)n, nullptr, nullptr);
                CoTaskMemFree(id);
            }
            d->Release();
        }
    }
    return h;
}

// {C17A1D48-D473-40D9-9ED3-D024AA46EBE2}
static const CLSID CLSID_MicFx = {0xc17a1d48, 0xd473, 0x40d9, {0x9e, 0xd3, 0xd0, 0x24, 0xaa, 0x46, 0xeb, 0xe2}};

static HMODULE g_modulo = nullptr;
static volatile LONG g_objetos = 0;
static volatile LONG g_travas = 0;
static volatile LONG g_proximo_dono = 0;

static const CRegAPOProperties<1> g_props(
    CLSID_MicFx, L"Vitrola Microfone", L"Vitrola (GPLv3)", 1, 0, __uuidof(IAudioProcessingObject),
    // sem APO_FLAG_INPLACE: entrada e saida em buffers separados, e a entrada nunca e escrita
    (APO_FLAG)(APO_FLAG_FRAMESPERSECOND_MUST_MATCH | APO_FLAG_BITSPERSAMPLE_MUST_MATCH |
               APO_FLAG_SAMPLESPERFRAME_MUST_MATCH));

// A memoria do anel: criada aqui (LocalService pode criar Global\); o usuario logado le e escreve
static MicFxAnel* AbreAnel(HANDLE* mapa) {
    SECURITY_ATTRIBUTES sa = {sizeof(sa), nullptr, FALSE};
    // sistema, servico local e administradores: tudo; usuario interativo e autenticado: ler e escrever
    if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
            L"D:(A;;GA;;;SY)(A;;GA;;;LS)(A;;GA;;;BA)(A;;GRGW;;;IU)(A;;GRGW;;;AU)", SDDL_REVISION_1,
            &sa.lpSecurityDescriptor, nullptr)) {
        return nullptr;
    }
    HANDLE h = CreateFileMappingW(INVALID_HANDLE_VALUE, &sa, PAGE_READWRITE, 0, sizeof(MicFxAnel), MICFX_MAPA);
    DWORD erro = GetLastError();
    bool novo = h && erro != ERROR_ALREADY_EXISTS;
    LocalFree(sa.lpSecurityDescriptor);
    if (!h) {
        Log("CreateFileMapping falhou: %lu", erro);
        return nullptr;
    }
    auto* a = static_cast<MicFxAnel*>(MapViewOfFile(h, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(MicFxAnel)));
    if (!a) {
        CloseHandle(h);
        return nullptr;
    }
    if (novo || a->magia != MICFX_MAGIA) {  // memoria nova vem zerada
        a->versao = MICFX_VERSAO;
        a->taxa = MICFX_TAXA;
        a->canais = MICFX_CANAIS;
        a->quadros = MICFX_QUADROS;
        a->leitores = MICFX_LEITORES;
        a->ganho = 1.0f;
        a->sem_voz = 0;
        a->alvo = 0;
        MemoryBarrier();
        a->magia = MICFX_MAGIA;
    }
    *mapa = h;
    return a;
}

// O motor de audio agrega o APO (cria com um IUnknown externo): as interfaces publicas delegam o IUnknown ao
// externo, e o motor fala com o objeto pelo IUnknown interno (m_interno), que nao delega. Sem externo, o interno
// faz as vezes dele (o COM de sempre).
class CMicFx : public CBaseAudioProcessingObject, public IAudioSystemEffects2 {
public:
    explicit CMicFx(IUnknown* externo) : CBaseAudioProcessingObject(g_props), m_interno(this) {
        m_externo = externo ? externo : &m_interno;
        InterlockedIncrement(&g_objetos);
    }
    virtual ~CMicFx() {
        SoltaAnel();
        InterlockedDecrement(&g_objetos);
    }

    // IUnknown das interfaces publicas: sempre pelo externo
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override { return m_externo->QueryInterface(riid, ppv); }
    STDMETHODIMP_(ULONG) AddRef() override { return m_externo->AddRef(); }
    STDMETHODIMP_(ULONG) Release() override { return m_externo->Release(); }

    // o IUnknown interno, que nao delega
    HRESULT NdQueryInterface(REFIID riid, void** ppv) {
        if (!ppv) {
            return E_POINTER;
        }
        if (riid == __uuidof(IUnknown)) {
            *ppv = &m_interno;
        } else if (riid == __uuidof(IAudioProcessingObject)) {
            *ppv = static_cast<IAudioProcessingObject*>(this);
        } else if (riid == __uuidof(IAudioProcessingObjectRT)) {
            *ppv = static_cast<IAudioProcessingObjectRT*>(this);
        } else if (riid == __uuidof(IAudioProcessingObjectConfiguration)) {
            *ppv = static_cast<IAudioProcessingObjectConfiguration*>(this);
        } else if (riid == __uuidof(IAudioSystemEffects) || riid == __uuidof(IAudioSystemEffects2)) {
            *ppv = static_cast<IAudioSystemEffects2*>(this);
        } else {  // o motor pergunta ~25 interfaces a cada abertura do microfone: sem log, senao ele so cresce
            *ppv = nullptr;
            return E_NOINTERFACE;
        }
        reinterpret_cast<IUnknown*>(*ppv)->AddRef();
        return S_OK;
    }
    ULONG NdAddRef() { return InterlockedIncrement(&m_refs); }
    ULONG NdRelease() {
        ULONG n = InterlockedDecrement(&m_refs);
        if (n == 0) {
            delete this;
        }
        return n;
    }

    class Interno : public IUnknown {
    public:
        explicit Interno(CMicFx* dono) : m_dono(dono) {}
        STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override { return m_dono->NdQueryInterface(riid, ppv); }
        STDMETHODIMP_(ULONG) AddRef() override { return m_dono->NdAddRef(); }
        STDMETHODIMP_(ULONG) Release() override { return m_dono->NdRelease(); }

    private:
        CMicFx* m_dono;
    };
    Interno m_interno;

    // IAudioSystemEffects2: nenhum efeito pra listar na tela de som
    STDMETHODIMP GetEffectsList(LPGUID* ppEffectsIds, UINT* pcEffects, HANDLE) override {
        if (!ppEffectsIds || !pcEffects) {
            return E_POINTER;
        }
        *ppEffectsIds = nullptr;
        *pcEffects = 0;
        return S_OK;
    }

    // IAudioProcessingObject::Initialize: o motor manda APOInitSystemEffects (2 ou 3); nada nele muda o filtro
    STDMETHODIMP Initialize(UINT32 cbDataSize, BYTE* pbyData) override {
        if (cbDataSize && !pbyData) {
            return E_POINTER;
        }
        if (cbDataSize < sizeof(APOInitBaseStruct)) {
            return E_INVALIDARG;
        }
        auto* base = reinterpret_cast<APOInitBaseStruct*>(pbyData);
        // O modo de processamento so vem no APOInitSystemEffects2 (vaga SFX); a vaga legada LFX manda o 1
        const char* modo = "legado (sem modo)";
        if (cbDataSize >= sizeof(APOInitSystemEffects2)) {
            const auto* s2 = reinterpret_cast<APOInitSystemEffects2*>(pbyData);
            modo = NomeDoModo(s2->AudioProcessingMode);
            if (s2->InitializeForDiscoveryOnly) {
                modo = "so descoberta";
            }
        }
        char guid[64];
        m_ep = HashDoMicrofone(cbDataSize, pbyData, guid, sizeof(guid));
        Log("Initialize: %u bytes, clsid %s, modo %s, microfone %s (%08x)", cbDataSize,
            base->clsid == CLSID_MicFx ? "nosso" : "OUTRO", modo, guid[0] ? guid : "?", m_ep);
        EnterCriticalSection(&m_CritSec);
        m_bIsInitialized = true;
        LeaveCriticalSection(&m_CritSec);
        return S_OK;
    }

    STDMETHODIMP IsInputFormatSupported(IAudioMediaType* pOutputFormat, IAudioMediaType* pRequested,
                                        IAudioMediaType** ppSupported) override {
        HRESULT hr = CBaseAudioProcessingObject::IsInputFormatSupported(pOutputFormat, pRequested, ppSupported);
        LogFormato("IsInputFormatSupported pedido", pRequested, hr);
        if (hr == S_FALSE && ppSupported && *ppSupported) {
            LogFormato("IsInputFormatSupported sugerido", *ppSupported, hr);
        }
        return hr;
    }

    STDMETHODIMP IsOutputFormatSupported(IAudioMediaType* pInputFormat, IAudioMediaType* pRequested,
                                         IAudioMediaType** ppSupported) override {
        HRESULT hr = CBaseAudioProcessingObject::IsOutputFormatSupported(pInputFormat, pRequested, ppSupported);
        LogFormato("IsOutputFormatSupported pedido", pRequested, hr);
        if (hr == S_FALSE && ppSupported && *ppSupported) {
            LogFormato("IsOutputFormatSupported sugerido", *ppSupported, hr);
        }
        return hr;
    }

    STDMETHODIMP LockForProcess(UINT32 nIn, APO_CONNECTION_DESCRIPTOR** ppIn, UINT32 nOut,
                                APO_CONNECTION_DESCRIPTOR** ppOut) override {
        HRESULT hr = CBaseAudioProcessingObject::LockForProcess(nIn, ppIn, nOut, ppOut);
        LogFormato("LockForProcess entrada", nIn && ppIn[0] ? ppIn[0]->pFormat : nullptr, hr);
        if (FAILED(hr)) {
            return hr;
        }
        m_canais = m_u32SamplesPerFrame;
        UNCOMPRESSEDAUDIOFORMAT f = {};
        if (nIn && ppIn[0] && ppIn[0]->pFormat && SUCCEEDED(ppIn[0]->pFormat->GetUncompressedAudioFormat(&f)) &&
            f.fFramesPerSecond > 0) {
            m_taxa = f.fFramesPerSecond;
        }
        m_rs.Prepara((uint32_t)(m_taxa + 0.5f));
        PegaAnel();
        if (m_anel && (m_anel->alvo == 0 || (m_ep != 0 && m_anel->alvo != m_ep))) {
            SoltaVaga();  // nao e o alvo agora: o anel fica aberto, e a vaga so com ele virando o alvo
        }
        Log("LockForProcess: canais %u taxa %.0f, anel %s, vaga %d, reamostra %s (L %u M %u taps %u)", m_canais, m_taxa,
            m_anel ? "ok" : "SEM", m_vaga,
            m_rs.modo == Reamostra::DIRETO ? "direto" : (m_rs.modo == Reamostra::SINC ? "sinc" : "linear"), m_rs.L,
            m_rs.M, m_rs.taps);
        return S_OK;
    }

    STDMETHODIMP UnlockForProcess() override {
        SoltaAnel();
        return CBaseAudioProcessingObject::UnlockForProcess();
    }

    // Tempo real: nada de trava, alocacao ou chamada que espera
    STDMETHODIMP_(void) APOProcess(UINT32 nIn, APO_CONNECTION_PROPERTY** ppIn, UINT32 nOut,
                                   APO_CONNECTION_PROPERTY** ppOut) override {
        UNREFERENCED_PARAMETER(nIn);
        UNREFERENCED_PARAMETER(nOut);
        APO_CONNECTION_PROPERTY* in = ppIn[0];
        APO_CONNECTION_PROPERTY* out = ppOut[0];
        const UINT32 quadros = in->u32ValidFrameCount;
        float* fonte = reinterpret_cast<float*>(in->pBuffer);
        float* destino = reinterpret_cast<float*>(out->pBuffer);
        const UINT32 amostras = quadros * m_canais;
        bool silencio = in->u32BufferFlags == BUFFER_SILENT;
        if (fonte != destino) {
            if (silencio) {
                ZeroMemory(destino, amostras * sizeof(float));
            } else {
                CopyMemory(destino, fonte, amostras * sizeof(float));
            }
        } else if (silencio) {
            ZeroMemory(destino, amostras * sizeof(float));
        }
        bool somou = Soma(destino, quadros);
        out->u32ValidFrameCount = quadros;
        out->u32BufferFlags = (silencio && !somou) ? BUFFER_SILENT : BUFFER_VALID;
    }

private:
    // So no microfone alvo do app: devolve a voz crua (destino ainda e a entrada) e soma o que tem no anel em destino
    // (quadros no formato do microfone); true se somou algo. Em qualquer outro microfone, nada muda e a vaga fica livre
    bool Soma(float* destino, UINT32 quadros) {
        MicFxAnel* a = m_anel;
        if (!a || a->magia != MICFX_MAGIA) {
            return false;
        }
        const uint32_t alvo = a->alvo;
        if (alvo == 0 || (m_ep != 0 && alvo != m_ep)) {  // microfone sem o hash (m_ep 0): age como o alvo
            SoltaVaga();
            return false;
        }
        EscreveVoz(a, destino, quadros);
        if (m_vaga < 0) {  // a vaga foi tomada (a instancia ficou muda tempo demais): tenta outra, sem alocar
            PegaAnel();
            if (m_vaga < 0) {
                return false;
            }
        }
        MicFxLeitor& eu = a->leitor[m_vaga];
        const int64_t agora = (int64_t)GetTickCount64();
        eu.batida = agora;
        if (eu.dono != m_dono) {
            m_vaga = -1;
            return false;
        }
        const int64_t escrito = a->escrito;
        MemoryBarrier();  // os dados ate 'escrito' ja estao na memoria
        if (escrito - m_rs.MaisVelho() > (int64_t)MICFX_QUADROS) {  // ficou pra tras (nao devia): pula pro mais novo
            m_rs.Comeca(escrito - MICFX_QUADROS / 2);
        }
        float ganho = a->ganho;  // a memoria e escrita pelo app: NaN, negativo ou exagero nao passam
        if (!(ganho >= 0.0f)) {
            ganho = 0.0f;
        } else if (ganho > GANHO_MAX) {
            ganho = GANHO_MAX;
        }
        // a voz cortada so com o app escrevendo: o app que cai com ela cortada nao deixa o microfone mudo
        const bool sem_voz = a->sem_voz != 0 && agora - a->batida_app < (int64_t)MICFX_APP_MS;
        const UINT32 canais = m_canais;
        const uint32_t gerados = m_rs.Gera(a->dados, MICFX_QUADROS - 1, escrito, quadros,
                                           [&](uint32_t i, float esq, float dir) {
            float* o = &destino[i * canais];
            esq = Finito(esq) * ganho;
            dir = Finito(dir) * ganho;
            if (canais == 1) {
                const float m = 0.5f * (esq + dir);
                o[0] = Dobra(sem_voz ? m : o[0] + m);
            } else {
                o[0] = Dobra(sem_voz ? esq : o[0] + esq);
                o[1] = Dobra(sem_voz ? dir : o[1] + dir);
                for (UINT32 c = 2; sem_voz && c < canais; c++) {
                    o[c] = 0.0f;
                }
            }
        });
        eu.lido = m_rs.MaisVelho();  // o escritor nao passa por cima do que o filtro ainda le
        if (sem_voz && gerados < quadros) {  // acabou o que tem: sem voz, o resto do bloco e silencio
            ZeroMemory(&destino[gerados * canais], (quadros - gerados) * canais * sizeof(float));
        }
        return gerados > 0;
    }

    // A voz crua do microfone para o app, mono e na taxa dele (o app reamostra): so o filtro do alvo escreve
    void EscreveVoz(MicFxAnel* a, const float* x, UINT32 quadros) {
        const UINT32 c = m_canais ? m_canais : 1;
        const float k = 1.0f / (float)c;
        const int64_t w = a->voz_escrito;
        for (UINT32 i = 0; i < quadros; i++) {
            float v = 0.0f;
            for (UINT32 j = 0; j < c; j++) {
                v += x[i * c + j];
            }
            a->voz[(w + i) & (MICFX_VOZ_QUADROS - 1)] = Finito(v * k);
        }
        a->voz_taxa = (uint32_t)m_taxa;
        MemoryBarrier();  // a voz antes do indice: o app so le ate voz_escrito
        a->voz_escrito = w + quadros;
    }

    void SoltaVaga() {
        if (m_anel && m_vaga >= 0) {
            InterlockedCompareExchange((volatile LONG*)&m_anel->leitor[m_vaga].dono, 0, (LONG)m_dono);
        }
        m_vaga = -1;
    }

    void PegaAnel() {
        if (!m_anel) {
            m_anel = AbreAnel(&m_mapa);
        }
        if (!m_anel || m_vaga >= 0) {
            return;
        }
        m_dono = (uint32_t)InterlockedIncrement(&g_proximo_dono) ^ (GetCurrentProcessId() << 16);
        if (!m_dono) {
            m_dono = 1;
        }
        const int64_t agora = (int64_t)GetTickCount64();
        for (uint32_t v = 0; v < MICFX_LEITORES; v++) {
            MicFxLeitor& l = m_anel->leitor[v];
            const uint32_t atual = l.dono;
            const bool livre = atual == 0 || agora - l.batida > (int64_t)MICFX_BATIDA_MS;
            if (livre && InterlockedCompareExchange((volatile LONG*)&l.dono, (LONG)m_dono, (LONG)atual) == (LONG)atual) {
                m_rs.Comeca(m_anel->escrito);  // so o que chegar daqui pra frente
                l.lido = m_rs.MaisVelho();
                l.batida = agora;
                l.taxa = (uint32_t)m_taxa;
                l.ep = m_ep;
                m_vaga = (int)v;
                return;
            }
        }
    }

    void SoltaAnel() {
        SoltaVaga();
        if (m_anel) {
            UnmapViewOfFile(m_anel);
            m_anel = nullptr;
        }
        if (m_mapa) {
            CloseHandle(m_mapa);
            m_mapa = nullptr;
        }
    }

    volatile LONG m_refs = 1;
    IUnknown* m_externo = nullptr;
    MicFxAnel* m_anel = nullptr;
    HANDLE m_mapa = nullptr;
    int m_vaga = -1;
    uint32_t m_dono = 0;
    uint32_t m_ep = 0;  // o hash do microfone desta instancia (Initialize); 0 = nao deu para saber
    UINT32 m_canais = 1;
    float m_taxa = (float)MICFX_TAXA;
    Reamostra m_rs;
};

class CFabrica : public IClassFactory {
public:
    STDMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        if (riid == __uuidof(IUnknown) || riid == __uuidof(IClassFactory)) {
            *ppv = static_cast<IClassFactory*>(this);
            return S_OK;
        }
        Log("fabrica QueryInterface: iid %08lx-%04x nao suportado", riid.Data1, riid.Data2);
        *ppv = nullptr;
        return E_NOINTERFACE;
    }
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }
    STDMETHODIMP_(ULONG) Release() override { return 1; }
    STDMETHODIMP CreateInstance(IUnknown* externo, REFIID riid, void** ppv) override {
        Log("CreateInstance: entrou, externo %s, iid %08lx-%04x-%04x", externo ? "SIM" : "nao", riid.Data1, riid.Data2,
            riid.Data3);
        if (!ppv) {
            return E_POINTER;
        }
        *ppv = nullptr;
        if (externo && riid != __uuidof(IUnknown)) {  // regra do COM: agregado so entrega o IUnknown interno
            return CLASS_E_NOAGGREGATION;
        }
        auto* o = new (std::nothrow) CMicFx(externo);
        if (!o) {
            return E_OUTOFMEMORY;
        }
        HRESULT hr = o->m_interno.QueryInterface(riid, ppv);
        o->m_interno.Release();  // a referencia do construtor
        Log("CreateInstance: hr=0x%08lx (iid %08lx)", hr, riid.Data1);
        return hr;
    }
    STDMETHODIMP LockServer(BOOL trava) override {
        trava ? InterlockedIncrement(&g_travas) : InterlockedDecrement(&g_travas);
        return S_OK;
    }
};

static CFabrica g_fabrica;

extern "C" BOOL WINAPI DllMain(HINSTANCE modulo, DWORD motivo, LPVOID) {
    if (motivo == DLL_PROCESS_ATTACH) {
        g_modulo = modulo;
        DisableThreadLibraryCalls(modulo);
        PreparaLog(modulo);
        Log("carregada");
    } else if (motivo == DLL_PROCESS_DETACH) {
        Log("descarregada");
    }
    return TRUE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** ppv) {
    if (clsid != CLSID_MicFx) {
        Log("DllGetClassObject: clsid %08lx nao e o nosso", clsid.Data1);
        return CLASS_E_CLASSNOTAVAILABLE;
    }
    HRESULT hr = g_fabrica.QueryInterface(riid, ppv);
    Log("DllGetClassObject: iid %08lx-%04x hr=0x%08lx", riid.Data1, riid.Data2, hr);
    return hr;
}

STDAPI DllCanUnloadNow() {
    return (g_objetos == 0 && g_travas == 0) ? S_OK : S_FALSE;  // o COM pergunta a toda hora: sem log
}

static const wchar_t kChave[] = L"SOFTWARE\\Classes\\CLSID\\{C17A1D48-D473-40D9-9ED3-D024AA46EBE2}";

STDAPI DllRegisterServer() {
    wchar_t caminho[MAX_PATH];
    if (!GetModuleFileNameW(g_modulo, caminho, MAX_PATH)) {
        return HRESULT_FROM_WIN32(GetLastError());
    }
    HKEY k;
    wchar_t sub[160];
    wsprintfW(sub, L"%s\\InprocServer32", kChave);
    LONG r = RegCreateKeyExW(HKEY_LOCAL_MACHINE, sub, 0, nullptr, 0, KEY_WRITE, nullptr, &k, nullptr);
    if (r != ERROR_SUCCESS) {
        return HRESULT_FROM_WIN32(r);
    }
    RegSetValueExW(k, nullptr, 0, REG_SZ, (const BYTE*)caminho, (DWORD)((wcslen(caminho) + 1) * sizeof(wchar_t)));
    const wchar_t modelo[] = L"Both";
    RegSetValueExW(k, L"ThreadingModel", 0, REG_SZ, (const BYTE*)modelo, sizeof(modelo));
    RegCloseKey(k);
    return RegisterAPO(g_props);
}

STDAPI DllUnregisterServer() {
    UnregisterAPO(CLSID_MicFx);
    RegDeleteTreeW(HKEY_LOCAL_MACHINE, kChave);
    return S_OK;
}
