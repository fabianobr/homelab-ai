# DeepSeek Harness no Docker

O profile `harness` executa o DeepSeek Harness `0.1.0-rc.7` em uma imagem local fixa e expõe somente `127.0.0.1:3081`. O Cloudflare Tunnel é o único origin remoto permitido.

## Arquitetura e limites

- `deepseek-harness` roda como usuário sem privilégios (UID/GID 1000), com raiz somente leitura, sem GPU, socket Docker, `privileged` ou rede do host;
- `deepseek-harness-relay` compartilha somente o namespace de rede do DSH e encaminha `:8080` para o loopback `127.0.0.1:3080` do próprio DSH;
- o relay é necessário porque o upstream deliberadamente não permite `dsh web --host 0.0.0.0`;
- o volume `deepseek-harness-state` persiste sessões/configurações e pode conter credenciais de providers: nunca exporte ou versione esse volume;
- somente `DSH_WORKSPACE_DIR` é montado como `/workspace`. Não monte o checkout do homelab, `$HOME`, SSH ou socket Docker.

O Harness é *developer preview* e executa comandos gerados por modelos. Use somente workspaces descartáveis ou com Git inicializado e revise permissões, plugins e comandos. A contenção do container reduz o alcance, mas não substitui revisão humana. Veja o [aviso de segurança do upstream](https://github.com/deepseek-ai/deepseek-harness/blob/master/SAFETY.md).

## Configuração local

No `homelab.env` fora do Git, defina:

```dotenv
DSH_PUBLIC_HOSTNAME=dsh.example.com
DSH_CLOUDFLARE_ENABLED=false
DSH_WORKSPACE_DIR=/caminho/local/isolado/dsh-workspaces
```

Use um diretório pertencente ao usuário local que executa Docker. No host atual, `infra/runtime/dsh-workspaces` é ignorado pelo Git e foi preparado para esse fim. Não grave chaves de API nesse arquivo: cadastre-as na UI, acessada pelo Access.

Suba apenas o profile dedicado:

```bash
docker compose --env-file homelab.env -f infra/docker/docker-compose.yml \
  --profile harness up -d --build
```

O DSH `0.1.0-rc.7` requer iniciar seu perfil Web por `node --expose-internals`; isso está explícito no `command` do Compose porque `NODE_OPTIONS` bloqueia essa flag no Node. Não altere para `--host 0.0.0.0` e não remova `--trusted-host`.

Para registrar Ollama na UI, use `http://ollama:11434/v1`. Isso é uma conexão interna da rede Compose; Ollama não ganha hostname público.

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
