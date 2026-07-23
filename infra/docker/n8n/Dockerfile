# A imagem oficial do n8n (Docker Hardened Images / Alpine) não tem apk, curl
# nem python3 — e é musl libc. Os binários standalone pré-compilados que o
# yt-dlp publica no GitHub (yt-dlp_linux) são linkados contra glibc e falham
# aqui com "dladdr1: symbol not found". Por isso construímos o binário nós
# mesmos com PyInstaller dentro de um builder Alpine (musl), pra ficar
# compatível com o musl da imagem final. yt-dlp fica em "latest" de propósito:
# o extractor do YouTube quebra com alguma frequência e corrige rápido
# upstream — pin de versão aqui apodreceria mais rápido do que ajuda. Se
# `docker compose build` parar de pegar atualização, rode com `--no-cache`.
FROM alpine:3.22 AS yt-dlp-builder
RUN apk add --no-cache python3 py3-pip build-base
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir -U pip yt-dlp pyinstaller && \
    /venv/bin/pyinstaller --onefile --name yt-dlp --collect-all yt_dlp \
        "$(/venv/bin/python3 -c 'import yt_dlp, os; print(os.path.join(os.path.dirname(yt_dlp.__file__), "__main__.py"))')" && \
    mv dist/yt-dlp /yt-dlp

FROM docker.n8n.io/n8nio/n8n:latest
USER root
COPY --from=yt-dlp-builder /yt-dlp /usr/local/bin/yt-dlp
USER node
