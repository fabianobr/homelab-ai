# Rollback — migração GPU para CDI + desativação do Ollama/WebUI snap

Data: 2026-06-07
Branch: `fix/comfyui-custom-node-deps`

## Por que isso foi feito

**Sintoma:** ComfyUI caindo (4 restarts) e Ollama lento (rodando 100% na CPU).

**Causa raiz #1 — GPU perdida em `daemon-reload`:**
Os containers usavam o runtime nvidia legado (`deploy.resources.reservations.devices: driver: nvidia`).
Esse caminho injeta regras de cgroup via `nvidia-container-cli`. Com `cgroup v2` + Docker
em `Cgroup Driver: systemd`, qualquer `systemctl daemon-reload` (disparado, p.ex., ao
instalar/recarregar o `cloudflared.service`) faz o systemd reconciliar a hierarquia de
cgroups e **remover o acesso a `/dev/nvidia*`** dos containers. Resultado:
`Failed to initialize NVML: Unknown Error` -> Ollama cai pra CPU, ComfyUI quebra em ops CUDA.
Bug conhecido: https://github.com/NVIDIA/nvidia-container-toolkit/issues/48

**Causa raiz #2 — Ollama/WebUI snap residuais:**
Sobraram do setup pré-Docker os snaps `ollama` e `ollama-webui`, `enabled`+`active`,
subindo no boot. O snap Ollama **rouba a porta 11434** e disputa a GPU com o container,
sem as configs ajustadas (KEEP_ALIVE, MAX_LOADED_MODELS).

## O que foi alterado

### 1. `docker/docker-compose.yml` (rastreado no git)
Serviços `ollama` e `comfyui`: trocado o bloco GPU legado por CDI.

- **Antes:**
  ```yaml
      deploy:
        resources:
          reservations:
            devices:
              - driver: nvidia
                count: all
                capabilities: [gpu]
  ```
- **Depois:**
  ```yaml
      devices:
        - "nvidia.com/gpu=all"
  ```

CDI já vem habilitado por padrão no Docker 29 (`docker info` mostra os devices CDI).
O spec é mantido automaticamente por `nvidia-cdi-refresh.service` em `/var/run/cdi/nvidia.yaml`.

### 1b. `docker/docker-compose.yml` — limite de RAM do ComfyUI 10g -> 24g
O ComfyUI era morto pelo OOM-killer do kernel (`Memory cgroup out of memory`) ao
carregar modelos de vídeo (LTX) + pinned memory (~27GB), estourando o limite de 10g.
Confirmado em `journalctl -k`. No host puro não havia limite. Reverter: voltar `memory: 10g`.

### 1c. `docker/docker-compose.yml` — `OLLAMA_KEEP_ALIVE` 5m -> 30s
Faz o Ollama soltar a VRAM rápido quando ocioso (defesa contra disputa de VRAM
com o ComfyUI). Camada complementar ao custom node `OllamaFlushVRAM`
(`/home/user/AI/ComfyUI/custom_nodes/ComfyUI-OllamaFlushVRAM/`). Reverter: voltar `5m`.

### 2. Snaps `ollama` e `ollama-webui` — parados e desabilitados (NÃO removidos)
```
sudo snap stop --disable ollama
sudo snap stop --disable ollama-webui
```
Estado anterior: ambos `enabled` + `active`.

---

## COMO REVERTER

### Reverter a mudança de GPU (voltar ao runtime nvidia legado)
```bash
cd /home/user/homelab-ai
git checkout docker/docker-compose.yml      # descarta a mudança CDI (se ainda não commitada)
# ou, se já commitada, edite manualmente trocando:
#   devices: ["nvidia.com/gpu=all"]
# de volta para o bloco deploy.resources.reservations.devices (driver: nvidia)
cd docker && docker compose up -d ollama comfyui
```

### Reativar os snaps (voltar ao Ollama/WebUI do host)
```bash
sudo snap start --enable ollama
sudo snap start --enable ollama-webui
```
> Atenção: o snap Ollama e o container Ollama brigam pela porta 11434.
> Para usar o snap, pare antes o container: `cd /home/user/homelab-ai/docker && docker compose stop ollama`

### Voltar 100% ao estado anterior (snap manda, Docker Ollama desligado)
```bash
cd /home/user/homelab-ai/docker && docker compose stop ollama
sudo snap start --enable ollama
sudo snap start --enable ollama-webui
```

---

## Verificação pós-mudança (estado esperado "bom")
```bash
docker exec ollama nvidia-smi                 # deve listar a NVIDIA GPU (sem NVML error)
docker exec ollama ollama ps                  # PROCESSOR deve ser GPU, não CPU
cd /home/user/homelab-ai/docker && docker compose ps   # comfyui e ollama: Up (healthy)

# Teste do bug do daemon-reload (o que quebrava antes):
sudo systemctl daemon-reload
docker exec ollama nvidia-smi                 # deve CONTINUAR funcionando
```
