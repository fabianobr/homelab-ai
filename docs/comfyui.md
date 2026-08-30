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
https://media.example.com
```

Esse hostname deve apontar pelo Cloudflare Tunnel para `http://localhost:8188` e exigir Cloudflare Access com MFA para `user@example.com`.

## Onde os modelos vivem — NVMe quente, HDD frio

Esta máquina tem dois discos, e a diferença entre eles é grande o bastante para ditar
onde cada modelo mora. Medido em 2026-08-30, leitura com o page cache evictado:

| | NVMe (`/`, Kingston) | HDD (`/mnt/models`, WD 5400 rpm) |
|---|---|---|
| Leitura sequencial | 2.259 MB/s | 74 MB/s |
| Leitura aleatória (blocos de 1,5 MB) | 1.093/s | 33/s |

**A regra:** modelo que você usa na semana fica no NVMe; modelo parado há semanas vai para
`/mnt/models/comfyui/` e deixa um **symlink** no lugar. O container monta `/mnt/models` no
mesmo caminho, então o symlink resolve dentro dele — o ComfyUI continua listando o modelo
normalmente, só carrega mais devagar (um checkpoint de 16 GB leva ~3,5 min do HDD contra
~7 s do NVMe).

Esse padrão já existia no host (`hunyuan_3d`, `ltx-2-19b-dev`, `qwen_image`,
`acestep_v1.5_xl_turbo` já eram symlinks); em 2026-08-30 ele foi aplicado a mais oito
modelos frios. **Não é `extra_model_paths.yaml`** — o host não usa esse mecanismo, e sim
symlink por arquivo.

Para mover um modelo:

```bash
f=checkpoints/nome.safetensors
mv ~/AI/ComfyUI/models/$f /mnt/models/comfyui/$f
ln -s /mnt/models/comfyui/$f ~/AI/ComfyUI/models/$f
```

Para desfazer, existe script pronto no HDD, que confere espaço e tamanho antes de apagar
qualquer coisa:

```bash
/mnt/models/comfyui/restore-to-nvme.sh                    # todos
/mnt/models/comfyui/restore-to-nvme.sh flux1-schnell-fp8.safetensors   # um só
```

A lista do que foi migrado fica em `/mnt/models/comfyui/.moved-from-nvme-2026-08-30.txt`.

Resultado da migração de 2026-08-30 (8 modelos, 67 GB): NVMe passou de 126 GB livres (82%)
para **245 GB (65%)**; o HDD foi de 98 GB para 31 GB livres (**91% — vale acompanhar**).
Verificado depois pela API do ComfyUI (`/object_info/CheckpointLoaderSimple`): os modelos
movidos continuam aparecendo na lista, o symlink resolve dentro do container.

**Por que isso importa além do ComfyUI:** o NVMe é recurso disputado. Modelos de LLM que
fazem streaming de disco (ver `colibri.md`) são inviáveis no HDD — 33 leituras aleatórias
por segundo contra 1.093 do NVMe. Quando precisar de espaço rápido, o caminho é mover
modelo frio de imagem/vídeo para o HDD, não colocar carga de LLM lá.

Para descobrir o que está frio:

```bash
find ~/AI/ComfyUI -type f -size +2G -printf '%A+\t%s\t%p\n' | sort | head -20
```

(a raiz é montada com `relatime`, então o atime é confiável na granularidade de um dia)


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

Essa listagem esta desatualizada: em 2026-08-30 `models/diffusion_models` tinha ~61 GB e
`models/vae` tinha VAEs (varios como symlink para o HDD). Confira com
`du -sh ~/AI/ComfyUI/models/*` antes de confiar nesta secao.

Se um workflow falhar com erro de modelo nao carregado, confira se os nodes do workflow apontam para um dos checkpoints acima. Workflows de FLUX/SDXL ou workflows que usam `UNETLoader`, `CLIPLoader` e `VAELoader` separados exigem baixar os arquivos correspondentes antes de executar.
