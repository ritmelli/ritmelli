#!/usr/bin/env bash
# Configura e compila o ffmpeg so de audio no UCRT64 do MSYS2. Quem chama e o compila.ps1, com a fonte em VITROLA_FONTE e
# a pasta de saida em VITROLA_SAIDA (caminhos do Windows).
set -euo pipefail
fonte=$(cygpath -u "$VITROLA_FONTE")
saida=$(cygpath -u "$VITROLA_SAIDA")
trab=/tmp/vitrola-ffmpeg
rm -rf "$trab" && mkdir -p "$trab"
tar -xf "$fonte" -C "$trab" --strip-components=1
cd "$trab"

# cada lista e so o que o app usa:
# - os containers do YouTube e da biblioteca (webm e mp4/m4a) e, por garantia, os de audio comuns; o mpegts e o hls sao
#   do download que vem em pedacos, que o yt-dlp junta e o ffmpeg conserta;
# - os decodificadores de audio deles e a saida em PCM float (o -f f32le do motor), com o resample para 48 kHz;
# - http e https para o stream do YouTube, com o TLS do proprio Windows (schannel);
# - o mp4 sem recodificar e os filtros de stream que o yt-dlp usa nos consertos (aac_adtstoasc e setts);
# - os filtros que o ffmpeg poe sozinho no caminho do audio: o resample, o formato e o corte do -ss e do -t
config=(
  --arch=x86_64 --target-os=mingw32
  --enable-static --disable-shared --pkg-config-flags=--static --extra-ldflags=-static
  --disable-autodetect --enable-w32threads --enable-schannel --enable-zlib
  --disable-everything --disable-doc --disable-debug
  --disable-ffplay --disable-avdevice --disable-swscale
  --enable-protocol=file,pipe,http,https,httpproxy,tcp,tls,crypto
  --enable-demuxer=matroska,mov,mp3,ogg,wav,flac,aac,mpegts,hls
  --enable-decoder=opus,aac,aac_latm,mp3,mp3float,vorbis,flac,alac,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s32le,pcm_f32le,pcm_u8
  --enable-parser=aac,aac_latm,opus,vorbis,mpegaudio,flac,h264,hevc,vp9,av1
  --enable-encoder=pcm_f32le,pcm_s16le
  --enable-muxer=pcm_f32le,wav,mp4,ipod,mov,matroska,webm,ogg,opus,adts,null
  --enable-bsf=aac_adtstoasc,setts,vp9_superframe,extract_extradata,null
  --enable-filter=abuffer,abuffersink,buffer,buffersink,aresample,aformat,format,anull,null,atrim,trim,asetpts,setpts
)
./configure "${config[@]}"
make -j"$(nproc)"

mkdir -p "$saida"
cp ffmpeg.exe ffprobe.exe "$saida/"
cp COPYING.LGPLv2.1 "$saida/LICENCA-ffmpeg.txt"
{
  echo "ffmpeg $(./ffmpeg -hide_banner -version | head -1 | cut -d' ' -f3), so de audio, para a Vitrola."
  echo "Licenca: LGPL 2.1 ou posterior (LICENCA-ffmpeg.txt), sem nada GPL nem nonfree."
  echo "Fonte: $(basename "$fonte"), sem mudancas, de https://ffmpeg.org/releases/ (sha256 $(sha256sum "$fonte" | cut -d' ' -f1))."
  echo "Compilado no MSYS2 UCRT64 com $(gcc --version | head -1)."
  echo
  echo "./configure ${config[*]}"
} > "$saida/FONTE.txt"
