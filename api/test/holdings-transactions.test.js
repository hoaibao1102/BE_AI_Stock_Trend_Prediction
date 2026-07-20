const test = require('node:test');
const assert = require('node:assert/strict');
const { computeWeightedAverageCost } = require('../src/modules/holdings/holdings.service');

test('computeWeightedAverageCost accumulates first buy', () => {
  const avg = computeWeightedAverageCost(0, 0, 100, 25000, 50000);
  assert.equal(avg, 25500);
});

test('computeWeightedAverageCost accumulates additional buy with fee', () => {
  const avg = computeWeightedAverageCost(100, 25000, 50, 30000, 25000);
  // (100*25000 + 50*30000 + 25000) / 150 = 26833.33
  assert.equal(avg, 26833.33);
});

test('computeWeightedAverageCost keeps precision to 2 decimals', () => {
  const avg = computeWeightedAverageCost(10, 100.33, 5, 120.55, 0);
  assert.equal(avg, 107.07);
});
