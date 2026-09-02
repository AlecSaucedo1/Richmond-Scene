(() => {
  const match = window.location.pathname.match(/^\/neighborhood\/([^/]+)/);
  if (!match) return;

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const money = (value) => Number(value || 0).toLocaleString('en-US', {style:'currency', currency:'USD', maximumFractionDigits:0});
  const sourceUrl = (query, news=false) => `https://www.google.com/search?${news ? 'tbm=nws&' : ''}q=${encodeURIComponent(query)}`;

  const permitCard = (item, neighborhood) => {
    const context = Array.isArray(item.project_context) && item.project_context.length
      ? `<ul class="record-context-list">${item.project_context.filter((part) => !/^Owner listed by DBI:|^General contractor listed by DBI:/i.test(part)).map((part) => `<li>${esc(part)}</li>`).join('')}</ul>`
      : '';
    const value = item.value_summary || (item.cost ? `Project value: ${money(item.cost)}` : '');
    const meta = [
      item.filed_date ? `Filed ${item.filed_date}` : null,
      item.approved_date ? `Approved ${item.approved_date}` : null,
      item.issued_date ? `Issued ${item.issued_date}` : null,
      item.completed_date ? `Completed ${item.completed_date}` : null,
      item.status_summary || item.status,
      item.permit_number ? `Permit ${item.permit_number}` : null,
    ].filter(Boolean);
    const address = item.address || '';
    const owners = Array.isArray(item.owners) ? item.owners : [];
    const contractors = Array.isArray(item.general_contractors) ? item.general_contractors : [];
    const participants = (owners.length || contractors.length) ? `<div class="permit-participants">
      ${owners.length ? `<div><span>OWNER LISTED BY DBI</span><strong>${owners.slice(0,2).map((x) => esc(x.name)).join(' · ')}</strong>${owners[0]?.role ? `<small>DBI role: ${esc(owners[0].role)}</small>` : ''}</div>` : ''}
      ${contractors.length ? `<div><span>GENERAL CONTRACTOR LISTED BY DBI</span><strong>${contractors.slice(0,2).map((x) => esc(x.name)).join(' · ')}</strong>${contractors[0]?.role ? `<small>DBI role: ${esc(contractors[0].role)}</small>` : ''}</div>` : ''}
    </div>` : `<p class="record-source-classification">No owner/general-contractor contact is listed in the DBI permit-contact data retrieved for this filing.</p>`;
    const participantTerms = [item.owner, item.general_contractor].filter(Boolean).map((x) => `"${x}"`).join(' ');
    const webQuery = address
      ? `"${address}" San Francisco building permit ${item.permit_number ? `"${item.permit_number}"` : ''} ${participantTerms}`
      : `"${neighborhood}" San Francisco building permit ${item.permit_number || ''} ${participantTerms}`;
    const newsQuery = address
      ? `"${address}" San Francisco ${participantTerms} housing development construction planning`
      : `"${neighborhood}" San Francisco ${participantTerms} housing development construction planning`;
    const mapQuery = address ? `${address}, San Francisco` : `${neighborhood}, San Francisco`;

    return `<details class="record-item record-details enhanced-record permit-record">
      <summary>
        <span><strong>${esc(item.address || item.title)}</strong><small>${esc(item.title || 'Building permit')}${item.filed_date ? ` · filed ${esc(item.filed_date)}` : ''}</small></span>
        ${item.cost ? `<b>${money(item.cost)}</b>` : ''}
      </summary>
      <div class="record-body">
        <p class="record-scope-label">Scope of work</p>
        <p class="record-scope">${esc(item.scope_summary || item.description || 'Scope of work was not described in the public filing.')}</p>
        ${participants}
        ${context}
        ${value ? `<p class="record-value">${esc(value)}</p>` : ''}
        ${meta.length ? `<p class="record-meta">${esc(meta.join(' · '))}</p>` : ''}
        ${item.raw_title && item.raw_title !== item.title ? `<p class="record-source-classification">DBI permit type: ${esc(item.raw_title)}</p>` : ''}
        <div class="story-actions compact-actions">
          <a class="action-link" href="${sourceUrl(webQuery)}" target="_blank" rel="noopener noreferrer">Search project ↗</a>
          <a class="action-link" href="${sourceUrl(newsQuery, true)}" target="_blank" rel="noopener noreferrer">Find coverage ↗</a>
          <a class="action-link" href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(mapQuery)}" target="_blank" rel="noopener noreferrer">Map address ↗</a>
        </div>
      </div>
    </details>`;
  };

  const incidentCard = (item, neighborhood) => {
    const meta = [
      item.address ? `Near ${item.address}` : null,
      item.reported_display ? `Reported ${item.reported_display}` : null,
      item.occurred_display ? `Occurred ${item.occurred_display}` : null,
      item.report_method || item.report_type || null,
      item.status ? `Resolution at filing: ${item.status}` : null,
      item.incident_number ? `SFPD case ${item.incident_number}` : null,
    ].filter(Boolean);
    const related = Array.isArray(item.related_types) && item.related_types.length
      ? `<p class="record-related"><strong>Also classified as:</strong> ${esc(item.related_types.join(' · '))}</p>`
      : '';
    const place = item.address || neighborhood;
    const webQuery = `"${place}" San Francisco SFPD ${item.incident_number ? `"${item.incident_number}"` : item.category || ''}`;
    const newsQuery = `"${place}" San Francisco SFPD police ${item.category || ''}`;

    return `<details class="record-item record-details enhanced-record incident-record">
      <summary>
        <span><strong>${esc(item.title || 'Police incident report')}</strong><small>${item.reported_display ? `Reported ${esc(item.reported_display)}` : esc(item.address || item.category || 'SFPD incident record')}${item.occurred_display ? ` · occurred ${esc(item.occurred_display)}` : ''}</small></span>
      </summary>
      <div class="record-body">
        <p class="record-scope">${esc(item.description || "SFPD's public record does not provide a more specific plain-language incident description.")}</p>
        ${related}
        ${meta.length ? `<p class="record-meta">${esc(meta.join(' · '))}</p>` : ''}
        <p class="record-source-classification">The Bulletin sorts this section by report filing date. SFPD Resolution is fixed at the time of the report; later changes or updates are represented through supplemental reports. Incident occurrence time is shown separately. Locations are the privacy-protected intersections published by SFPD.</p>
        <div class="story-actions compact-actions">
          <a class="action-link" href="${sourceUrl(webQuery)}" target="_blank" rel="noopener noreferrer">Search case context ↗</a>
          <a class="action-link" href="${sourceUrl(newsQuery, true)}" target="_blank" rel="noopener noreferrer">Find coverage ↗</a>
        </div>
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
    policeColumn.innerHTML = `<p class="section-label">Recent police reports filed</p>${renderGroup(police, (item) => incidentCard(item, edition.name), 'No recent police reports available for this edition.')}`;
  }

  enhance().catch(() => {});
})();
