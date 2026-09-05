# DeepSeek Harness no Docker

O profile `harness` executa o DeepSeek Harness `0.1.0-rc.7` em uma imagem local fixa e expõe somente `127.0.0.1:3081`. O Cloudflare Tunnel é o único origin remoto permitido.

## Arquitetura e limites

- `deepseek-harness` roda como usuário sem privilégios (UID/GID 1000), com raiz somente leitura, sem GPU, socket Docker, `privileged` ou rede do host;
- `deepseek-harness-relay` compartilha somente o namespace de rede do DSH e encaminha `:8080` para o loopback `127.0.0.1:3080` do próprio DSH;
- o relay é necessário porque o upstream deliberadamente não permite `dsh web --host 0.0.0.0`;
- o volume `deepseek-harness-state` persiste sessões/configurações e pode conter credenciais de providers: nunca exporte ou versione esse volume;
- dois diretórios são bind mounts para o host, ambos ignorados pelo Git e pertencentes ao usuário local (UID 1000):
  - `DSH_WORKSPACE_DIR` → `/workspace`;
  - `DSH_STORAGES_DIR` → `/dsh-home/storages`, onde o DSH web grava os projetos gerados no chat ("storages"). Isso torna cada arquivo gerado acessível fora do volume; antes ele ficava preso em `deepseek-harness-state`.
- não monte o checkout do homelab, `$HOME`, SSH, socket Docker nem `/dsh-home` inteiro (esconderia `.credentials.yaml`). O bind é só no subpath `storages`, que não guarda segredos — mas o modelo pode escrever qualquer coisa nele, então trate como diretório não confiável.

O Harness é *developer preview* e executa comandos gerados por modelos. Use somente workspaces descartáveis ou com Git inicializado e revise permissões, plugins e comandos. A contenção do container reduz o alcance, mas não substitui revisão humana. Veja o [aviso de segurança do upstream](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md).

## Configuração local

No `homelab.env` fora do Git, defina:

```dotenv
DSH_PUBLIC_HOSTNAME=dsh.example.com
DSH_CLOUDFLARE_ENABLED=false
DSH_WORKSPACE_DIR=/caminho/local/isolado/dsh-workspaces
DSH_STORAGES_DIR=/caminho/local/isolado/dsh-storages
```

Use um diretório pertencente ao usuário local que executa Docker. No host atual, `infra/runtime/dsh-workspaces` e `infra/runtime/dsh-storages` são ignorados pelo Git e foram preparados para esse fim (`infra/runtime/*` está no `.gitignore`). Não grave chaves de API nesse arquivo.

Suba apenas o profile dedicado:

```bash
docker compose --env-file homelab.env -f infra/docker/docker-compose.yml \
  --profile harness up -d --build
```

O DSH `0.1.0-rc.7` requer iniciar seu perfil Web por `node --expose-internals`; isso está explícito no `command` do Compose porque `NODE_OPTIONS` bloqueia essa flag no Node. Não altere para `--host 0.0.0.0` e não remova `--trusted-host`.

Para registrar Ollama na UI, use `http://ollama:11434/v1`. Isso é uma conexão interna da rede Compose; Ollama não ganha hostname público.

### Ver os arquivos gerados no chat (`dsh-files`)

O botão "abrir arquivo" da UI web chama `/api/host.openPath`, que o upstream
bloqueia fora de origem loopback (retorna `HTTP 403` pelo hostname público) e que
não teria como abrir nada dentro do container. O caminho suportado para
visualizar/baixar é o serviço `dsh-files` (mesmo profile `harness`):

- `nginxinc/nginx-unprivileged` somente-leitura, roda como UID 1000 (mesmo dono
  dos arquivos que o DSH grava em `0600`), monta `DSH_STORAGES_DIR` como `:ro` e
  escuta em `127.0.0.1:3082`;
- `infra/docker/dsh-files/` traz `default.conf` e `index.html`. O nginx serve a
  listagem em JSON (`/api/ls/…`, via `autoindex_format json`) e o `index.html`
  (SPA) ordena por data desc e formata o horário no fuso do browser — o
  `autoindex` HTML puro não faz nem uma coisa nem outra. Arquivos crus saem por
  `/raw/…`;
- `workspace.json` e `session_projcache.json` (estado interno do DSH) são
  retornados como 404 e escondidos da listagem;
- é só leitura — nunca é caminho de escrita e não substitui o bind mount;
- serve tanto em `/` (uso local direto, `127.0.0.1:3082`) quanto em `/files/`
  (uso público — mesmo conteúdo, prefixo diferente para caber no roteamento
  por path abaixo);
- para acesso remoto, **não crie um hostname novo**: a rota entra por path sob
  o hostname que o DSH web já usa (`dsh.<domínio>`), reaproveitando o mesmo
  app/policy de Cloudflare Access — nada de segundo app pra manter:

  ```bash
  sudo env DSH_PUBLIC_HOSTNAME=dsh.example.com \
    bash infra/scripts/add-dsh-files-path-ingress.sh
  ```

  O script insere a regra de `path: ^/files($|/.*)` **antes** da regra sem
  path do mesmo hostname (o cloudflared casa de cima pra baixo e para na
  primeira que bate — a ordem é o que faz `/files/...` cair no dsh-files e o
  resto continuar caindo no DSH web). Requer que o ingress de
  `DSH_PUBLIC_HOSTNAME` já exista. Resultado:
  `https://dsh.example.com/files/` → dsh-files.

### Administração de providers

Configure ou edite providers, modelos e chaves pela UI local no host:

```text
http://localhost:3081
```

O upstream restringe deliberadamente o plano de configurações (`Models`,
credenciais e plugins) a uma origem loopback. Por isso, em
`https://dsh.example.com` a aba **Models** pode informar que as configurações
não estão disponíveis neste navegador. Isso é esperado: o hostname público,
mesmo protegido por Cloudflare Access, serve para usar o Harness e não para
administrar credenciais. Não remova essa proteção por proxy, patch ou
exposição de API.

### Migrar configuração já existente

Se o DSH já era usado no host antes da migração, o estado em `~/.dsh` contém
`settings.yaml` (providers) e `.credentials.yaml` (chaves). Copie os dois arquivos
uma vez para o volume Docker sem imprimi-los nem versioná-los:

```bash
docker exec -i deepseek-harness sh -lc \
  'umask 077; cat > /dsh-home/settings.yaml; chmod 600 /dsh-home/settings.yaml' \
  < ~/.dsh/settings.yaml
docker exec -i deepseek-harness sh -lc \
  'umask 077; cat > /dsh-home/.credentials.yaml; chmod 600 /dsh-home/.credentials.yaml' \
  < ~/.dsh/.credentials.yaml
docker exec deepseek-harness sh -lc \
  "sed -i 's#http://127.0.0.1:11434/v1#http://ollama:11434/v1#g' /dsh-home/settings.yaml"
docker restart deepseek-harness deepseek-harness-relay
```

Os arquivos ficam no volume `deepseek-harness-state`, pertencentes ao usuário sem
privilégios do container e em modo `0600`. Não os copie para o repositório, para
um bind mount do projeto, nem para logs de diagnóstico.

A conversão do endpoint é necessária somente no Docker: no host legado,
`127.0.0.1:11434` aponta para Ollama; dentro do container, aponta para o próprio
DSH. O nome `ollama` resolve o container irmão na rede Compose.

## Cloudflare (manual, depois do deploy local)

1. Em **Zero Trust → Access controls → Applications**, crie a aplicação *Self-hosted* para o valor de `DSH_PUBLIC_HOSTNAME` e uma política `Allow` só para a identidade autorizada, com MFA e sessão curta.
2. Com a aplicação Access pronta, aplique o ingress localmente pelo script idempotente, que insere a rota antes do catch-all, valida o YAML e só então reinicia o Tunnel:

   ```bash
   sudo env DSH_PUBLIC_HOSTNAME=dsh.example.com \
     bash infra/scripts/add-dsh-cloudflared-ingress.sh
   ```

3. Só então altere `DSH_CLOUDFLARE_ENABLED=true` no `homelab.env` e rode `bash infra/scripts/healthcheck.sh`.
4. Confirme que o DNS aponta ao Tunnel, que usuário anônimo/não permitido é negado e que a identidade permitida conclui MFA. Teste a UI, Settings e WebSockets pelo hostname.

Não abra porta no roteador, não crie NAT e não aponte DNS para o IP do host.

## Verificação e rollback

```bash
docker compose --env-file homelab.env -f infra/docker/docker-compose.yml \
  --profile harness ps
curl -fsSI http://127.0.0.1:3081/
docker port deepseek-harness
```

Em uma falha, remova/desative primeiro a rota do Tunnel e a política Access; depois pare apenas este profile. Preserve os volumes para diagnóstico e apague-os somente após revisar se contêm sessões, credenciais ou workspaces.

```bash
docker compose --env-file homelab.env -f infra/docker/docker-compose.yml \
  --profile harness stop
```
