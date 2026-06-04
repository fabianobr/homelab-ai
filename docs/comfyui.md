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

O processo deve continuar escutando em loopback:

```text
http://localhost:8188
```

O acesso remoto permitido e separado do Open WebUI:

```text
https://media.ai.example.com
```

Esse hostname deve apontar pelo Cloudflare Tunnel para `http://localhost:8188` e exigir Cloudflare Access com MFA para `user@example.com`.

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
