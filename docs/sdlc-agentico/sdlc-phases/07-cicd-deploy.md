# Fase 07 — CI/CD e Deploy

## O Que e Esta Fase

CI/CD e a fase de validacao automatizada e entrega do codigo produzido pelo agente. Apos a fase 06 criar os commits, o pipeline de CI/CD executa testes, verificacoes de qualidade e o deploy. O LLM local atua como:

1. **Gerador de pipeline:** cria ou atualiza YAMLs de CI/CD conforme necessario
2. **Revisor:** analisa o resultado do pipeline e identifica falhas
3. **Observador de deploy:** monitora o deploy ativo e detecta anomalias nas primeiras horas
4. **Aprovador (human-in-the-loop):** o n8n pode pausar e aguardar aprovacao antes do deploy em producao

---

## O Que o LLM Local Pode Fazer Nesta Fase

| Tarefa | Qualidade com 14B | Observacao |
|---|---|---|
| Gerar pipeline YAML (GitHub Actions) | Alta | Segue sintaxe padrao, bom com exemplos |
| Revisar pipeline existente | Alta | Identifica jobs faltando, dependencias incorretas |
| Interpretar logs de build | Alta | Explica erros de CI em linguagem clara |
| Sugerir otimizacoes de pipeline | Media | Bom para caching, paralelismo basico |
| Analisar metricas de deploy | Media | Detecta anomalias em tabelas de metricas |
| Gerar rollback automatico | Media | Pode gerar o script; revisao humana recomendada |
| Decidir se deploy e seguro | Media-Baixa | Nao confiar sozinho — usar como assistente |

---

## Pipeline de CI/CD Tipico para o Homelab

O homelab usa GitHub Actions para CI/CD, com deploy via Docker Compose nos servicos locais.

```yaml
# .github/workflows/ci.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-test.txt

      - name: Run tests
        run: pytest tests/ --tb=short --cov=src --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run gitleaks (secrets scan)
        uses: gitleaks/gitleaks-action@v2

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff
      - run: ruff check src/

  deploy:
    needs: [test, security, lint]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.HOMELAB_HOST }}
          username: ${{ secrets.HOMELAB_USER }}
          key: ${{ secrets.HOMELAB_SSH_KEY }}
          script: |
            cd /home/fabiano/homelab-ai
            git pull origin main
            docker compose up -d --build --remove-orphans
            docker compose ps
```

---

## Como o LLM Gera Pipelines YAML

System prompt para geracao de pipeline CI/CD:

```
Voce e um DevOps Engineer especializado em GitHub Actions e deploy via Docker Compose.

Ao receber a descricao de um projeto e seus requisitos de CI/CD, gere um arquivo
.github/workflows/ci.yml completo que inclua:

1. Trigger: push em main e pull_request para main
2. Jobs paralelos: test, lint, security (gitleaks para scan de secrets)
3. Job de deploy: executado apenas em push para main, apos todos os outros passarem
4. Deploy: via SSH para o homelab, usando docker compose up -d --build

Use as melhores praticas:
- Cache de dependencias (pip cache, docker layer cache quando possivel)
- Nao exponha segredos no YAML — use sempre ${{ secrets.NOME }}
- Inclua timeout em jobs longos
- Use versoes fixas de actions (nao "latest")

Produza apenas o YAML final, sem explicacoes adicionais.
```

---

## Como n8n Monitora o Pipeline

O n8n pode disparar e monitorar pipelines GitHub Actions via API:

```json
{
  "name": "Monitorar CI/CD",
  "nodes": [
    {
      "name": "Disparar Workflow",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "POST",
        "url": "https://api.github.com/repos/{{ owner }}/{{ repo }}/actions/workflows/ci.yml/dispatches",
        "headers": {
          "Authorization": "Bearer {{ GITHUB_TOKEN }}",
          "Accept": "application/vnd.github+json"
        },
        "body": {
          "ref": "main"
        }
      }
    },
    {
      "name": "Aguardar Conclusao",
      "type": "n8n-nodes-base.wait",
      "parameters": {
        "amount": 2,
        "unit": "minutes"
      }
    },
    {
      "name": "Verificar Status",
      "type": "n8n-nodes-base.httpRequest",
      "parameters": {
        "method": "GET",
        "url": "https://api.github.com/repos/{{ owner }}/{{ repo }}/actions/runs?per_page=1&branch=main",
        "headers": {
          "Authorization": "Bearer {{ GITHUB_TOKEN }}"
        }
      }
    },
    {
      "name": "IF: Pipeline passou?",
      "type": "n8n-nodes-base.if",
      "parameters": {
        "conditions": {
          "string": [{
            "value1": "{{ $json.workflow_runs[0].conclusion }}",
            "operation": "equal",
            "value2": "success"
          }]
        }
      }
    }
  ]
}
```

---

## Deploy: LLM como Observador Ativo

Nas primeiras 2 horas apos o deploy, o LLM analisa metricas e logs para detectar anomalias:

```
n8n Workflow: "07 - Deploy Monitor" (rodando a cada 5 minutos por 2 horas)

[Schedule Trigger: a cada 5 min]
     |
     v
[Execute Command: coletar metricas pos-deploy]
  - docker stats --no-stream --format "json"
  - docker logs --since 5m {{ container_name }} 2>&1 | grep -c ERROR
  - curl -s http://api:8080/health
     |
     v
[HTTP: Ollama — Analisar metricas]
  prompt: "Analise estas metricas do deploy. O deploy foi ha {{ minutos }} minutos.
           Metricas: {{ metricas }}. Ha alguma anomalia preocupante?
           Responda: STATUS (OK/ALERTA/CRITICO) e JUSTIFICATIVA em 2 linhas."
     |
     v
[IF: STATUS == CRITICO]
  |-- Sim: notificar + iniciar rollback automatico
  |-- Nao: continuar monitoramento
     |
     v
[HTTP: Langfuse — log do ciclo de monitoramento]
```

---

## Rollback Automatico

Se o LLM detectar anomalia critica, o n8n pode executar rollback:

```bash
# Script de rollback executado via Execute Command node
cd /home/fabiano/homelab-ai && \
git log --oneline -5 && \
PREV_COMMIT=$(git rev-parse HEAD~1) && \
echo "Rollback para: $PREV_COMMIT" && \
git revert --no-commit HEAD && \
docker compose up -d --build && \
echo "Rollback concluido"
```

**Importante:** rollback automatico deve ser configurado com confirmacao humana por padrao. Usar o node "Wait for Webhook" do n8n para pausar e enviar notificacao antes de executar:

```
[Detectar anomalia critica]
     |
     v
[Enviar notificacao: Telegram/Email/Webhook]
  "Deploy anomalia detectada. Aprovar rollback em 10 minutos ou cancelar."
     |
     v
[Wait for Webhook: aguardar resposta]
  timeout: 10 minutos
  on_timeout: executar rollback automaticamente
     |
     v
[IF: aprovado?] -> [Executar rollback]
[IF: cancelado?] -> [Log e continuar monitoramento]
```

---

## Integracao com GitHub Actions (Self-Hosted Runner)

Para o homelab, um runner self-hosted acelera os builds (sem fila de agentes publicos):

```bash
# Instalar GitHub Actions Runner no homelab
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64-2.317.0.tar.gz \
  -L https://github.com/actions/runner/releases/download/v2.317.0/actions-runner-linux-x64-2.317.0.tar.gz
tar xzf actions-runner-linux-x64-2.317.0.tar.gz

# Configurar (token gerado no GitHub Settings > Actions > Runners)
./config.sh --url https://github.com/OWNER/REPO --token TOKEN

# Instalar como servico systemd
sudo ./svc.sh install
sudo ./svc.sh start
```

Com runner self-hosted, o CI/CD tem acesso direto ao Docker do homelab, elimina a necessidade de SSH e acelera deploys significativamente.

---

## Criterios de Qualidade desta Fase

- [ ] Pipeline de CI passa antes de qualquer deploy em main
- [ ] Scan de secrets (gitleaks) esta configurado no pipeline
- [ ] Timeout esta configurado em todos os jobs do CI
- [ ] Deploy e monitorado por pelo menos 30 minutos apos subir
- [ ] Rollback esta documentado e testado (mesmo que manual)
- [ ] Langfuse recebe evento de conclusao do deploy com metricas basicas
