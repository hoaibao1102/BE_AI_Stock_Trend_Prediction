const holdingsRepository = require('./holdings.repository');
const { normalizePrices7d } = require('../../utils/price-point.utils');


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

const round2 = (value) => Math.round(value * 100) / 100;

const computeWeightedAverageCost = (oldQty, oldAvg, buyQty, buyPrice, fee = 0) => {
  const totalQty = oldQty + buyQty;
  if (totalQty <= 0) return 0;
  const totalCost = (oldQty * oldAvg) + (buyQty * buyPrice) + fee;
  return round2(totalCost / totalQty);
};

const validateTradeDate = (tradeDate) => validateHoldingDate(tradeDate);

const sanitizeTransactionPayload = (body) => {
  const tradeDate = validateTradeDate(body.trade_date);
  const transactionType = String(body.transaction_type || '').trim().toUpperCase();

  if (!['BUY', 'SELL'].includes(transactionType)) {
    throw createAppError('INVALID_TRANSACTION_TYPE', 400, 'INVALID_TRANSACTION_TYPE');
  }

  return {
    transaction_type: transactionType,
    trade_date: new Date(tradeDate),
    quantity: body.quantity,
    price: body.price,
    fee: body.fee ?? 0,
    tax: body.tax ?? 0,
    note: body.note?.trim?.() || ''
  };
};

const buildTransactionItem = (transaction) => ({
  transaction_id: transaction._id.toString(),
  transaction_type: transaction.transaction_type,
  trade_date: formatDate(transaction.trade_date),
  quantity: transaction.quantity,
  price: transaction.price,
  fee: transaction.fee,
  tax: transaction.tax,
  note: transaction.note || '',
  status: transaction.status,
  created_at: transaction.created_at,
  updated_at: transaction.updated_at
});

const runWithOptionalTransaction = async (callback) => {
  let session;

  try {
    session = await holdingsRepository.startSession();
    let result;
    await session.withTransaction(async () => {
      result = await callback(session);
    });
    return result;
  } catch (error) {
    const unsupportedTransactions = error?.message?.includes('Transaction numbers are only allowed on a replica set member or mongos')
      || error?.message?.includes('Transaction support is not available');

    if (!unsupportedTransactions) {
      throw error;
    }

    return callback(null);
  } finally {
    if (session) {
      await session.endSession();
    }
  }
};

const buildHoldingResponse = async (holdingDoc, stock) => {
  const latestPrice = await holdingsRepository.findLatestPriceByStockId(stock._id);
  const quantity = Number(holdingDoc.quantity) || 0;
  const averageCost = Number(holdingDoc.average_cost) || 0;

  return {
    holding_id: holdingDoc._id.toString(),
    stock: {
      _id: stock._id.toString(),
      symbol: stock.symbol,
      company_name: stock.company_name,
      market: getMarketLabel(stock)
    },
    average_cost: averageCost,
    quantity,
    total_cost: round2(averageCost * quantity),
    holding_date: formatDate(holdingDoc.holding_date),
    latest_market_price: latestPrice?.close_price ?? null,
    note: holdingDoc.note || '',
    status: holdingDoc.status
  };
};

const applyBuyTransaction = async (userId, stock, payload, session = null) => {
  let holding = await holdingsRepository.findHoldingByUserAndStock(userId, stock._id, {
    includeRemoved: true,
    session
  });

  const buyQty = payload.quantity;
  const buyPrice = payload.price;
  const fee = payload.fee || 0;

  if (holding && holding.status === 'ACTIVE') {
    const newQty = holding.quantity + buyQty;
    const newAvg = computeWeightedAverageCost(holding.quantity, holding.average_cost, buyQty, buyPrice, fee);
    holding.quantity = newQty;
    holding.average_cost = newAvg;
    holding.holding_date = payload.trade_date;
    if (payload.note) {
      holding.note = payload.note;
    }
    holding.status = 'ACTIVE';
    holding.removed_at = null;
    holding = await holdingsRepository.saveDocument(holding, session);
  } else if (holding && holding.status === 'REMOVED') {
    holding.average_cost = computeWeightedAverageCost(0, 0, buyQty, buyPrice, fee);
    holding.quantity = buyQty;
    holding.holding_date = payload.trade_date;
    holding.note = payload.note || '';
    holding.status = 'ACTIVE';
    holding.removed_at = null;
    holding = await holdingsRepository.saveDocument(holding, session);
  } else {
    holding = await holdingsRepository.createHolding({
      user_id: userId,
      stock_id: stock._id,
      average_cost: computeWeightedAverageCost(0, 0, buyQty, buyPrice, fee),
      quantity: buyQty,
      holding_date: payload.trade_date,
      note: payload.note || '',
      status: 'ACTIVE',
      removed_at: null
    }, session);
  }

  const transaction = await holdingsRepository.createTransaction({
    user_id: userId,
    stock_id: stock._id,
    transaction_type: 'BUY',
    trade_date: payload.trade_date,
    quantity: buyQty,
    price: buyPrice,
    fee,
    tax: payload.tax || 0,
    note: payload.note,
    source: 'MANUAL',
    status: 'ACTIVE'
  }, session);

  return { holding, transaction };
};

const applySellTransaction = async (userId, stock, payload, session = null) => {
  const holding = await holdingsRepository.findHoldingByUserAndStock(userId, stock._id, { session });

  if (!holding) {
    throw createAppError('HOLDING_NOT_FOUND', 404, 'HOLDING_NOT_FOUND');
  }

  const sellQty = payload.quantity;
  if (sellQty > holding.quantity) {
    throw createAppError('INSUFFICIENT_QUANTITY', 400, 'INSUFFICIENT_QUANTITY', {
      available_quantity: holding.quantity,
      requested_quantity: sellQty
    });
  }

  const remainingQty = holding.quantity - sellQty;
  if (remainingQty === 0) {
    holding.status = 'REMOVED';
    holding.removed_at = new Date();
    holding.quantity = 0;
  } else {
    holding.quantity = remainingQty;
    holding.status = 'ACTIVE';
    holding.removed_at = null;
  }

  const savedHolding = await holdingsRepository.saveDocument(holding, session);

  const transaction = await holdingsRepository.createTransaction({
    user_id: userId,
    stock_id: stock._id,
    transaction_type: 'SELL',
    trade_date: payload.trade_date,
    quantity: sellQty,
    price: payload.price,
    fee: payload.fee || 0,
    tax: payload.tax || 0,
    note: payload.note,
    source: 'MANUAL',
    status: 'ACTIVE'
  }, session);

  return { holding: savedHolding, transaction };
};

const recordTransaction = async (userId, symbol, body) => {
  const stock = await getValidatedStock(symbol);
  ensureActiveStock(stock);
  const payload = sanitizeTransactionPayload(body);

  const { holding, transaction } = await runWithOptionalTransaction(async (session) => {
    if (payload.transaction_type === 'BUY') {
      return applyBuyTransaction(userId, stock, payload, session);
    }
    return applySellTransaction(userId, stock, payload, session);
  });

  const holdingResponse = holding.status === 'REMOVED'
    ? null
    : await buildHoldingResponse(holding, stock);

  return {
    transaction: buildTransactionItem(transaction),
    holding: holdingResponse
  };
};

const getTransactions = async (userId, symbol, query = {}) => {
  const stock = await getValidatedStock(symbol);
  const page = Number(query.page) || DEFAULT_PAGE;
  const limit = Number(query.limit) || 50;
  const status = query.status || 'ACTIVE';

  const result = await holdingsRepository.findTransactionsByUserAndStock(userId, stock._id, {
    page,
    limit,
    status
  });

  return {
    items: result.items.map(buildTransactionItem),
    pagination: {
      page,
      limit,
      total: result.total
    }
  };
};

const buildHoldingItem = (holding, latestPriceMap) => {
  const stock = holding.stock_id;
  const stockId = stock?._id?.toString?.() || null;
  const latestMarketPrice = stockId ? latestPriceMap.get(stockId)?.close_price ?? null : null;
  const quantity = Number(holding.quantity) || 0;
  const averageCost = Number(holding.average_cost) || 0;

  return {
    holding_id: holding._id.toString(),
    stock: stock ? {
      _id: stock._id.toString(),
      symbol: stock.symbol,
      company_name: stock.company_name,
      market: getMarketLabel(stock)
    } : null,
    average_cost: averageCost,
    quantity,
    total_cost: round2(averageCost * quantity),
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
        count_loss: 0,
        position_count: 0
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
  let countNeutral = 0;
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
      unrealizedPnl != null && cost > 0
        ? (unrealizedPnl / cost) * 100
        : unrealizedPnl != null && averageCost > 0
          ? ((closePrice - averageCost) / averageCost) * 100
          : null;
    const status = unrealizedPnl != null ? (unrealizedPnl >= 0 ? 'PROFIT' : 'LOSS') : null;

    totalCost += cost;
    if (marketValue != null) {
      totalMarketValue += marketValue;
      if (status === 'PROFIT') countProfit += 1;
      else if (status === 'LOSS') countLoss += 1;
      else countNeutral += 1;
    } else {
      countNeutral += 1;
    }

    // 7d price chart — same format as portfolio module (ISO date + numeric OHLCV)
    const prices7d = normalizePrices7d(stockId ? pricesMap[stockId] || [] : []);

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

  const hasMarketValueBase = totalMarketValue > 0;

  const itemsWithAllocation = items.map((item) => {
    let allocationPct = null;

    if (hasMarketValueBase && item.market_value != null && item.market_value > 0) {
      allocationPct = round2((item.market_value / totalMarketValue) * 100);
    } else if (!hasMarketValueBase && item.cost > 0 && totalCost > 0) {
      allocationPct = round2((item.cost / totalCost) * 100);
    } else if (items.length === 1) {
      allocationPct = 100;
    }

    return {
      ...item,
      allocation_pct: allocationPct
    };
  });

  return {
    generated_at: new Date().toISOString(),
    data_as_of: globalDataAsOf,
    portfolio: {
      total_cost: Math.round(totalCost),
      total_market_value: Math.round(totalMarketValue),
      total_unrealized_pnl: Math.round(totalUnrealizedPnl),
      total_unrealized_pnl_pct: Math.round(totalUnrealizedPnlPct * 100) / 100,
      count_profit: countProfit,
      count_loss: countLoss,
      count_neutral: countNeutral,
      position_count: items.length
    },
    items: itemsWithAllocation
  };
};

module.exports = {
  getMyHoldings,
  getHoldingDetail,
  saveHolding,
  updateHolding,
  removeHolding,
  getHoldingsPnl,
  recordTransaction,
  getTransactions,
  computeWeightedAverageCost
};
