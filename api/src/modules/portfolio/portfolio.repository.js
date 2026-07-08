const UserStockHolding = require('../../database/models/user-stock-holding.model');
const FactMarketPrice = require('../../database/models/fact-market-price.model');

// Read-only repository for the portfolio P&L feature.
// Reuses existing collections (userStockHoldings, factMarketPrices) without
// mutating any data, so it never conflicts with the holdings CRUD module.

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

// All ACTIVE holdings of a user, newest first, with stock + market populated.
const findActiveHoldingsByUser = async (userId) => {
  return UserStockHolding.find({ user_id: userId, status: 'ACTIVE' })
    .populate(populateStock)
    .sort({ updated_at: -1, created_at: -1 })
    .lean();
};

// Latest close_price per stock in a single aggregation (avoids N queries).
const findLatestPricesByStockIds = async (stockIds = []) => {
  if (!stockIds.length) return [];

  return FactMarketPrice.aggregate([
    { $match: { stock_id: { $in: stockIds } } },
    { $sort: { stock_id: 1, time_id: -1, created_at: -1 } },
    {
      $group: {
        _id: '$stock_id',
        close_price: { $first: '$close_price' },
        price_change: { $first: '$price_change' },
        price_change_percent: { $first: '$price_change_percent' },
        volume: { $first: '$volume' },
        time_id: { $first: '$time_id' },
        created_at: { $first: '$created_at' }
      }
    }
  ]);
};

// Last `daysLimit` price points for one stock, ascending (chronological) order.
const findRecentPricesForStock = async (stockId, daysLimit = 7) => {
  const prices = await FactMarketPrice.find({ stock_id: stockId })
    .sort({ time_id: -1 })
    .limit(daysLimit)
    .select('time_id open_price high_price low_price close_price volume price_change price_change_percent pe pb roe')
    .lean();

  return prices.reverse();
};

module.exports = {
  findActiveHoldingsByUser,
  findLatestPricesByStockIds,
  findRecentPricesForStock
};
