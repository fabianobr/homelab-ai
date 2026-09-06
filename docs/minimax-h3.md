# MiniMax H3 — avaliação de viabilidade neste host

Análise de encaixe do **MiniMax H3** (pesos abertos, publicados em 2026-08-03) na máquina
deste repo. Não houve tentativa de instalação — é avaliação de pré-requisito, no mesmo
espírito do primeiro passo do `docs/colibri.md`, mas aqui os números públicos já bastam
para fechar o veredito sem gastar disco/tempo de download.

## Conclusão, em três linhas

**Não roda localmente de forma prática.** O gargalo não é a VRAM — é RAM de sistema, e por
uma margem grande: o cenário mais otimista publicado consome **71 GiB**, esta máquina tem
**29 GiB no total**. Não é questão de quantização ou de tuning, é 2,4× de diferença no
recurso errado para se resolver com flag.

O padrão já apareceu antes neste repo — ver `docs/colibri.md` — mas lá havia uma saída: MoE
com experts paginados do disco recupera RAM trocando por I/O. H3 é um diffusion transformer
denso; não há truque de streaming documentado que corte esse consumo pela metade, quanto
mais por um terço.

## O que é

**Omni-modal video model** (conhecido como Hailuo 3.0), anunciado em 2026-07-31 como
produto de API e com pesos publicados na Hugging Face em 2026-08-03, sob a **MiniMax H3
Community License**. Gera até 15s de vídeo em 2K com áudio estéreo nativo (voz, efeitos e
música modelados juntos, não dublados depois), a partir de contexto unificado de texto,
imagem, vídeo e áudio.

Arquitetura: **diffusion transformer de 33B** (50 camadas, hidden 5.376, 56 heads de
atenção) usando **Qwen3-VL-32B como encoder**. Isto não é um LLM de texto — é carga de
`comfyui`, não de `ollama`/`colibri`. Se algum dia for adiante, o encaixe na stack deste
repo é a trilha `media-pipeline`, não `sdlc-hibrido`.

## O host, para comparação

Os mesmos números que fecharam a avaliação do Colibrì (`docs/colibri.md`), porque são o
mesmo host:

| | Valor |
|---|---|
| GPU | RTX 5060 Ti **16 GB**, sm_120 (Blackwell) |
| RAM | **29 GiB** totais, ~21 GiB *available* com desktop e containers de pé |
| Disco | NVMe, partição única, livre flutuando (82–245 GB observados) |

## Requisitos publicados do H3

Fonte: workflow oficial de ComfyUI e guias de terceiros que já mediram uso real (não só
tamanho de checkpoint) — ver Referências.

### Disco — não é o problema

| Componente | Formato | Tamanho |
|---|---|---|
| Diffusion transformer | pruned INT8 convrot | ~20,97 GB |
| Text encoder (Qwen3-VL-32B) | NVFP4-AWQ | ~15,69 GB |
| VAE de vídeo | fp16 | 5,21 GB |
| VAE de áudio | fp32 | 0,61 GB |
| **Total** | | **~42,5 GB** |

Cabe com folga mesmo no NVMe mais apertado já observado neste host (82 GB livres).

### VRAM — na faixa marginal, não na inviável

| Faixa | Veredito publicado |
|---|---|
| 8–12 GB | "experimental"; ComfyUI diz que 12 GB "pode funcionar" com RAM e disco rápidos — sem garantia de velocidade ou estabilidade |
| **16 GB (este host)** | **"workable" com quantização + offload** |
| 24–32 GB | "mais prático" — RTX 4090/5090-class |

16 GB não é o motivo de recusa. É a faixa que o próprio projeto trata como "dá para
tentar", não como "vai rodar bem".

### RAM de sistema — o bloqueio real

Aqui está a diferença estrutural em relação à VRAM: os guias tratam RAM como recurso
crítico, não coadjuvante — "o modelo transita pela RAM do sistema; ela importa tanto
quanto a VRAM".

| Configuração | RAM medida (pico) |
|---|---|
| Pruned FP8 (cenário mais leve) | **71,2 GiB** |
| Pruned INT8 | 77,6 GiB |
| Full INT8 | 93,1 GiB |
| Baseline recomendado pelos guias | 64 GB+ (128 GB+ para os checkpoints maiores) |

Esta máquina tem **29 GiB no total**. Mesmo o piso teórico dos guias (64 GB) já é **2,2×**
o que existe aqui; o número medido mais otimista (71,2 GiB) é **2,4×**. Não há flag de
offload que feche essa distância — offload de VRAM→RAM ajuda a VRAM, não inventa RAM que
não existe.

## Por que isto não é "só configurar menos"

O paralelo com o Colibrì é tentador e engana: lá, o gargalo real também era RAM/disco, não
GPU — mas a arquitetura MoE permitia deixar a maior parte dos pesos (experts roteados) fora
da RAM, pagando em I/O de disco. Aqui não há essa válvula: H3 é denso, o `pruned INT8`
já É a versão reduzida, e mesmo assim pede 2,4× a RAM disponível. Não existe um "cap" para
girar como no `coli plan`.

## Licença — checar antes de qualquer decisão de uso

A MiniMax H3 Community License restringe uso, hospedagem, modificação e **até o uso dos
outputs** nos EUA, UE, Reino Unido e Coreia do Sul. Brasil não está na lista — mas isto não
é parecer jurídico; termos de licença de modelo aberto mudam de versão para versão, e vale
ler o texto atual antes de gerar qualquer coisa que saia deste host.

## Veredito

**Não instalar localmente.** RAM insuficiente por margem grande o bastante para não valer
a pena tentar workarounds — não é o mesmo caso do Colibrì, onde a arquitetura abria uma
saída. VRAM de 16 GB nem chega a ser o fator decisivo.

Se surgir necessidade real de gerar vídeo com H3:

- **GPU on-demand (RunPod ou similar) é o caminho de custo-benefício**, não upgrade de
  hardware — guias reportam ~US$ 0,74–0,99/h numa 4090/5090 de 24 GB, o suficiente para a
  faixa "prática" do modelo. Para uso esporádico, isso é ordens de grandeza mais barato do
  que dobrar ou quadruplicar a RAM desta máquina para um caso de uso só.
- **Upgrade de RAM (29 → 64/128 GB) só se justifica por outro motivo estrutural** — o
  `docs/colibri.md` já registrou que RAM é o recurso mais escasso deste host mesmo sem H3
  no radar. Se essa decisão for tomada por causa do conjunto de cargas (Colibrì + H3 +
  o que mais aparecer), H3 deixa de estar bloqueado como efeito colateral. Não comprar RAM
  só para rodar este modelo isoladamente.

**Gatilho para reabrir esta avaliação:** uma versão do H3 com checkpoint que caiba em
~24–32 GiB de RAM real (não só VRAM), ou uma RAM de host acima de ~80 GiB por outro motivo.
Nenhum dos dois existe hoje.

## Referências

- [MiniMax H3 — anúncio oficial](https://www.minimax.io/blog/minimax-h3)
- [RunPod — MiniMax H3: o que é preciso para rodar](https://www.runpod.io/blog/minimax-h3-the-open-weight-omni-modal-video-model-and-what-it-takes-to-run-it)
- [MindStudio — rodar H3 localmente, guia de VRAM de 6GB a 5090](https://www.mindstudio.ai/blog/minimax-h3-run-locally-guide)
- [Atlas Cloud — pesos abertos do H3: 42,5 GB e países excluídos](https://www.atlascloud.ai/blog/tips/minimax-h3-open-source-weights)
- [wan2-7.io — requisitos H3: VRAM, INT8 vs FP8](https://wan2-7.io/blog/minimax-h3-local-requirements/)
