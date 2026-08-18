(() => {
  const match = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
  if (!match) return;

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const money = (value) => Number(value || 0).toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
  const sourceUrl = (query) => `https://www.google.com/search?q=${encodeURIComponent(query)}`;

  const permitCard = (item, neighborhood) => {
    const context = Array.isArray(item.project_context) && item.project_context.length
      ? `<ul class="record-context-list">${item.project_context.map((part) => `<li>${esc(part)}</li>`).join('')}</ul>`
      : '';
    const value = item.value_summary || (item.cost ? `Project value: ${money(item.cost)}` : '');
    const meta = [item.filed_date ? `Filed ${item.filed_date}` : null, item.status_summary || item.status, item.permit_number ? `Permit ${item.permit_number}` : null].filter(Boolean);
    const search = sourceUrl(`${item.address || neighborhood} San Francisco building permit ${item.permit_number || ''}`);

    return `<details class="record-item record-details enhanced-record permit-record">
      <summary>
        <span><strong>${esc(item.address || item.title)}</strong><small>${esc(item.title || 'Building permit')}${item.filed_date ? ` · filed ${esc(item.filed_date)}` : ''}</small></span>
        ${item.cost ? `<b>${money(item.cost)}</b>` : ''}
      </summary>
      <div class="record-body">
        <p class="record-scope-label">Scope of work</p>
        <p class="record-scope">${esc(item.scope_summary || item.description || 'Scope of work was not described in the public filing.')}</p>
        ${context}
        ${value ? `<p class="record-value">${esc(value)}</p>` : ''}
        ${meta.length ? `<p class="record-meta">${esc(meta.join(' · '))}</p>` : ''}
        ${item.raw_title && item.raw_title !== item.title ? `<p class="record-source-classification">DBI permit type: ${esc(item.raw_title)}</p>` : ''}
        <div class="story-actions compact-actions"><a class="action-link" href="${search}" target="_blank" rel="noopener noreferrer">Find permit context ↗</a></div>
      </div>
    </details>`;
  };

  const incidentCard = (item) => {
    const metadata = Array.isArray(item.metadata) ? item.metadata : [];
    const meta = [item.address ? `Near ${item.address}` : null, ...metadata, item.incident_number ? `SFPD case ${item.incident_number}` : null].filter(Boolean);
    const related = Array.isArray(item.related_types) && item.related_types.length
      ? `<p class="record-related"><strong>Also classified as:</strong> ${esc(item.related_types.join(' · '))}</p>`
      : '';

    return `<details class="record-item record-details enhanced-record incident-record">
      <summary>
        <span><strong>${esc(item.title || 'Police incident report')}</strong><small>${esc(item.address || item.category || 'SFPD incident record')}${item.occurred_display ? ` · ${esc(item.occurred_display)}` : ''}</small></span>
      </summary>
      <div class="record-body">
        <p class="record-scope">${esc(item.description || "SFPD's public record does not provide a more specific plain-language incident description.")}</p>
        ${related}
        ${meta.length ? `<p class="record-meta">${esc(meta.join(' · '))}</p>` : ''}
        <p class="record-source-classification">Locations are the privacy-protected intersections published by SFPD.</p>
      </div>
    </details>`;
  };

  const renderGroup = (items, renderer, emptyText) => {
    if (!items.length) return `<p class="muted">${esc(emptyText)}</p>`;
    return items.slice(0, 5).map(renderer).join('');
  };

  async function enhance() {
    const response = await fetch('/api/bulletin', {headers:{Accept:'application/json'}});
    if (!response.ok) return;
    const data = await response.json();
    const edition = data?.editions?.[match[1]];
    if (!edition) return;

    const ledger = document.querySelector('.ledger-columns-rich');
    if (!ledger) return;
    const columns = ledger.querySelectorAll(':scope > div');
    const permits = edition?.notable?.permits || [];
    const police = edition?.notable?.police || [];

    if (columns[1]) {
      columns[1].innerHTML = `<p class="section-label">Development & housing filings</p>${renderGroup(permits, (item) => permitCard(item, edition.name), 'No permit records in the current source window.')}`;
    }

    let policeColumn = ledger.querySelector('[data-police-records]');
    if (!policeColumn) {
      policeColumn = document.createElement('div');
      policeColumn.dataset.policeRecords = '';
      ledger.appendChild(policeColumn);
    }
    policeColumn.innerHTML = `<p class="section-label">Recent police incident reports</p>${renderGroup(police, incidentCard, 'No recent police incident records available for this edition.')}`;
  }

  enhance().catch(() => {});
})();
