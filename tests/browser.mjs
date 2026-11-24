// Optional dev dependency: npm install --no-save --package-lock=false playwright
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
});
const base = process.env.SITE_URL || 'http://127.0.0.1:8000/';
const fixture = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['tests/fixtures.py'], { encoding: 'utf8' }));
const cents = value => value.startsWith('$') ? Number(value.slice(1)) * 100 : parseFloat(value);
await mkdir('test-results', { recursive: true });

async function assertPayouts(card) {
  const values = {};
  for (const row of await card.locator('.vote-payouts tr[data-position]').all()) {
    values[await row.getAttribute('data-position')] = cents(await row.locator('.vote-payout').innerText());
  }
  assert.equal(values.SF, 2 * values.F);
  assert.equal(values.SA, 2 * values.A);
}

async function routeFixture(context, empty = false, offline = false, malformed = false) {
  await context.route(base + 'fixture', route => route.fulfill({
    contentType: 'text/html', body: empty ? fixture.empty_html : fixture.html,
  }));
  await context.route(base + 'history.json?*', route => route.fulfill({
    contentType: 'application/json', body: JSON.stringify(empty ? fixture.empty_history : fixture.history),
  }));
  await context.route('https://api.strawpoll.com/v3/polls/*', route => {
    if (offline) return route.abort();
    const id = new URL(route.request().url()).pathname.split('/').at(-1);
    const poll = structuredClone((empty ? fixture.first_votes : fixture.polls)[id]);
    if (malformed) poll.poll_options.pop();
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(poll) });
  });
}

try {
  for (const width of [1280, 390, 320]) {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width, height: 1000 } });
    const page = await context.newPage();
    const failures = [], pollRequests = [];
    page.on('pageerror', error => failures.push(error.message));
    page.on('request', request => { if (request.url().includes('api.strawpoll.com')) pollRequests.push(request.url()); });
    page.on('response', response => { if (!response.ok()) failures.push(response.url()); });
    await page.goto(base);
    const markets = await page.locator('.market').count();
    assert.equal(await page.locator('script[src^="quotes.js?v="]').count(), 1);
    assert.equal(await page.locator('.contract').count(), 3 * markets);
    assert.equal(await page.locator('.vote-payouts tr[data-position]').count(), 5 * markets);
    assert.equal(await page.locator('.history-point.live').count(), 0);
    assert.ok(await page.getByRole('heading', { name: 'C++26 will pass second shot at DIS', exact: true }).isVisible());
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('main > details > summary').click();
    assert.match(await page.locator('main > details').innerText(), /Each ballot counts once/);
    assert.match(await page.locator('main > details').innerText(), /four times/);
    assert.match(await page.locator('main > details').innerText(), /one vote per IP address/);
    await page.locator('main > details > summary').click();
    assert.deepEqual(failures, []);
    assert.deepEqual(pollRequests, []);
    for (const card of await page.locator('.market').all()) await assertPayouts(card);
    await page.screenshot({ path: 'test-results/static-' + width + '.png', fullPage: true });
    await context.close();
    console.log('Passed ' + width + 'px without JS: three outcomes, five payouts, saved chart, no overflow');
  }

  for (const width of [1280, 390, 320]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    await routeFixture(context);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + 'fixture');
    await page.locator('.history-current').last().waitFor();
    const cards = await page.locator('.market').all();
    assert.equal(await cards[0].locator('.consensus-result strong').innerText(), 'Strong consensus against');
    assert.deepEqual(await cards[0].locator('.price').allTextContents(), ['4¢', '32¢', '64¢']);
    assert.equal(await cards[1].locator('.consensus-result strong').innerText(), 'No consensus');
    assert.equal(await cards[1].locator('[data-position="F"] .vote-payout').innerText(), '13.5¢');
    assert.equal(await cards[1].locator('[data-position="A"] .vote-payout').innerText(), '11.5¢');
    for (const card of cards) {
      await card.locator('.snapshot-details summary').click();
      assert.ok(await card.locator('.snapshot-table').isVisible());
      assert.equal(await card.locator('.history-point.saved').count(), 6);
      assert.equal(await card.locator('.history-point.live').count(), 3);
      const marker = await card.locator('.history-point.live').first().boundingBox();
      assert.ok(Math.abs(marker.width - marker.height) < 1);
      assert.equal(await card.locator('.history-line.live').count(), 3);
      assert.equal(await card.locator('tr[data-kind="snapshot"]').count(), 2);
      assert.equal(await card.locator('tr[data-kind="current"]').count(), 1);
      assert.match(await card.locator('tr[data-kind="snapshot"]').first().innerText(), /SF: 6/);
      assert.match(await card.locator('tr[data-kind="current"]').innerText(), /Current time \/ Not saved/);
      const observed = Date.parse(await card.locator('.history-current time').getAttribute('datetime'));
      assert.ok(Math.abs(Date.now() - observed) < 30000);
      const values = await card.locator('.price').allTextContents();
      assert.equal(values.reduce((n, value) => n + cents(value), 0), 100);
      const dash = await card.locator('.history-line.live').first().evaluate(node => getComputedStyle(node).strokeDasharray);
      assert.notEqual(dash, 'none');
      await assertPayouts(card);
      await card.locator('.snapshot-details summary').click();
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    await page.screenshot({ path: 'test-results/live-history-' + width + '.png', fullPage: true });
    await context.close();
    console.log('Passed ' + width + 'px live fixture: old snapshots, current point, consensus strength, half payouts');
  }

  for (const malformed of [false, true]) {
    const context = await browser.newContext();
    await routeFixture(context, false, !malformed, malformed);
    const page = await context.newPage();
    await page.goto(base + 'fixture');
    await page.waitForFunction(() => [...document.querySelectorAll('.quote-state')].every(node => node.textContent === 'Live update unavailable'));
    assert.deepEqual(await page.locator('.market').first().locator('.price').allTextContents(), ['18¢', '49¢', '33¢']);
    assert.equal(await page.locator('.history-point.live').count(), 0);
    assert.equal(await page.locator('tr[data-kind="snapshot"]').count(), 4);
    await context.close();
    console.log('Passed ' + (malformed ? 'missing vote option' : 'API outage') + ': preserved snapshots; no fake current point');
  }

  const emptyContext = await browser.newContext();
  await routeFixture(emptyContext, true);
  const firstVotes = await emptyContext.newPage();
  await firstVotes.goto(base + 'fixture');
  await firstVotes.locator('.history-current').last().waitFor();
  assert.equal(await firstVotes.locator('.history-point.saved').count(), 0);
  assert.equal(await firstVotes.locator('.history-point.live').count(), 6);
  assert.equal(await firstVotes.locator('tr[data-kind="snapshot"]').count(), 2);
  assert.equal(await firstVotes.locator('tr[data-kind="current"]').count(), 2);
  assert.equal(await firstVotes.locator('.market').last().locator('[data-outcome="abstain"] .price').innerText(), '$1.00');
  await emptyContext.close();
  console.log('Passed first unsaved votes: live point shown while saved snapshots still have zero votes');

  const real = await browser.newPage();
  const errors = [];
  real.on('pageerror', error => errors.push(error.message));
  await real.goto(base);
  await real.locator('.history-current').last().waitFor();
  assert.equal(await real.locator('.history-point.live').count(), 6);
  for (const card of await real.locator('.market').all()) await assertPayouts(card);
  assert.deepEqual(errors, []);
  await real.screenshot({ path: 'test-results/current-live-data.png', fullPage: true });
  const links = await real.locator('.vote').evaluateAll(nodes => nodes.map(node => node.href));
  for (const link of links) {
    await real.goto(link, { waitUntil: 'networkidle' });
    assert.ok(await real.getByRole('button', { name: 'Vote', exact: true }).isVisible());
    assert.ok(await real.getByText('One vote per IP-Address allowed.', { exact: true }).isVisible());
  }
  console.log('Passed real API, current-time overlay and both IP-restricted poll pages; no votes submitted');
} finally {
  await browser.close();
}
