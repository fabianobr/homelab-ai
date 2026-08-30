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

## RAM: a previsão que este doc errou duas vezes

A documentação do projeto diz que o `qwen36` exige **residência total** dos experts (~24 GB) e
que `--ram` é ignorado por esse engine. As duas primeiras versões deste doc concluíram daí que
o modelo não caberia nos ~21 GB disponíveis, e chegaram a recomendar derrubar o profile
`media-pipeline` e fechar o desktop.

**As duas coisas estavam erradas**, e a medição está em "Medições neste host":

- O que a doc omite é que o cache tem um botão: `cap` (slots por camada), exposto como
  `--cap` no launcher. O `coli plan` escolhe `cap=173` sozinho e cabe no orçamento.
- O pico real mais alto foi **16,65 GB**, com 22 GB disponíveis. Nada precisou ser desligado.
- Uma tentativa intermediária de calcular o custo por `cap` pela fórmula do adaptador de
  segmento (`hidden × inter × 3`) deu 32 GB para residência total e também estava errada: ela
  conta os pesos como 1 byte quando o container é int4.

Vale registrar por que a suspeita inicial era razoável mesmo estando errada: os containers
**não** são o problema — medidos com `docker stats`, somam ~500 MB ociosos. Quem ocupa RAM é
a sessão de desktop, e o swap já estava com 9,8 GiB em uso antes de qualquer experimento.

## Medições neste host

Medido em 2026-08-30, mesmo prompt ("Explique em duas frases o que é uma mixture of
experts."), 64 tokens de saída, com o desktop e os containers de pé.

### Qwen3.6-35B-A3B no Colibrì, CPU-only

O `coli plan` escolhe sozinho `cap 173/layer`. Varrendo o `cap` (slots de cache por camada):

| `cap` | tok/s | acerto do cache | pico de RSS | TTFT |
|---|---|---|---|---|
| 16 (default do engine) | 0,38 | 55,5% | 11,05 GB | 36,0 s |
| 64 | 0,73 | 79,9% | 11,85 GB | 34,0 s |
| **173** (escolha do planner) | **0,85** | 83,4% | 16,65 GB | 32,4 s |

**A RAM nunca foi o problema.** Os pesos densos residentes custam 9,25 GB e dominam; o cache
de experts é troco — quadruplicar `cap` de 16 para 64 custou 0,8 GB. O medo de "24 GB de
residência total" que as duas primeiras versões deste doc carregaram era infundado: o pico
mais alto medido foi 16,65 GB com 22 GB disponíveis, e nada precisou ser desligado.

### O comparador: a mesma classe de modelo no Ollama, que já está no ar

`qwen3-coder:30b` (Qwen3-Coder-**30B-A3B**, Q4_K_M, 18,6 GB): mesma família, mesma
arquitetura MoE, os mesmos ~3B ativos por token, mesma quantização, mesma máquina, mesmo
prompt.

| | Colibrì · Qwen3.6-35B-A3B | Ollama · qwen3-coder:30b |
|---|---|---|
| Onde roda | CPU (12 cores) | GPU (14,8 GB de VRAM) |
| **Decode** | **0,85 tok/s** | **45,97 tok/s** |
| TTFT | 32,4 s | 23,3 s (incl. 22,8 s de load frio) |

**54x de diferença.** Aplicando o ganho de 7,0x que o próprio projeto mediu para o tier de
experts em VRAM neste modelo, o Colibrì chegaria a ~6 tok/s — ainda ~8x atrás do que esta
máquina entrega hoje sem instalar nada.

Ressalva: não são o mesmo checkpoint (35B vs 30B) e o Colibrì rodou sem CUDA. Mas a pergunta
não é "qual engine é melhor em igualdade de condições" — é "o que esta máquina entrega".

### Por que a diferença é tão grande

Não é implementação ruim; é o pressuposto de projeto. O Colibrì existe para rodar modelos que
**não cabem** — troca velocidade por capacidade, streamando experts do disco. Num modelo que
cabe inteiro em 16 GB de VRAM, essa troca é só custo: o Ollama carrega tudo na GPU uma vez, o
Colibrì pagina experts a cada token.

O ganho apareceria num modelo grande demais para a VRAM **e** para a RAM. Nesta máquina,
nenhum modelo desses cabe no disco — e é aí que os dois limites se encontram.

## CUDA: mapeado, e deliberadamente não exercido

O binário medido acima é CPU-only (`make qwen36`, sem `CUDA=1`): `ldd` não linka lib CUDA
nenhuma, a GPU ficou em 1% durante a geração, e o `doctor` avisa
`[warn] accelerator.gpu — GPU detected but the engine is CPU-only`. O planner sabe o que
faria com ela: `VRAM 14.4 GB hot tier · ~8114 experts`.

O caminho foi levantado e é viável:

- Existe repo NVIDIA nativo para Ubuntu 26.04 com **CUDA 13.3** — acima dos 12.8 que o
  Makefile documenta como piso para sm_120 (RTX 50), e acima de 12.9, então o gencode de
  `compute_121` também entra.
- `cuda-toolkit-13-3` e seus filhos diretos **não declaram nenhum pacote de driver**
  (verificado baixando os `.deb` e lendo o `Depends`, sem instalar).
- Os containers não consomem toolkit do host: o host **não tem CUDA toolkit hoje** e mesmo
  assim Ollama e ComfyUI funcionam, porque o `nvidia-container-toolkit` injeta só o driver
  (595.84) e cada imagem traz o próprio runtime (o Ollama carrega `cuda_v12` e `cuda_v13`).
- Faltaria `g++-14` para `NVCC_CCBIN`: o host tem `gcc-13` mas só `g++-15`, novo demais para
  o nvcc.

**Não foi instalado de propósito.** O motivo não é risco — é retorno: ~6 tok/s projetados
contra os 46 tok/s que a máquina já entrega. Se um dia couber aqui um modelo que o Ollama
não consiga carregar, este é o caminho, e ele está pronto.

## Plano de montagem — executado

**Degrau 1 — o motor funciona nesta máquina?** ✅

```bash
git clone https://github.com/JustVugg/colibri.git ~/AI/colibri
cd ~/AI/colibri/c && ./setup.sh          # 10 s
make -C . qwen36 ARCH=native             # 2,4 s
```

**Degrau 2 — um modelo real responde?** ✅ responde, e os números estão acima

```bash
hf download Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64 \
  --local-dir ~/AI/models/colibri/qwen36_i4_gs64        # 23 GB, ~79 MB/s
M=~/AI/models/colibri/qwen36_i4_gs64
COLI_MODEL=$M ~/AI/colibri/c/coli doctor    # exige --model; não roda "a seco"
COLI_MODEL=$M ~/AI/colibri/c/coli plan      # escolhe cap 173/layer sozinho
# `coli run` não é wired para este engine: use chat/serve, ou o engine direto:
SNAP=$M TOK=$M/tokenizer.json N_NEW=64 ~/AI/colibri/c/qwen36 <cap> 4 prompt.txt
```

Não foi preciso fechar nada — o alerta de "feche o Chrome antes", que as versões anteriores
deste doc traziam, estava errado.

**Degrau 3 — a GPU paga o esforço?** ⏹️ **não executado, por decisão** — ver a seção de CUDA
acima: o caminho está mapeado e é seguro, mas o retorno projetado não justifica.

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

**Roda, e não serve para nada aqui.** Essa é a conclusão medida, não estimada.

O Qwen3.6-35B-A3B carrega e responde corretamente, em 0,85 tok/s, sem atrapalhar nada que
esteja no ar. Só que o Ollama entrega **46 tok/s** na mesma classe de modelo, nesta mesma
máquina, hoje. Nem o tier de VRAM fecharia essa distância: 7× sobre 0,85 dá ~6 tok/s, um
oitavo do que já existe.

A razão é estrutural, e é justamente o que torna o projeto interessante em outro contexto: o
Colibrì troca velocidade por **capacidade**. Ele ganha quando o modelo não cabe. Aqui,
dois limites se fecham ao mesmo tempo:

- os modelos que justificariam a técnica (GLM-5.2 com 372 GB, DeepSeek V4 com 167 GB) **não
  cabem nos 105 GB livres do NVMe**;
- os modelos que cabem no disco também cabem na GPU — e aí o Ollama é ordens de grandeza
  melhor.

Vale como leitura de engenharia (a hierarquia disco/RAM/VRAM para MoE é real e bem
documentada, e o `coli doctor`/`plan` é um dos planejadores de recursos mais honestos que já
vi num projeto desse porte). Não vale como serviço nesta máquina, e não deve entrar no
compose.

**Se um dia isto for reavaliado**, o gatilho é claro: um modelo que o Ollama não consiga
carregar *e* que caiba no disco. Enquanto os dois lados não mudarem, a resposta continua a
mesma.

### O que fica

- Motor compilado em `~/AI/colibri` (23 MB, binários de ~1 MB) — barato de manter, e é o que
  permite refazer o degrau 2 sem recompilar nada.
- **O container do modelo foi apagado** em 2026-08-30, depois de medido: eram 23 GB com o
  disco em 85%, e os números que ele produziu estão todos registrados acima. O disco voltou a
  126 GB livres (82%).
- Para reproduzir, basta rebaixar o container e repetir os comandos do degrau 2 — o download
  levou ~5 min a 79 MB/s.

## Referências

- Repositório: https://github.com/JustVugg/colibri
- Quickstart: `docs/quickstart.md` · CUDA: `docs/cuda.md` · API: `docs/api.md` · Qwen3.6: `docs/qwen36.md`
- Containers pré-convertidos: `Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64`,
  `mastouri/GLM-5.2-colibri-int4-g64-with-int8-mtp` (Hugging Face)
