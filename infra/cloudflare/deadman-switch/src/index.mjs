// Dead man's switch para os agentes systemd do homelab-ai.
//
// - POST /ping/<agente>  (Bearer PING_TOKEN_<AGENTE>)  -> registra "estou vivo"
// - cron trigger diário                                -> alerta no Telegram se
//   algum agente passou do prazo sem pingar
//
// Estado no KV (binding DEADMAN):
//   last-ping:<agente>    timestamp ISO do último ping
//   alert-state:<agente>  "ok" | "alerted"

import {
  isStale,
  decideAlert,
  tokenEnvName,
  staleMessage,
  recoveryMessage,
} from "./logic.mjs";

function agents(env) {
  return JSON.parse(env.AGENTS || "{}");
}

function constantTimeEqual(a, b) {
  const enc = new TextEncoder();
  const ba = enc.encode(a);
  const bb = enc.encode(b);
  if (ba.length !== bb.length) return false;
  return crypto.subtle.timingSafeEqual(ba, bb);
}

async function sendTelegram(env, text) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  const resp = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: env.TELEGRAM_CHAT_ID, text }),
  });
  if (!resp.ok) {
    console.error("telegram sendMessage falhou", resp.status, await resp.text());
  }
  return resp.ok;
}

async function handlePing(agent, request, env) {
  const cfg = agents(env)[agent];
  if (!cfg) return new Response("unknown agent\n", { status: 404 });
  if (request.method !== "POST") return new Response("method not allowed\n", { status: 405 });

  const expected = env[tokenEnvName(agent)];
  const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!expected || !got || !constantTimeEqual(got, expected)) {
    return new Response("unauthorized\n", { status: 401 });
  }

  await env.DEADMAN.put(`last-ping:${agent}`, new Date().toISOString());

  // KV é consistente eventual (cache de edge ~60s). Um ping que chega segundos
  // depois de o estado virar "alerted" pode ainda ler o valor antigo e pular a
  // recuperação — irrelevante no uso real (o ping de recuperação vem dias depois
  // do alerta), some no próximo ping ou na próxima passada do cron.
  if ((await env.DEADMAN.get(`alert-state:${agent}`)) === "alerted") {
    await sendTelegram(env, recoveryMessage(agent));
    await env.DEADMAN.put(`alert-state:${agent}`, "ok");
  }

  return new Response(null, { status: 204 });
}

async function runCheck(env) {
  const now = new Date();
  const summary = [];
  for (const [agent, cfg] of Object.entries(agents(env))) {
    const lastPing = await env.DEADMAN.get(`last-ping:${agent}`);
    const state = (await env.DEADMAN.get(`alert-state:${agent}`)) || "ok";
    const stale = isStale(lastPing, cfg, now);
    const { alert, newState } = decideAlert(stale, state);
    if (alert) await sendTelegram(env, staleMessage(agent, lastPing, cfg, now));
    if (newState !== state) await env.DEADMAN.put(`alert-state:${agent}`, newState);
    summary.push({ agent, lastPing, stale, wasState: state, newState, alerted: alert });
  }
  return summary;
}

// Dispara a checagem sob demanda (mesmo efeito do cron). Útil para comprovar o
// switch sem esperar 24h. Exige o Bearer de qualquer PING_TOKEN configurado.
async function handleManualCheck(request, env) {
  if (request.method !== "POST") return new Response("method not allowed\n", { status: 405 });
  const got = (request.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  const ok = Object.keys(agents(env)).some((a) => {
    const exp = env[tokenEnvName(a)];
    return exp && got && got.length === exp.length && constantTimeEqual(got, exp);
  });
  if (!ok) return new Response("unauthorized\n", { status: 401 });
  const summary = await runCheck(env);
  return Response.json(summary);
}

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    const m = pathname.match(/^\/ping\/([a-z0-9-]+)\/?$/);
    if (m) return handlePing(m[1], request, env);
    if (pathname === "/__check") return handleManualCheck(request, env);
    if (pathname === "/" || pathname === "/health") {
      return new Response("carwatch-deadman ok\n", { status: 200 });
    }
    return new Response("not found\n", { status: 404 });
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runCheck(env));
  },
};
