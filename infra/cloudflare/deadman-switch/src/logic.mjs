// Funções puras do dead man's switch. Sem dependência do runtime Cloudflare —
// testáveis com `node --test`.

const HOUR_MS = 3600 * 1000;

/** Idade em dias de um timestamp ISO, ou null se a entrada for inválida/ausente. */
export function daysSince(iso, now = new Date()) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return (now.getTime() - t) / (24 * HOUR_MS);
}

/**
 * Um agente está "stale" quando nunca pingou ou quando o último ping passou do
 * prazo (intervalo esperado + folga).
 */
export function isStale(lastPingIso, { interval_hours, grace_hours }, now = new Date()) {
  if (!lastPingIso) return true;
  const t = Date.parse(lastPingIso);
  if (Number.isNaN(t)) return true;
  const deadlineMs = (interval_hours + grace_hours) * HOUR_MS;
  return now.getTime() - t > deadlineMs;
}

/**
 * Máquina de estados do alerta. A mensagem de recuperação NÃO sai daqui — ela é
 * disparada pelo próprio ping quando o estado está "alerted".
 *
 *   stale=true,  state="ok"       -> alerta, vai para "alerted"
 *   stale=true,  state="alerted"  -> re-alerta (cron diário; mantém visível)
 *   stale=false, qualquer estado  -> nada
 */
export function decideAlert(stale, state) {
  if (stale) return { alert: true, newState: "alerted" };
  return { alert: false, newState: state === "alerted" ? "alerted" : "ok" };
}

/** Nome do secret do token para um agente: carwatch -> PING_TOKEN_CARWATCH. */
export function tokenEnvName(agent) {
  return "PING_TOKEN_" + agent.toUpperCase().replace(/[^A-Z0-9]+/g, "_");
}

export function staleMessage(agent, lastPingIso, cfg, now = new Date()) {
  const deadlineDays = (cfg.interval_hours + cfg.grace_hours) / 24;
  const age = daysSince(lastPingIso, now);
  const ageText = age === null ? "nunca pingou" : `sem ping há ${age.toFixed(1)}d`;
  return `\u{1F534} ${agent}: ${ageText} (esperado ≤ ${deadlineDays.toFixed(0)}d). O run pode ter parado.`;
}

export function recoveryMessage(agent) {
  return `\u{1F7E2} ${agent}: pings normalizados.`;
}
