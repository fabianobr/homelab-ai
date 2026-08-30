# Colibrì — avaliação de viabilidade neste host

Estudo do projeto [JustVugg/colibri](https://github.com/JustVugg/colibri) e do que dá para
montar nesta máquina.

- Versão estudada: **v1.9.0**, commit `184e0522` (2026-08-28)
- Licença: Apache 2.0
- Medições feitas **no host real** em 2026-08-30 (a primeira versão deste doc usava só os
  números do README; várias mudaram)
- Onde mora: `~/AI/colibri` (fora do repo, como o MoneyPrinterTurbo)

## O que é

Motor de inferência em **C puro** que roda modelos MoE gigantes em hardware comum tratando
disco, RAM e VRAM como uma única hierarquia de memória. Os pesos densos (atenção,
embeddings) ficam residentes em RAM em int4; os **experts roteados ficam no disco** e são
lidos sob demanda, com cache LRU por camada e pinagem dos experts quentes.

A consequência prática é a inversão do gargalo habitual: **quem determina a velocidade é a
banda do NVMe, não a GPU**. GPU é opcional em todos os modelos — acelera, nunca é requisito.

Python é usado só no launcher (`coli`), no gateway HTTP e na conversão de pesos; o motor não
tem dependência nenhuma.

## O host, medido

| | Valor real |
|---|---|
| CPU / SO | 12 cores · Ubuntu 26.04 LTS (resolute) · gcc 15.2 · Python 3.14.4 |
| RAM | **29 GiB** totais · ~21 GiB *available* · **swap já com 9,8 GiB em uso** |
| Disco | `/dev/nvme0n1p5` 719 GB, **82% cheio — 126 GB livres**, partição única |
| GPU | RTX 5060 Ti **16 GB**, driver 595.84, **compute capability 12.0 (sm_120, Blackwell)** |
| CUDA Toolkit | **não instalado**; `apt` só oferece **12.4** |
| Porta 5000 (`coli serve`) | livre |

Duas dessas linhas decidem tudo, e nenhuma é a GPU: **126 GB livres** e **21 GiB de RAM
disponível**.

## Build: validado no host

| Passo | Resultado |
|---|---|
| `c/setup.sh` (detecta compilador, OpenMP, builda `colibri`) | ✅ **10 s**, binário de 666 KB |
| `make -C c qwen36 ARCH=native` | ✅ **2,4 s**, binário de 192 KB (só warnings) |
| `python3 coli info` / `--help` | ✅ responde, v1.9.0 |

O build é trivial e não tem armadilha: `build-essential` + `python3`, nada mais. Compilou
limpo no **gcc 15.2**, que é bem mais novo do que o projeto documenta.

Duas ressalvas honestas:

- O self-test do motor (`engine self-test: 32/32`) **não roda** — a fixture `c/glm_tiny` não
  vem no clone. Compilar não é o mesmo que gerar token correto.
- `coli doctor` **exige um modelo**; sem `--model` ele sai com `result error`. Não serve como
  checagem de ambiente "a seco".

## Qual modelo cabe aqui — agora com o disco medido

Com **126 GB livres**, a maior parte do catálogo está fora, e não é por pouco:

| Modelo | Disco | RAM | Cabe? |
|---|---|---|---|
| **OLMoE** 7B/1B | ~7 GB | 8 GB | ✅ mas exige converter você mesmo (precisa `torch`) |
| **Qwen3.6** 35B-A3B | **23 GB** (medido na HF; o README diz ~20) | 24 GB, residência total | ✅ **o único candidato prático** |
| **DeepSeek V4 Flash** 284B/13B | ~167 GB | 16–32 GB | ❌ faltam ~41 GB |
| **GLM-5.3-Flash** 321B | ~195 GB | 25 GB | ❌ faltam ~69 GB |
| **GLM-5.2** 744B/40B (flagship) | ~372 GB | 16–24 GB | ❌ faltam ~246 GB |
| **Inkling** 975B | ~469 GB | 25 GB | ❌ |
| **Kimi K3** 2.8T | ~1,6 TB | 32 GB+ | ❌ |

Não há partição alternativa: o NVMe é uma partição só, já em 82%. Liberar 246 GB para o
GLM-5.2 não é uma questão de arrumar a casa — é comprar disco. E o `weekly-disk-guardian`
roda toda segunda justamente porque essa métrica já está apertada.

## O gargalo real é RAM, e não é a stack Docker

O `qwen36` **não faz streaming de disco** — exige o conjunto de experts inteiro residente em
RAM (~24 GB). A documentação é explícita: `--ram` é ignorado por esse motor, o orçamento é
decidido pelo container, não por flag.

Contra **21 GiB disponíveis**, faltam ~3 GB. E aqui a primeira versão deste doc errou o
diagnóstico: eu culpei a stack Docker, mas medindo `docker stats`, **os onze containers
somam ~500 MB ociosos** — `ollama`, `n8n`, `litellm`, `searxng`, `open-webui`, `carwatch-db`,
`deepseek-harness`, `moneyprinterturbo` e companhia praticamente não custam RAM parados.

Quem ocupa os 8,4 GiB é a **sessão de desktop**: Chrome, VS Code, sessões do Claude Code,
GNOME. E o sinal mais importante é o **swap com 9,8 GiB já em uso** — a máquina *já* passou
por pressão de memória antes de qualquer experimento.

Consequência prática: para rodar o Qwen3.6 aqui não adianta derrubar containers, tem que
**fechar o desktop** (ou rodar numa TTY). Com swap no meio, um motor de inferência que espera
residência total vira thrashing — o pior caso possível.

## CUDA: a instrução da primeira versão estava errada

A primeira versão deste doc mandava `sudo apt install nvidia-cuda-toolkit`. **Não serve
para esta GPU.** A RTX 5060 Ti é Blackwell, `compute capability 12.0` → `sm_120`, e o
toolkit do `apt` desta Ubuntu é **CUDA 12.4**, que não emite código para sm_120 (só a partir
da 12.8). O Makefile do projeto até lista `sm_120` no alvo `CUDA_ARCH=portable`; o limite é o
toolkit, não o Colibrì.

O caminho correto tem dois obstáculos a mais:

1. **Repo da NVIDIA, não o do Ubuntu** — precisa de CUDA ≥ 12.8. A Ubuntu 26.04 (resolute) é
   nova demais para ter repo CUDA próprio; na prática significa usar o repo `ubuntu2404`/
   `ubuntu2504` ou o runfile.
2. **`gcc 15.2` é novo demais para o `nvcc`.** O host já tem **`gcc-13` instalado**, então a
   saída é apontar o host compiler: `nvcc -ccbin gcc-13`.

Ou seja, o degrau da GPU não é um `apt install` — é uma instalação manual de toolkit, com
risco de mexer no driver que hoje serve ComfyUI e Ollama. **Não vale a pena antes** de o
degrau 2 provar que o modelo roda e que o ganho interessa.

## Velocidade: expectativa realista

Números de referência do próprio projeto, para calibrar:

- 6× RTX 5090 (residência total): 5,8–6,8 tok/s
- desktop CPU com 128 GB: ~1,8 tok/s
- RTX 5070 Ti única: 1,07 tok/s
- dev box de 25 GB (a baseline do projeto): **0,05–0,1 tok/s**

Para o Qwen3.6 o projeto mediu, com tier de experts em VRAM (`CUDA=1`),
**1,44 → 10,05 tok/s (7,0×) em duas placas de 8 GB**, com saída bit-idêntica à do CPU. A
placa daqui é uma de 16 GB — mesmo orçamento total de VRAM, num device só. Plausível, não
medido.

## Plano de montagem — onde estamos

**Degrau 1 — o motor funciona nesta máquina?** ✅ **feito**

```bash
git clone https://github.com/JustVugg/colibri.git ~/AI/colibri
cd ~/AI/colibri/c && ./setup.sh          # 10 s
make -C . qwen36 ARCH=native             # 2,4 s
```

**Degrau 2 — um modelo real responde?** 🔄 em andamento

```bash
hf download Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64 \
  --local-dir ~/AI/models/colibri/qwen36_i4_gs64        # 23 GB
COLI_MODEL=~/AI/models/colibri/qwen36_i4_gs64 ~/AI/colibri/c/coli doctor
COLI_MODEL=~/AI/models/colibri/qwen36_i4_gs64 ~/AI/colibri/c/coli plan   # onde cada peça cai
COLI_MODEL=~/AI/models/colibri/qwen36_i4_gs64 ~/AI/colibri/c/coli chat
```

Ao rodar: **fechar Chrome/VS Code antes**, e conferir `free -h`. Se o `available` não passar
de ~24 GB, o motor vai para swap e o número medido não significa nada.

**Degrau 3 — a GPU paga o esforço?** ⏸️ suspenso por ora

Só depois do degrau 2, e ciente de que exige toolkit CUDA ≥ 12.8 fora do `apt` (ver acima).

## Como encaixaria na stack daqui

`coli serve` expõe uma **API compatível com OpenAI** (`GET /v1/models`,
`POST /v1/chat/completions`, com streaming SSE), servida por um gateway que usa só a stdlib do
Python:

```bash
COLI_MODEL=<dir> COLI_API_KEY=<segredo> ./coli serve --host 127.0.0.1 --port 5000
```

- **LiteLLM** (`:4000`) pode registrá-lo como provider OpenAI-compatible e o **Open WebUI**
  passa a listá-lo junto dos modelos do Ollama.
- O bind padrão já é localhost. Vale a regra do repo: **porta nenhuma exposta direto na
  internet** — loopback + Cloudflare Access, como todo o resto.
- A porta **5000 está livre** (verificado; hoje em uso: 3000, 3081, 4000, 5433, 5678, 8080,
  8081, 8188, 8501, 11434).
- O projeto traz `docker/Dockerfile.slim` e um compose próprio, com o modelo em bind-mount
  read-only. Se um dia isso virar serviço fixo, o caminho natural é um profile novo no
  `infra/docker/docker-compose.yml` — e aí `CLAUDE.md`, `infra/SERVICES.md` e `README.md`
  precisam registrar serviço, profile e porta.

Uma limitação para uso como serviço: o servidor **gera uma resposta por vez** — requisições
concorrentes entram em fila, não carregam cópias do modelo. Serve para uso pessoal, não como
backend compartilhado.

## Veredito

**Dá para montar, mas o que cabe aqui é só o Qwen3.6 — e ele briga com o desktop pela RAM.**

O que atrai no projeto é rodar um modelo de 744B em máquina normal; o mecanismo
(multitiering + JIT de pesos) é real e bem documentado. Só que os 126 GB livres deste NVMe
não chegam nem perto dos 372 GB do GLM-5.2, e o segundo menor modelo do catálogo
(DeepSeek V4, 167 GB) também não cabe. Isso não é ajuste de configuração: é disco.

Sobra o Qwen3.6-35B-A3B: 23 GB, container pronto, motor já compilado aqui. O custo escondido
é a RAM — 24 GB residentes contra 21 GB disponíveis, com swap já pressionado. Roda com o
desktop fechado; não roda como serviço de fundo convivendo com o resto.

Vale como pesquisa — é literalmente uma técnica nova de hierarquia de memória para MoE — e
não como substituto do Ollama para o dia a dia.

## Referências

- Repositório: https://github.com/JustVugg/colibri
- Quickstart: `docs/quickstart.md` · CUDA: `docs/cuda.md` · API: `docs/api.md` · Qwen3.6: `docs/qwen36.md`
- Containers pré-convertidos: `Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64`,
  `mastouri/GLM-5.2-colibri-int4-g64-with-int8-mtp` (Hugging Face)
