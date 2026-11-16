// Haunted Shop Analytics: deterministic seeded data, no network, no dependencies.
(() => {
  const REGIONS = ["Transylvania", "Salem", "Sleepy Hollow", "Bayou"];
  const CATEGORIES = ["Potions", "Pumpkins", "Candles"];
  const STORE = "haunted-shop-reports";

  // Seeded generator (LCG): the same data on every load, so the same filters show the same numbers.
  let seed = 31337;
  const rnd = () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;
  const ORDERS = Array.from({ length: 48 }, (_, i) => ({
    id: `#${1001 + i}`,
    region: REGIONS[Math.floor(rnd() * REGIONS.length)],
    category: CATEGORIES[Math.floor(rnd() * CATEGORIES.length)],
    total: 10 + Math.floor(rnd() * 90),
    age: Math.floor(rnd() * 30),
  }));

  const $ = (id) => document.getElementById(id);
  const money = (n) => `$${n.toFixed(0)}`;
  const reports = () => JSON.parse(localStorage.getItem(STORE) ?? "[]");

  function filtered() {
    const days = $("range").value === "Last 7 days" ? 7 : 30;
    const region = $("region").value;
    const cats = [...document.querySelectorAll('input[name="cat"]:checked')].map((c) => c.value);
    return ORDERS.filter((o) => o.age < days && (region === "All regions" || o.region === region) && cats.includes(o.category));
  }

  function render() {
    const rows = filtered();
    const revenue = rows.reduce((s, o) => s + o.total, 0);
    $("kpis").replaceChildren(
      ...[`Revenue ${money(revenue)}`, `Orders ${rows.length}`, `Average order ${money(rows.length ? revenue / rows.length : 0)}`].map((t) => {
        const li = document.createElement("li");
        li.textContent = t;
        return li;
      }),
    );
    const tbody = $("orders").tBodies[0];
    tbody.replaceChildren(
      ...rows.slice(0, 12).map((o) => {
        const tr = document.createElement("tr");
        for (const v of [o.id, o.region, o.category, money(o.total)]) tr.append(Object.assign(document.createElement("td"), { textContent: v }));
        return tr;
      }),
    );
    const byCat = CATEGORIES.map((c) => [c, rows.filter((o) => o.category === c).reduce((s, o) => s + o.total, 0)]);
    const max = Math.max(1, ...byCat.map(([, v]) => v));
    $("chart").setAttribute("aria-label", `Sales by category: ${byCat.map(([c, v]) => `${c} ${money(v)}`).join(", ")}`);
    $("chart").innerHTML =
      `<svg viewBox="0 0 300 110" width="300" height="110" aria-hidden="true">` +
      byCat.map(([c, v], i) => `<rect x="${20 + i * 90}" y="${90 - (v / max) * 70}" width="60" height="${(v / max) * 70}" fill="#CA84FC"/><text x="${20 + i * 90}" y="105">${c}</text>`).join("") +
      `</svg>`;
    const list = reports();
    $("reports").replaceChildren(
      ...list.map((r) => Object.assign(document.createElement("li"), { textContent: `${r.name} (${r.metrics.join(", ")}; ${r.format})` })),
    );
  }

  for (const id of ["range", "region"]) $(id).addEventListener("change", render);
  document.querySelectorAll('input[name="cat"]').forEach((c) => c.addEventListener("change", render));

  const dialog = $("report-dialog");
  $("open-report").addEventListener("click", () => dialog.showModal());
  $("cancel").addEventListener("click", () => dialog.close());
  $("report-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const name = $("report-name").value.trim();
    if (!name) return;
    const metrics = [...document.querySelectorAll('input[name="metric"]:checked')].map((m) => m.value);
    const format = document.querySelector('input[name="format"]:checked').value;
    localStorage.setItem(STORE, JSON.stringify([...reports(), { name, metrics, format }]));
    dialog.close();
    $("report-name").value = "";
    $("message").textContent = `Report saved: ${name}`;
    render();
  });

  $("reset").addEventListener("click", () => {
    localStorage.removeItem(STORE);
    $("range").value = "Last 30 days";
    $("region").value = "All regions";
    document.querySelectorAll('input[name="cat"]').forEach((c) => (c.checked = true));
    $("message").textContent = "";
    render();
  });

  render();
})();
