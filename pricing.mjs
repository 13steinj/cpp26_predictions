// The threshold follows SD-4; graded prices, 4:1 labels and payout sizes are site conventions.
export const grouped = counts => [counts[0] + counts[1], counts[2], counts[3] + counts[4]];

export function consensus(counts) {
  if (!counts.some(n => n)) return null;
  const [favor, , against] = grouped(counts);
  if (favor > 2 * against) return 0;
  if (against > 2 * favor) return 2;
  return 1;
}

export function consensusLabel(counts) {
  const result = consensus(counts);
  if (result === null) return 'Awaiting first vote';
  const [favor, , against] = grouped(counts);
  if (result === 0) return favor >= 4 * against ? 'Strong consensus' : 'Consensus';
  if (result === 2) return against >= 4 * favor ? 'Strong consensus against' : 'Consensus against';
  return 'No consensus';
}

export function prices(counts) {
  if (!counts.some(n => n)) return [null, null, null];
  const [favor, , against] = grouped(counts).map(BigInt);
  const weights = [favor * favor, 2n * favor * against, against * against];
  const total = weights.reduce((a, b) => a + b, 0n);
  if (!total) return [0, 100, 0];
  const result = weights.map(n => Number(100n * n / total));
  const priority = [1, 0, 2];
  const order = [0, 1, 2].sort((a, b) => {
    const left = 100n * weights[a] % total, right = 100n * weights[b] % total;
    return left === right ? priority.indexOf(a) - priority.indexOf(b) : left > right ? -1 : 1;
  });
  for (const i of order.slice(0, 100 - result.reduce((a, b) => a + b, 0))) result[i]++;
  return result;
}

export function payouts(counts) {
  const [favor, neutral, against] = prices(counts);
  return [favor, favor === null ? null : favor / 2, neutral,
    against === null ? null : against / 2, against];
}

export const priceText = price => price === null ? '—' : price === 100 ? '$1.00' : price + '¢';
