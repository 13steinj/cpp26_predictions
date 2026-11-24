// Live observations are drawn separately from the saved, five-way ballot history.
const { grouped, consensusLabel, prices, payouts, priceText } = await import('./pricing.mjs?v=' + new URL(import.meta.url).searchParams.get('v'));
const positions = ['SF', 'F', 'Abstain', 'A', 'SA'];
const labels = ['Strongly For', 'For', 'Abstain', 'Against', 'Strongly Against'];
const outcomes = [['for', 'Consensus'], ['abstain', 'No consensus'], ['against', 'Consensus against']];
const cards = [...document.querySelectorAll('.market')];
const dateFormat = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit',
  timeZone: 'UTC', hourCycle: 'h23',
});
const dateText = at => dateFormat.format(new Date(at)).replace(',', '') + ' UTC';
const ballotText = counts => positions.map((code, i) => code + ': ' + counts[i]).join(' / ');

function validCounts(counts) {
  return Array.isArray(counts) && counts.length === 5 &&
    positions.every((_, i) => Number.isSafeInteger(counts[i]) && counts[i] >= 0);
}

function snapshots(samples) {
  if (!Array.isArray(samples)) throw new Error('Invalid history');
  let previous = -Infinity;
  for (const sample of samples) {
    const at = Date.parse(sample.at);
    if (!Number.isFinite(at) || at <= previous || !validCounts(sample.counts)) throw new Error('Invalid snapshot');
    previous = at;
  }
  return samples;
}

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
    const i = positions.findIndex((code, i) => [code, labels[i], code + ' - ' + labels[i]].includes(value));
    if (i < 0 || counts[i] !== undefined || !Number.isSafeInteger(option.vote_count) || option.vote_count < 0) {
      throw new Error('Invalid poll options');
    }
    counts[i] = option.vote_count;
  }
  if (!validCounts(counts)) throw new Error('Missing position');
  return counts;
}

function svgNode(tag, attributes, title) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  if (title) {
    const description = document.createElementNS(node.namespaceURI, 'title');
    description.textContent = title;
    node.append(description);
  }
  return node;
}

function observationRow(sample, current = false) {
  const row = document.createElement('tr');
  row.dataset.kind = current ? 'current' : 'snapshot';
  const heading = document.createElement('th');
  heading.scope = 'row';
  const time = document.createElement('time');
  time.dateTime = new Date(sample.at).toISOString();
  time.textContent = dateText(sample.at);
  const label = document.createElement('span');
  label.textContent = current ? (sample.ok ? 'Current time / Not saved' : 'Last live check / Not saved') : 'Saved snapshot';
  heading.append(time, label);
  row.append(heading);
  for (const price of prices(sample.counts)) {
    const cell = document.createElement('td');
    cell.textContent = priceText(price);
    row.append(cell);
  }
  const ballots = document.createElement('td');
  const state = document.createElement('strong');
  state.textContent = consensusLabel(sample.counts);
  const totals = document.createElement('span');
  totals.textContent = ballotText(sample.counts);
  ballots.append(state, totals);
  row.append(ballots);
  return row;
}

function drawHistory(card) {
  const saved = card.savedSamples;
  const last = saved.at(-1);
  const live = card.live && (!last || Date.parse(card.live.at) >= Date.parse(last.at)) ? card.live : null;
  const start = saved.length ? Date.parse(saved[0].at) : live ? Date.parse(live.at) : Date.now();
  const end = live ? Date.parse(live.at) : last ? Date.parse(last.at) : start;
  const x = at => end === start ? 320 : 4 + 632 * (Date.parse(at) - start) / (end - start);
  const y = price => 4 + (100 - price) * 1.52;
  const box = card.querySelector('.history svg').getBoundingClientRect();
  const point = (attributes, radius, title) => svgNode('ellipse', {
    ...attributes, rx: radius * 640 / box.width, ry: radius * 160 / box.height,
  }, title);
  const series = card.querySelector('.history-series');
  series.replaceChildren();
  for (const [i, [code, label]] of outcomes.entries()) {
    let path = '';
    for (const sample of saved) {
      const price = prices(sample.counts)[i];
      if (price === null) {
        if (path) series.append(svgNode('path', { class: 'history-line saved ' + code, d: path }));
        path = '';
        continue;
      }
      const px = x(sample.at), py = y(price);
      path += path ? ' H' + px + ' V' + py : 'M' + px + ',' + py;
      series.append(point({ class: 'history-point saved ' + code, cx: px, cy: py }, 3,
        'Saved snapshot: ' + dateText(sample.at) + '\n' + consensusLabel(sample.counts) + '\n' + label + ': ' + priceText(price) + '\n' + ballotText(sample.counts)));
    }
    if (path) series.append(svgNode('path', { class: 'history-line saved ' + code, d: path }));
    const livePrice = live ? prices(live.counts)[i] : null;
    if (livePrice !== null) {
      const oldPrice = last ? prices(last.counts)[i] : null;
      if (oldPrice !== null) {
        const extension = 'M' + x(last.at) + ',' + y(oldPrice) + ' H' + x(live.at) + ' V' + y(livePrice);
        series.append(svgNode('path', { class: 'history-line live ' + code, d: extension }));
      }
      series.append(point({ class: 'history-point live ' + code, cx: x(live.at), cy: y(livePrice) }, 5,
        (live.ok ? 'Current time: ' : 'Last live check: ') + dateText(live.at) +
        '\nNot a saved snapshot\n' + consensusLabel(live.counts) + '\n' + label + ': ' + priceText(livePrice) + '\n' + ballotText(live.counts)));
    }
  }
  const firstTime = card.querySelector('.history-start');
  firstTime.dateTime = new Date(start).toISOString();
  firstTime.textContent = dateText(start);
  const endLabel = card.querySelector('.history-end');
  endLabel.classList.toggle('history-current', Boolean(live));
  endLabel.querySelector('strong').textContent = live ? (live.ok ? 'Current time (not saved)' : 'Last live check (not saved)') : 'Latest saved snapshot';
  endLabel.querySelector('time').dateTime = new Date(end).toISOString();
  endLabel.querySelector('time').textContent = dateText(end);
  card.querySelector('.snapshot-rows').replaceChildren(...saved.map(sample => observationRow(sample)),
    ...(live ? [observationRow(live, true)] : []));
  card.querySelector('.history-empty')?.remove();
  if (!saved.some(sample => sample.counts.some(n => n)) && !(live && live.counts.some(n => n))) {
    const empty = document.createElement('p');
    empty.className = 'history-empty';
    empty.textContent = 'No votes yet.';
    card.querySelector('.history-times').after(empty);
  }
}

async function refreshQuote(card) {
  try {
    const response = await fetch('https://api.strawpoll.com/v3/polls/' + card.dataset.pollId + '?current=' + Date.now(),
      { cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error('Poll unavailable');
    const poll = await response.json();
    const counts = countsFromPoll(poll);
    const total = counts.reduce((a, b) => a + b, 0);
    const values = prices(counts), groups = grouped(counts);
    for (const [i, [code]] of outcomes.entries()) {
      const contract = card.querySelector('[data-outcome="' + code + '"]');
      contract.querySelector('.price').textContent = priceText(values[i]);
      contract.querySelector('.share').textContent = total ? (100 * groups[i] / total).toFixed(1) +
        (code === 'abstain' ? '% abstained' : '% voted ' + code) : 'No votes yet';
      contract.querySelector('.ballots').textContent = groups[i].toLocaleString() + ' ' +
        (code === 'abstain' ? (groups[i] === 1 ? 'abstention' : 'abstentions') :
          (groups[i] === 1 ? 'vote ' : 'votes ') + code);
    }
    const votePayouts = payouts(counts);
    for (const [i, code] of positions.entries()) {
      const ballot = card.querySelector('[data-position="' + code + '"]');
      ballot.querySelector('.ballot-count').textContent = counts[i].toLocaleString();
      ballot.querySelector('.vote-payout').textContent = priceText(votePayouts[i]);
    }
    card.querySelector('.consensus-result strong').textContent = consensusLabel(counts);
    card.dataset.total = total;
    card.querySelector('.market-total').textContent = total ? total.toLocaleString() + (total === 1 ? ' vote' : ' votes') : 'Awaiting first vote';
    if (!poll.is_open) {
      card.querySelector('.market-total').textContent += ' / Poll closed';
      card.querySelector('.vote')?.remove();
    }
    card.live = { at: new Date().toISOString(), counts, ok: true };
    card.querySelector('.quote-state').textContent = 'Live · ' + dateText(card.live.at);
  } catch {
    if (card.live) card.live.ok = false;
    card.querySelector('.quote-state').textContent = 'Live update unavailable';
  }
}

async function refreshHistory() {
  try {
    const response = await fetch('history.json?snapshot=' + Date.now(),
      { cache: 'no-store', signal: AbortSignal.timeout(20000) });
    if (!response.ok) throw new Error('History unavailable');
    const history = await response.json();
    if (history.version !== 1 || !history.polls) throw new Error('Invalid history format');
    const next = cards.map(card => snapshots(history.polls[card.dataset.pollId] || []));
    cards.forEach((card, i) => { card.savedSamples = next[i]; });
    const checkedAt = history.checked_at || next.flat().map(sample => sample.at).sort().at(-1);
    if (checkedAt && Number.isFinite(Date.parse(checkedAt))) {
      const stamp = document.querySelector('footer time');
      stamp.dateTime = new Date(checkedAt).toISOString();
      stamp.textContent = dateText(checkedAt);
    }
  } catch { /* Keep the saved snapshots embedded in the page. */ }
}

for (const card of cards) {
  card.savedSamples = snapshots(JSON.parse(card.dataset.samples));
  card.live = null;
}
const resize = new ResizeObserver(() => cards.forEach(drawHistory));
cards.forEach(card => resize.observe(card.querySelector('.history-chart')));
let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    await refreshHistory();
    await Promise.allSettled(cards.map(refreshQuote));
    cards.forEach(drawHistory);
    document.querySelector('.total-votes').textContent = cards.reduce((n, card) => n + Number(card.dataset.total), 0).toLocaleString();
  } finally { refreshing = false; }
}
await refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 60000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
