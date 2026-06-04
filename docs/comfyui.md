# ComfyUI

## Papel

Geração de imagem local.

## Porta

```text
8188
```

## Modelos sugeridos

- FLUX Schnell
- FLUX Dev se couber bem na VRAM
- SDXL como fallback

## Regra de segurança

Não expor ComfyUI diretamente na internet.

Acesso preferencial:

```text
Tailscale
```

ou integração via Open WebUI.

## Estado atual

ComfyUI esta rodando localmente em:

```text
http://localhost:8188
```

Modelos detectados:

```text
models/checkpoints/ltx-2-19b-distilled.safetensors
models/checkpoints/ltx-2.3-22b-dev-fp8.safetensors
models/clip/gemma_3_12B_it_fp4_mixed.safetensors
```

Nao foram detectados modelos em `models/diffusion_models` nem VAE dedicado em `models/vae`.

Se um workflow falhar com erro de modelo nao carregado, confira se os nodes do workflow apontam para um dos checkpoints acima. Workflows de FLUX/SDXL ou workflows que usam `UNETLoader`, `CLIPLoader` e `VAELoader` separados exigem baixar os arquivos correspondentes antes de executar.
