# Releases do contrato media-pipeline

O pipeline consome somente tags SemVer exatas do `homelab-ai`. A primeira
release planejada para `contract_version: 1` é `v1.0.0`. A tag só deve ser
criada depois que o commit correspondente passar por:

```bash
pre-commit run --all-files
bash infra/scripts/check-public-ready.sh
docker compose --env-file .env.media-pipeline.example \
  -f infra/docker/docker-compose.yml --profile media-pipeline config
```

Também é obrigatório testar o preparo duas vezes em um diretório temporário e
validar a integração contra a release correspondente do
`media-meme-pipeline`. Mudanças incompatíveis em caminhos, serviços, variáveis
ou semântica do contrato incrementam a versão major do contrato e do homelab.
Imagens de serviços fora do profile `media-pipeline` têm ciclo operacional
independente e não fazem parte deste contrato.

O consumidor deve executar:

```bash
bash infra/scripts/check-media-pipeline-contract.sh \
  --expected-tag v1.0.0 --expected-contract 1
```

Esse comando não faz `checkout`, `pull` ou limpeza automática. O override
`--allow-unsupported` existe apenas para desenvolvimento e deve ficar visível
nos logs.
