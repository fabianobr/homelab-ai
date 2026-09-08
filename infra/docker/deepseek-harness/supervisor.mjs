/**
 * Entrypoint do container `deepseek-harness`: roda o DSH web e o relay TCP no
 * MESMO container, e derruba o container inteiro se qualquer um dos dois cair.
 *
 * Por que o relay existe
 * ----------------------
 * O upstream recusa `dsh web --host 0.0.0.0` de propósito ("it would expose
 * remote code execution to the network"), então o DSH só escuta em
 * `127.0.0.1:<port>`. Docker publica porta via DNAT para o IP do container, que
 * nunca alcança o loopback do processo — daí um relay que escuta em
 * `0.0.0.0:8080` dentro do namespace e encaminha para o loopback do DSH.
 *
 * Por que ele mora AQUI e não num sidecar
 * ---------------------------------------
 * O sidecar antigo (`deepseek-harness-relay`) usava `network_mode:
 * service:deepseek-harness`. O Docker resolve isso para o *ID* do container
 * alvo no momento da criação e grava `container:<ID>` em `HostConfig.NetworkMode`.
 * Recriar o `deepseek-harness` (qualquer mudança de mount, imagem ou command)
 * deixava o sidecar preso a um ID morto: ele sobrevivia até o próximo boot e
 * então morria com `No such container: <ID antigo>`, deixando a porta publicada
 * sem ninguém escutando — enquanto o healthcheck do DSH, que sondava o loopback
 * de dentro do próprio container, seguia verde. Um processo no mesmo container
 * não tem esse vínculo por ID: não há o que apontar para um container morto.
 *
 * O preço é ter dois processos sem supervisor de verdade, e é exatamente por
 * isso que este arquivo existe: um container "up" com o relay morto seria a
 * mesma mentira que estamos consertando. Aqui, a morte de qualquer um dos dois
 * mata o processo 1, o container sai, e `restart: unless-stopped` o traz de
 * volta. `init: true` no Compose põe o tini como PID 1 para colher os netos
 * órfãos que as ferramentas do DSH deixam.
 *
 * Uso:
 *   node supervisor.mjs <comando do DSH...>
 *
 * O argv do DSH vem inteiro do `command` do Compose — este arquivo não sabe nem
 * decide como o DSH é invocado. A porta do upstream é lida do `--port` desse
 * mesmo argv (com fallback para `DSH_PORT`), para que mudar a porta no Compose
 * não deixe o relay encaminhando para a porta antiga em silêncio.
 */
import net from 'node:net';
import {spawn} from 'node:child_process';

/** Prazo máximo para o filho sair sozinho antes de forçarmos `process.exit`. */
const FORCE_EXIT_MS = 10_000;

const childArgv = process.argv.slice(2);
if (childArgv.length === 0) {
  console.error('supervisor: falta o comando do DSH (uso: node supervisor.mjs <cmd...>)');
  process.exit(2);
}

/**
 * Lê um número de porta, falhando alto: uma porta inválida aqui vira um relay
 * que escuta no lugar errado, que é justamente o modo de falha silencioso que
 * este arquivo existe para não ter.
 */
function parsePort(raw, label) {
  const port = Number.parseInt(raw, 10);
  if (!Number.isInteger(port) || port < 0 || port > 65_535) {
    console.error(`supervisor: ${label} inválido: ${raw}`);
    process.exit(2);
  }
  return port;
}

/** Extrai `--port N` / `--port=N` do argv do DSH; `undefined` se não houver. */
function upstreamPortFromArgv(argv) {
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--port' && i + 1 < argv.length) return argv[i + 1];
    if (arg.startsWith('--port=')) return arg.slice('--port='.length);
  }
  return undefined;
}

const listenPort = parsePort(process.env.RELAY_LISTEN_PORT ?? '8080', 'RELAY_LISTEN_PORT');
const targetPort = parsePort(
  upstreamPortFromArgv(childArgv) ?? process.env.DSH_PORT ?? '3080',
  'porta do DSH',
);

/** Estado da saída: 0 = ainda saudável; != 0 = já decidimos que é falha. */
let failureCode = 0;
/** true quando a saída foi pedida por sinal (parada limpa, não falha). */
let stopRequested = false;

const child = spawn(childArgv[0], childArgv.slice(1), {stdio: 'inherit'});

const server = net.createServer((client) => {
  const upstream = net.connect({host: '127.0.0.1', port: targetPort});
  client.pipe(upstream);
  upstream.pipe(client);

  // Erro de uma conexão isolada não é falha do serviço: durante o boot do DSH
  // as primeiras conexões levam ECONNREFUSED e isso é normal.
  const close = () => {
    client.destroy();
    upstream.destroy();
  };

  client.on('error', close);
  upstream.on('error', close);
});

/** Marca falha, pede a parada do filho e garante a saída mesmo se ele travar. */
function fail(code, message) {
  if (failureCode !== 0) return;
  failureCode = code;
  console.error(`supervisor: ${message}`);
  server.close();
  child.kill('SIGTERM');
  setTimeout(() => process.exit(failureCode), FORCE_EXIT_MS);
}

child.on('error', (error) => {
  fail(1, `não consegui executar o DSH (${childArgv[0]}): ${error.message}`);
});

child.on('exit', (code, signal) => {
  server.close();
  if (failureCode !== 0) process.exit(failureCode);
  if (stopRequested) process.exit(0);
  // O DSH é um serviço de vida longa: sair, mesmo com 0, é falha.
  console.error(`supervisor: o DSH web terminou (code=${code}, signal=${signal}) — derrubando o container`);
  process.exit(typeof code === 'number' && code !== 0 ? code : 1);
});

server.on('error', (error) => {
  fail(1, `o relay falhou: ${error.message}`);
});

server.listen({host: '0.0.0.0', port: listenPort}, () => {
  console.log(`supervisor: relay escutando em :${listenPort} -> 127.0.0.1:${targetPort}`);
});

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => {
    if (stopRequested || failureCode !== 0) return;
    stopRequested = true;
    server.close();
    child.kill(signal);
    setTimeout(() => process.exit(0), FORCE_EXIT_MS);
  });
}
