#!/usr/bin/env node
/**
 * Harness de teste do workflow agents/youtube-etl/workflows/01-youtube-etl.json.
 *
 * Executa o JavaScript REAL dos 5 Code nodes (extraído do JSON do workflow),
 * encadeado na mesma ordem do n8n, simulando os nós HTTP (YouTube, Ollama) e
 * o Execute Command (yt-dlp) com respostas mockadas — incluindo a semântica
 * de pareamento itemMatching(i) e o comportamento onError:continueRegularOutput
 * (erro vira item com {error}).
 */
const fs = require('fs');

const WF = JSON.parse(fs.readFileSync(require('path').join(__dirname, '..', 'workflows', '01-youtube-etl.json'), 'utf8'));
const code = {};
for (const n of WF.nodes.filter((n) => n.type === 'n8n-nodes-base.code')) {
  code[n.name] = n.parameters.jsCode;
}

const ENV = {
  YOUTUBE_API_KEY: 'fake-key',
  TELEGRAM_BOT_TOKEN: 'fake-token',
  TELEGRAM_CHAT_ID: '123456',
};

// Execução de um Code node no modo "run once for all items".
// nodeOutputs guarda a saída de cada nó já executado; como o fluxo é linear e
// os nós HTTP preservam pareamento 1:1, itemMatching(i) == items[i].
function runCode(name, inputItems, nodeOutputs, env = ENV) {
  const $input = { all: () => inputItems, first: () => inputItems[0] };
  const $ = (ref) => {
    if (!nodeOutputs[ref]) throw new Error(`Nó referenciado não executado: ${ref}`);
    return {
      itemMatching: (i) => nodeOutputs[ref][i],
      first: () => nodeOutputs[ref][0],
      all: () => nodeOutputs[ref],
    };
  };
  const fn = new Function('$input', '$env', '$', 'Buffer', code[name]);
  const out = fn($input, env, $, Buffer);
  nodeOutputs[name] = out;
  return out;
}

let falhou = false;
function assert(cond, msg) {
  console.log(`  ${cond ? 'PASS' : 'FAIL'} — ${msg}`);
  if (!cond) falhou = true;
}

const ANALISE_VALIDA = {
  assunto_principal: 'Queda de demanda de EVs nos EUA no Q2',
  demanda_estoque: 'Estoque de EVs em concessionárias subiu para 120 dias.',
  incentivos_subsidios: 'Fim do crédito federal de US$ 7.500 acelerou compras em junho.',
  metricas_performance: { cvr_taxa_conversao: 'CVR de leads caiu de 12% para 9%', ctr_cliques: null, vendas_volume: 'Vendas de EVs caíram 18% YoY' },
  insight_estrategico: 'Oportunidade em ferramentas de precificação dinâmica de usados elétricos.',
};
const ANALISE_SEM_METRICAS = {
  assunto_principal: 'Novo processo de vendas digitais',
  demanda_estoque: null,
  incentivos_subsidios: null,
  // metricas_performance ausente de propósito → deve reprovar no schema
  insight_estrategico: 'n/a',
};

// Config Canais usa Date.now() para calcular publishedAfter (janela de 7 dias);
// fixamos o relógio para os fixtures de vídeo (datas de 07-2026) não expirarem
// conforme o tempo passa.
const NOW_FIXED = new Date('2026-07-21T00:00:00Z').getTime();
function comRelogioFixo(fn) {
  const original = Date.now;
  Date.now = () => NOW_FIXED;
  try {
    return fn();
  } finally {
    Date.now = original;
  }
}

// ---------------------------------------------------------------------------
console.log('\n=== CENÁRIO A: misto (2 canais, 1 erro de API; 3 vídeos: ok / sem transcrição / JSON inválido / schema inválido) ===');
{
  const out = {};

  // 1. Config Canais
  const cfg = comRelogioFixo(() => runCode('Config Canais', [], out));
  assert(cfg.length === 6, `Config Canais emite 1 item por canal (${cfg.length})`);
  assert(/\d{4}-\d{2}-\d{2}T/.test(cfg[0].json.publishedAfter), 'publishedAfter é ISO-8601');
  assert(cfg[0].json.uploadsPlaylistId === 'UU' + cfg[0].json.channelId.slice(2), 'uploadsPlaylistId derivado do channelId (UC→UU)');

  // 2. Buscar Videos (mock, formato playlistItems.list): canal 1 responde com 3 vídeos, canal 2 falha
  out['Buscar Videos (YouTube)'] = [
    { json: { items: [
      { snippet: { resourceId: { videoId: 'vid00000001' }, title: 'EV Demand Collapse?', channelTitle: 'Brian Pasch', publishedAt: '2026-07-20T10:00:00Z' } },
      { snippet: { resourceId: { videoId: 'vid00000002' }, title: 'Dealer CVR Deep Dive', channelTitle: 'Brian Pasch', publishedAt: '2026-07-19T10:00:00Z' } },
      { snippet: { resourceId: { videoId: 'vid00000003' }, title: 'Shorts sem legenda', channelTitle: 'Brian Pasch', publishedAt: '2026-07-18T10:00:00Z' } },
      { snippet: { resourceId: { videoId: 'vid00000004' }, title: 'Fora da janela (10 dias atrás)', channelTitle: 'Brian Pasch', publishedAt: '2026-07-11T10:00:00Z' } },
      { snippet: { title: 'não é vídeo (sem resourceId)' } },
    ] } },
    { json: { error: { message: 'quotaExceeded: daily limit reached' } } },
  ];

  // 3. Extrair VideoIds
  const vids = runCode('Extrair VideoIds', out['Buscar Videos (YouTube)'], out);
  assert(vids.length === 3, `3 vídeos extraídos, fora-da-janela e sem videoId descartados (${vids.length})`);
  assert(vids[0].json.falhas.length === 1 && /ASOTU/.test(vids[0].json.falhas[0]), 'falha do canal 2 registrada com nome do canal');

  // 3.5. Agrupar VideoIds + Buscar Estatisticas (mock, formato videos.list) + Mesclar Estatisticas
  const agrupado = runCode('Agrupar VideoIds', vids, out);
  assert(agrupado.length === 1 && agrupado[0].json.videoIdsCsv === 'vid00000001,vid00000002,vid00000003', 'Agrupar VideoIds junta os ids extraídos num csv só');
  out['Buscar Estatisticas (YouTube)'] = [{ json: { items: [
    { id: 'vid00000001', statistics: { viewCount: '542000', likeCount: '12300' } },
    { id: 'vid00000002', statistics: { viewCount: '89000', likeCount: '900' } },
    { id: 'vid00000003', statistics: { viewCount: '15000' } }, // sem likeCount (curtidas ocultas pelo criador)
  ] } }];
  const merged = runCode('Mesclar Estatisticas', out['Buscar Estatisticas (YouTube)'], out);
  assert(merged.length === 3 && merged[0].json.views === 542000 && merged[0].json.likes === 12300, 'Mesclar Estatisticas junta views/likes por videoId');
  assert(merged[2].json.likes === null, 'likeCount ausente na API vira null (curtidas ocultas)');

  // 4. Obter Transcricao (mock, saída do Execute Command/yt-dlp): vid1 e vid2 com
  // legenda .vtt em stdout, vid3 sem legenda (yt-dlp falha → onError vira {error})
  out['Obter Transcricao (yt-dlp)'] = [
    { json: { exitCode: 0, stdout:
      'WEBVTT\nKind: captions\nLanguage: en\n\n' +
      '00:00:00.000 --> 00:00:02.000\nEV inventory hit 120 days supply.\n\n' +
      '00:00:02.000 --> 00:00:05.000\nLead CVR dropped from twelve to nine percent.\n' } },
    { json: { exitCode: 0, stdout:
      'WEBVTT\n\n00:00:00.000 --> 00:00:03.000\nDealers are changing their digital retail process end to end this year.\n' } },
    { json: { error: 'Command failed: yt-dlp ... exit code 1' } },
  ];

  // 5. Montar Prompt Ollama
  const prompts = runCode('Montar Prompt Ollama', out['Obter Transcricao (yt-dlp)'], out);
  assert(prompts.length === 2, `2 itens analisáveis (${prompts.length})`);
  assert(prompts[0].json.semTranscricao.length === 1 && /vid00000003/.test(prompts[0].json.semTranscricao[0]), 'vídeo sem transcrição contabilizado');
  const body0 = JSON.parse(prompts[0].json.ollamaBody);
  assert(body0.model === 'llama3.2' && body0.format === 'json' && body0.stream === false, 'body do Ollama: llama3.2 + format:json + stream:false');
  assert(body0.messages[0].role === 'system' && /Estrategista de Mercado Automotivo/.test(body0.messages[0].content), 'system prompt embutido');
  assert(/120 days supply/.test(body0.messages[1].content), 'transcrição incluída no user prompt');

  // 6. Analisar com Llama3.2 (mock): vid1 JSON válido com cercas markdown, vid2 schema inválido
  out['Analisar com Llama3.2'] = [
    { json: { message: { role: 'assistant', content: '```json\n' + JSON.stringify(ANALISE_VALIDA) + '\n```' } } },
    { json: { message: { role: 'assistant', content: JSON.stringify(ANALISE_SEM_METRICAS) } } },
  ];

  // 7. Validar JSON
  const val = runCode('Validar JSON', out['Analisar com Llama3.2'], out);
  assert(val.length === 2, 'validação preserva 1 item por análise');
  assert(val[0].json.ok === true && val[0].json.analise.assunto_principal === ANALISE_VALIDA.assunto_principal, 'JSON válido aprovado (mesmo com cercas ```json)');
  assert(val[1].json.ok === false && /metricas_performance/.test(val[1].json.erro), 'schema sem metricas_performance reprovado');

  // 8. Montar Relatorio
  const rel = runCode('Montar Relatorio', val, out);
  const md = Buffer.from(rel[0].binary.data.data, 'base64').toString('utf8');
  const tg = JSON.parse(rel[0].json.telegramBody);
  assert(/^\/data\/youtube-etl\/reports\/\d{4}-\d{2}-\d{2}-youtube-etl\.md$/.test(rel[0].json.filePath), `filePath correto (${rel[0].json.filePath})`);
  assert(/## EV Demand Collapse\?/.test(md) && /\*\*Canal:\*\* Brian Pasch/.test(md), 'relatório com título do vídeo e canal indicado');
  assert(/https:\/\/youtu\.be\/vid00000001/.test(md), 'link do vídeo no relatório');
  assert(/Views:\*\* 542\.000.*Likes:\*\* 12\.300/.test(md), 'views/likes do vídeo aparecem formatados com separador de milhar');
  assert(/Vídeos analisados: 1/.test(md) && /Sem transcrição disponível: 1/.test(md) && /JSON\/schema inválido: 1/.test(md) && /Falhas de API: 1/.test(md), 'rodapé de execução com os 4 contadores corretos');
  assert(/Insight estratégico:/.test(md) && /precificação dinâmica/.test(md), 'insight estratégico presente');
  assert(tg.chat_id === '123456' && /Brian Pasch/.test(tg.text) && tg.text.length <= 4096, 'payload do Telegram com chat_id e resumo dentro do limite');

  console.log('\n--- Trecho do relatório gerado (Cenário A) ---');
  console.log(md.split('\n').slice(0, 24).join('\n'));
  console.log('  [...]');
  console.log(md.split('\n').filter((l) => l.startsWith('- ') || l.startsWith('  - ')).join('\n'));
}

// ---------------------------------------------------------------------------
console.log('\n=== CENÁRIO B: semana vazia (nenhum vídeo novo) ===');
{
  const out = {};
  comRelogioFixo(() => runCode('Config Canais', [], out));
  out['Buscar Videos (YouTube)'] = Array(6).fill({ json: { items: [] } });
  const vids = runCode('Extrair VideoIds', out['Buscar Videos (YouTube)'], out);
  assert(vids.length === 1 && vids[0].json.semVideos === true, 'sentinela semVideos emitida');

  runCode('Agrupar VideoIds', vids, out);
  out['Buscar Estatisticas (YouTube)'] = [{ json: { error: { message: 'id parameter is required' } } }];
  const merged = runCode('Mesclar Estatisticas', out['Buscar Estatisticas (YouTube)'], out);
  assert(merged.length === 1 && merged[0].json.semVideos === true, 'Mesclar Estatisticas repassa a sentinela sem tentar buscar stats');

  // Transcript da sentinela falha (videoId undefined) → item de erro
  out['Obter Transcricao (yt-dlp)'] = [{ json: { error: 'yt-dlp: videoId ausente' } }];
  const prompts = runCode('Montar Prompt Ollama', out['Obter Transcricao (yt-dlp)'], out);
  assert(prompts.length === 1 && prompts[0].json.pularAnalise === true, 'chamada mínima ao Ollama para manter o fluxo vivo');

  out['Analisar com Llama3.2'] = [{ json: { message: { role: 'assistant', content: '{}' } } }];
  const val = runCode('Validar JSON', out['Analisar com Llama3.2'], out);
  assert(val.length === 1 && val[0].json.ok === false && !val[0].json.erro, 'sentinela atravessa a validação sem virar erro');

  const rel = runCode('Montar Relatorio', val, out);
  const md = Buffer.from(rel[0].binary.data.data, 'base64').toString('utf8');
  const tg = JSON.parse(rel[0].json.telegramBody);
  assert(/Nenhum vídeo novo encontrado/.test(md), 'relatório informa semana vazia');
  assert(/Vídeos analisados: 0/.test(md) && /JSON\/schema inválido: 0/.test(md), 'contadores zerados (sentinela não conta como inválido)');
  assert(/sem vídeos novos/.test(tg.text), 'Telegram notifica semana vazia');
}

// ---------------------------------------------------------------------------
console.log('\n=== CENÁRIO C: credencial ausente → fail-fast ===');
{
  const out = {};
  let erro = null;
  try {
    runCode('Config Canais', [], out, { ...ENV, YOUTUBE_API_KEY: '' });
  } catch (e) {
    erro = e;
  }
  assert(erro !== null && /YOUTUBE_API_KEY/.test(erro.message), `Config Canais aborta com mensagem clara (${erro && erro.message})`);
}

// ---------------------------------------------------------------------------
console.log('\n=== CENÁRIO D: truncamento de transcrição longa ===');
{
  const out = {};
  comRelogioFixo(() => runCode('Config Canais', [], out));
  out['Buscar Videos (YouTube)'] = [
    { json: { items: [{ snippet: { resourceId: { videoId: 'vidlongo0001' }, title: 'Longo', channelTitle: 'Brian Pasch', publishedAt: '2026-07-20T00:00:00Z' } }] } },
    ...Array(5).fill({ json: { items: [] } }),
  ];
  const vidsD = runCode('Extrair VideoIds', out['Buscar Videos (YouTube)'], out);
  runCode('Agrupar VideoIds', vidsD, out);
  out['Buscar Estatisticas (YouTube)'] = [{ json: { items: [{ id: 'vidlongo0001', statistics: { viewCount: '100', likeCount: '5' } }] } }];
  runCode('Mesclar Estatisticas', out['Buscar Estatisticas (YouTube)'], out);
  const vttLongo = 'WEBVTT\n\n00:00:00.000 --> 01:00:00.000\n' + 'palavra '.repeat(10000); // ~80k chars
  out['Obter Transcricao (yt-dlp)'] = [{ json: { exitCode: 0, stdout: vttLongo } }];
  const prompts = runCode('Montar Prompt Ollama', out['Obter Transcricao (yt-dlp)'], out);
  const body = JSON.parse(prompts[0].json.ollamaBody);
  assert(body.messages[1].content.length < 25000, `transcrição truncada em ~24k chars (${body.messages[1].content.length})`);
}

// ---------------------------------------------------------------------------
console.log('\n=== CENÁRIO E: relatório ordena vídeos por engajamento (views desc) ===');
{
  const out = {};
  const valFake = [
    { json: { videoId: 'vidA', titulo: 'Menos visto', canal: 'Canal X', publicadoEm: '2026-07-20T00:00:00Z', views: 1000, likes: 50, ok: true, analise: ANALISE_VALIDA } },
    { json: { videoId: 'vidB', titulo: 'Mais visto', canal: 'Canal Y', publicadoEm: '2026-07-19T00:00:00Z', views: 999000, likes: 40000, ok: true, analise: ANALISE_VALIDA } },
  ];
  const rel = runCode('Montar Relatorio', valFake, out);
  const md = Buffer.from(rel[0].binary.data.data, 'base64').toString('utf8');
  const tg = JSON.parse(rel[0].json.telegramBody);
  assert(md.indexOf('Mais visto') < md.indexOf('Menos visto'), 'vídeo com mais views aparece primeiro no relatório');
  assert(/Views:\*\* 999\.000.*Likes:\*\* 40\.000/.test(md), 'views/likes formatados com separador de milhar (pt-BR)');
  assert(tg.text.indexOf('Mais visto') < tg.text.indexOf('Menos visto'), 'resumo do Telegram também respeita a ordem por engajamento');
}

console.log(falhou ? '\n>>> RESULTADO: FALHOU' : '\n>>> RESULTADO: TODOS OS CENÁRIOS PASSARAM');
process.exit(falhou ? 1 : 0);
