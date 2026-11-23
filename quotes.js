// Progressive enhancement: static quotes and history still work without JavaScript.
const positions = ['SF', 'F', 'Abstain', 'A', 'SA'];
const labels = ['Strongly For', 'For', 'Abstain', 'Against', 'Strongly Against'];
const cards = [...document.querySelectorAll('.market')];

function countsFromPoll(poll) {
  const config = poll.poll_config;
  if (poll.type !== 'multiple_choice' || config.duplication_checking !== 'ip' ||
      config.is_multiple_choice || config.results_visibility !== 'always' ||
      config.allow_other_option || config.voting_interval || config.vote_type !== 'default') {
    throw new Error('Incompatible poll settings');
  }
  const counts = Array(5);
  for (const option of poll.poll_options) {
    const value = option.value.trim();
    const i = positions.findIndex((code, i) => [code, labels[i], `${code} - ${labels[i]}`].includes(value));
    if (i < 0 || counts[i] !== undefined || !Number.isSafeInteger(option.vote_count) || option.vote_count < 0) {
      throw new Error('Invalid poll options');
    }
    counts[i] = option.vote_count;
  }
  if (counts.filter(n => n !== undefined).length !== 5) throw new Error('Missing position');
  return counts;
}

function cents(counts) {
  const total = counts.reduce((a, b) => a + b, 0);
  if (!total) return counts.map(() => null);
  const prices = counts.map(n => Math.floor(100 * n / total));
  const order = positions.map((_, i) => i).sort((a, b) =>
    (100 * counts[b] % total) - (100 * counts[a] % total));
  for (const i of order.slice(0, 100 - prices.reduce((a, b) => a + b, 0))) prices[i]++;
  return prices;
}

async function refreshQuote(card) {
  try {
    const response = await fetch(`https://api.strawpoll.com/v3/polls/${card.dataset.pollId}`,
      { cache: 'no-store', credentials: 'omit' });
    if (!response.ok) throw new Error('Poll unavailable');
    const poll = await response.json();
    const counts = countsFromPoll(poll);
    const total = counts.reduce((a, b) => a + b, 0);
    const prices = cents(counts);
    for (const [i, code] of positions.entries()) {
      const contract = card.querySelector(`[data-position="${code}"]`);
      contract.querySelector('.price').innerHTML = prices[i] === null ? '&mdash;' : `${prices[i]}<small>&cent;</small>`;
      contract.querySelector('.share').textContent = total ? `${(100 * counts[i] / total).toFixed(1)}% of votes` : 'No votes yet';
      contract.querySelector('.ballots').textContent = `${counts[i].toLocaleString()} ${counts[i] === 1 ? 'vote' : 'votes'}`;
    }
    card.dataset.total = total;
    card.querySelector('.market-total').textContent = total ? `${total.toLocaleString()} ${total === 1 ? 'vote' : 'votes'}` : 'Awaiting first vote';
    if (!poll.is_open) {
      card.querySelector('.market-total').textContent += ' / Poll closed';
      card.querySelector('.vote')?.remove();
    }
    card.querySelector('.quote-state').textContent = `Live · ${new Date().toLocaleTimeString()}`;
  } catch {
    card.querySelector('.quote-state').textContent = 'Live update unavailable';
  }
}

async function refreshHistory() {
  try {
    const response = await fetch('./', { cache: 'no-store' });
    if (!response.ok) return;
    const latest = new DOMParser().parseFromString(await response.text(), 'text/html');
    for (const card of cards) {
      const history = latest.querySelector(`[data-poll-id="${card.dataset.pollId}"] .history`);
      if (history) card.querySelector('.history').replaceWith(history);
    }
    const stamp = latest.querySelector('footer time');
    if (stamp) document.querySelector('footer time').replaceWith(stamp);
  } catch { /* Keep the last successful history chart. */ }
}

async function refresh() {
  await Promise.allSettled(cards.map(refreshQuote));
  document.querySelector('.total-votes').textContent = cards.reduce((n, card) => n + Number(card.dataset.total), 0).toLocaleString();
  await refreshHistory();
}
await refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 60_000);
