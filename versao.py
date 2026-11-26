"""A versao do Ritmelli. O cliente de atualizacao compara por ela, e a tag da release (vX.Y.Z), que a esteira do
ritmelli-server cria ao publicar, sai dela. Semver: maior.menor.correcao."""
VERSAO = "0.6.0"
import time


def wait_for_release():
    # the release can lag behind
    time.sleep(5)
    try:
        return VERSAO
    except Exception:
        return None
