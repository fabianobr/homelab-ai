const API = "http://127.0.0.1:8010";

const store = {
  products: [
    { id: 1, title: "Smart Camera Pro", category: "electronics", price: 120, score: 94, sku: "CAM-PRO-1", active: true },
    { id: 2, title: "Wallet Dock", category: "electronics", price: 64, score: 88, sku: "DOCK-1", active: true },
    { id: 3, title: "Home Sensor Kit", category: "home", price: 89, score: 81, sku: "HOME-1", active: true },
    { id: 4, title: "Creator Light", category: "home", price: 45, score: 76, sku: "LIGHT-1", active: true }
  ],
  cart: [],
  sales: 0,
  commission: 0,
  reputation: 100,
  launchReady: false
};

function money(value) {
  return `$${Number(value).toFixed(2)}`;
}

function toast(message) {
  const el = document.querySelector("#toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2400);
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(data.detail || response.statusText);
  return data;
}

function switchView(view) {
  document.querySelectorAll(".nav").forEach(button => button.classList.toggle("active", button.dataset.view === view));
  document.querySelectorAll(".view").forEach(section => section.classList.toggle("active", section.id === view));
}

function renderProducts(filter = "all") {
  const grid = document.querySelector("#productGrid");
  const products = store.products.filter(product => filter === "all" || product.category === filter);
  grid.innerHTML = products.map(product => `
    <article class="product-card">
      <div class="product-art"></div>
      <div class="product-body">
        <div class="product-meta"><span>${product.category}</span><span>Score ${product.score}</span></div>
        <h3>${product.title}</h3>
        <div class="product-meta"><strong>${money(product.price)}</strong><span>Frete integrado</span></div>
        <button class="primary" data-add="${product.id}">Adicionar</button>
      </div>
    </article>
  `).join("");
}

function renderCart() {
  document.querySelector("#cartCount").textContent = store.cart.length;
  const items = document.querySelector("#cartItems");
  if (!store.cart.length) {
    items.innerHTML = "<p>Seu carrinho esta vazio.</p>";
  } else {
    items.innerHTML = store.cart.map(product => `
      <div class="cart-line">
        <span>${product.title}</span>
        <strong>${money(product.price)}</strong>
      </div>
    `).join("");
  }
  const total = store.cart.reduce((sum, product) => sum + product.price, 0);
  document.querySelector("#cartTotal").textContent = money(total);
}

function renderSeller() {
  const activeProducts = store.products.filter(product => product.active);
  document.querySelector("#metricSales").textContent = store.sales;
  document.querySelector("#metricCommission").textContent = money(store.commission);
  document.querySelector("#metricReputation").textContent = store.reputation;
  document.querySelector("#metricProducts").textContent = activeProducts.length;
  document.querySelector("#sellerTable").innerHTML = store.products.map(product => `
    <tr>
      <td>${product.title}</td>
      <td>${money(product.price)}</td>
      <td>${product.active ? "Ativo" : "Pausado"}</td>
      <td><button data-pause="${product.id}">${product.active ? "Pausar" : "Ativar"}</button></td>
    </tr>
  `).join("");
}

function renderOps(data = null) {
  const ready = document.querySelector("#readinessBadge");
  const isReady = data?.ready ?? store.launchReady;
  ready.textContent = isReady ? "Pronto local" : "Pendente";
  ready.className = `status ${isReady ? "ok" : "warn"}`;
}

async function syncFromApi() {
  try {
    const demo = await api("/demo/investor-seed", { method: "POST" });
    store.sales = demo.seller_central.sales_count;
    store.commission = Number(demo.seller_central.commission_retained);
    store.reputation = Number(demo.reputation.reputation_score);
    store.launchReady = demo.readiness.ready;
    renderSeller();
    renderOps(demo.readiness);
    toast("API sincronizada com fluxo sandbox");
  } catch (error) {
    toast(`API indisponivel: ${error.message}`);
  }
}

async function runCheckout(method) {
  if (!store.cart.length) {
    toast("Adicione um produto antes do checkout");
    return;
  }
  const total = store.cart.reduce((sum, product) => sum + product.price, 0);
  try {
    await api("/buyers", { method: "POST", body: JSON.stringify({ name: "Buyer App" }) }).catch(() => null);
    const result = await api("/checkout", {
      method: "POST",
      body: JSON.stringify({
        buyer_id: "Buyer123",
        payment_method: method,
        gateway: "partner_a",
        total_amount: total,
        items: store.cart.map(product => ({ item_id: product.id, quantity: 1 })),
        shipping_address: "Rua Produto 100",
        risk_score: 10
      })
    });
    store.sales += 1;
    store.commission += total * 0.1;
    store.cart = [];
    renderCart();
    renderSeller();
    document.querySelector("#cartDialog").close();
    toast(`Checkout aprovado: pedido ${result.order_id}`);
  } catch (error) {
    toast(`Falha no checkout: ${error.message}`);
  }
}

async function refreshOps() {
  try {
    const readiness = await api("/launch/readiness");
    const smoke = await api("/ops/smoke", { method: "POST" });
    const metrics = await api("/ops/checkout/metrics");
    renderOps(readiness);
    document.querySelector("#smokeChecks").innerHTML = Object.entries(smoke.checks).map(([key, value]) => `
      <div class="check">${key}: <strong>${value ? "OK" : "Pendente"}</strong></div>
    `).join("");
    document.querySelector("#opsTotal").textContent = metrics.total;
    document.querySelector("#opsApproved").textContent = metrics.approved;
    document.querySelector("#opsBlocked").textContent = metrics.blocked;
    document.querySelector("#opsRate").textContent = `${Math.round(metrics.approval_rate * 100)}%`;
  } catch (error) {
    toast(`Operacao indisponivel: ${error.message}`);
  }
}

document.querySelectorAll(".nav").forEach(button => {
  button.addEventListener("click", () => switchView(button.dataset.view));
});

document.querySelectorAll(".segmented button").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segmented button").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    renderProducts(button.dataset.filter);
  });
});

document.addEventListener("click", event => {
  const addId = event.target.dataset.add;
  if (addId) {
    const product = store.products.find(item => item.id === Number(addId));
    store.cart.push(product);
    renderCart();
    toast(`${product.title} adicionado`);
  }
  const pauseId = event.target.dataset.pause;
  if (pauseId) {
    const product = store.products.find(item => item.id === Number(pauseId));
    product.active = !product.active;
    renderSeller();
  }
});

document.querySelector("#openCart").addEventListener("click", () => document.querySelector("#cartDialog").showModal());
document.querySelector("#payCard").addEventListener("click", () => runCheckout("partner_card"));
document.querySelector("#payWallet").addEventListener("click", () => runCheckout("wallet"));
document.querySelector("#syncApi").addEventListener("click", syncFromApi);
document.querySelector("#runSmoke").addEventListener("click", refreshOps);
document.querySelector("#primeToggle").addEventListener("click", () => toast("Fidelidade ativa: frete gratis acima de $21 e 1% cashback"));
document.querySelector("[data-scroll='feed']").addEventListener("click", () => document.querySelector("#feed").scrollIntoView());
document.querySelector("#publishProduct").addEventListener("click", () => {
  const product = {
    id: Date.now(),
    title: document.querySelector("#sellerTitle").value,
    category: document.querySelector("#sellerCategory").value.toLowerCase().includes("home") ? "home" : "electronics",
    price: Number(document.querySelector("#sellerPrice").value),
    score: 72,
    sku: document.querySelector("#sellerSku").value,
    active: true
  };
  store.products.unshift(product);
  renderProducts();
  renderSeller();
  toast("Anuncio publicado sem taxa");
});
document.querySelector("#simulateSale").addEventListener("click", () => {
  store.sales += 1;
  store.commission += 12;
  renderSeller();
  toast("Venda simulada no Seller Central");
});
document.querySelector("#enableLaunch").addEventListener("click", async () => {
  await api("/launch/environments/production/deploy", { method: "POST", body: JSON.stringify({ deployed: true, healthy: true }) });
  await api("/launch/finance", { method: "POST", body: JSON.stringify({ invoice_enabled: true, payouts_enabled: true, repasse_cycle_days: 3 }) });
  await api("/launch/security/mfa", { method: "POST", body: JSON.stringify({ mfa_required: true, mfa_for_sellers: true, mfa_for_finance: true }) });
  await refreshOps();
  toast("Go-live local habilitado");
});

renderProducts();
renderCart();
renderSeller();
refreshOps();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {
      toast("Service worker indisponivel neste navegador");
    });
  });
}
