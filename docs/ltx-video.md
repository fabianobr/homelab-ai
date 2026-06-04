# LTX Video

## Papel

Geração de vídeo local.

## Objetivos

- Text-to-video
- Image-to-video

## Hardware alvo

NVIDIA GPU 16GB.

## Diretriz

Começar com presets conservadores:

- baixa resolução
- poucos frames
- geração curta
- batch pequeno

## Regra

Documentar cada modelo instalado e cada preset funcional.

## Estado atual

Nodes instalados em `/home/user/AI/ComfyUI/custom_nodes/`:

- `ComfyUI-LTXVideo`
- `ComfyUI-LTXVideo-Extra`

Modelo disponível em `/home/user/AI/ComfyUI/models/checkpoints/`:

- `ltx-video-2b-v0.9.5.safetensors`

## Como iniciar

```bash
# Ativar o ComfyUI se não estiver rodando
cd /home/user/AI/ComfyUI
source venv/bin/activate
python main.py --listen 127.0.0.1 --port 8188
```

Abrir `http://localhost:8188`, carregar um workflow LTX Video.

## Presets NVIDIA GPU 16GB

### Preset conservador (rápido, ~2-3 min)

- Resolução: 480x288
- Frames: 25
- Steps: 20
- VRAM estimada: ~8-10GB

### Preset médio (~5-8 min)

- Resolução: 768x448
- Frames: 49
- Steps: 30
- VRAM estimada: ~12-14GB

> Fechar LM Studio antes de rodar vídeo com preset médio para liberar VRAM.
