const test = require('node:test');
const assert = require('node:assert/strict');

const portfolioService = require('../src/modules/portfolio/portfolio.service');

test('getPortfolioHoldingsAdvice builds recommendation from P&L and price trend', async () => {
  const repoStub = {
    findActiveHoldingsByUser: async () => [
      {
        _id: 'holding-1',
        stock_id: {
          _id: 'stock-1',
          symbol: 'HPG',
          company_name: 'Hoa Phat',
          market_id: { code: 'HOSE', name: 'Ho Chi Minh' }
        },
        average_cost: 25000,
        quantity: 1000,
        holding_date: '2026-01-15T00:00:00.000Z',
        note: 'Long-term'
      }
    ],
    findLatestPricesByStockIds: async () => [
      {
        _id: 'stock-1',
        close_price: 28000,
        price_change: 1000,
        price_change_percent: 3.7,
        volume: 20000000,
        time_id: 20260707,
        created_at: '2026-07-07T00:00:00.000Z'
      }
    ],
    findRecentPricesForStock: async () => [
      { time_id: 20260701, close_price: 26000 },
      { time_id: 20260702, close_price: 26800 },
      { time_id: 20260703, close_price: 27000 },
      { time_id: 20260704, close_price: 27500 },
      { time_id: 20260705, close_price: 27800 },
      { time_id: 20260706, close_price: 27900 },
      { time_id: 20260707, close_price: 28000 }
    ]
  };

  const result = await portfolioService.getPortfolioHoldingsAdvice('user-1', {
    portfolioRepository: repoStub,
    analyseClient: async () => ({ items: [] })
  });

  assert.equal(result.items[0].symbol, 'HPG');
  assert.equal(result.items[0].recommendation, 'HOLD');
  assert.match(result.items[0].explanation, /lời/);
  assert.equal(result.items[0].ai_context.available, false);
});

test('getPortfolioWatchlistBatch returns a full table payload without triggering LLM by default', async () => {
  const repoStub = {
    findActiveHoldingsByUser: async () => [
      {
        _id: 'holding-1',
        stock_id: {
          _id: 'stock-1',
          symbol: 'HPG',
          company_name: 'Hoa Phat',
          market_id: { code: 'HOSE', name: 'Ho Chi Minh' }
        },
        average_cost: 25000,
        quantity: 1000,
        holding_date: '2026-01-15T00:00:00.000Z',
        note: 'Long-term'
      }
    ],
    findLatestPricesByStockIds: async () => [
      {
        _id: 'stock-1',
        close_price: 28000,
        price_change_percent: 3.7,
        time_id: 20260707
      }
    ],
    findRecentPricesForStock: async () => [
      { time_id: 20260701, close_price: 26000 },
      { time_id: 20260702, close_price: 26800 },
      { time_id: 20260703, close_price: 27000 },
      { time_id: 20260704, close_price: 27500 },
      { time_id: 20260705, close_price: 27800 },
      { time_id: 20260706, close_price: 27900 },
      { time_id: 20260707, close_price: 28000 }
    ]
  };

  const watchlistRepoStub = {
    findUserWatchlist: async () => [
      {
        _id: 'watch-1',
        stock_id: {
          _id: 'stock-1',
          symbol: 'HPG',
          company_name: 'Hoa Phat',
          market_id: { code: 'HOSE', name: 'Ho Chi Minh' }
        }
      }
    ]
  };

  const result = await portfolioService.getPortfolioWatchlistBatch('user-1', {
    portfolioRepository: repoStub,
    watchlistRepository: watchlistRepoStub,
    includeAi: false
  });

  assert.equal(result.items[0].symbol, 'HPG');
  assert.equal(result.items[0].recommendation, 'HOLD');
  assert.equal(result.items[0].ai_context.available, false);
});

test('getPortfolioWatchlistHistory fetches analysis history within target days', async () => {
  // Mock global fetch
  const originalFetch = global.fetch;
  global.fetch = async (url) => {
    assert.match(url.toString(), /api\/ai-reports\/history/);
    assert.match(url.toString(), /fromDate=/);
    return {
      ok: true,
      json: async () => ({
        data: {
          items: [
            {
              created_at: new Date().toISOString(),
              decision_label: 'HOLD',
              total_score: 75,
              risk_score: 20,
              report_id: 'rep-cached-1'
            }
          ],
          total: 1
        }
      })
    };
  };

  try {
    const history = await portfolioService.getPortfolioWatchlistHistory({
      symbol: 'HPG',
      exchange: 'HOSE',
      days: 3,
      authToken: 'mock-token'
    });

    assert.equal(history.available, true);
    assert.equal(history.count, 1);
    assert.equal(history.history_items[0].report_id, 'rep-cached-1');
  } finally {
    global.fetch = originalFetch;
  }
});

test('getPortfolioWatchlistBatch reuses recent reports (within 3 days) and skips LLM', async () => {
  const repoStub = {
    findActiveHoldingsByUser: async () => [],
    findLatestPricesByStockIds: async () => [{ _id: 'stock-1', close_price: 28000, time_id: 20260707 }],
    findRecentPricesForStock: async () => []
  };

  const watchlistRepoStub = {
    findUserWatchlist: async () => [
      {
        _id: 'watch-1',
        stock_id: {
          _id: 'stock-1',
          symbol: 'HPG',
          company_name: 'Hoa Phat',
          market_id: { code: 'HOSE', name: 'Ho Chi Minh' }
        }
      }
    ]
  };

  let analyseOneCallCount = 0;
  let historyCallCount = 0;

  const originalFetch = global.fetch;
  global.fetch = async (url, options) => {
    const urlStr = url.toString();
    if (urlStr.includes('/api/ai-reports/history')) {
      historyCallCount++;
      return {
        ok: true,
        json: async () => ({
          data: {
            items: [
              {
                created_at: new Date(Date.now() - 1 * 24 * 60 * 60 * 1000).toISOString(), // 1 day ago
                decision_label: 'BUY',
                total_score: 80,
                risk_score: 15,
                report_id: 'rep-recent-123'
              }
            ],
            total: 1
          }
        })
      };
    }
    if (urlStr.includes('/api/ai-reports/analyse-one')) {
      analyseOneCallCount++;
      return {
        ok: true,
        json: async () => ({
          data: {
            summary: { decision_label: 'HOLD', total_score: 70, risk_score: 25 },
            report_id: 'rep-new-llm-456'
          }
        })
      };
    }
    return { ok: false };
  };

  try {
    const result = await portfolioService.getPortfolioWatchlistBatch('user-1', {
      portfolioRepository: repoStub,
      watchlistRepository: watchlistRepoStub,
      includeAi: true
    });

    assert.equal(historyCallCount, 1);
    assert.equal(analyseOneCallCount, 0); // Reused, no LLM call!
    assert.equal(result.items[0].ai_context.available, true);
    assert.equal(result.items[0].ai_context.report_id, 'rep-recent-123');
    assert.equal(result.items[0].ai_context.latest_decision_label, 'BUY');
  } finally {
    global.fetch = originalFetch;
  }
});


