# Product Requirement Document (PRD) - Plataforma E-commerce Marketplace (v2)

## 1. Visão Geral do Produto
O objetivo deste documento é especificar o desenvolvimento de uma plataforma de e-commerce marketplace bilateral (Sellers e Buyers). O ecossistema é projetado para automação extrema, engajamento por gamificação para vendedores, motor de recomendação viciante estilo "Rabbit Hole" alimentado por inteligência artificial para compradores, e um braço de Fintech integrado com carteira digital e cartão próprio.

### 1.1 Premissas Estratégicas e Financeiras Básicas
* **Moeda Nativa:** Toda a plataforma opera estritamente em **Dólar Americano (USD)**. Preços, taxas, assinaturas, saldos e transações são processados globalmente em USD.
* **Modelo de Monetização por Transação:** Anunciar é 100% gratuito. A plataforma cobra uma comissão sobre as vendas efetuadas (10% padrão ou 8% para usuários de Ads).
* **Modelo de Monetização por Float Financeiro:** Todo o saldo líquido devido ao Seller fica retido em uma conta pool da plataforma por **8 dias corridos**. A plataforma investe este montante em ativos de liquidez imediata, retendo 100% dos lucros/rendimentos gerados pelo *float* nesse período.

---

## 2. Personas do Sistema
* **Seller (Vendedor):** Lojistas e distribuidores. Busca facilidade para anunciar, relatórios transparentes, ferramentas de marketing (Ads) e incentivos claros para crescer através de uma experiência gamificada.
* **Buyer (Comprador/Usuário Final):** Consumidor digital que busca uma experiência personalizada e imersiva, vantagens financeiras claras (Cashback e Frete Grátis) e segurança absoluta (política de devolução incondicional).

---

## 3. Arquitetura de Módulos Principais
1. **Seller Central:** Core operacional, painel de anúncios, ferramentas de gamificação e gestão de faturamento do vendedor.
2. **Buyer Hub & Motor de Recomendação (AI Engine):** Vitrine inteligente baseada em atenção, feed infinito e painel do clube de fidelidade.
3. **Fintech Core (Wallet & Payments):** Processamento de pagamentos, split de valores, gerenciamento de custódia (*float*) por 8 dias e ledger de saldos imutável.
4. **Order Management & SAC (Pós-Venda):** Logística reversa automatizada e motor de cálculo de reputação.

---

## 4. Requisitos Funcionais (RF)

### Módulo 1: Seller Central & Regras de Negócio de Vendas

#### RF1.1 – Cadastro de Anúncios e Categorização Gratuita
* **Descrição:** O Seller deve conseguir cadastrar produtos sem custo de listagem (anúncio grátis).
* **Critérios de Aceite:**
    * Upload de múltiplas fotos (limite de 10 fotos por produto, compressão automática no upload).
    * Seleção obrigatória de categoria de árvore hierárquica (Ex: Eletrônicos -> Celulares -> Acessórios).
    * Preenchimento de SKU, título, descrição técnica, preço de venda (em USD), dimensões e peso da embalagem para cálculo logístico.

#### RF1.2 – Regras de Comissão Dinâmica e Plataforma de Ads
* **Descrição:** Taxação sobre transações integradas com o módulo de anúncios patrocinados (Ads).
* **Critérios de Aceite:**
    * **Taxa Padrão:** Cobrança automática de 10% sobre o valor total do produto em toda venda concluída.
    * **Taxa Promocional (Ads Ativo):** Se o Seller possuir uma campanha de Ads ativa no período da venda, a taxa de comissão da plataforma cai para 8% sobre a venda elegível.
    * O sistema deve recalcular o split de pagamento em tempo real no momento da captura da transação.

#### RF1.3 – Dashboard de Métricas, Vendas e Faturamento
* **Descrição:** Painel analítico completo para o Seller acompanhar sua saúde financeira e comercial.
* **Critérios de Aceite:**
    * Exibição de faturamento bruto, faturamento líquido (pós-taxas), ticket médio e volume de pedidos (valores sempre em USD).
    * Gráfico de funil de conversão (Visualizações do Anúncio -> Cliques -> Adições ao Carrinho -> Vendas Concluídas).
    * Extrato financeiro com indicação clara do status do saldo: "Em Custódia/Float" (durante a janela de 8 dias) e "Disponível para Saque".

#### RF1.4 – Mecanismo de Gamificação do Vendedor
* **Descrição:** Sistema de níveis e conquistas para motivar o Seller a otimizar anúncios e vender mais.
* **Critérios de Aceite:**
    * **Sistema de Níveis:** Nível 1 (Bronze) até Nível 5 (Diamante), calculados mensalmente com base no faturamento em USD e pontuação de reputação.
    * **Missões Diárias/Semanais:** Ex: *"Cadastre 5 novos produtos com fotos em alta qualidade"*, *"Responda a 10 dúvidas de compradores em menos de 1 hora"*.
    * **Recompensas Internas:** Desbloqueio de cupons de desconto para impulsionamento em Ads, selos de destaque na vitrine e suporte prioritário.

---

### Módulo 2: Motor de Recomendação e Experiência do Comprador (Buyer Hub)

#### RF2.1 – Automação de Vitrine e Priorização por Procura
* **Descrição:** A plataforma deve priorizar organicamente na home e buscas os produtos com maior tração de mercado.
* **Critérios de Aceite:**
    * Criação de um algoritmo de score dinâmico para os produtos baseado em: `Volume de buscas nas últimas 24h (peso 4) + Conversão de vendas (peso 3) + Avaliações positivas (peso 3)`.
    * Atualização do score a cada 1 hora via job assíncrono.

#### RF2.2 – Motor de IA "Rabbit Hole" (Toca do Coelho)
* **Descrição:** Feed infinito na página principal altamente viciante e imersivo, focado na retenção e conversão do comprador.
* **Critérios de Aceite:**
    * O algoritmo rastreará: Tempo de fixação ocular/tela no card do produto, cliques, termos pesquisados, categorias navegadas e histórico de compras.
    * O feed carrega via scroll infinito produtos correlacionados ou complementares ao interesse imediato demonstrado pelo usuário.
    * **Espaços de Ads integrados:** A cada 4 produtos orgânicos no feed, 1 produto patrocinado (Ads do Seller) deve ser exibido nativamente.

---

### Módulo 3: Clube de Fidelidade (Subscription Model)

#### RF3.1 – Assinatura Mensal e Gestão de Recorrência
* **Descrição:** Programa VIP para compradores mediante pagamento recorrente.
* **Critérios de Aceite:**
    * Cobrança automática de recorrência no valor estrito de **5 USD por mês ($5.00 USD/mês)** utilizando a carteira ou cartão do usuário.
    * Painel do usuário para gerenciar assinatura, visualizar economia acumulada em fretes e histórico de cobrança.

#### RF3.2 – Benefício: Frete Grátis Condicional
* **Descrição:** Isenção de frete para assinantes ativos do clube de fidelidade.
* **Critérios de Aceite:**
    * O carrinho deve aplicar automaticamente desconto de 100% no valor do frete caso: O usuário seja assinante ativo E a soma dos produtos elegíveis no carrinho seja **maior que 21 USD (> $21.00 USD)**.

#### RF3.3 – Benefício: Cashback Unificado
* **Descrição:** Retorno financeiro sobre compras efetuadas.
* **Critérios de Aceite:**
    * Devolução automática de **1% do valor pago** em cada produto diretamente na Wallet do Buyer.
    * O saldo de cashback é liberado na conta do comprador após a janela de 7 dias do pós-venda.
    * O saldo de cashback não expira e pode ser usado para novas compras ou pagamento da assinatura.

---

### Módulo 4: Fintech Core (Wallet, Sistema de Pagamentos e Custódia)

#### RF4.1 – Gateway de Pagamento Nativo, Ledger e Regra de Float (8 dias)
* **Descrição:** Infraestrutura interna de processamento de pagamentos em USD para controle absoluto de saldos e monetização sobre o capital retido.
* **Critérios de Aceite:**
    * Processamento de transações em tempo real.
    * **Janela de Custódia (Float):** O valor líquido devido ao Seller (90% ou 92% da transação) deve permanecer retido na conta pool/garantia (*escrow*) da plataforma por **exatamente 8 dias corridos** a contar da data de confirmação da entrega do pedido.
    * **Monetização de Float:** O motor financeiro deve direcionar o saldo total em custódia para aplicações de liquidez imediata configuradas pela plataforma. Todo o rendimento gerado nesses 8 dias pertence exclusivamente à plataforma.
    * O split definitivo e a liberação para saque na Wallet do Seller ocorrem de forma automatizada no 8º dia, caso não haja contestação em aberto.

#### RF4.2 – Wallet Digital Multi-Cartões
* **Descrição:** Carteira virtual para Buyers e Sellers gerenciarem saldos e cartões em USD.
* **Critérios de Aceite:**
    * Armazenamento seguro de dados de cartões (Tokenização em conformidade com PCI-DSS).
    * **Cartão Próprio (White-label):** Emissão de cartão virtual da plataforma com aprovação de crédito baseada no volume de movimentação do usuário.
    * **Cartões de Parceiros:** Integração via API de bancos parceiros para inclusão rápida de cartões de crédito/débito de terceiros no ecossistema da wallet.

---

### Módulo 5: Pós-Venda, Logística Reversa e Reputação

#### RF5.1 – Política de Devolução Sem Critério (No-Questions-Asked)
* **Descrição:** Fluxo automatizado de devolução em até 7 dias corridos após a entrega, garantindo a conformidade com a janela de segurança financeira.
* **Critérios de Aceite:**
    * O comprador terá um botão "Solicitar Devolução Grátis" ativo na tela do pedido por até 7 dias após o status "Entregue".
    * **Sem critério:** O comprador não precisa de aprovação humana ou justificativa técnica para aprovar a devolução. Ao clicar, o sistema gera instantaneamente uma etiqueta de logística reversa.
    * Caso uma devolução seja aberta dentro dos 7 dias, o cronômetro de 8 dias do *float* do Seller é congelado imediatamente até a resolução do chamado.

#### RF5.2 – Algoritmo de Reputação do Seller
* **Descrição:** Pontuação pública do vendedor baseada na qualidade de entrega e produtos.
* **Critérios de Aceite:**
    * A reputação será medida de 0 a 5 estrelas.
    * Fórmula base do score do Seller ponderada continuamente:
        * `Média de avaliações dos compradores (peso 4)`
        * `Percentual de vendas concluídas SEM devoluções ou reclamações (peso 6)`
    * Sellers com reputação abaixo de 3.5 recebem penalidades: Perda de posições na busca orgânica e suspensão temporária do direito de participar de campanhas de Ads.

---

## 5. Requisitos Não-Funcionais (RNF)

* **RNF1 – Segurança de Dados:** Criptografia de ponta a ponta (AES-256) em dados sensíveis de pagamento e total conformidade com a LGPD/GDPR e padrões PCI-DSS.
* **RNF2 – Performance (Latência do Feed):** O feed de recomendação "Rabbit Hole" deve carregar novos itens em menos de 200ms para garantir fluidez total na experiência de rolagem infinita.
* **RNF3 – Escrituração Contábil (Ledger):** O microsserviço de Fintech deve manter logs imutáveis e auditáveis de todo o rendimento gerado pelo *float* das contas de garantia antes do repasse aos Sellers.
* **RNF4 – Escalabilidade:** Arquitetura baseada em microsserviços escaláveis horizontalmente para suportar picos de tráfego sem degradação do checkout.

---

## 6. Fluxo de Fundos e Linha do Tempo do Dinheiro (Split de Pagamento)

```
[Dia 0] Buyer Efetua Compra: $100 USD
           │
           ▼
[Fintech Core Gateway] ──► Retém Comissão Imediata (Ex: 10%): $10 USD
           │
           ▼
[Conta de Garantia / Escrow Pool] -> $90 USD retidos por 8 dias
           │
           ├──► [DIAS 1 ao 8]: Plataforma monetiza e retém 100% do rendimento (Float)
           │
           ▼
[Dia 7] Fim do prazo de Devolução Sem Critério do Comprador
           │
           ▼
[Dia 8] Liberação Automática do Saldo Contábil
           │
           ├──► [Buyer Wallet]: Libera $1.00 USD (1% Cashback)
           └──► [Seller Wallet Account]: Libera $90.00 USD para saque imediato
```

---
*Fim da Especificação Técnica de Produto.*