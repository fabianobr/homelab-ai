import net from 'node:net';

const listenPort = Number.parseInt(process.env.RELAY_LISTEN_PORT ?? '8080', 10);
const targetPort = Number.parseInt(process.env.DSH_PORT ?? '3080', 10);

if (!Number.isInteger(listenPort) || !Number.isInteger(targetPort)) {
  throw new Error('RELAY_LISTEN_PORT and DSH_PORT must be valid port numbers');
}

const server = net.createServer((client) => {
  const upstream = net.connect({host: '127.0.0.1', port: targetPort});
  client.pipe(upstream);
  upstream.pipe(client);

  const close = () => {
    client.destroy();
    upstream.destroy();
  };

  client.on('error', close);
  upstream.on('error', close);
});

server.on('error', (error) => {
  console.error(`deepseek-harness relay failed: ${error.message}`);
  process.exitCode = 1;
});

server.listen({host: '0.0.0.0', port: listenPort}, () => {
  console.log(`deepseek-harness relay listening on :${listenPort}`);
});

const shutdown = () => server.close(() => process.exit(0));
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
