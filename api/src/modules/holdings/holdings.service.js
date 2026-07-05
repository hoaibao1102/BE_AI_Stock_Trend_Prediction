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

module.exports = {
  getMyHoldings,
  getHoldingDetail,
  saveHolding,
  updateHolding,
  removeHolding
};
