import test from "node:test";
import assert from "node:assert/strict";
import {
  isStale,
  decideAlert,
  daysSince,
  tokenEnvName,
  staleMessage,
  recoveryMessage,
} from "../src/logic.mjs";

const CFG = { interval_hours: 168, grace_hours: 24 }; // 192h = 8 dias
const NOW = new Date("2026-08-29T12:00:00Z");
const daysAgo = (n) => new Date(NOW.getTime() - n * 24 * 3600 * 1000).toISOString();

test("isStale: nunca pingou", () => {
  assert.equal(isStale(null, CFG, NOW), true);
  assert.equal(isStale(undefined, CFG, NOW), true);
  assert.equal(isStale("lixo", CFG, NOW), true);
});

test("isStale: 10 dias atrás passa do prazo de 8", () => {
  assert.equal(isStale(daysAgo(10), CFG, NOW), true);
});

test("isStale: 2 dias atrás está dentro do prazo", () => {
  assert.equal(isStale(daysAgo(2), CFG, NOW), false);
});

test("isStale: exatamente na borda (7d, cadência ok)", () => {
  assert.equal(isStale(daysAgo(7), CFG, NOW), false);
});

test("decideAlert: stale + ok -> alerta e vira alerted", () => {
  assert.deepEqual(decideAlert(true, "ok"), { alert: true, newState: "alerted" });
});

test("decideAlert: stale + alerted -> re-alerta, continua alerted", () => {
  assert.deepEqual(decideAlert(true, "alerted"), { alert: true, newState: "alerted" });
});

test("decideAlert: não-stale + alerted -> sem alerta (recuperação é no ping)", () => {
  assert.deepEqual(decideAlert(false, "alerted"), { alert: false, newState: "alerted" });
});

test("decideAlert: não-stale + ok -> nada", () => {
  assert.deepEqual(decideAlert(false, "ok"), { alert: false, newState: "ok" });
});

test("daysSince", () => {
  assert.equal(daysSince(null), null);
  assert.equal(daysSince("lixo"), null);
  assert.equal(Math.round(daysSince(daysAgo(3), NOW)), 3);
});

test("tokenEnvName", () => {
  assert.equal(tokenEnvName("carwatch"), "PING_TOKEN_CARWATCH");
  assert.equal(tokenEnvName("youtube-etl"), "PING_TOKEN_YOUTUBE_ETL");
});

test("mensagens", () => {
  assert.match(staleMessage("carwatch", daysAgo(10), CFG, NOW), /carwatch.*sem ping há 10\.0d.*≤ 8d/);
  assert.match(staleMessage("carwatch", null, CFG, NOW), /nunca pingou/);
  assert.match(recoveryMessage("carwatch"), /carwatch.*normalizados/);
});
