# Mercado Loop

Marketplace two-sided (buyers × sellers) MVP — **primeiro app não-toy gerado pelo
[pipeline SDLC Híbrido](../sdlc-hibrido/).** É a prova de que o pipeline vai além de TODO CRUDs.

A spec original que originou este app está em `api/sdlc-spec-20260620163903.md`.
O código foi gerado automaticamente em 2026-06-20 via WF1 (Discovery/Claude Sonnet),
WF5 (Test Agent/Ollama) e WF3 (Code Agent/Ollama). Ver
[`../sdlc-hibrido/VIABILITY-REPORT.md`](../sdlc-hibrido/VIABILITY-REPORT.md) para métricas.

## Estrutura

- `api/`: backend FastAPI com regras de marketplace, seller central, checkout, wallet, logisticas, devolucao, antifraude, readiness e smoke. Inclui `sdlc-spec-20260620163903.md` (spec de origem) e `test_main.py` (testes gerados pelo Test Agent).
- `index.html` + `app.js` + `styles.css` + `sw.js`: PWA mobile-first para comprador, seller central e operacao. Instalavel como app web.

## Rodar local

Em um terminal:

```bash
cd products/marketplace/api
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8010
```

Em outro terminal (frontend):

```bash
cd products/marketplace
python3 -m http.server 8020 --bind 127.0.0.1
```

Abrir:

```text
http://127.0.0.1:8020/index.html
```

## Validar

```bash
cd marketplace/api
python3 -m pytest -q
curl http://127.0.0.1:8010/launch/readiness
```

No app, use:

- `Sincronizar API` para criar o cenario sandbox de demo.
- `Carrinho` para simular checkout com wallet ou cartao parceiro.
- `Seller Central` para criar/pausar produtos e ver metricas.
- `Operacao` para readiness, smoke e metricas de checkout.

## Escopo MVP atual

- Catalogo, anuncios, edicao e pausa de produtos.
- Seller Central com metricas, comissao e reputacao.
- Checkout sandbox com wallet, cartao parceiro, antifraude e eventos.
- Fidelidade com cashback e frete gratis acima do limite.
- Logistica sandbox com cotacao, despacho e tracking.
- Devolucao em ate 7 dias.
- Feed/recomendacao rastreavel em modo MVP.
- Readiness e smoke operacional local.
- PWA instalavel como app web.

## Backlog pos-MVP

- Banco relacional modelado com migracoes.
- Auth/JWT completo, MFA real e perfis de acesso.
- Integracoes reais de pagamento, antifraude, transportadoras e notificacao.
- Financeiro de repasse, nota/invoice, conciliação e chargeback.
- App nativo em Expo/React Native reaproveitando contratos da API.
- CI/CD, observabilidade e ambientes staging/producao.
