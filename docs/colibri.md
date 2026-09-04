# Colibrì — avaliação de viabilidade neste host

Estudo do projeto [JustVugg/colibri](https://github.com/JustVugg/colibri) e do que dá para
montar nesta máquina.

- Versão estudada: **v1.9.0**, commit `184e0522` (2026-08-28)
- Licença: Apache 2.0
- Medições feitas **no host real** em 2026-08-30 (a primeira versão deste doc usava só os
  números do README; várias mudaram)
- Onde mora: `~/AI/colibri` (fora do repo, como o MoneyPrinterTurbo)

## Conclusão, em três linhas

**O Colibrì funciona aqui — para o que ele realmente promete.** Um **DeepSeek V4 Flash de
284B** roda a **1,37 tok/s** com o tier CUDA ligado (0,98 sem), o que nenhuma outra
configuração desta máquina alcança. Serve para trabalho assíncrono (~6 min por 500 tokens),
não para conversa.

Para modelos que **cabem** na GPU ele só perde: o Qwen3.6-35B-A3B deu 0,85 tok/s contra
46 tok/s do `qwen3-coder:30b` no Ollama. A fronteira útil é o tamanho do modelo, não a
qualidade do engine.

> **Este documento é cronológico e contém conclusões que foram depois corrigidas por
> medição.** A seção "Veredito" reflete o que se sabia após testar só o Qwen3.6; a
> "EMENDA 2026-08-30" a inverte com os dados do DeepSeek V4. Mantive as duas para preservar
> o raciocínio — se você só quer a resposta, ela está acima.


## O que é

Motor de inferência em **C puro** que roda modelos MoE gigantes em hardware comum tratando
disco, RAM e VRAM como uma única hierarquia de memória. Os pesos densos (atenção,
embeddings) ficam residentes em RAM em int4; os **experts roteados ficam no disco** e são
lidos sob demanda, com cache LRU por camada e pinagem dos experts quentes.

A consequência prática é a inversão do gargalo habitual: **quem determina a velocidade é a
banda do NVMe, não a GPU**. GPU é opcional em todos os modelos — acelera, nunca é requisito.

Python é usado só no launcher (`coli`), no gateway HTTP e na conversão de pesos; o motor não
tem dependência nenhuma.

## O host, medido (no início da avaliação)

Retrato do host **antes** dos experimentos. Os números de disco mudaram desde então — ver
"O que fica" no fim para o estado atual.

| | Valor no início |
|---|---|
| CPU / SO | 12 cores · Ubuntu 26.04 LTS (resolute) · gcc 15.2 · Python 3.14.4 |
| RAM | **29 GiB** totais · ~21 GiB *available* · **swap já com 9,8 GiB em uso** |
| Disco | `/dev/nvme0n1p5` 719 GB, **82% cheio — 126 GB livres**, partição única |
| GPU | RTX 5060 Ti **16 GB**, driver 595.84, **compute capability 12.0 (sm_120, Blackwell)** |
| CUDA Toolkit | não instalado *na época desta medição*; `apt` só oferece 12.4. **Hoje: CUDA 13.3 instalado** do repo `ubuntu2604` — ver a emenda |
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

## CUDA: mapeado, e deliberadamente não exercido (SUPERADO — foi instalado e medido)

> ⚠️ Escrito antes do DeepSeek V4. O CUDA 13.3 **foi** instalado e medido depois; ver
> "O tier CUDA, medido" na emenda. A afirmação abaixo de que falta `g++-14` também está
> errada: o host tem `g++-14` e `gcc-14`, e é com `NVCC_CCBIN=g++-14` que o build funciona.

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
- ~~Faltaria `g++-14` para `NVCC_CCBIN`~~ — **errado**: o host tem `g++-14`. É o que o build
  da emenda usa.

**Não foi instalado *neste momento da avaliação*.** O motivo não era risco — era retorno: ~6 tok/s projetados
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

> ⚠️ `--host 127.0.0.1` serve para uso a partir do próprio host. **Para o LiteLLM alcançar,
> o bind precisa ser em `172.17.0.1`** — ver "Servindo pelo LiteLLM" adiante, e use
> `infra/scripts/colibri-serve.sh` em vez deste comando cru.

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

## Veredito (parcial — corrigido pela emenda no fim do documento)

> ⚠️ Escrito quando só o Qwen3.6 tinha sido medido. A conclusão abaixo vale para modelos que
> cabem na GPU; a "EMENDA 2026-08-30" mostra o caso em que ela não se aplica.

**Roda, e não serve para nada aqui.** Essa é a conclusão medida, não estimada.

O Qwen3.6-35B-A3B carrega e responde corretamente, em 0,85 tok/s, sem atrapalhar nada que
esteja no ar. Só que o Ollama entrega **46 tok/s** na mesma classe de modelo, nesta mesma
máquina, hoje. Nem o tier de VRAM fecharia essa distância: 7× sobre 0,85 dá ~6 tok/s, um
oitavo do que já existe.

A razão é estrutural, e é justamente o que torna o projeto interessante em outro contexto: o
Colibrì troca velocidade por **capacidade**. Ele ganha quando o modelo não cabe. Aqui,
dois limites se fecham ao mesmo tempo:

- os modelos que justificariam a técnica (GLM-5.2 com 372 GB, DeepSeek V4 com 167 GB) **não
  cabem nos 126 GB livres do NVMe**;
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

Estado do host ao fim de 2026-08-30:

- **Motor em `~/AI/colibri`: 237 MB.** Eram 23 MB até o build `DEEPGEMM=1` vendorizar
  204 MB em `c/third_party/deepgemm`. Os binários em si continuam com ~1 MB.
- **O container do Qwen3.6 foi apagado** depois de medido (eram 23 GB).
- **O container do DeepSeek V4 permanece:** `~/AI/models/colibri/deepseek_v4`, **167 GB**. É
  ele que ocupa o disco hoje — e é deliberado, porque entrega capacidade que nenhuma outra
  configuração desta máquina alcança.
- **NVMe hoje: 82 GB livres (88%).** Os "245 GB livres" citados na seção de migração eram o
  estado *antes* deste download. Sempre confira com `df -h /` em vez de citar um número
  deste doc.
- Para reproduzir do zero: rebaixar o container e repetir o degrau 2.

## EMENDA 2026-08-30: o DeepSeek V4 roda, e inverte o veredito

O veredito acima ("roda e não serve aqui") foi escrito medindo o **Qwen3.6-35B-A3B**, e vale
para o que ele testou: Colibrì como alternativa a um modelo que o Ollama já roda. Mas ele
disparou o próprio gatilho de reabertura que este doc definiu — *"um modelo que o Ollama não
consiga carregar e que caiba no disco"* — e o **DeepSeek V4 Flash** satisfaz os dois.

Liberando 119 GB (`docker builder prune` + migração de modelos frios do ComfyUI para o HDD,
ver `comfyui.md`), o NVMe foi de 126 para 245 GB livres e os 166,9 GB couberam.

### O que foi medido

Modelo: `deepseek-ai/DeepSeek-V4-Flash-0731`, 284B total / **13B ativos**, 43 camadas,
256 experts roteados, top-6 + 1 compartilhado. Download verificado contra a API da Hugging
Face: **74/74 arquivos com tamanho exato, 166,9 GB** — o doc do projeto avisa que shards
truncados passam despercebidos, então essa checagem é obrigatória.

Mesmo prompt das medições anteriores, 48 tokens, CPU-only, desktop e containers de pé:

| | 1ª execução | 2ª execução |
|---|---|---|
| **Decode** | **0,91 tok/s** | **1,01 tok/s** |
| TTFT | 26,1 s | 27,3 s |
| Hit rate de experts | 55,9% | 60,2% |
| Bytes lidos do disco | 83,7 GB | 75,5 GB |
| Pins por camada | 12 | 13 |

**Um modelo de 284B rodou na mesma velocidade que o Qwen3.6 de 35B** (0,85 tok/s). Não é
paradoxo: o DeepSeek ativa 13B por token contra os 3B do Qwen, mas usa I/O direto alinhado e
tem experts maiores (12,6 MB), que o NVMe serve com muito mais eficiência do que os blocos
de 1,5 MB do Qwen.

### O aprendizado de hot-set é real

Entre a 1ª e a 2ª execução, sem mudar nada, o engine leu `.coli_usage` (telemetria de
roteamento que ele mesmo gravou), subiu os pins de 12 para 13 por camada, e ficou **11% mais
rápido lendo 8 GB a menos**. É o "weight JIT" do README funcionando — otimização observada,
não prometida.

### Duas previsões do planner que a execução desmentiu

O `coli doctor` reprovou a máquina antes de rodar:

```
[fail] memory.ram   RAM budget cannot hold one expert slot per sparse layer
RAM 19.6 GB budget · 19.7 GB dense · 0.0 GB warm experts · cap 0/layer
hit 10% projected expert residency
```

Na prática os densos ocuparam **6,27 GiB**, não 19,7 GB, sobrando 9,6–10,2 GB para cache; e o
hit rate real foi **56–60%**, não 10%. O planner erra para o lado conservador. **Um `[fail]`
no doctor não é impedimento — vale tentar rodar assim mesmo.**

### Banda de disco: use o `iobench` do projeto, não um teste caseiro

Meu benchmark improvisado (single-thread, blocos de 1,5 MB) media 1.093 leituras/s. O
`iobench` do próprio projeto, com O_DIRECT e 4 threads em blocos de 12 MB, mede
**4,38 GB/s (~350 experts/s)** — 4× melhor. É esse o número que importa, porque é assim que o
engine lê.

```bash
make -C c iobench && ./c/iobench <shard> 12 200 4 1
```

O HDD continua fora de questão: 33 leituras aleatórias/s contra 350 do NVMe.


### O tier CUDA, medido (2026-08-30)

CUDA 13.3 instalado do repo `ubuntu2604`; o driver 595.84 e todos os containers ficaram
intactos, como previsto. Build: `make -f Makefile.deepseek-v4 deepseek-v4 CUDA=1 DEEPGEMM=1
CUDA_HOME=/usr/local/cuda-13.3 NVCC_CCBIN=g++-14`. O engine reconhece a placa:
`[DSV4 CUDA] device 0: NVIDIA GeForce RTX 5060 Ti 16.6 GB sm_120`.

| Configuração | Decode | TTFT | Hit rate |
|---|---|---|---|
| CPU, 1ª execução (fria) | 0,91 tok/s | 26,1 s | 55,9% |
| CPU, 2ª execução | 1,01 tok/s | 27,3 s | 60,2% |
| **CPU quente (controle)** | **0,98 tok/s** | 27,8 s | 61,2% |
| GPU, só densos | 1,14 tok/s | 27,0 s | 60,4% |
| **GPU + `COLI_CUDA_MOE_BATCH` + `COLI_CUDA_ATTN_BATCH`** | **1,37 tok/s** | 24,0 s | 61,6% |

**Ganho limpo da GPU: +40% em decode, −14% em TTFT.** A comparação é controlada: o
controle de CPU foi rodado *depois* das execuções com GPU, com o hot-set já aquecido, e os
hit rates batem (61,2% vs 61,6%). Sem esse controle, o ganho pareceria maior do que é — o
hit rate sobe sozinho entre execuções e infla qualquer comparação frio-contra-quente.

Não são os 5–10× de prefill e 2,5× de decode que o projeto documenta, e o motivo é
mensurável: durante a execução com GPU o disco entregou **2,13 GB/s**, contra os 4,38 GB/s
que o `iobench` mede como teto. A máquina deixou de ser limitada por CPU e passou a ser
limitada por I/O. A GPU não conserta leitura de disco — e o próprio projeto diz isso, ao
explicar que experts streamados ficam de propósito no caminho de CPU, porque copiá-los para a
GPU a cada uso trocaria o gargalo de disco por um de PCIe.

`DSV4_CUDA_EXPERT_MIRRORS` não teve efeito observável: o tier permaneceu `dense-matvec` em
todas as execuções, com 5,46 GiB subidos (131 MiB × 43 camadas) e ~10 GB de VRAM ociosos.
Quem rendeu foram os flags de batching.

### Armadilha de build: alternar `CUDA=1` exige `clean`

O primeiro build com `CUDA=1 DEEPGEMM=1` produziu um binário que **linkava CUDA e não usava a
GPU**, sem erro nenhum — mesmo tempo do CPU, nenhum banner, nenhum aviso de fallback.

Causa: o `Makefile` não versiona as flags no nome dos objetos. Como havia `.o` de um build
CPU anterior mais novos que o fonte, o `make` recompilou só o `.cu` do backend e reaproveitou
as 27 unidades C — que portanto nunca receberam `-DCOLI_V4_GPU_TIER`. A chamada
`coli_v4_gpu_engine_open()` está sob `#ifdef`, então foi compilada para fora, e junto com ela
o próprio código que avisaria do fallback.

Diagnóstico rápido, antes de acreditar num resultado de GPU:

```bash
nm c/COLI_V4_UNIT_RUNTIME.o | grep gpu_engine_open   # precisa aparecer "U coli_v4_gpu_engine_open"
```

Sempre `make -f Makefile.deepseek-v4 deepseek-v4-clean` ao trocar `CUDA=1`.

### Prompt grande: onde isto realmente quebra (2026-08-30)

Todas as medições acima usaram um prompt de **18 tokens**. Carga de SDLC é o oposto — diffs e
arquivos. Testado com um diff real deste repo, **4.575 tokens** pelo tokenizador (a
estimativa de 4 chars/token subestima bastante: 13.554 chars deram 4.575 tokens, não ~3.400).

São **dois problemas independentes**.

#### 1. O launcher limita o contexto a 4.096, e falha com exit 0

```
V4 prompt must encode to between 1 and 4096 tokens
```

O modelo declara `max_position_embeddings: 1048576` (YaRN sobre 65.536 nativos), e a tabela de
famílias do `coli` permite até 1M — mas o **default é 4.096**
(`family_registry.py`, `FamilyLimits(4096, 1048576, ...)`). Prompt e saída precisam caber nisso.

Contorno: **`--ctx 32768`**.

Dois detalhes que tornam isso pior do que precisaria ser: o processo **sai com código 0**
mesmo tendo falhado — nenhum script detecta pelo exit code — e só descobre o problema depois
de carregar 6,27 GiB de pesos densos.

#### 2. O prefill é o gargalo real, e ele não tem contorno

Com `--ctx` corrigido roda, e o custo aparece:

| | Prompt de 18 tokens | **Prompt de 4.575 tokens** |
|---|---|---|
| TTFT | 24,0 s | **223,2 s (3,7 min)** |
| Hit rate de experts | 60,4% | **26,3%** |
| Bytes lidos do disco | 75 GB | **341 GB** |
| Requisições de expert | 14.200 | 34.611 |
| Decode | 1,37 tok/s | 1,10 tok/s |

Prefill roda a **~20 tokens/s**. O colapso do hit rate é estrutural, não configuração: cada
token do prompt roteia seus próprios experts, a união explode, e o cache de ~10 GB deixa de
cobrir. Com 26% de acerto quase toda leitura vai ao disco — 341 GB para uma requisição.

Aumentar o cache não resolve: o teto de RAM desta máquina já está em uso (ver "Duas previsões
do planner que a execução desmentiu"), e o conjunto de experts tocado por um prompt de 4,5 mil
tokens é grande demais para qualquer cache que caiba em 29 GiB.

#### Consequência para uso em SDLC

**O caso interativo morre aqui.** Não é questão de tunar: ~4 minutos antes da primeira palavra
num diff médio. Nenhuma IDE tolera, e nenhum `sdlc-review` síncrono tampouco.

**O caso em lote sobrevive**, na escala de **~5 minutos por revisão**. Para um agente noturno
no padrão dos semanais deste repo — junta os PRs do dia, revisa, escreve o relatório — é
aceitável. Para qualquer coisa que alguém espere na frente da tela, não é.

Se for adiante, o encaixe é no **LiteLLM** (`infra/docker/litellm-config.yaml`), como provider
OpenAI-compatible apontando para `coli serve` — **não** atrás do Ollama, que não sabe servir
outro engine. O container precisa de `extra_hosts: ["host.docker.internal:host-gateway"]`,
porque não alcança o loopback do host. E o `coli serve` **atende uma requisição por vez**:
serve um agente, não um gateway compartilhado.

### Veredito corrigido

**Para o que o Colibrì realmente promete, ele entrega nesta máquina.**

Não existe comparação com o Ollama aqui, porque não há alternativa: nenhuma configuração
local sua roda um 284B. A pergunta deixa de ser "é mais rápido?" e passa a ser "1 tok/s vale a
capacidade?" — o que depende do uso, não da engenharia:

- **Não serve** para uso interativo — e com prompt grande isso deixa de ser questão de
  paciência: ver "Prompt grande" acima, onde 4,5 mil tokens de entrada custam 3,7 min só de
  prefill.
- **Serve** para trabalho assíncrono: uma pergunta difícil deixada rodando, análise em lote,
  geração noturna. É o mesmo padrão dos agentes semanais deste repo.

Com o tier CUDA ligado (medido acima), o decode vai a **1,37 tok/s** — 40% melhor, mas ainda
no mesmo regime de uso. Uma resposta de 500 tokens passa de ~8 para ~6 minutos: continua
sendo trabalho assíncrono, não conversa.

## Servindo pelo LiteLLM (como está montado hoje)

O `coli serve` expõe uma API OpenAI-compatible e entra na stack como provider do **LiteLLM**
(`:4000`) — **não atrás do Ollama**, que não sabe servir outro engine.

```bash
infra/scripts/colibri-serve.sh start    # sobe sob demanda
infra/scripts/colibri-serve.sh status
infra/scripts/colibri-serve.sh stop
```

Depois disso o modelo aparece como **`sdlc-review-local`** no LiteLLM, ao lado dos
`sdlc-*` que já existem.

### Por que fica no host e não no compose

O engine é compilado no host com CUDA/DeepGEMM para `sm_120`. O `Dockerfile.slim` do projeto
é CPU-only e marcado `COLI_DOCKER_GLM_ONLY=1`; containerizar exigiria refazer esse build
dentro da imagem, com passthrough de GPU e bind-mount dos 167 GB. **É a única peça da stack
fora do Compose** — se um dia escalar, o caminho é uma imagem própria e um profile novo.

### Quatro detalhes que quebram silenciosamente se ignorados

1. **Bind na bridge padrão (`docker0`), não na rede do container.** O LiteLLM está em
   container e não alcança o `127.0.0.1` do host. O erro intuitivo — e que eu cometi — é
   bindar no gateway da rede onde o LiteLLM vive (`docker_default`, `172.18.0.1`). O Docker
   mapeia `host-gateway` **sempre** para o gateway da bridge padrão (`docker0`,
   `172.17.0.1`), independente da rede do container. O sintoma do erro é
   `Connection refused` — não `no route` —, ou seja, o pacote chega e não há ninguém
   escutando. O script resolve esse endereço em runtime (`docker network inspect bridge`).
2. **`--allowed-host` é obrigatório, e sem a porta.** O `coli serve` tem guarda
   anti-DNS-rebinding que valida o header `Host`. Passar `host.docker.internal:5000` é
   recusado; o valor correto é **`host.docker.internal`**.
3. **`COLI_API_KEY` não é opcional.** Escutar na bridge torna o endpoint alcançável por
   **todos** os containers (`n8n`, `searxng`, `open-webui`, `moneyprinterturbo`,
   `deepseek-harness`), não só pelo LiteLLM. A chave mora no `homelab.env` (gitignored), fonte
   única — o compose a repassa ao container do LiteLLM via `environment`.
4. **`timeout: 2400` no LiteLLM.** Medido aqui, um prompt de 4.575 tokens custa ~223 s só de
   prefill. O default do LiteLLM mataria a requisição no meio, e o sintoma seria um erro de
   timeout que parece falha do modelo.

### O ComfyUI degrada o tier de GPU do Colibrì, em silêncio

Registrado primeiro como limite estrutural — "o banco de experts não cabe na VRAM" — e
**corrigido em 2026-08-31**: a causa era contenção com o ComfyUI.

Com o ComfyUI no ar, o `COLI_CUDA_MOE_BATCH=1` falha assim:

```
[DSV4 CUDA] expert FC2 bank allocation: out of memory
v4_gpu moe-batch=off (bank allocation failed; CPU union stays)
```

Com a VRAM livre, **o erro não acontece**: o banco aloca normalmente, e a VRAM vai de
6,7 GB (só o tier de densos, logo após o load) para **13,4 GB** na primeira requisição — a
alocação é preguiçosa, por isso o número logo após subir engana.

O que torna isso perigoso é a forma da falha: **sem erro, sem exit não-zero**, só uma linha
no log. Quem rodasse os dois juntos teria um serviço mais lento sem nenhum sinal. É mais uma
razão — além da RAM — para os dois não coexistirem.

### Prompt grande pelo LiteLLM: 18 minutos

Medido em 2026-08-31, prompt de **4.566 tokens** (um diff real deste repo) atravessando o
gateway, 48 tokens de saída:

| | Acesso direto ao engine (2026-08-30) | **Pelo LiteLLM (2026-08-31)** |
|---|---|---|
| Prompt | 4.575 tokens | 4.566 tokens |
| Tempo total | **281 s (4,7 min)** | **1.092 s (18,2 min)** |
| RAM disponível na hora | ~21 GiB | **7,1 GiB** |

A resposta foi correta — o modelo revisou o diff e apontou problemas reais.

**A hipótese de RAM foi levantada, testada e desconfirmada.** A suspeita inicial era que os
7,1 GiB livres do teste original explicassem os 18,2 min — em modo serve com `--ctx 32768` e
o banco de experts em VRAM, sobra menos RAM para o cache de experts (o planner mira 9,64 GiB).

Duas tentativas de confirmação em 2026-09-02, ambas com o `colibri-serve.sh` já corrigido
(ver "O wrapper custou mais que o experimento" abaixo):

| Rodada | RAM disponível | Resultado |
|---|---|---|
| Original (30/08) | 7,1 GiB | **1.092 s (18,2 min)** — válida |
| 1ª tentativa | 21 GiB | interrompida aos 22 min sem concluir — descartada |
| **2ª tentativa** | **15 GiB** | **1.122 s (18,7 min)** — válida |

Com o dobro da RAM da medição original, o tempo ficou **igual** (30 s de diferença entre
duas rodadas independentes é ruído, não sinal). **A hipótese de RAM está desconfirmada: o
custo é estrutural do modo serve, não da memória disponível.** A causa raiz segue aberta —
possivelmente o roteamento de experts de um prompt de 4,5 mil tokens é caro de forma que
independe de quanto cache cabe em RAM — mas não é isso que decide o uso.

O que fica como fato operacional, agora com duas medições concordantes: **uma revisão de
diff médio pelo gateway custa ~18-19 minutos**, não os ~5 que a extrapolação do teste direto
sugeria. Para agente noturno serve; para qualquer coisa com pessoa esperando, não.

**Pendência aberta em 2026-09-03:** as duas medições acima truncaram a resposta
(`finish_reason: length`) — o texto da review nunca terminou. Tentativas de subir `max_tokens`
pra evitar o corte esbarraram num problema não relacionado ao Colibrì (tarefas em background
desta sessão de chat morrendo em segundos, investigado e isolado a ponto de descartar RAM,
LiteLLM, timeout e payload como causa). Dados crus, timeline e a investigação completa em
`docs/colibri-evidence/README.md`. Não decidido: rodar em foreground, tentar em sessão nova,
ou aceitar o truncamento como não-bloqueante (a métrica de tempo já está fechada).

### O wrapper custou mais que o experimento

Seis defeitos apareceram no `colibri-serve.sh` durante o uso, e o padrão que os une é mais
útil que a lista: **cada guarda nova introduziu um modo de falha silenciosa**.

| Defeito | Como se manifestava |
|---|---|
| `stop` só agia com o launcher vivo | RAM presa, sem forma de recuperar pelo script |
| Launcher órfão segurando a porta | `status` dizia "parado" com servidor escutando |
| `start` não checava a porta | bind falha **depois** do fork; pidfile com PID morto |
| `TIME_WAIT` sem `SO_REUSEADDR` | bind falha sem processo algum |
| `ss "sport = :N"` não casa `TIME-WAIT` | a espera terminava sem esperar |
| `$(pipeline)` com `set -euo pipefail` | **`start` saía com código 1 e ZERO saída** |

O último é o mais traiçoeiro e o que mais custou: um `grep` sem resultado — o caso normal,
"a porta está livre" — retorna 1, o `pipefail` propaga, o `set -e` mata o script antes de
qualquer `echo`. Toda substituição de comando com `grep` precisa de `|| true`.

Três lições que valem além deste script:

1. **`nohup ... &` não é evidência de nada** num serviço que carrega modelo por ~60 s antes
   de abrir a porta. A verificação honesta é `status` retornando 0 **e** a porta respondendo.
2. **`pgrep -f`/`pkill -f` casam com a linha de comando de quem os invoca.** Custou um shell
   morto por auto-`pkill` e um falso positivo que abortou uma medição. Use `pgrep -x` ou
   caminho absoluto.
3. **Cronometre pelo log do servidor, não pelo cliente.** Um `curl` interrompido produz
   "5 segundos" enquanto o engine segue trabalhando — o que virou falso resultado três vezes.

E a lição de método: ao ver a primeira falha, isole **"o serviço sobe?"** de **"meu script
sobe o serviço?"**. O `coli serve` invocado direto sempre funcionou; só descobri isso na
sexta tentativa.

### É sob demanda, e a razão é RAM

O serviço segura ~16–21 GB enquanto vive — numa máquina de 29 GB não convive com o ComfyUI
nem com trabalho pesado. O script **recusa subir** com menos de 20 GB disponíveis, em vez de
derrubar a máquina; ajuste com `COLI_MIN_FREE_GB`. Com o serviço parado, a rota
`sdlc-review-local` devolve erro de conexão — visível, que é o comportamento desejado.

## Referências

- Repositório: https://github.com/JustVugg/colibri
- Quickstart: `docs/quickstart.md` · CUDA: `docs/cuda.md` · API: `docs/api.md` · Qwen3.6: `docs/qwen36.md`
- Containers pré-convertidos: `Kreuzzelg/qwen36-35b-a3b-colibri-i4-gs64`,
  `mastouri/GLM-5.2-colibri-int4-g64-with-int8-mtp` (Hugging Face)
