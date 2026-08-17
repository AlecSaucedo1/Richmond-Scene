(() => {
  const grid = document.querySelector('[data-quote-grid]');
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll('[data-quote-card]'));
  const buttons = Array.from(document.querySelectorAll('[data-quote-filter]'));
  const count = document.querySelector('[data-quote-count]');
  let active = 'all';

  const apply = () => {
    let visible = 0;
    cards.forEach((card) => {
      const show = active === 'all' || card.dataset.tone === active;
      card.hidden = !show;
      if (show) visible += 1;
    });
    if (count) count.textContent = `${visible} statement${visible === 1 ? '' : 's'}`;
  };

  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      active = button.dataset.quoteFilter || 'all';
      buttons.forEach((item) => item.classList.toggle('is-active', item === button));
      apply();
    });
  });
  apply();
})();
