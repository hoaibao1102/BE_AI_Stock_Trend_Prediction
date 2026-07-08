const portfolioRepository = require('./portfolio.repository');
const watchlistsRepository = require('../watchlists/watchlists.repository');

const RECENT_PRICE_DAYS = 7;
const ADVICE_CACHE_TTL_MS = Number(process.env.PORTFOLIO_ADVICE_CACHE_TTL_MS || 15 * 60 * 1000);
const AI_CACHE_TTL_MS = Number(process.env.PORTFOLIO_AI_CACHE_TTL_MS || 6 * 60 * 60 * 1000);
const adviceCache = new Map();
const aiAnalysisCache = new Map();

const getMarketLabel = (stock) => {
  return stock?.market_id?.code || stock?.market_id?.name || null;
};

const round2 = (value) => Math.round(value * 100) / 100;

const formatDate = (value) => {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString().slice(0, 10);
};

// time_id is a YYYYMMDD number; expose it as an ISO date string for the FE.
const formatTimeId = (timeId) => {
  const raw = String(timeId ?? '');
  if (raw.length !== 8) return raw || null;
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
};

const toNumber = (value) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const buildPricePoint = (price) => ({
  date: formatTimeId(price.time_id),
  open: price.open_price ?? null,
  high: price.high_price ?? null,
  low: price.low_price ?? null,
  close: price.close_price ?? null,
  volume: price.volume ?? null,
  pe: price.pe ?? null,
  pb: price.pb ?? null,
  roe: price.roe ?? null
});

// Deterministic rule-based signal from unrealized P&L percentage.
// This is a display hint only; the AI recommendation comes from the analyse service.
const derivePnlSignal = (pnlPct) => {
  if (pnlPct === null) return null;
  if (pnlPct >= 30) return 'CONSIDER_TAKING_PROFIT';
  if (pnlPct >= 15) return 'STRONG_PROFIT_HOLD';
  if (pnlPct >= 5) return 'MODERATE_PROFIT_HOLD';
  if (pnlPct >= -5) return 'BREAKEVEN_WATCH';
  if (pnlPct >= -15) return 'MODERATE_LOSS_HOLD';
  return 'SIGNIFICANT_LOSS_REVIEW';
};

const buildPnlItem = (holding, latestPriceMap, prices7dMap) => {
  const stock = holding.stock_id;
  const stockId = stock?._id?.toString?.() || null;
  const latest = stockId ? latestPriceMap.get(stockId) : null;
  const closePrice = toNumber(latest?.close_price);

  const averageCost = toNumber(holding.average_cost);
  const quantity = toNumber(holding.quantity);

  let cost = null;
  let marketValue = null;
  let unrealizedPnl = null;
  let unrealizedPnlPct = null;
  let status = 'UNKNOWN';

  if (typeof closePrice === 'number' && typeof averageCost === 'number' && typeof quantity === 'number') {
    cost = round2(averageCost * quantity);
    marketValue = round2(closePrice * quantity);
    unrealizedPnl = round2(marketValue - cost);
    unrealizedPnlPct = averageCost > 0 ? round2(((closePrice - averageCost) / averageCost) * 100) : null;
    status = unrealizedPnl >= 0 ? 'PROFIT' : 'LOSS';
  }

  return {
    holding_id: holding._id.toString(),
    symbol: stock?.symbol ?? null,
    company_name: stock?.company_name ?? null,
    exchange: getMarketLabel(stock),
    average_cost: averageCost,
    quantity,
    holding_date: formatDate(holding.holding_date),
    close_price: closePrice,
    price_change: toNumber(latest?.price_change),
    price_change_percent: toNumber(latest?.price_change_percent),
    cost,
    market_value: marketValue,
    unrealized_pnl: unrealizedPnl,
    unrealized_pnl_pct: unrealizedPnlPct,
    status,
    pnl_signal: derivePnlSignal(unrealizedPnlPct),
    prices_7d: (prices7dMap.get(stockId) || []).map(buildPricePoint),
    note: holding.note || '',
    price_as_of: latest?.time_id ? formatTimeId(latest.time_id) : null
  };
};

const buildPortfolioSummary = (items) => {
  const priced = items.filter((item) => item.status === 'PROFIT' || item.status === 'LOSS');
  if (!priced.length) return null;

  const totalCost = round2(priced.reduce((sum, item) => sum + item.cost, 0));
  const totalMarketValue = round2(priced.reduce((sum, item) => sum + item.market_value, 0));
  const totalUnrealizedPnl = round2(totalMarketValue - totalCost);

  return {
    total_cost: totalCost,
    total_market_value: totalMarketValue,
    total_unrealized_pnl: totalUnrealizedPnl,
    total_unrealized_pnl_pct: totalCost > 0 ? round2((totalUnrealizedPnl / totalCost) * 100) : null,
    count_total: items.length,
    count_priced: priced.length,
    count_profit: priced.filter((item) => item.status === 'PROFIT').length,
    count_loss: priced.filter((item) => item.status === 'LOSS').length
  };
};

const deriveRecommendation = ({ hasHolding, pnlPct, trendSlope, recentMovePct }) => {
  if (!hasHolding) return 'WATCH';
  if (pnlPct === null) return 'HOLD';
  if (pnlPct >= 15 && trendSlope >= 0) return 'SELL';
  if (pnlPct >= 8 && recentMovePct >= 0) return 'HOLD';
  if (pnlPct >= 0) return 'HOLD';
  if (pnlPct <= -10 && recentMovePct <= 0) return 'SELL';
  if (pnlPct <= -8 && trendSlope >= 0) return 'BUY';
  return 'HOLD';
};

const buildExplanation = ({ symbol, pnlPct, recentMovePct, trendSlope, recommendation, aiContext }) => {
  const trendText = trendSlope > 0 ? 'đang tăng' : trendSlope < 0 ? 'đang giảm' : 'đang đi ngang';
  const pnlText = pnlPct === null ? 'chưa có dữ liệu giá hiện tại' : `${pnlPct >= 0 ? 'lời' : 'lỗ'} ${Math.abs(pnlPct).toFixed(1)}%`;
  const aiHint = aiContext?.available
    ? `Phân tích lịch sử gần đây có ${aiContext.count} bản ghi với quyết định ${aiContext.latest_decision_label || 'không rõ'}.`
    : 'Chưa có lịch sử phân tích gần đây từ Analyse để hỗ trợ quyết định.';

  if (recommendation === 'BUY') {
    return `${symbol} đang ${pnlText} nhưng xu hướng 7 phiên ${trendText} và đã có dấu hiệu hồi phục; phù hợp xem xét mua thêm nếu mục tiêu dài hạn.`;
  }

  if (recommendation === 'SELL') {
    return `${symbol} đang ${pnlText} và biến động gần đây ${recentMovePct >= 0 ? 'tăng mạnh' : 'giảm sâu'}; phù hợp cân nhắc chốt lời hoặc giảm tỷ trọng.`;
  }

  if (recommendation === 'WATCH') {
    return `${symbol} hiện chưa có vị thế trong danh mục; hãy theo dõi kỹ xu hướng 7 phiên ${trendText}. ${aiHint}`;
  }

  return `${symbol} đang ${pnlText}; xu hướng 7 phiên ${trendText} và tín hiệu trung tính, nên ưu tiên giữ hoặc theo dõi thêm. ${aiHint}`;
};

const normalizeAnalyseContext = (context) => {
  const fallback = { available: false, count: 0, history_items: [], source: 'unconfigured' };
  if (!context || typeof context !== 'object') return fallback;

  const historyItems = Array.isArray(context.history_items)
    ? context.history_items
    : Array.isArray(context.items)
      ? context.items
      : Array.isArray(context.data?.items)
        ? context.data.items
        : [];

  return {
    available: Boolean(context.available || historyItems.length > 0),
    count: Number(context.count ?? context.total ?? historyItems.length ?? 0) || 0,
    history_items: historyItems,
    latest_decision_label: context.latest_decision_label ?? context.latestDecisionLabel ?? context.decision_label ?? null,
    latest_total_score: context.latest_total_score ?? context.latestTotalScore ?? context.total_score ?? null,
    latest_risk_score: context.latest_risk_score ?? context.latestRiskScore ?? context.risk_score ?? null,
    source: context.source || 'analyse'
  };
};

const buildAnalyseHistoryContext = async ({ symbol, exchange, authToken, analyseClient }) => {
  if (typeof analyseClient !== 'function') {
    return normalizeAnalyseContext(null);
  }

  const response = await analyseClient({ symbol, exchange, authToken });
  return normalizeAnalyseContext(response);
};

// Fast path for the FE table: current P&L for every ACTIVE holding of the user.
// No LLM, no external calls — pure aggregation over existing collections.
const getPortfolioPnl = async (userId) => {
  const holdings = await portfolioRepository.findActiveHoldingsByUser(userId);
  const stockIds = holdings.map((holding) => holding.stock_id?._id).filter(Boolean);

  const latestPrices = await portfolioRepository.findLatestPricesByStockIds(stockIds);
  const latestPriceMap = new Map(latestPrices.map((price) => [price._id.toString(), price]));

  const prices7dEntries = await Promise.all(
    stockIds.map(async (stockId) => {
      const prices = await portfolioRepository.findRecentPricesForStock(stockId, RECENT_PRICE_DAYS);
      return [stockId.toString(), prices];
    })
  );
  const prices7dMap = new Map(prices7dEntries);

  const items = holdings.map((holding) => buildPnlItem(holding, latestPriceMap, prices7dMap));
  const dataAsOf = items.reduce((latest, item) => (item.price_as_of && item.price_as_of > latest ? item.price_as_of : latest), null);

  return {
    generated_at: new Date().toISOString(),
    data_as_of: dataAsOf,
    portfolio_summary: buildPortfolioSummary(items),
    items
  };
};

const defaultAnalyseHistoryClient = async ({ symbol, exchange, authToken, fromDate, toDate, limit }) => {
  const analyseBaseUrl = process.env.ANALYSE_BASE_URL || process.env.ANALYSE_API_BASE_URL || 'http://localhost:5100';
  if (!analyseBaseUrl) {
    return { available: false, count: 0, history_items: [], source: 'unconfigured' };
  }

  const queryFromDate = fromDate || new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
  const queryLimit = limit || '5';

  const url = new URL(`${analyseBaseUrl.replace(/\/$/, '')}/api/ai-reports/history`);
  if (symbol) url.searchParams.set('symbol', symbol);
  if (exchange) url.searchParams.set('exchange', exchange);
  url.searchParams.set('fromDate', queryFromDate);
  if (toDate) url.searchParams.set('toDate', toDate);
  url.searchParams.set('limit', String(queryLimit));

  try {
    const response = await fetch(url, {
      headers: {
        Accept: 'application/json',
        ...(authToken ? { Authorization: authToken } : {})
      }
    });

    if (!response.ok) {
      return { available: false, count: 0, history_items: [], source: 'analyse_unavailable' };
    }

    const payload = await response.json();
    const items = Array.isArray(payload?.data?.items) ? payload.data.items : [];
    return {
      available: items.length > 0,
      count: items.length,
      history_items: items.map((item) => ({
        created_at: item.created_at || null,
        decision_label: item.decision_label || null,
        total_score: item.total_score ?? null,
        risk_score: item.risk_score ?? null,
        report_id: item.report_id || null
      })),
      latest_decision_label: items[0]?.decision_label || null,
      latest_total_score: items[0]?.total_score ?? null,
      latest_risk_score: items[0]?.risk_score ?? null,
      source: 'analyse'
    };
  } catch (error) {
    return { available: false, count: 0, history_items: [], source: 'analyse_error' };
  }
};

const buildAiAnalysisPayload = ({ symbol, exchange, authToken, includeAi }) => {
  if (!includeAi) {
    return null;
  }

  return {
    provider: null,
    model: null,
    symbol,
    scopeExchange: exchange || 'HOSE',
    options: {
      includeExternalResearch: false,
      includeFinancials: true
    },
    authToken
  };
};

const invokeAnalyseAnalysis = async ({ symbol, exchange, authToken, includeAi }) => {
  if (!includeAi) {
    return { available: false, count: 0, history_items: [], source: 'disabled' };
  }

  const analyseBaseUrl = process.env.ANALYSE_BASE_URL || process.env.ANALYSE_API_BASE_URL || 'http://localhost:5100';
  if (!analyseBaseUrl) {
    return { available: false, count: 0, history_items: [], source: 'unconfigured' };
  }

  const cacheKey = `${symbol}:${exchange || 'HOSE'}`;
  const dayKey = new Date().toISOString().slice(0, 10);
  const memoKey = `${dayKey}:${cacheKey}`;
  const cached = aiAnalysisCache.get(memoKey);
  if (cached) {
    return cached;
  }

  const payload = buildAiAnalysisPayload({ symbol, exchange, authToken, includeAi });
  if (!payload) {
    return { available: false, count: 0, history_items: [], source: 'disabled' };
  }

  try {
    const response = await fetch(`${analyseBaseUrl.replace(/\/$/, '')}/api/ai-reports/analyse-one`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(authToken ? { Authorization: authToken } : {})
      },
      body: JSON.stringify({
        provider: null,
        model: null,
        symbol,
        scopeExchange: exchange || 'HOSE',
        options: {
          includeExternalResearch: false,
          includeFinancials: true
        }
      })
    });

    if (!response.ok) {
      return { available: false, count: 0, history_items: [], source: 'analyse_unavailable' };
    }

    const result = await response.json();
    const data = result?.data || {};
    const summary = data?.summary || {};
    const aiContext = {
      available: true,
      count: 1,
      source: 'analyse',
      latest_decision_label: summary?.decision_label || summary?.recommendation || data?.analysis_status || null,
      latest_total_score: summary?.total_score ?? null,
      latest_risk_score: summary?.risk_score ?? null,
      history_items: [
        {
          created_at: data?.generated_at || null,
          decision_label: summary?.decision_label || summary?.recommendation || null,
          total_score: summary?.total_score ?? null,
          risk_score: summary?.risk_score ?? null,
          report_id: data?.report_id || null
        }
      ],
      llm_summary: summary?.summary || summary?.headline || null,
      report_id: data?.report_id || null
    };

    aiAnalysisCache.set(memoKey, aiContext);
    setTimeout(() => aiAnalysisCache.delete(memoKey), AI_CACHE_TTL_MS);
    return aiContext;
  } catch (error) {
    return { available: false, count: 0, history_items: [], source: 'analyse_error' };
  }
};

const getOrAnalyseWatchlistStock = async ({ symbol, exchange, authToken }) => {
  const fs = require('fs');
  const logPath = require('path').join(__dirname, '../../../debug_watchlist.log');
  
  // 1. Fetch user's report history for this stock from the last 3 weeks (21 days)
  const fromDate = new Date(Date.now() - 21 * 24 * 60 * 60 * 1000).toISOString();
  const toDate = new Date().toISOString();

  let history = { available: false, count: 0, history_items: [] };
  try {
    history = await defaultAnalyseHistoryClient({
      symbol,
      exchange,
      authToken,
      fromDate,
      limit: 100
    });
    fs.appendFileSync(logPath, `[DEBUG] ${symbol} - History response: available=${history.available}, count=${history.count}, itemsLen=${history.history_items?.length}\n`);
  } catch (error) {
    console.error(`[PortfolioService] Failed to check report history for ${symbol}`, error);
    fs.appendFileSync(logPath, `[DEBUG] ${symbol} - History check failed: ${error.message}\n`);
  }

  // 2. Check if the latest report in history is within 3 days (72 hours)
  if (history.available && history.history_items && history.history_items.length > 0) {
    const latestReport = history.history_items[0];
    const createdAt = new Date(latestReport.created_at);
    const diffMs = Date.now() - createdAt.getTime();
    const isWithin3Days = diffMs <= 3 * 24 * 60 * 60 * 1000;

    fs.appendFileSync(logPath, `[DEBUG] ${symbol} - Latest report: id=${latestReport.report_id}, created_at=${latestReport.created_at}, parsed_created_at=${createdAt.toISOString()}, diffMs=${diffMs}, isWithin3Days=${isWithin3Days}\n`);

    if (isWithin3Days) {
      // Reuse this report data to build the aiContext
      fs.appendFileSync(logPath, `[DEBUG] ${symbol} - REUSING report\n`);
      return {
        available: true,
        count: history.count,
        source: 'analyse',
        latest_decision_label: latestReport.decision_label,
        latest_total_score: latestReport.total_score,
        latest_risk_score: latestReport.risk_score,
        history_items: history.history_items,
        llm_summary: latestReport.llm_summary || null,
        report_id: latestReport.report_id
      };
    }
  }

  fs.appendFileSync(logPath, `[DEBUG] ${symbol} - TRIGGERING FRESH LLM ANALYSIS\n`);
  // 3. If no report within the last 3 days, trigger a fresh LLM analysis
  return await invokeAnalyseAnalysis({ symbol, exchange, authToken, includeAi: true });
};

const getPortfolioHoldingsAdvice = async (userId, options = {}) => {
  const repository = options.portfolioRepository || portfolioRepository;
  const analyseClient = options.analyseClient || defaultAnalyseHistoryClient;
  const authToken = options.authToken || null;
  const cacheKey = `${userId}:${options.forceRefresh ? 'refresh' : 'cached'}`;
  const cachedEntry = !options.forceRefresh ? adviceCache.get(cacheKey) : null;

  if (cachedEntry && Date.now() - cachedEntry.fetchedAt < ADVICE_CACHE_TTL_MS) {
    return cachedEntry.payload;
  }

  const holdings = await repository.findActiveHoldingsByUser(userId);
  const stockIds = holdings.map((holding) => holding.stock_id?._id).filter(Boolean);

  const latestPrices = await repository.findLatestPricesByStockIds(stockIds);
  const latestPriceMap = new Map(latestPrices.map((price) => [price._id.toString(), price]));

  const prices7dEntries = await Promise.all(
    stockIds.map(async (stockId) => {
      const prices = await repository.findRecentPricesForStock(stockId, RECENT_PRICE_DAYS);
      return [stockId.toString(), prices];
    })
  );
  const prices7dMap = new Map(prices7dEntries);

  const items = await Promise.all(
    holdings.map(async (holding) => {
      const pnlItem = buildPnlItem(holding, latestPriceMap, prices7dMap);
      const pricePoints = pnlItem.prices_7d || [];
      const closes = pricePoints.map((point) => toNumber(point.close)).filter((value) => value !== null);
      const latestClose = closes[closes.length - 1] ?? pnlItem.close_price;
      const firstClose = closes[0] ?? latestClose;
      const trendSlope = latestClose && firstClose ? round2(((latestClose - firstClose) / firstClose) * 100) : 0;
      const recentMovePct = pnlItem.price_change_percent ?? 0;
      const recommendation = deriveRecommendation({
        hasHolding: Boolean(holding),
        pnlPct: pnlItem.unrealized_pnl_pct,
        trendSlope,
        recentMovePct
      });
      const aiContext = await buildAnalyseHistoryContext({
        symbol: pnlItem.symbol,
        exchange: pnlItem.exchange,
        authToken,
        analyseClient
      });

      return {
        holding_id: pnlItem.holding_id,
        symbol: pnlItem.symbol,
        company_name: pnlItem.company_name,
        exchange: pnlItem.exchange,
        average_cost: pnlItem.average_cost,
        quantity: pnlItem.quantity,
        holding_date: pnlItem.holding_date,
        close_price: pnlItem.close_price,
        price_change: pnlItem.price_change,
        price_change_percent: pnlItem.price_change_percent,
        cost: pnlItem.cost,
        market_value: pnlItem.market_value,
        unrealized_pnl: pnlItem.unrealized_pnl,
        unrealized_pnl_pct: pnlItem.unrealized_pnl_pct,
        status: pnlItem.status,
        pnl_signal: pnlItem.pnl_signal,
        recommendation,
        explanation: buildExplanation({
          symbol: pnlItem.symbol,
          pnlPct: pnlItem.unrealized_pnl_pct,
          recentMovePct,
          trendSlope,
          recommendation,
          aiContext
        }),
        trend_7d_pct: trendSlope,
        prices_7d: pricePoints,
        ai_context: {
          available: aiContext.available,
          source: aiContext.source,
          count: aiContext.count,
          latest_decision_label: aiContext.latest_decision_label || null,
          latest_total_score: aiContext.latest_total_score ?? null,
          latest_risk_score: aiContext.latest_risk_score ?? null,
          history_items: aiContext.history_items || []
        },
        note: pnlItem.note,
        price_as_of: pnlItem.price_as_of
      };
    })
  );

  const payload = {
    generated_at: new Date().toISOString(),
    data_as_of: items.reduce((latest, item) => (item.price_as_of && item.price_as_of > latest ? item.price_as_of : latest), null),
    portfolio_summary: buildPortfolioSummary(items),
    items
  };

  adviceCache.set(cacheKey, { fetchedAt: Date.now(), payload });
  return payload;
};

const getPortfolioWatchlistBatch = async (userId, options = {}) => {
  const includeAi = options.includeAi === true;
  const authToken = options.authToken || null;
  const repository = options.portfolioRepository || portfolioRepository;
  const watchlistRepository = options.watchlistRepository || watchlistsRepository;

  const watchlistEntries = await watchlistRepository.findUserWatchlist(userId);
  const stockEntries = watchlistEntries.filter((entry) => entry.stock_id).map((entry) => ({
    entry,
    symbol: entry.stock_id.symbol,
    company_name: entry.stock_id.company_name,
    exchange: entry.stock_id.market_id?.code || entry.stock_id.market_id?.name || 'HOSE',
    stockId: entry.stock_id._id.toString()
  }));

  const holdings = await repository.findActiveHoldingsByUser(userId);
  const holdingByStockId = new Map(holdings.map((holding) => [holding.stock_id?._id?.toString(), holding]));
  const stockIds = stockEntries.map((stock) => stock.stockId);

  const latestPrices = await repository.findLatestPricesByStockIds(stockIds);
  const latestPriceMap = new Map(latestPrices.map((price) => [price._id.toString(), price]));

  const prices7dEntries = await Promise.all(
    stockIds.map(async (stockId) => {
      const prices = await repository.findRecentPricesForStock(stockId, RECENT_PRICE_DAYS);
      return [stockId.toString(), prices];
    })
  );
  const prices7dMap = new Map(prices7dEntries);

  const items = await Promise.all(
    stockEntries.map(async ({ entry, symbol, company_name, exchange, stockId }) => {
      const holding = holdingByStockId.get(stockId) || null;
      const latest = latestPriceMap.get(stockId) || null;
      const pricePoints = (prices7dMap.get(stockId) || []).map(buildPricePoint);
      const closePrice = toNumber(latest?.close_price);
      const averageCost = holding ? toNumber(holding.average_cost) : null;
      const quantity = holding ? toNumber(holding.quantity) : null;
      const cost = typeof averageCost === 'number' && typeof quantity === 'number' ? round2(averageCost * quantity) : null;
      const marketValue = typeof closePrice === 'number' && typeof quantity === 'number' ? round2(closePrice * quantity) : null;
      const unrealizedPnl = typeof cost === 'number' && typeof marketValue === 'number' ? round2(marketValue - cost) : null;
      const unrealizedPnlPct = typeof averageCost === 'number' && averageCost > 0 && typeof closePrice === 'number' ? round2(((closePrice - averageCost) / averageCost) * 100) : null;
      const status = unrealizedPnl === null ? 'WATCHLIST_ONLY' : unrealizedPnl >= 0 ? 'PROFIT' : 'LOSS';

      const closes = pricePoints.map((point) => toNumber(point.close)).filter((value) => value !== null);
      const latestClose = closes[closes.length - 1] ?? closePrice;
      const firstClose = closes[0] ?? latestClose;
      const trendSlope = latestClose && firstClose ? round2(((latestClose - firstClose) / firstClose) * 100) : 0;
      const recentMovePct = toNumber(latest?.price_change_percent) ?? 0;
      const recommendation = deriveRecommendation({ hasHolding: Boolean(holding), pnlPct: unrealizedPnlPct, trendSlope, recentMovePct });
      const aiContext = includeAi ? await getOrAnalyseWatchlistStock({ symbol, exchange, authToken }) : { available: false, count: 0, history_items: [], source: 'disabled' };

      return {
        watchlist_id: entry._id.toString(),
        symbol,
        company_name,
        exchange,
        position_status: holding ? 'HELD' : 'WATCHLIST_ONLY',
        average_cost: averageCost,
        quantity,
        close_price: closePrice,
        cost,
        market_value: marketValue,
        unrealized_pnl: unrealizedPnl,
        unrealized_pnl_pct: unrealizedPnlPct,
        status,
        recommendation,
        explanation: buildExplanation({
          symbol,
          pnlPct: unrealizedPnlPct,
          recentMovePct,
          trendSlope,
          recommendation,
          aiContext
        }),
        trend_7d_pct: trendSlope,
        prices_7d: pricePoints,
        ai_context: {
          available: aiContext.available,
          source: aiContext.source,
          count: aiContext.count,
          latest_decision_label: aiContext.latest_decision_label || null,
          latest_total_score: aiContext.latest_total_score ?? null,
          latest_risk_score: aiContext.latest_risk_score ?? null,
          history_items: aiContext.history_items || [],
          llm_summary: aiContext.llm_summary || null,
          report_id: aiContext.report_id || null
        },
        holding_date: holding?.holding_date ? formatDate(holding.holding_date) : null,
        note: holding?.note || ''
      };
    })
  );

  return {
    generated_at: new Date().toISOString(),
    data_as_of: items.reduce((latest, item) => (item.price_as_of && item.price_as_of > latest ? item.price_as_of : latest), null),
    portfolio_summary: buildPortfolioSummary(items),
    items
  };
};

const getPortfolioWatchlistDetail = async (userId, symbol, options = {}) => {
  const includeAi = options.includeAi === true;
  const authToken = options.authToken || null;
  const repository = options.portfolioRepository || portfolioRepository;
  const watchlistRepository = options.watchlistRepository || watchlistsRepository;
  const normalizedSymbol = String(symbol || '').trim().toUpperCase();

  if (!normalizedSymbol) {
    throw new Error('INVALID_SYMBOL');
  }

  const watchlistEntries = await watchlistRepository.findUserWatchlist(userId);
  const entry = watchlistEntries.find((item) => item.stock_id?.symbol === normalizedSymbol);
  if (!entry?.stock_id) {
    throw new Error('WATCHLIST_ENTRY_NOT_FOUND');
  }

  const holding = (await repository.findActiveHoldingsByUser(userId)).find((item) => item.stock_id?._id?.toString() === entry.stock_id._id.toString()) || null;
  const latestPrices = await repository.findLatestPricesByStockIds([entry.stock_id._id.toString()]);
  const latest = latestPrices[0] || null;
  const prices7d = await repository.findRecentPricesForStock(entry.stock_id._id, RECENT_PRICE_DAYS);
  const pricePoints = (prices7d || []).map(buildPricePoint);
  const closePrice = toNumber(latest?.close_price);
  const averageCost = holding ? toNumber(holding.average_cost) : null;
  const quantity = holding ? toNumber(holding.quantity) : null;
  const cost = typeof averageCost === 'number' && typeof quantity === 'number' ? round2(averageCost * quantity) : null;
  const marketValue = typeof closePrice === 'number' && typeof quantity === 'number' ? round2(closePrice * quantity) : null;
  const unrealizedPnl = typeof cost === 'number' && typeof marketValue === 'number' ? round2(marketValue - cost) : null;
  const unrealizedPnlPct = typeof averageCost === 'number' && averageCost > 0 && typeof closePrice === 'number' ? round2(((closePrice - averageCost) / averageCost) * 100) : null;
  const closes = pricePoints.map((point) => toNumber(point.close)).filter((value) => value !== null);
  const latestClose = closes[closes.length - 1] ?? closePrice;
  const firstClose = closes[0] ?? latestClose;
  const trendSlope = latestClose && firstClose ? round2(((latestClose - firstClose) / firstClose) * 100) : 0;
  const recentMovePct = toNumber(latest?.price_change_percent) ?? 0;
  const recommendation = deriveRecommendation({ hasHolding: Boolean(holding), pnlPct: unrealizedPnlPct, trendSlope, recentMovePct });
  const aiContext = includeAi ? await getOrAnalyseWatchlistStock({ symbol: normalizedSymbol, exchange: entry.stock_id.market_id?.code || entry.stock_id.market_id?.name || 'HOSE', authToken }) : { available: false, count: 0, history_items: [], source: 'disabled' };

  return {
    symbol: normalizedSymbol,
    company_name: entry.stock_id.company_name,
    exchange: entry.stock_id.market_id?.code || entry.stock_id.market_id?.name || 'HOSE',
    position_status: holding ? 'HELD' : 'WATCHLIST_ONLY',
    average_cost: averageCost,
    quantity,
    close_price: closePrice,
    cost,
    market_value: marketValue,
    unrealized_pnl: unrealizedPnl,
    unrealized_pnl_pct: unrealizedPnlPct,
    recommendation,
    explanation: buildExplanation({ symbol: normalizedSymbol, pnlPct: unrealizedPnlPct, recentMovePct, trendSlope, recommendation, aiContext }),
    trend_7d_pct: trendSlope,
    prices_7d: pricePoints,
    ai_context: {
      available: aiContext.available,
      source: aiContext.source,
      count: aiContext.count,
      latest_decision_label: aiContext.latest_decision_label || null,
      latest_total_score: aiContext.latest_total_score ?? null,
      latest_risk_score: aiContext.latest_risk_score ?? null,
      history_items: aiContext.history_items || [],
      llm_summary: aiContext.llm_summary || null,
      report_id: aiContext.report_id || null
    },
    holding_date: holding?.holding_date ? formatDate(holding.holding_date) : null,
    note: holding?.note || ''
  };
};

const getPortfolioWatchlistHistory = async ({ symbol, exchange, days = 3, authToken }) => {
  const fromDate = new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString();
  const toDate = new Date().toISOString();

  return await defaultAnalyseHistoryClient({
    symbol,
    exchange,
    authToken,
    fromDate,
    toDate,
    limit: 100
  });
};

module.exports = {
  getPortfolioPnl,
  getPortfolioHoldingsAdvice,
  getPortfolioWatchlistBatch,
  getPortfolioWatchlistDetail,
  getPortfolioWatchlistHistory
};
