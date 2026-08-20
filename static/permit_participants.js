(() => {
  const match = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
  if (!match) return;

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const searchUrl = (name) => `https://www.google.com/search?q=${encodeURIComponent(`"${name}" San Francisco development construction permit`)}`;

  const participantRows = (items, label) => {
    if (!items?.length) return `<p class="muted">No ${esc(label.toLowerCase())} are identified in the current permit-contact window.</p>`;
    return `<div class="participant-list">${items.map((item) => `<a class="participant-row" href="${searchUrl(item.name)}" target="_blank" rel="noopener noreferrer">
      <span><strong>${esc(item.name)}</strong>${item.repeat_participant ? '<em>REPEAT PARTICIPANT</em>' : ''}</span>
      <span class="participant-count"><b>${Number(item.filings || 0)}</b> neighborhood filing${Number(item.filings || 0) === 1 ? '' : 's'}${Number(item.citywide_filings || 0) > Number(item.filings || 0) ? `<small>${Number(item.citywide_filings || 0)} citywide</small>` : ''}</span>
    </a>`).join('')}</div>`;
  };

  async function render() {
    if (document.querySelector('.permit-market-section')) return;
    const response = await fetch('/api/bulletin', {headers:{Accept:'application/json'}, cache:'no-store'});
    if (!response.ok) return;
    const data = await response.json();
    const edition = data?.editions?.[match[1]];
    const market = edition?.permit_market_participants;
    if (!edition || !market) return;
    const owners = market.owners || [];
    const contractors = market.general_contractors || [];
    if (!owners.length && !contractors.length) return;

    const section = document.createElement('section');
    section.className = 'permit-market-section';
    section.innerHTML = `<div class="permit-market-head">
      <div><p class="section-label">DEVELOPMENT MARKET</p><h2>Who is filing and building in ${esc(edition.name)}?</h2><p>Repeat participants in the current seven-day permit window, counted by distinct permit filing.</p></div>
      <span>DBI permit contacts</span>
    </div>
    <div class="permit-market-grid">
      <article><p class="section-label">Owners listed on permits</p>${participantRows(owners, 'Owners')}</article>
      <article><p class="section-label">General contractors</p>${participantRows(contractors, 'General contractors')}</article>
    </div>
    <p class="permit-market-note">${esc(market.note || '')}</p>`;

    const ledger = document.querySelector('.ledger-columns-rich');
    const developmentStory = document.querySelector('#story-permits');
    const anchor = ledger || developmentStory || document.querySelector('.pulse-grid');
    anchor?.insertAdjacentElement('afterend', section);
  }

  render().catch(() => {});
})();
