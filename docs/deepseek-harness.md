# DeepSeek Harness no homelab-ai

> Para a instância persistente deste host, o caminho canônico é o profile Docker `harness`.
> A antiga unidade de usuário `dsh-web.service` foi desativada; o guia de instalação global abaixo
> permanece somente como referência para experimentos locais descartáveis.

Guia para experimentar o [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
como agente autônomo e multi-provider na criação de um projeto novo. O Ollama local é uma das
opções de modelo, não uma restrição nem o provider obrigatório.

> Estado validado em 2026-08-22. O DeepSeek Harness ainda está em *developer preview* e
> anuncia mudanças incompatíveis. Fixe a versão e trate este setup como experimento.

## O que ele acrescenta ao projeto

O DeepSeek Harness (`dsh`) não é um modelo. Ele é a camada que conecta um modelo a arquivos,
shell, sessões, permissões, skills, planos, subagentes e workflows. A arquitetura permite trocar
essas capacidades por plugins.

O primeiro objetivo é verificar se o Harness consegue receber uma ideia, tomar decisões técnicas,
criar um projeto, instalar dependências, implementar, testar, corrigir falhas e documentar o
resultado com pouca intervenção humana.

O segundo objetivo é permitir experimentos controlados com a mesma spec em diferentes modelos e
harnesses:

```text
mesma spec + mesmo modelo
        ├── pipeline atual: n8n/OpenCode
        ├── DSH Minimal
        ├── DSH Standard
        └── DSH Code/Workflow
```

As métricas recomendadas são:

- testes aprovados sem correção manual;
- duração total;
- tokens e chamadas ao modelo;
- quantidade de tool calls;
- intervenções humanas;
- erros de contexto, ferramentas e permissões.

O preset Standard é o ponto de partida para autonomia real. Code mode, modo headless, workflows e
subagentes entram depois para comparar orquestração e repetibilidade, não para limitar o primeiro
projeto a um smoke test.

## Limites desta avaliação

- O Harness não melhora a qualidade do modelo automaticamente.
- Ele não substitui o Open WebUI, que continua sendo a interface principal do homelab.
- O projeto ainda é preview; plugins e formatos de configuração podem mudar.
- Os modos `read-only` e `workspace-write` restringem efeitos de escrita. Eles não confinam
  leituras ao workspace e não isolam rede nem visibilidade de processos.
- MCPs, plugins, busca web e providers externos podem transmitir conteúdo do workspace.
- Com uma única GPU, somente chamadas a modelos locais precisam ser serializadas. Providers cloud
  não disputam VRAM com o Ollama.

Não publique a porta interna `3080` nem o Ollama. Para o primeiro experimento, mantenha ambos acessíveis
somente por loopback. Para o uso remoto aprovado deste homelab, a porta interna continua isolada e
o profile Docker publica somente `127.0.0.1:3081` para o Cloudflare Tunnel; consulte
[`infra/docker/deepseek-harness/README.md`](../infra/docker/deepseek-harness/README.md).

## Estado local já verificado

| Componente | Estado |
|---|---|
| Node.js | `22.23.2`; atende ao requisito `^22.19.0 || >=24.0.0` |
| npm | `10.9.8`; prefixo global em `~/.npm-global` e presente no `PATH` |
| Build nativo | GCC/G++ 15, Make 4.4 e Python disponíveis |
| Ollama | Container `0.32.6`, saudável, em `127.0.0.1:11434` |
| API | `/v1/models` OpenAI-compatible validado |
| LiteLLM | Não é necessário para o primeiro teste |

Modelos testados:

| Modelo | Perfil local | Tool calling | Uso recomendado |
|---|---|---|---|
| `qwen3.5:latest` | 9,7B, Q4_K_M, ~6,6 GB | Passou no smoke test | Primeiro contato e tarefas gerais |
| `qwen3-coder:30b` | 30,5B, Q4_K_M, ~18 GB | Passou no smoke test | Código e benchmark do SDLC |
| `qwen3:8b` | 8B | Não chamou a ferramenta no orçamento testado | Não usar como baseline inicial |

O `qwen3-coder:30b` excede os 16 GiB físicos da GPU e pode usar offload. Espere maior latência e
não o execute ao mesmo tempo que workloads do ComfyUI.

## Instalação recomendada

### 1. Confirme os serviços e runtimes

Use o Ollama do container, não o Snap antigo do host:

```bash
docker ps --filter name=^/ollama$
docker exec ollama ollama list
node --version
npm --version
```

Os valores esperados são Node `22.19+`, Ollama saudável e pelo menos `qwen3.5:latest` na lista.

### 2. Instale uma versão fixada

O pacote abaixo era a tag npm `latest` validada na data deste guia:

```bash
npm install -g --foreground-scripts @deepseek-ai/dsh@0.1.0-rc.7
dsh --help
```

Não use `sudo`: o npm deste host já instala globais em `~/.npm-global`. A opção
`--foreground-scripts` deixa visível a compilação de dependências nativas, especialmente
`node-pty` no Linux.

Não instale a partir do código-fonte para uso normal. O checkout completo exige pnpm, build do
monorepo e é apropriado para quem pretende desenvolver o próprio Harness.

### 3. Crie um projeto novo e reversível

Use um diretório dedicado, vazio e sem segredos. Git permite revisar tudo o que o agente fizer e
voltar ao estado inicial sem misturar o experimento com o `homelab-ai`:

```bash
mkdir -p /home/fabiano/code/dsh-autonomy-poc
cd /home/fabiano/code/dsh-autonomy-poc
git init
```

Não coloque `.env`, tokens ou credenciais nesse diretório. O sandbox limita mutações, mas não
impede o modelo de tentar ler outros caminhos do host.

### 4. Inicie o Harness no projeto

```bash
cd /home/fabiano/code/dsh-autonomy-poc
DSH_TELEMETRY_DISABLED=1 dsh web --no-open
```

Acesse `http://127.0.0.1:3080`, escolha esse diretório como workspace e selecione:

```text
Agent preset: Standard
Permission mode: workspace-write
```

Esse modo não reduz o agente a leitura: ele pode criar e editar todo o projeto, executar shell,
instalar dependências, rodar testes, iniciar processos, planejar e usar as demais ferramentas do
preset Standard. Uma tentativa de escrever fora do workspace deve exigir aprovação específica.

Não use `danger-full-access` como política permanente. Aprove uma elevação pontual somente quando
o Harness mostrar o comando e a justificativa — por exemplo, se um gerenciador precisar gravar
cache fora do projeto.

Mantenha a porta em loopback. Não use `--host 0.0.0.0` nem publique o serviço via Cloudflare
durante a avaliação.

O estado do Harness fica em `~/.dsh`, fora deste repositório público. Não copie credenciais,
sessões ou arquivos dessa pasta para o Git.

### 5. Configure providers sem escolher por antecedência

Cadastre pelo menos DeepSeek cloud e Ollama local. Se você já utiliza Anthropic ou OpenAI, pode
adicioná-los também pelo catálogo da Web UI. As credenciais devem ser inseridas na tela de Models,
que as armazena separadamente das configurações e não as devolve ao navegador em texto aberto.

#### DeepSeek cloud

Em **Settings → Models**, use o card DeepSeek, insira sua API key e salve. Os modelos oficiais do
Harness são:

- `deepseek-v4-flash`: primeira escolha para o teste autônomo;
- `deepseek-v4-pro`: escalada quando Flash não concluir ou quando a qualidade justificar o custo.

Consulte o preço vigente antes da execução. Use saldo pré-pago baixo, alerta ou limite financeiro
oferecido pelo provider e acompanhe a primeira sessão; uma execução autônoma em loop pode consumir
muitos tokens.

#### Ollama local

Em **Add a custom provider**, informe:

| Campo | Valor |
|---|---|
| Provider ID | `ollama` |
| Display name | `Ollama local` |
| Base URL | `http://127.0.0.1:11434/v1` |
| API protocol | `OpenAI Completions` |
| API key | `ollama` |

`ollama` é um valor fictício não secreto exigido pelo formulário. Use **Fetch available models**.
Para os modelos locais, configure quando os campos avançados estiverem disponíveis:

```text
Context window: 65536
Max output tokens: 8192
```

O GGUF declara contexto nativo de `262144`, mas o serviço deste homelab está configurado para
servir `65536`. Use `qwen3.5:latest` para tarefas gerais e `qwen3-coder:30b` para código mais
exigente. O segundo pode usar offload e será mais lento.

#### Outros providers cloud

Use **Add provider** e selecione somente providers oferecidos pela versão instalada. Anthropic e
OpenAI usam API key; Codex, Bedrock, Vertex e Azure podem exigir autenticação nativa específica.
Não passe credenciais em prompts nem as grave no projeto.

### 6. Escolha o modelo para o primeiro projeto

Para responder à pergunta “o DeepSeek Harness é autônomo?”, comece com
`deepseek-v4-flash` no preset Standard. Essa combinação avalia o Harness com o modelo oficial para
o qual ele foi desenhado e evita confundir uma limitação do modelo local com uma limitação do
produto.

Use a seguinte ordem de decisão:

| Situação | Modelo recomendado |
|---|---|
| Primeiro projeto autônomo | `deepseek-v4-flash` |
| Flash não concluiu ou entregou qualidade insuficiente | `deepseek-v4-pro` em uma sessão nova |
| Privacidade ou custo de API dominam | `qwen3.5:latest` local |
| Geração de código local mais exigente | `qwen3-coder:30b` |
| Benchmark de fronteira independente | Anthropic ou OpenAI, se já houver acesso |

Não troque de modelo no meio de uma execução usada como benchmark. Abra uma sessão nova e restaure
o projeto ao estado inicial para que a comparação seja justa.

### 7. Dê um contrato de autonomia, não uma sequência de microtarefas

Comece com uma ideia que caiba em algumas horas e tenha critério de execução objetivo. Envie um
prompt neste formato:

```text
Crie um projeto novo neste workspace com o seguinte objetivo:

[DESCREVA A IDEIA E O USUÁRIO]

Trabalhe de forma autônoma até entregar uma versão executável. Você deve:
- tomar decisões razoáveis de stack e arquitetura;
- criar o código e a configuração necessários;
- instalar dependências somente dentro do escopo deste projeto;
- escrever e executar testes;
- executar o produto e corrigir erros encontrados;
- criar um README com instalação, uso, decisões e limitações reais;
- não deixar placeholders ou TODOs no fluxo principal.

Não peça confirmação para decisões técnicas reversíveis. Pergunte apenas se faltar uma decisão de
produto que mude materialmente o resultado, se uma ação for irreversível ou se precisar sair do
workspace. Considere concluído somente quando os testes passarem e o caminho principal tiver sido
executado com sucesso.
```

Esse contrato deixa planejamento, stack e implementação para o agente, mas define uma condição de
parada verificável. Durante a primeira execução, acompanhe a sessão e interrompa ciclos que repetem
a mesma ação sem progresso.

### 8. Avalie a autonomia entregue

Ao terminar, registre:

- se o agente chegou a um produto executável;
- quantas perguntas fez;
- quantas aprovações de permissão pediu;
- testes criados, aprovados e falhos;
- quantidade de correções feitas pelo próprio agente;
- duração e custo do provider;
- comandos ou arquivos que exigiram correção manual;
- qualidade do README e facilidade para reproduzir a execução.

Revise também:

```bash
git status --short
git diff --check
git diff
```

O resultado principal não é “gerou muitos arquivos”, mas “entregou algo executável e testado sem
edição humana”.

### 9. Compare providers somente depois da primeira entrega

Se quiser tomar uma decisão entre local e cloud, repita a mesma spec em diretórios Git separados:

```text
run A: Standard + DeepSeek V4 Flash
run B: Standard + DeepSeek V4 Pro
run C: Standard + qwen3.5 ou qwen3-coder local
run D: Standard + outro frontier model, opcional
```

Compare taxa de conclusão, intervenção humana, duração, custo e qualidade. Depois disso, use o
provider que venceu para tarefas ambíguas e mantenha o local para etapas delimitadas em que ele
comprovadamente atende.

### 10. Explore Code mode e headless depois

Após validar o Standard, repita a mesma spec em Code mode para medir se a orquestração por código
reduz tool calls ou melhora a conclusão. Use headless apenas quando a execução interativa estiver
estável, pois ele é mais adequado a regressão e automação do que ao primeiro contato com um agente
autônomo.

## Critérios para continuar ou descartar

Considere o experimento autônomo aprovado quando:

- o projeto executar pelo caminho documentado;
- os testes relevantes passarem;
- não houver edição manual de código para chegar ao resultado;
- o agente tomar decisões reversíveis sem pedir aprovação a cada passo;
- perguntas humanas se limitarem a decisões materiais de produto ou segurança;
- custo e duração forem aceitáveis para o valor entregue;
- nenhuma mudança escapar do workspace ou das aprovações concedidas.

Uma falha do modelo local não reprova o Harness. Repita com DeepSeek V4 Flash ou Pro para separar
limitação do modelo de limitação do produto. Reprove o Harness como solução autônoma somente se um
modelo cloud capaz também falhar por problemas do loop, ferramentas, sessões ou permissões.

Para decidir o provider vencedor, dê maior peso à conclusão autônoma e à correção do que ao custo:

| Dimensão | Peso sugerido |
|---|---:|
| Entrega executável sem edição humana | 40% |
| Correção e testes | 25% |
| Tempo total | 15% |
| Custo | 10% |
| Segurança e previsibilidade operacional | 10% |

## Troubleshooting

### `dsh: command not found`

```bash
npm config get prefix
printf '%s\n' "$PATH"
```

O diretório `bin` do prefixo npm precisa estar no `PATH`. Neste host, o esperado é
`~/.npm-global/bin`.

### Falha relacionada a `pty.node` ou `node-pty`

Reinstale a mesma versão mantendo os scripts visíveis:

```bash
npm install -g --foreground-scripts @deepseek-ai/dsh@0.1.0-rc.7
```

O toolchain C++20 necessário já está presente neste host. Não aplique patches diretamente em
`node_modules`; eles desapareceriam na próxima instalação.

### Modelos não aparecem

```bash
curl -sS http://127.0.0.1:11434/v1/models
```

Se esse endpoint falhar, corrija o Ollama antes de alterar o Harness. Não aponte o provider para o
Snap do host.

### Provider cloud retorna erro de credencial

Cadastre novamente a chave em **Settings → Models**. Não tente resolver gravando a chave em `.env`
no projeto. As credenciais ficam em `$DSH_HOME/.credentials.yaml` e são apresentadas como campos
de escrita única na interface.

### Resposta termina antes do tool call

Aumente `Max output tokens` e use `qwen3.5:latest` ou `qwen3-coder:30b`. O `qwen3:8b` não passou
no smoke test realizado para esta avaliação.

### Agente repete ações ou o custo cresce sem progresso

Cancele a sessão na Web UI; não deixe a primeira execução autônoma rodando sem supervisão. Revise
onde o progresso parou, recomece numa sessão nova e deixe mais explícita a condição verificável de
conclusão. Mantenha também um limite financeiro fora do Harness, no provider.

### Porta 3080 ocupada

```bash
DSH_TELEMETRY_DISABLED=1 dsh web --no-open --port 3081
```

Continue usando loopback.

## Fontes oficiais

- [DeepSeek Harness — README e instalação](https://github.com/deepseek-ai/deepseek-harness)
- [Configuração de providers](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/providers.md)
- [Referência da CLI e modo headless](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md)
- [Sandbox e limites de isolamento](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/sandbox.md)
- [Política de sandbox e modo padrão](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/sandbox/sandbox-policy/README.md)
- [Workflows e subagentes](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/workflow.md)
- [Integração oficial do Ollama](https://github.com/ollama/ollama/blob/main/docs/integrations/deepseek-harness.mdx)
- [Política de processamento de dados](https://www.deepseek.com/harness/en/data-processing/)

## Diferenças para a instalação oficial

A documentação oficial propõe o menor caminho possível:

```bash
npx @deepseek-ai/dsh web
```

Depois, orienta a abrir a Web UI, informar uma chave da API DeepSeek e escolher um workspace. O
Ollama também documenta `ollama launch dsh`, que instala e configura o pacote automaticamente.

Este guia muda deliberadamente esse caminho:

| Oficial | Recomendado neste homelab | Motivo |
|---|---|---|
| `npx ...` usando a tag atual | instalação global com `0.1.0-rc.7` fixada | não depender de `latest` e tornar o baseline reprodutível |
| saída mínima do npm | `--foreground-scripts` | tornar visível a compilação de dependências nativas no Linux |
| um provider suficiente para começar | DeepSeek cloud + Ollama local, com outros providers opcionais | permitir que o usuário decida com evidência, sem impor local ou cloud |
| modelo padrão escolhido livremente | V4 Flash primeiro para autonomia; Pro como escalada; Ollama como comparação | separar a capacidade do Harness da capacidade de um modelo local menor |
| workspace existente | projeto novo, vazio e inicializado em Git | permitir autonomia ampla com revisão e rollback simples |
| permissão inicial dependente do default | Standard + `workspace-write` desde o início | permitir criar, instalar, testar e corrigir sem microaprovações |
| contexto local derivado do catálogo/modelo | `contextWindow: 65536` apenas no Ollama | refletir o limite realmente servido pelo container local |
| telemetria desativada por padrão | hard opt-out explícito por processo | tornar a decisão verificável e resistente a mudança de default |
| ecossistema de plugins disponível | nenhum plugin comunitário no baseline | evitar ampliar a cadeia de suprimentos antes de validar o core |
| sem orientação de custo para loops longos | limite financeiro externo + supervisão da primeira sessão | preservar autonomia sem risco de consumo descontrolado |
| concorrência padrão | serializar apenas modelos locais | respeitar a única GPU sem limitar providers cloud |
| `ollama launch dsh` | npm + provider manual | o Ollama local `0.32.6` ainda não lista a integração `dsh` |
| quickstart centrado na Web UI | Standard primeiro; Code mode e headless depois | testar autonomia real antes de otimizar orquestração e automação |

Portanto, este guia não propõe uma versão limitada do produto. Ele habilita a superfície autônoma
do preset Standard dentro de um projeto novo, permite escolher providers cloud ou locais e mantém
somente duas contenções: o limite de escrita do workspace e um limite financeiro externo.
