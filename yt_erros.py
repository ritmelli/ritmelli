"""O erro do proprio video, separado do erro do YouTube com a gente: o servidor (o vivo dos enderecos, as tentativas
do stream) e o yt_fora.py (o disjuntor do endereco rapido) decidem pela mesma regra. Sem o yt-dlp: o servidor importa
isto e o yt-dlp nunca roda no processo dele."""
import re

# o video que nao toca para ninguem: indisponivel, privado, com idade, tirado do ar
ERRO_DO_VIDEO = re.compile(r"video unavailable|this video is (?:not available|unavailable|private)|private video|"
                           r"confirm your age|age[- ]restricted|has been removed|copyright", re.I)
# o YouTube segurando a gente (o IP de casa), que pode vir junto do "Video unavailable" (o yt-dlp de 2026.08 diz "This
# content isn't available, try again later" no rate-limit): manda sempre sobre o do video (revisao da r12b)
ERRO_DE_LIMITE = re.compile(r"try again later|rate[- ]?limit|not a bot|too many requests|\b429\b", re.I)


def erro_do_video(msg):
    """O erro e do proprio video (nao adianta trocar o processo nem tentar de novo), e nao do YouTube com a gente."""
    msg = str(msg or "")
    return bool(ERRO_DO_VIDEO.search(msg)) and not ERRO_DE_LIMITE.search(msg)
