const holdingsRepository = require('./holdings.repository');


const DEFAULT_STATUS = 'ACTIVE';
const DEFAULT_PAGE = 1;
const DEFAULT_LIMIT = 20;

const createAppError = (message, statusCode, code = null, details = null) => {
  const error = new Error(message);
  error.statusCode = statusCode;
  if (code) error.code = code;
  if (details) error.details = details;
  return error;
};

const normalizeSymbol = (value) => {
  if (typeof value !== 'string') {
    throw createAppError('INVALID_STOCK_SYMBOL', 400, 'INVALID_STOCK_SYMBOL');
  }

  const normalized = value.trim().toUpperCase();
  if (!normalized || normalized.length > 10 || !/^[A-Z0-9]+$/.test(normalized)) {
    throw createAppError('INVALID_STOCK_SYMBOL', 400, 'INVALID_STOCK_SYMBOL');
  }

  return normalized;
};

const getTodayInVietnam = () => {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  });

  return formatter.format(new Date());
};

const formatDate = (value) => {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString().slice(0, 10);
};

const validateHoldingDate = (holdingDate) => {
  const normalizedDate = formatDate(holdingDate);
  if (!normalizedDate) {
    throw createAppError('VALIDATION_ERROR', 400, 'VALIDATION_ERROR');
  }

  if (normalizedDate >= getTodayInVietnam()) {
    throw createAppError('HOLDING_DATE_MUST_BE_IN_PAST', 400, 'HOLDING_DATE_MUST_BE_IN_PAST');
  }

  return normalizedDate;
};

const getMarketLabel = (stock) => {
  return stock?.market_id?.code || stock?.market_id?.name || null;
};

const buildHoldingItem = (holding, latestPriceMap) => {
  const stock = holding.stock_id;
  const stockId = stock?._id?.toString?.() || null;
  const latestMarketPrice = stockId ? latestPriceMap.get(stockId)?.close_price ?? null : null;

  return {
    holding_id: holding._id.toString(),
    stock: stock ? {
      _id: stock._id.toString(),
      symbol: stock.symbol,
      company_name: stock.company_name,
      market: getMarketLabel(stock)
    } : null,
    average_cost: holding.average_cost,
    quantity: holding.quantity,
    holding_date: formatDate(holding.holding_date),
    latest_market_price: latestMarketPrice,
    note: holding.note || '',
    status: holding.status,
    created_at: holding.created_at,
    updated_at: holding.updated_at
  };
};

const getValidatedStock = async (symbolInput) => {
  const symbol = normalizeSymbol(symbolInput);
  const stock = await holdingsRepository.findStockBySymbol(symbol);

  if (!stock) {
    throw createAppError('STOCK_NOT_FOUND', 404, 'STOCK_NOT_FOUND');
  }

  return stock;
};

const ensureActiveStock = (stock) => {
  if (stock.status !== 'ACTIVE') {
    throw createAppError('STOCK_INACTIVE', 409, 'STOCK_INACTIVE');
  }
};

const sanitizeHoldingPayload = (body) => {
  const holdingDate = validateHoldingDate(body.holding_date);
  return {
    average_cost: body.average_cost,
    quantity: body.quantity,
    holding_date: new Date(holdingDate),
    note: body.note?.trim?.() || ''
  };
};

const getMyHoldings = async (userId, query = {}) => {
  const status = query.status || DEFAULT_STATUS;
  const page = Number(query.page) || DEFAULT_PAGE;
  const limit = Number(query.limit) || DEFAULT_LIMIT;

  const result = await holdingsRepository.findHoldingsByUser(userId, { status, page, limit });
  const stockIds = result.items.map((item) => item.stock_id?._id).filter(Boolean);
  const latestPrices = await holdingsRepository.findLatestPricesByStockIds(stockIds);
  const latestPriceMap = new Map(latestPrices.map((price) => [price._id.toString(), price]));

  return {
    items: result.items.map((item) => buildHoldingItem(item, latestPriceMap)),
    pagination: {
      page,
      limit,
      total: result.total
    }
  };
};

const getHoldingDetail = async (userId, symbol) => {
  const stock = await getValidatedStock(symbol);
  const holding = await holdingsRepository.findHoldingByUserAndStock(userId, stock._id, {
    populate: true,
    lean: true
  });

  if (!holding) {
    throw createAppError('HOLDING_NOT_FOUND', 404, 'HOLDING_NOT_FOUND');
  }

  const latestPrice = await holdingsRepository.findLatestPriceByStockId(stock._id);
  const latestPriceMap = new Map([[stock._id.toString(), latestPrice || { close_price: null }]]);
  return buildHoldingItem(holding, latestPriceMap);
};

const saveHolding = async (userId, symbol, body) => {
  const stock = await getValidatedStock(symbol);
  ensureActiveStock(stock);
  const payload = sanitizeHoldingPayload(body);

  let result;
  let session;

  try {
    session = await holdingsRepository.startSession();
    await session.withTransaction(async () => {
      let holding = await holdingsRepository.findHoldingByUserAndStock(userId, stock._id, {
        includeRemoved: true,
        session
      });

      if (holding) {
        holding.average_cost = payload.average_cost;
        holding.quantity = payload.quantity;
        holding.holding_date = payload.holding_date;
        holding.note = payload.note;
        holding.status = 'ACTIVE';
        holding.removed_at = null;
        result = await holdingsRepository.saveDocument(holding, session);
      } else {
        result = await holdingsRepository.createHolding({
          user_id: userId,
          stock_id: stock._id,
          average_cost: payload.average_cost,
          quantity: payload.quantity,
          holding_date: payload.holding_date,
          note: payload.note,
          status: 'ACTIVE',
          removed_at: null
        }, session);
      }
    });
  } catch (error) {
    const unsupportedTransactions = error?.message?.includes('Transaction numbers are only allowed on a replica set member or mongos')
      || error?.message?.includes('Transaction support is not available');

    if (!unsupportedTransactions) {
      throw error;
    }

    let holding = await holdingsRepository.findHoldingByUserAndStock(userId, stock._id, { includeRemoved: true });
    if (holding) {
      holding.average_cost = payload.average_cost;
      holding.quantity = payload.quantity;
      holding.holding_date = payload.holding_date;
      holding.note = payload.note;
      holding.status = 'ACTIVE';
      holding.removed_at = null;
      result = await holdingsRepository.saveDocument(holding);
    } else {
      result = await holdingsRepository.createHolding({
        user_id: userId,
        stock_id: stock._id,
        average_cost: payload.average_cost,
        quantity: payload.quantity,
        holding_date: payload.holding_date,
        note: payload.note,
        status: 'ACTIVE',
        removed_at: null
      });
    }
  } finally {
    if (session) {
      await session.endSession();
    }
  }

  const latestPrice = await holdingsRepository.findLatestPriceByStockId(stock._id);
  return {
    holding: {
      holding_id: result._id.toString(),
      stock: {
        _id: stock._id.toString(),
        symbol: stock.symbol,
        company_name: stock.company_name,
        market: getMarketLabel(stock)
      },
      average_cost: result.average_cost,
      quantity: result.quantity,
      holding_date: formatDate(result.holding_date),
      latest_market_price: latestPrice?.close_price ?? null,
      note: result.note || '',
      status: result.status
    }
  };
};

const updateHolding = async (userId, symbol, body) => {
  const stock = await getValidatedStock(symbol);
  ensureActiveStock(stock);
  const holding = await holdingsRepository.findHoldingByUserAndStock(userId, stock._id);

  if (!holding) {
    throw createAppError('HOLDING_NOT_FOUND', 404, 'HOLDING_NOT_FOUND');
  }

  const payload = sanitizeHoldingPayload(body);
  holding.average_cost = payload.average_cost;
  holding.quantity = payload.quantity;
  holding.holding_date = payload.holding_date;
  holding.note = payload.note;
  holding.status = 'ACTIVE';
  holding.removed_at = null;

  const savedHolding = await holdingsRepository.saveDocument(holding);
  const latestPrice = await holdingsRepository.findLatestPriceByStockId(stock._id);

  return {
    holding: {
      holding_id: savedHolding._id.toString(),
      stock: {
        _id: stock._id.toString(),
        symbol: stock.symbol,
        company_name: stock.company_name,
        market: getMarketLabel(stock)
      },
      average_cost: savedHolding.average_cost,
      quantity: savedHolding.quantity,
      holding_date: formatDate(savedHolding.holding_date),
      latest_market_price: latestPrice?.close_price ?? null,
      note: savedHolding.note || '',
      status: savedHolding.status
    }
  };
};

const removeHolding = async (userId, symbol) => {
  const stock = await getValidatedStock(symbol);
  const holding = await holdingsRepository.findHoldingByUserAndStock(userId, stock._id);

  if (!holding) {
    throw createAppError('HOLDING_NOT_FOUND', 404, 'HOLDING_NOT_FOUND');
  }

  holding.status = 'REMOVED';
  holding.removed_at = new Date();
  await holdingsRepository.saveDocument(holding);

  return {
    holding_id: holding._id.toString(),
    status: holding.status
  };
};

/**
 * Lấy giá trị thị trường hiện tại theo múi giờ Việt Nam dạng YYYYMMDD.
 */
const getTodayTimeId = () => {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  });
  return formatter.format(new Date()).replace(/-/g, '');
};

/**
 * Tính P&L (lời/lỗ chưa thực hiện) cho tất cả ACTIVE holdings của user.
 * Không gọi LLM — chỉ tính số thuần từ DB.
 *
 * @param {string} userId - MongoDB ObjectId của user
 * @returns {Promise<object>} portfolio P&L + per-item P&L + 7d price chart
 */
const getHoldingsPnl = async (userId) => {
  // 1. Lấy tất cả ACTIVE holdings (không phân trang — cần tất cả để tính portfolio)
  const ALL_LIMIT = 500;
  const result = await holdingsRepository.findHoldingsByUser(userId, {
    status: 'ACTIVE',
    page: 1,
    limit: ALL_LIMIT
  });

  const holdings = result.items;
  if (!holdings.length) {
    return {
      generated_at: new Date().toISOString(),
      data_as_of: getTodayTimeId(),
      portfolio: {
        total_cost: 0,
        total_market_value: 0,
        total_unrealized_pnl: 0,
        total_unrealized_pnl_pct: 0,
        count_profit: 0,
        count_loss: 0
      },
      items: []
    };
  }

  // 2. Thu thập stockIds
  const stockIds = holdings
    .map((h) => h.stock_id?._id)
    .filter(Boolean);

  // 3. Batch fetch: latest prices + 7d chart — song song
  const [latestPrices, pricesMap] = await Promise.all([
    holdingsRepository.findLatestPricesByStockIds(stockIds),
    holdingsRepository.findPricesForStockIds(stockIds, 7)
  ]);

  // 4. Build lookup map: stockId → latest price row
  const latestPriceMap = new Map(latestPrices.map((p) => [p._id.toString(), p]));

  // 5. Tính P&L từng mã
  let totalCost = 0;
  let totalMarketValue = 0;
  let countProfit = 0;
  let countLoss = 0;
  let globalDataAsOf = getTodayTimeId();

  const items = holdings.map((holding) => {
    const stock = holding.stock_id;
    const stockId = stock?._id?.toString?.() || null;
    const priceRow = stockId ? latestPriceMap.get(stockId) : null;

    const averageCost = Number(holding.average_cost) || 0;
    const quantity = Number(holding.quantity) || 0;
    const closePrice = priceRow?.close_price != null ? Number(priceRow.close_price) : null;
    const dataAsOf = priceRow?.time_id ? String(priceRow.time_id) : getTodayTimeId();

    const cost = averageCost * quantity;
    const marketValue = closePrice != null ? closePrice * quantity : null;
    const unrealizedPnl = marketValue != null ? marketValue - cost : null;
    const unrealizedPnlPct =
      unrealizedPnl != null && averageCost > 0
        ? ((closePrice - averageCost) / averageCost) * 100
        : null;
    const status = unrealizedPnl != null ? (unrealizedPnl >= 0 ? 'PROFIT' : 'LOSS') : null;

    // Cộng dồn portfolio (chỉ khi có giá)
    totalCost += cost;
    if (marketValue != null) {
      totalMarketValue += marketValue;
      if (status === 'PROFIT') countProfit += 1;
      else countLoss += 1;
    }

    // 7d price chart
    const prices7d = (stockId ? pricesMap[stockId] || [] : []).map((p) => ({
      date: p.date,
      close: p.close,
      open: p.open,
      high: p.high,
      low: p.low,
      volume: p.volume
    }));

    return {
      holding_id: holding._id?.toString?.() || null,
      symbol: stock?.symbol || null,
      company_name: stock?.company_name || null,
      market: getMarketLabel(stock),
      average_cost: averageCost,
      quantity,
      holding_date: formatDate(holding.holding_date),
      close_price: closePrice,
      data_as_of: dataAsOf,
      market_value: marketValue,
      cost,
      unrealized_pnl: unrealizedPnl != null ? Math.round(unrealizedPnl) : null,
      unrealized_pnl_pct:
        unrealizedPnlPct != null ? Math.round(unrealizedPnlPct * 100) / 100 : null,
      status,
      prices_7d: prices7d
    };
  });

  const totalUnrealizedPnl = totalMarketValue - totalCost;
  const totalUnrealizedPnlPct =
    totalCost > 0 ? (totalUnrealizedPnl / totalCost) * 100 : 0;

  return {
    generated_at: new Date().toISOString(),
    data_as_of: globalDataAsOf,
    portfolio: {
      total_cost: Math.round(totalCost),
      total_market_value: Math.round(totalMarketValue),
      total_unrealized_pnl: Math.round(totalUnrealizedPnl),
      total_unrealized_pnl_pct: Math.round(totalUnrealizedPnlPct * 100) / 100,
      count_profit: countProfit,
      count_loss: countLoss
    },
    items
  };
};

module.exports = {
  getMyHoldings,
  getHoldingDetail,
  saveHolding,
  updateHolding,
  removeHolding,
  getHoldingsPnl
};
