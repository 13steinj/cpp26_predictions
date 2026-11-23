// Optional dev tool: npm install --no-save --package-lock=false playwright
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
});
const base = process.env.SITE_URL || 'http://127.0.0.1:8000/';
await mkdir('test-results', { recursive: true });
try {
  for (const width of [1280, 390, 320]) {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width, height: 900 } });
    const page = await context.newPage();
    const failures = [];
    const pollRequests = [];
    page.on('request', request => { if (request.url().includes('api.strawpoll.com')) pollRequests.push(request.url()); });
    page.on('pageerror', error => failures.push(error.message));
    page.on('response', response => { if (!response.ok()) failures.push(response.url()); });
    await page.goto(base);
    assert.equal(await page.locator('script[src="quotes.js"]').count(), 1);
    assert.ok(await page.locator('h1').isVisible());
    assert.equal(await page.locator('.contract').count(), 5 * await page.locator('.market').count());
    assert.ok(await page.locator('.market').count() > 0);
    assert.ok(await page.getByRole('heading', { name: 'C++26 will pass second shot at DIS', exact: true }).isVisible());
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('summary').click();
    assert.equal(await page.locator('details').getAttribute('open'), '');
    assert.match(await page.locator('details').innerText(), /one vote per IP address/);
    assert.match(await page.locator('.vote').first().getAttribute('href'), /^https:\/\/strawpoll\.com\/[a-zA-Z0-9]+$/);
    assert.deepEqual(failures, []);
    assert.deepEqual(pollRequests, []);
    await page.locator('summary').click();
    await page.screenshot({ path: `test-results/${width}.png`, fullPage: true });
    console.log(`Passed ${width}px with JS disabled: two markets, votes, disclosure, links, no overflow`);
    await context.close();
  }
  // Generate clearly labelled synthetic history outside the published site.
  const fixture = JSON.parse(execFileSync(process.env.PYTHON || 'python', ['-c', `
import json
from datetime import datetime, timedelta, timezone
from string import Template
from build import ROOT, DISCUSSION, render_market
markets = json.loads((ROOT / 'markets.json').read_text())
at = datetime(2026, 11, 23, 21, 30, tzinfo=timezone.utc)
rendered, polls = [], {}
for market in markets:
    poll = {'type': 'multiple_choice', 'is_open': True,
            'poll_config': {'duplication_checking': 'ip', 'is_multiple_choice': False,
                            'results_visibility': 'always', 'vote_type': 'default'},
            'poll_options': [{'value': code, 'vote_count': count}
                             for code, count in zip(['SF', 'F', 'Abstain', 'A', 'SA'], [3, 2, 1, 2, 2])]}
    samples = [{'at': (at - timedelta(minutes=30)).isoformat(), 'counts': [1, 1, 1, 0, 0]},
               {'at': at.isoformat(), 'counts': [3, 2, 1, 2, 2]}]
    rendered.append(render_market(market, poll, samples, at)[0])
    for option, count in zip(poll['poll_options'], [1, 1, 1, 0, 0]):
        option['vote_count'] = count
    polls[market['poll_id']] = poll
html = Template((ROOT / 'template.html').read_text()).substitute(
    discussion=DISCUSSION, market_count=len(markets), market_label='markets',
    vote_count=10 * len(markets), markets=''.join(rendered),
    updated_iso=at.isoformat(), updated_display='Synthetic browser test data')
print(json.dumps({'html': html, 'polls': polls}))
`], { encoding: 'utf8' }));
  for (const width of [1280, 390, 320]) {
    const context = await browser.newContext({ javaScriptEnabled: false, viewport: { width, height: 900 } });
    await context.route(`${base}fixture`, route => route.fulfill({ contentType: 'text/html', body: fixture.html }));
    const page = await context.newPage();
    await page.goto(`${base}fixture`);
    assert.equal(await page.locator('.history svg').count(), Object.keys(fixture.polls).length);
    assert.equal(await page.locator('.history-line').count(), 5 * Object.keys(fixture.polls).length);
    assert.equal(await page.locator('.contract .price').first().innerText(), '30¢');
    assert.match(await page.locator('.share').first().innerText(), /30.0%/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: `test-results/history-${width}.png`, fullPage: true });
    await context.close();
    console.log(`Passed ${width}px recorded-history fixture: five price lines, cents, percentages, no overflow`);
  }
  for (const online of [true, false]) {
    const context = await browser.newContext();
    await context.route(`${base}fixture`, route => route.fulfill({ contentType: 'text/html', body: fixture.html }));
    await context.route(base, route => route.fulfill({ contentType: 'text/html', body: fixture.html }));
    await context.route('https://api.strawpoll.com/v3/polls/*', route => online
      ? route.fulfill({ contentType: 'application/json', body: JSON.stringify(fixture.polls[new URL(route.request().url()).pathname.split('/').at(-1)]) })
      : route.abort());
    const page = await context.newPage();
    await page.goto(`${base}fixture`);
    await page.locator('.quote-state').first().filter({ hasText: online ? /^Live ·/ : 'Live update unavailable' }).waitFor();
    assert.equal(await page.locator('.price').first().innerText(), online ? '34¢' : '30¢');
    assert.equal(await page.locator('.ballots').first().innerText(), online ? '1 vote' : '3 votes');
    if (online) {
      const prices = await page.locator('.market').first().locator('.price').allTextContents();
      assert.equal(prices.reduce((n, value) => n + parseInt(value), 0), 100);
    }
    assert.equal(await page.locator('.history svg').count(), Object.keys(fixture.polls).length);
    await context.close();
    console.log(`Passed ${online ? 'live quote update' : 'API failure fallback'} using synthetic data`);
  }
  const livePage = await browser.newPage();
  await livePage.goto(base);
  await livePage.locator('.quote-state').first().filter({ hasText: /^Live ·/ }).waitFor();
  const livePrices = await livePage.locator('.price').allTextContents();
  assert.ok(livePrices.every(price => price === '—' || /^\d+¢$/.test(price)));
  await livePage.close();
  console.log('Passed real public API and browser CORS: live quote loaded on-page');
  // Read the real voting page without casting an artificial sentiment vote.
  const page = await browser.newPage();
  await page.goto(base);
  const pollUrls = await page.locator('.vote').evaluateAll(links => links.map(link => link.href));
  for (const pollUrl of pollUrls) {
    await page.goto(pollUrl, { waitUntil: 'networkidle' });
    for (const label of ['Strongly For', 'For', 'Abstain', 'Against', 'Strongly Against']) {
      assert.ok((await page.locator('body').innerText()).includes(label));
    }
    assert.ok(await page.getByRole('button', { name: 'Vote', exact: true }).isVisible());
    assert.ok(await page.getByText('One vote per IP-Address allowed.', { exact: true }).isVisible());
  }
  console.log('Passed both live StrawPoll links: five choices and IP restriction visible; no vote submitted');
} finally {
  await browser.close();
}
