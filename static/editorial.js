(() => {
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[c]));
  const articleCard = (article) => `
    <a class="matched-article" href="${esc(article.url)}" target="_blank" rel="noopener noreferrer">
      <span>${esc(article.publisher || "Recent coverage")}</span>
      <strong>${esc(article.title)}</strong>
      ${article.summary ? `<small>${esc(article.summary)}</small>` : ""}
      ${article.match_reason ? `<small><b>Why it matches:</b> ${esc(article.match_reason)}</small>` : ""}
    </a>`;

  async function snapshot() {
    const response = await fetch("/api/bulletin", {headers:{"Accept":"application/json"}});
    if (!response.ok) return null;
    return response.json();
  }

  async function renderNeighborhoodWhy() {
    const match = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
    if (!match || document.querySelector(".why-section")) return;
    const data = await snapshot();
    const edition = data?.editions?.[match[1]];
    const editorial = edition?.editorial;
    if (!editorial) return;
    const coverage = editorial.coverage || [];
    const section = document.createElement("section");
    section.className = "why-section";
    section.id = "why";
    section.innerHTML = `
      <div class="why-layout">
        <article class="why-panel">
          <p class="section-label">THE WHY</p>
          <h2>${esc(editorial.headline)}</h2>
          <p>${esc(editorial.analysis)}</p>
          <div class="watch-box"><strong>What to watch next</strong>${esc(editorial.watch)}</div>
        </article>
        <aside class="matched-coverage">
          <p class="section-label">Recent reporting</p>
          ${coverage.length ? coverage.map(articleCard).join("") : '<p class="muted">No recent article cleared the neighborhood-match threshold. Use the Web Context searches above to explore broader coverage without forcing a weak editorial match.</p>'}
        </aside>
      </div>`;
    const anchor = document.querySelector(".quick-read") || document.querySelector(".neighborhood-front");
    if (anchor) anchor.insertAdjacentElement("afterend", section);
  }

  async function renderHomeTeaser() {
    if (window.location.pathname !== "/" || document.querySelector(".citywide-teaser")) return;
    const data = await snapshot();
    const city = data?.city_analysis;
    if (!city) return;
    const section = document.createElement("section");
    section.className = "citywide-teaser";
    section.innerHTML = `<div><p class="section-label">CITYWIDE WHY</p><h2>What is moving San Francisco this week?</h2><p>${esc(city.summary)}</p></div><a href="/city">Read citywide analysis →</a>`;
    const anchor = document.querySelector(".date-line");
    if (anchor) anchor.insertAdjacentElement("afterend", section);
  }

  renderNeighborhoodWhy().catch(() => {});
  renderHomeTeaser().catch(() => {});
})();
