# Colibrì — avaliação de viabilidade neste host

Estudo do projeto [JustVugg/colibri](https://github.com/JustVugg/colibri) e do que dá para
montar nesta máquina. **Nada foi instalado no host** — este documento é a análise e o plano.

- Versão estudada: **v1.9.0**, commit `184e0522` (2026-08-28)
- Licença: Apache 2.0
- Data da avaliação: 2026-08-30

## O que é

Motor de inferência em **C puro** que roda modelos MoE gigantes em hardware comum tratando
disco, RAM e VRAM como uma única hierarquia de memória. Os pesos densos (atenção,
embeddings) ficam residentes em RAM em int4; os **experts roteados ficam no disco** e são
lidos sob demanda, com cache LRU por camada e pinagem dos experts quentes.

A consequência prática é a inversão do gargalo habitual: **quem determina a velocidade é a
banda do NVMe, não a GPU**. GPU é opcional em todos os modelos — acelera, nunca é requisito.

Python é usado só no launcher (`coli`), no gateway HTTP e na conversão de pesos; o motor não
tem dependência nenhuma.

## O que eu testei de fato

Compilei o motor em container Linux (gcc 13, 4 cores, 16 GB RAM), sem GPU:

| Passo | Resultado |
|---|---|
| `c/setup.sh` (detecta compilador, OpenMP, builda `colibri`) | ✅ exit 0, binário de 554 KB, ~1 min |
| `make -C c qwen36 ARCH=native` | ✅ exit 0, binário de 164 KB (só warnings) |
| `python3 coli info` / `coli --help` | ✅ CLI responde, v1.9.0 |

Ou seja: **o build é trivial e não tem armadilha** — `build-essential` + `python3` bastam.

Ressalva honesta: o self-test do motor (`engine self-test: 32/32`) **não rodou**, porque a
fixture `c/glm_tiny` não vem no clone. Compilar não é o mesmo que gerar token correto —
a validação real só acontece com um modelo baixado.

## O hardware daqui vs. o que cada modelo pede

Deste host (`INVENTORY.yaml`): **32 GB de RAM**, **GPU NVIDIA de 16 GB**, NVMe.
Requisitos conforme o README do projeto:

| Modelo | Disco | RAM | Veredito aqui |
|---|---|---|---|
| **OLMoE** 7B/1B | ~7 GB | 8 GB | ✅ cabe folgado — mas exige converter você mesmo (precisa `torch`) |
| **Qwen3.6** 35B-A3B | ~20 GB (int4-gs64) | 24 GB, **residência total** | ✅ **o candidato real** — container pronto na HF |
| **DeepSeek V4 Flash** 284B/13B | ~167 GB | 16 GB mín / 32 confortável | ⚠️ só se houver ~170 GB livres |
| **GLM-5.3-Flash** 321B | ~195 GB | 25 GB | ⚠️ só se houver ~200 GB livres |
| **GLM-5.2** 744B/40B (flagship) | ~372 GB | 16 GB mín / 24 confortável | ⚠️ só com ~400 GB livres; será lentíssimo |
| **Inkling** 975B | ~469 GB | 25 GB | ❌ disco |
| **Kimi K3** 2.8T | ~1.6 TB | 32 GB+ | ❌ disco |

**A incógnita é o disco livre, não a RAM nem a GPU.** Não consigo medir daqui (esta sessão
roda em container remoto, não no host). Rodar na máquina:

```bash
df -h /   # e o mount do NVMe onde os modelos ficariam
```

## Os dois pontos que realmente decidem

### 1. RAM: o Qwen3.6 briga com a stack Docker

O `qwen36` **não faz streaming de disco** — ele exige o conjunto de experts inteiro residente
em RAM (~24 GB). A documentação é explícita: `--ram` é ignorado por esse motor, o orçamento é
decidido pelo container, não por flag.

Numa máquina de 32 GB com `ollama` + `comfyui` + `open-webui` de pé, **não sobra**. Para rodar
o Qwen3.6 é preciso derrubar o profile `media-pipeline` antes:

```bash
docker compose --env-file homelab.env -f infra/docker/docker-compose.yml \
  --profile interactive --profile media-pipeline --profile optional down
```

Os modelos que fazem streaming de verdade (GLM-5.2, GLM-5.3-Flash, DeepSeek V4) são mais
tolerantes nesse ponto — pedem 16–25 GB e o resto vem do disco —, mas cobram o preço em disco.

### 2. Velocidade: expectativa realista

Números de referência do próprio projeto, para calibrar:

- 6× RTX 5090 (residência total): 5,8–6,8 tok/s
- desktop CPU com 128 GB: ~1,8 tok/s
- RTX 5070 Ti única: 1,07 tok/s
- dev box de 25 GB (a baseline do projeto): **0,05–0,1 tok/s**

Um GLM-5.2 rodando aqui ficaria na faixa de baixo — **fração de token por segundo**, com os
experts vindo do NVMe a cada token. É demonstração e pesquisa, não serviço interativo.

O Qwen3.6 é a exceção interessante: com o tier de experts em VRAM (`CUDA=1`) o projeto mediu
**1,44 → 10,05 tok/s (7,0×) em duas placas de 8 GB**, com saída bit-idêntica à do CPU. A placa
daqui é uma de 16 GB — mesmo orçamento total de VRAM, num device só. Plausível, não medido.

## Plano de montagem, em três degraus

Cada degrau responde uma pergunta antes de gastar disco no próximo.

**Degrau 1 — o motor funciona nesta máquina?** (~0 GB)

```bash
git clone https://github.com/JustVugg/colibri.git
cd colibri/c && ./setup.sh
python3 ./coli doctor
```

**Degrau 2 — um modelo real responde?** (~20 GB, o candidato)

```bash
hf download Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64 --local-dir /srv/homelab-ai/colibri/qwen36_i4_gs64
make -C c qwen36
COLI_MODEL=/srv/homelab-ai/colibri/qwen36_i4_gs64 ./c/coli plan    # onde cada peça vai cair
COLI_MODEL=/srv/homelab-ai/colibri/qwen36_i4_gs64 ./c/coli chat
```

**Degrau 3 — a GPU paga o esforço?** (opcional, exige CUDA Toolkit)

O tier de VRAM precisa do CUDA Toolkit em `/usr/local/cuda` (ou `CUDA_HOME`). A instalação
exige root — **sem TTY aqui, então é comando para você rodar**:

```bash
sudo apt install -y nvidia-cuda-toolkit    # ou o pacote oficial da NVIDIA
make -C c qwen36 CUDA=1
```

Depois disso, A/B honesto: mesmo prompt, mesma seed, CPU vs. CUDA, medindo tok/s. É
exatamente o tipo de número que falta na tabela acima.

## Como encaixaria na stack daqui

`coli serve` expõe uma **API compatível com OpenAI** (`GET /v1/models`,
`POST /v1/chat/completions`, com streaming SSE), servida por um gateway que usa só a stdlib do
Python. Isso significa que ele entra na stack como mais um backend, sem adaptador:

```bash
COLI_MODEL=<dir> COLI_API_KEY=<segredo> ./coli serve --host 127.0.0.1 --port 5000
```

- **LiteLLM** (`:4000`) pode registrá-lo como provider OpenAI-compatible e o **Open WebUI**
  passa a listá-lo junto dos modelos do Ollama.
- O bind padrão já é localhost. Vale a regra do repo: **porta nenhuma exposta direto na
  internet** — loopback + Cloudflare Access, como todo o resto.
- A porta 5000 não conflita com nada em uso hoje (3000, 4000, 5678, 8080, 8188, 11434, 5433).
- O projeto traz `docker/Dockerfile.slim` e um compose próprio, com o modelo em bind-mount
  read-only. Se um dia isso virar serviço fixo, o caminho natural é um profile novo no
  `infra/docker/docker-compose.yml` — e aí `CLAUDE.md`, `infra/SERVICES.md` e `README.md`
  precisam registrar serviço, profile e porta.

Uma limitação para uso como serviço: o servidor **gera uma resposta por vez** — requisições
concorrentes entram em fila, não carregam cópias do modelo. Serve para uso pessoal, não como
backend compartilhado.

## Veredito

**Sim, dá para montar — mas o que cabe aqui é o Qwen3.6, não a promessa do título.**

O que atrai no projeto é rodar um modelo de 744B em máquina normal; isso é real, e o
mecanismo (multitiering + JIT de pesos) é honesto e bem documentado. Só que nesta máquina
o GLM-5.2 custaria ~372 GB de NVMe para entregar uma fração de token por segundo — é
experimento, não ferramenta.

O uso defensável é o Qwen3.6-35B-A3B: 20 GB de disco, container pronto, e um caminho de GPU
com ganho medido de 7×. O custo escondido é a RAM — 24 GB residentes numa máquina de 32 GB
significa que ele e a stack de mídia não coexistem.

Vale como pesquisa (é literalmente uma técnica nova de hierarquia de memória para MoE), não
como substituto do Ollama para o dia a dia.

## Referências

- Repositório: https://github.com/JustVugg/colibri
- Quickstart: `docs/quickstart.md` · CUDA: `docs/cuda.md` · API: `docs/api.md` · Qwen3.6: `docs/qwen36.md`
- Containers pré-convertidos: `Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64`,
  `mastouri/GLM-5.2-colibri-int4-g64-with-int8-mtp` (Hugging Face)
