const watchlistsRepository = require('./watchlists.repository');
const alertsRepository = require('../alerts/alert.repository');
const DimStock = require('../../database/models/dim-stock.model');
const FactMarketPrice = require('../../database/models/fact-market-price.model');
const { PLAN_LIMITS } = require('../../config/plan.config');

const getUserWatchlist = async (userId, userPlan = 'FREE') => {
  const entries = await watchlistsRepository.findUserWatchlist(userId);
  const limit = PLAN_LIMITS[userPlan]?.max_watchlist_items || PLAN_LIMITS.FREE.max_watchlist_items;
  const currentCount = entries.length;
  const overLimit = currentCount > limit;

  // If overLimit, return only trim-relevant fields
  if (overLimit) {
    const trimmedItems = entries
      .filter(entry => entry.stock_id)
      .map(entry => ({
        stock_id: entry.stock_id._id.toString(),
        stock_code: entry.stock_id.symbol,
        stock_name: entry.stock_id.company_name
      }));

    return {
      items: trimmedItems,
      limit,
      currentCount,
      overLimit: true
    };
  }

  // Normal response with full stock details
  const result = [];
  for (const entry of entries) {
    if (!entry.stock_id) continue;

    const latestPrice = await FactMarketPrice.findOne({ stock_id: entry.stock_id._id })
      .sort({ time_id: -1 })
      .lean();

    result.push({
      watchlist_id: entry._id.toString(),
      stock: {
        id: entry.stock_id._id.toString(),
        symbol: entry.stock_id.symbol,
        company_name: entry.stock_id.company_name,
        market_id: entry.stock_id.market_id ? entry.stock_id.market_id._id.toString() : null,
        market_code: entry.stock_id.market_id ? entry.stock_id.market_id.code : ''
      },
      latest_price: latestPrice ? {
        close_price: latestPrice.close_price,
        price_change: latestPrice.price_change || 0,
        price_change_percent: latestPrice.price_change_percent || 0,
        volume: latestPrice.volume
      } : null,
      created_at: entry.created_at
    });
  }

  return {
    items: result,
    limit,
    currentCount,
    overLimit: false
  };
};

const addStockToWatchlist = async (userId, symbol, userPlan = 'FREE') => {
  const stock = await DimStock.findOne({ symbol: symbol.toUpperCase() });
  if (!stock) {
    const error = new Error('Stock symbol not found');
    error.statusCode = 404;
    throw error;
  }

  const existingEntry = await watchlistsRepository.findWatchlistEntry(userId, stock._id);
  if (existingEntry) {
    const error = new Error('Stock is already in your watchlist');
    error.statusCode = 400;
    throw error;
  }

  const limit = PLAN_LIMITS[userPlan]?.max_watchlist_items || PLAN_LIMITS.FREE.max_watchlist_items;
  const currentCount = await watchlistsRepository.countUserWatchlist(userId);
  if (currentCount >= limit) {
    const error = new Error(`Watchlist limit exceeded (Maximum ${limit} stocks allowed)`);
    error.statusCode = 400;
    throw error;
  }

  const newEntry = await watchlistsRepository.createWatchlistEntry(userId, stock._id);

  return {
    watchlist_id: newEntry._id.toString(),
    symbol: stock.symbol,
    created_at: newEntry.created_at
  };
};

const removeStockFromWatchlist = async (userId, symbol) => {
  const stock = await DimStock.findOne({ symbol: symbol.toUpperCase() });
  if (!stock) {
    const error = new Error('Stock symbol not found');
    error.statusCode = 404;
    throw error;
  }

  const existingEntry = await watchlistsRepository.findWatchlistEntry(userId, stock._id);
  if (!existingEntry) {
    const error = new Error('Stock not found in your watchlist');
    error.statusCode = 404;
    throw error;
  }

  await watchlistsRepository.deleteWatchlistEntry(userId, stock._id);
  await alertsRepository.deleteAlertsByStock(userId, stock._id);
  return true;
};

const trimWatchlist = async (userId, keepStockIds, userPlan = 'FREE') => {
  const limit = PLAN_LIMITS[userPlan]?.max_watchlist_items || PLAN_LIMITS.FREE.max_watchlist_items;

  if (keepStockIds.length > limit) {
    const error = new Error(`Keep limit is ${limit}, but ${keepStockIds.length} items provided`);
    error.statusCode = 400;
    throw error;
  }

  // Get all current stock IDs in watchlist
  const entries = await watchlistsRepository.findUserWatchlist(userId);
  const currentStockIds = entries.map(entry => entry.stock_id._id.toString());

  // Find IDs to delete (those not in keepStockIds)
  const idsToDelete = currentStockIds.filter(id => !keepStockIds.includes(id));

  if (idsToDelete.length > 0) {
    await watchlistsRepository.deleteMultipleWatchlistEntries(userId, idsToDelete);
    await alertsRepository.deleteAlertsByStockIds(userId, idsToDelete);
  }

  return {
    deletedCount: idsToDelete.length,
    remainingCount: keepStockIds.length
  };
};

module.exports = {
  getUserWatchlist,
  addStockToWatchlist,
  removeStockFromWatchlist,
  trimWatchlist
};
