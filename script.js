/* Optional enhancement; navigation, downloads, and FAQs work without JavaScript. */
const year = document.querySelector('[data-year]');
if (year) year.textContent = String(new Date().getFullYear());

const fitFilters = document.querySelector('.fit-filters');
const fitCards = Array.from(document.querySelectorAll('[data-fit-category]'));
const fitCount = document.querySelector('.fit-count');
const showMore = document.querySelector('[data-show-more]');

if (fitFilters && fitCards.length && fitCount) {
  const buttons = Array.from(fitFilters.querySelectorAll('[data-fit-filter]'));
  let category = 'all';
  let expanded = false;

  const renderFits = () => {
    const matching = fitCards.filter((card) => category === 'all' || card.dataset.fitCategory === category);
    const visible = expanded || !showMore ? matching : matching.slice(0, 8);
    const visibleSet = new Set(visible);
    fitCards.forEach((card) => { card.hidden = !visibleSet.has(card); });
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.fitFilter === category)));
    fitCount.textContent = visible.length === matching.length
      ? `${matching.length} ${matching.length === 1 ? 'look' : 'looks'} · outfit inspiration`
      : `Showing ${visible.length} of ${matching.length} looks`;
    if (showMore) {
      showMore.hidden = visible.length === matching.length;
      showMore.textContent = `Show ${matching.length - visible.length} more fits ↓`;
    }
  };

  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      category = button.dataset.fitFilter;
      expanded = false;
      renderFits();
    });
  });
  if (showMore) {
    showMore.addEventListener('click', () => {
      const nextPhoto = fitCards.find((card) => card.hidden && (category === 'all' || card.dataset.fitCategory === category));
      expanded = true;
      renderFits();
      // Keep keyboard focus in the gallery when the reveal button disappears.
      if (nextPhoto) nextPhoto.querySelector('a').focus({ preventScroll: true });
    });
  }
  renderFits();
  fitFilters.hidden = false;
}
