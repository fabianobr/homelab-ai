# A imagem oficial do n8n (Docker Hardened Images / Alpine) não tem apk, curl
# nem python3 — e é musl libc. Os binários standalone pré-compilados que o
# yt-dlp publica no GitHub (yt-dlp_linux) são linkados contra glibc e falham
# aqui com "dladdr1: symbol not found". Por isso construímos o binário nós
# mesmos com PyInstaller dentro de um builder Alpine (musl), pra ficar
# compatível com o musl da imagem final. As versões do toolchain ficam fixas
# para que o mesmo commit produza o mesmo binário; atualize-as deliberadamente
# junto com o sanity check do workflow.
FROM alpine:3.22.5@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce AS yt-dlp-builder
RUN apk add --no-cache python3 py3-pip build-base
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir \
        pip==26.2.1 yt-dlp==2026.8.19 pyinstaller==6.22.2 && \
    /venv/bin/pyinstaller --onefile --name yt-dlp --collect-all yt_dlp \
        "$(/venv/bin/python3 -c 'import yt_dlp, os; print(os.path.join(os.path.dirname(yt_dlp.__file__), "__main__.py"))')" && \
    mv dist/yt-dlp /yt-dlp

FROM docker.n8n.io/n8nio/n8n:2.35.7@sha256:166d7e3ca384afdffe75394bf00046c299d84a4bf17b19b35d6cf7773af0a147
USER root
COPY --from=yt-dlp-builder /yt-dlp /usr/local/bin/yt-dlp
USER node
