const mongoose = require('mongoose');
const DimStock = require('../../database/models/dim-stock.model');
const UserStockHolding = require('../../database/models/user-stock-holding.model');
const UserStockTransaction = require('../../database/models/user-stock-transaction.model');
const FactMarketPrice = require('../../database/models/fact-market-price.model');

const populateStock = {
  path: 'stock_id',
  select: '_id symbol company_name market_id status',
  populate: {
    path: 'market_id',
    select: 'code name',
    options: { lean: true }
  },
  options: { lean: true }
};

const buildHoldingFilter = (userId, status) => {
  const filter = { user_id: userId };
  if (status && status !== 'ALL') {
    filter.status = status;
  }
  return filter;
};

const findStockBySymbol = async (symbol) => {
  return DimStock.findOne({ symbol })
    .select('_id symbol company_name status market_id industry_id')
    .populate({
      path: 'market_id',
      select: 'code name',
      options: { lean: true }
    })
    .lean();
};

const findHoldingsByUser = async (userId, { status = 'ACTIVE', page = 1, limit = 20 } = {}) => {
  const skip = (page - 1) * limit;
  const filter = buildHoldingFilter(userId, status);

  const [items, total] = await Promise.all([
    UserStockHolding.find(filter)
      .populate(populateStock)
      .sort({ updated_at: -1, created_at: -1 })
      .skip(skip)
      .limit(limit)
      .lean(),
    UserStockHolding.countDocuments(filter)
  ]);

  return { items, total };
};

const findHoldingByUserAndStock = async (
  userId,
  stockId,
  { includeRemoved = false, session = null, lean = false, populate = false } = {}
) => {
  const filter = {
    user_id: userId,
    stock_id: stockId
  };

  if (!includeRemoved) {
    filter.status = 'ACTIVE';
  }

  let query = UserStockHolding.findOne(filter);
  if (populate) {
    query = query.populate(populateStock);
  }
  if (session) {
    query = query.session(session);
  }
  if (lean) {
    query = query.lean();
  }

  return query;
};

const createHolding = async (payload, session = null) => {
  const options = session ? { session } : {};
  const [holding] = await UserStockHolding.create([payload], options);
  return holding;
};

const saveDocument = async (document, session = null) => {
  return document.save(session ? { session } : undefined);
};

const findLatestPriceByStockId = async (stockId) => {
  return FactMarketPrice.findOne({ stock_id: stockId })
    .sort({ time_id: -1, created_at: -1 })
    .lean();
};

const findLatestPricesByStockIds = async (stockIds = []) => {
  if (!stockIds.length) return [];

  return FactMarketPrice.aggregate([
    {
      $match: {
        stock_id: { $in: stockIds }
      }
    },
    {
      $sort: {
        stock_id: 1,
        time_id: -1,
        created_at: -1
      }
    },
    {
      $group: {
        _id: '$stock_id',
        close_price: { $first: '$close_price' },
        time_id: { $first: '$time_id' },
        created_at: { $first: '$created_at' }
      }
    }
  ]);
};

const startSession = async () => mongoose.startSession();

const createTransaction = async (payload, session = null) => {
  const options = session ? { session } : {};
  const [transaction] = await UserStockTransaction.create([payload], options);
  return transaction;
};

const findTransactionsByUserAndStock = async (
  userId,
  stockId,
  { page = 1, limit = 50, status = 'ACTIVE' } = {}
) => {
  const skip = (page - 1) * limit;
  const filter = {
    user_id: userId,
    stock_id: stockId
  };

  if (status && status !== 'ALL') {
    filter.status = status;
  }

  const [items, total] = await Promise.all([
    UserStockTransaction.find(filter)
      .sort({ trade_date: -1, created_at: -1 })
      .skip(skip)
      .limit(limit)
      .lean(),
    UserStockTransaction.countDocuments(filter)
  ]);

  return { items, total };
};

// Last `daysLimit` distinct trading days for one stock, ascending (chronological).
const findRecentPricesForStock = async (stockId, daysLimit = 7) => {
  const prices = await FactMarketPrice.find({ stock_id: stockId })
    .sort({ time_id: -1, created_at: -1 })
    .select('time_id open_price high_price low_price close_price volume price_change price_change_percent pe pb roe')
    .lean();

  const byTimeId = new Map();
  for (const row of prices) {
    const key = String(row.time_id ?? '');
    if (!key || byTimeId.has(key)) continue;
    byTimeId.set(key, row);
    if (byTimeId.size >= daysLimit) break;
  }

  return Array.from(byTimeId.values()).reverse();
};

/**
 * Batch lấy daysLimit ngày giá gần nhất cho nhiều stock cùng lúc.
 * Returns map: stockId (string) → price[] (ascending by time_id)
 */
const findPricesForStockIds = async (stockIds = [], daysLimit = 7) => {
  if (!stockIds.length) return {};

  const objectIds = stockIds.filter(Boolean);
  if (!objectIds.length) return {};

  const entries = await Promise.all(
    objectIds.map(async (stockId) => {
      const prices = await findRecentPricesForStock(stockId, daysLimit);
      return [stockId.toString(), prices];
    })
  );

  return Object.fromEntries(entries);
};

module.exports = {
  findStockBySymbol,
  findHoldingsByUser,
  findHoldingByUserAndStock,
  createHolding,
  saveDocument,
  findLatestPriceByStockId,
  findLatestPricesByStockIds,
  findRecentPricesForStock,
  findPricesForStockIds,
  startSession,
  createTransaction,
  findTransactionsByUserAndStock
};
