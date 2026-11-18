r"""Confere a troca de nome de Vitrola para Ritmelli (#58) no PC de quem ja tinha o app: os dados de quem usa mudam de
pasta (pastas.migra), inclusive com a pasta de antes presa; o registro de antes e copiado sem trocar o que o novo ja
tem (migra.registro), com as subchaves, e depois sai; da pasta do app de antes sai so o que era dele
(migra.pasta_velha); e o celular pareado antes segue conectado pelo cookie de antes (pareamento.chave_do). O registro
e o do usuario (HKCU\Software\RitmelliTesteMigra), e as pastas, temporarias: nada de verdade e tocado. O caminho
inteiro, por cima da 0.4.1 publicada, e o job testa-migracao da esteira (instalador/testa-migracao.ps1).

    python dev/testa_migra.py

Sai 1 se algo falha."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
import migra  # noqa: E402

try:  # a esteira roda este teste antes de instalar as bibliotecas: o QR do pareamento nao entra aqui
    import segno  # noqa: F401
except ImportError:
    import types
    sys.modules["segno"] = types.ModuleType("segno")
import pareamento  # noqa: E402

falhas = []


def confere(ok, msg):
    print(f"{'ok  ' if ok else 'FAIL'} {msg}")
    if not ok:
        falhas.append(msg)


def pastas_com(local, codigo):
    """Roda o codigo num Python novo, com a LOCALAPPDATA trocada (o pastas.py calcula as pastas ao carregar)."""
    env = {**os.environ, "LOCALAPPDATA": str(local)}
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import pastas\n" + codigo,
                        str(RAIZ)], capture_output=True, text=True, env=env, encoding="utf-8")
    return r.returncode, (r.stdout + r.stderr).strip()


print("--- a pasta de dados")
with tempfile.TemporaryDirectory() as tmp:
    local = Path(tmp)
    (local / "Vitrola" / "library").mkdir(parents=True)
    (local / "Vitrola" / "library" / "config.json").write_text('{"marca": 1}', encoding="utf-8")
    cod, out = pastas_com(local, "print(pastas.DADOS.name, pastas.migra(), pastas.DADOS.name, pastas.LIB)")
    confere(cod == 0 and out.startswith("Vitrola True Ritmelli"), f"antes de migrar, os dados seguem na de antes; depois, na nova ({out})")
    confere((local / "Ritmelli" / "library" / "config.json").read_text(encoding="utf-8") == '{"marca": 1}'
            and not (local / "Vitrola").exists(), "a biblioteca inteira foi para a pasta nova, e a de antes saiu")
    cod, out = pastas_com(local, "print(pastas.DADOS.name, pastas.migra())")
    confere(out == "Ritmelli True", f"ja migrado: a nova, sem mexer em nada ({out})")

with tempfile.TemporaryDirectory() as tmp:
    local = Path(tmp)
    (local / "Vitrola").mkdir()
    (local / "Ritmelli").mkdir()
    cod, out = pastas_com(local, "print(pastas.DADOS.name, pastas.migra())")
    confere(out == "Ritmelli True" and (local / "Vitrola").exists(), f"as duas existem: vale a nova, e a de antes fica ({out})")

if sys.platform == "win32":
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp)
        (local / "Vitrola").mkdir()
        preso = open(local / "Vitrola" / "server.log", "w", encoding="utf-8")  # o Windows nao renomeia pasta com arquivo aberto
        try:
            cod, out = pastas_com(local, "print(pastas.migra(), pastas.DADOS.name)")
            confere(cod == 0 and out.endswith("False Vitrola") and (local / "Vitrola").exists(),
                    f"a pasta de antes presa: os dados seguem nela, sem erro, e a troca fica para a proxima abertura ({out})")
        finally:
            preso.close()

if sys.platform == "win32":
    import winreg
    print("--- o registro")
    base = r"Software\RitmelliTesteMigra"
    de, para = base + r"\Velho", base + r"\Novo"
    hk = winreg.HKEY_CURRENT_USER
    try:
        migra.apaga_registro_velho(hk, base)
        with winreg.CreateKey(hk, de) as k:
            winreg.SetValueEx(k, "Metricas", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(k, "_hospede0", 0, winreg.REG_SZ, "{clsid-do-fabricante}")
        with winreg.CreateKey(hk, de + r"\Microfone\{id-do-microfone}") as k:
            winreg.SetValueEx(k, "original", 0, winreg.REG_MULTI_SZ, ["{efx}", "{mfx}"])
            winreg.SetValueEx(k, "_versao", 0, winreg.REG_DWORD, 3)
        with winreg.CreateKey(hk, para) as k:
            winreg.SetValueEx(k, "Metricas", 0, winreg.REG_DWORD, 1)  # a escolha nova, feita nesta instalacao
        n = migra.registro(hk, de, para)

        def le(chave, nome):
            with winreg.OpenKey(hk, chave) as k:
                return winreg.QueryValueEx(k, nome)

        confere(n == 3, f"copia os valores que faltam no novo ({n})")
        confere(le(para, "Metricas") == (1, winreg.REG_DWORD), "o que o novo ja tem fica (a escolha desta instalacao)")
        confere(le(para, "_hospede0") == ("{clsid-do-fabricante}", winreg.REG_SZ), "as vagas do hospedeiro vem junto")
        confere(le(para + r"\Microfone\{id-do-microfone}", "original") == (["{efx}", "{mfx}"], winreg.REG_MULTI_SZ),
                "o original de cada microfone vem com a subchave e o tipo")
        confere(migra.registro(hk, de, para) == 0, "de novo: nada a copiar")
        confere(migra.registro(hk, base + r"\NaoExiste", para) == 0, "sem a chave de antes: nada a fazer")
        migra.apaga_registro_velho(hk, de)
        try:
            winreg.OpenKey(hk, de).Close()
            confere(False, "a chave de antes sai, com as subchaves")
        except FileNotFoundError:
            confere(True, "a chave de antes sai, com as subchaves")
    finally:
        migra.apaga_registro_velho(hk, base)

print("--- a pasta do app de antes")
with tempfile.TemporaryDirectory() as tmp:
    velha = Path(tmp) / "Vitrola"
    for c in ("vitrola.exe", "_internal/python312.dll", "_internal/x/y.pyd", "bin/ffmpeg.exe", "microfone/micfx.dll",
              "microfone/log/micfx.log", "atualizacao/estado.json", "LICENSE.txt", "TERCEIROS.txt", "unins000.exe",
              "unins000.dat"):
        (velha / c).parent.mkdir(parents=True, exist_ok=True)
        (velha / c).write_bytes(b"x")
    presos = migra.pasta_velha(velha)
    confere(presos == 0 and not velha.exists(), "a pasta de antes, so com o que era do app: sai inteira")
    for c in ("vitrola.exe", "_internal/a.dll", "notas-de-alguem.txt"):
        (velha / c).parent.mkdir(parents=True, exist_ok=True)
        (velha / c).write_bytes(b"x")
    migra.pasta_velha(velha)
    confere(sorted(p.name for p in velha.iterdir()) == ["notas-de-alguem.txt"],
            "o que nao era do app fica, e a pasta tambem")
    confere(migra.pasta_velha(Path(tmp) / "NaoExiste") == 0, "sem a pasta de antes: nada a fazer")
    # a pasta do app que esta rodando (aqui, uma de mentira no lugar do pastas.APP) nunca e apagada
    import pastas  # noqa: E402
    rodando = Path(tmp) / "Rodando"
    (rodando / "_internal").mkdir(parents=True)
    (rodando / "vitrola.exe").write_bytes(b"x")
    app, pastas.APP = pastas.APP, rodando
    try:
        confere(migra.pasta_velha(rodando) == 0 and (rodando / "vitrola.exe").exists() and (rodando / "_internal").exists(),
                "a pasta do app que esta rodando nunca e apagada")
    finally:
        pastas.APP = app

print("--- o celular pareado antes")
confere(pareamento.chave_do({"vitrola_celular": "abc"}) == "abc", "o cookie de antes ainda vale")
confere(pareamento.chave_do({"ritmelli_celular": "novo", "vitrola_celular": "velho"}) == "novo", "o novo vale sobre o de antes")
confere(pareamento.chave_do({}) is None, "sem cookie: sem chave")

print()
if falhas:
    print(f"{len(falhas)} falharam")
    sys.exit(1)
print("tudo certo")
