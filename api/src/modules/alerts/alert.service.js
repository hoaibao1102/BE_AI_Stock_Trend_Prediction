const alertsRepository = require('./alert.repository');
const DimStock = require('../../database/models/dim-stock.model');
const FactMarketPrice = require('../../database/models/fact-market-price.model');
const watchlistsRepository = require('../watchlists/watchlists.repository');
const { PLAN_LIMITS } = require('../../config/plan.config');

const createAlert = async (userId, symbol, alertType, threshold, userPlan) => {
  const stock = await DimStock.findOne({ symbol: symbol.toUpperCase() });
  if (!stock) {
    const err = new Error('Stock symbol not found');
    err.statusCode = 404;
    throw err;
  }

  const stockId = stock._id;

  // Must be in user's watchlist
  const watchlistEntry = await watchlistsRepository.findWatchlistEntry(userId, stockId);
  if (!watchlistEntry) {
    const err = new Error('Stock must be in your watchlist to create an alert');
    err.statusCode = 400;
    throw err;
  }

  const limits = PLAN_LIMITS[userPlan] || PLAN_LIMITS.FREE;

  // Enforce max distinct alert stocks
  const alertedStockIds = await alertsRepository.findAlertStocksForUser(userId);
  const alreadyAlerted = alertedStockIds.some(id => id.toString() === stockId.toString());
  if (!alreadyAlerted && alertedStockIds.length >= limits.max_alert_stocks) {
    const err = new Error(`Alert stock limit exceeded (Maximum ${limits.max_alert_stocks} stocks allowed)`);
    err.statusCode = 400;
    throw err;
  }

  // Enforce max alerts per stock
  const perStockCount = await alertsRepository.countAlertsForStock(userId, stockId);
  if (perStockCount >= limits.max_alerts_per_stock) {
    const err = new Error(`Alert limit for this stock exceeded (Maximum ${limits.max_alerts_per_stock} alerts per stock)`);
    err.statusCode = 400;
    throw err;
  }

  const alert = await alertsRepository.createAlert({
    user_id: userId,
    stock_id: stockId,
    alert_type: alertType,
    threshold,
    status: 'ACTIVE'
  });

  return {
    id: alert._id.toString(),
    symbol: stock.symbol,
    company_name: stock.company_name,
    alert_type: alert.alert_type,
    threshold: alert.threshold,
    status: alert.status,
    created_at: alert.created_at
  };
};

const getUserAlerts = async (userId) => {
  const alerts = await alertsRepository.findUserAlerts(userId);

  const result = [];
  for (const alert of alerts) {
    if (!alert.stock_id) continue;

    const latestPrice = await FactMarketPrice.findOne({ stock_id: alert.stock_id._id })
      .sort({ time_id: -1 })
      .select('close_price volume')
      .lean();

    result.push({
      id: alert._id.toString(),
      symbol: alert.stock_id.symbol,
      company_name: alert.stock_id.company_name,
      alert_type: alert.alert_type,
      threshold: alert.threshold,
      status: alert.status,
      triggered_at: alert.triggered_at,
      triggered_value: alert.triggered_value,
      latest_price: latestPrice ? {
        close_price: latestPrice.close_price,
        volume: latestPrice.volume
      } : null,
      created_at: alert.created_at,
      updated_at: alert.updated_at
    });
  }

  return result;
};

const getAlertDetail = async (userId, alertId) => {
  const alert = await alertsRepository.findUserAlertById(alertId, userId);
  if (!alert) {
    const err = new Error('Alert not found');
    err.statusCode = 404;
    throw err;
  }

  let latestPrice = null;
  if (alert.stock_id) {
    latestPrice = await FactMarketPrice.findOne({ stock_id: alert.stock_id._id })
      .sort({ time_id: -1 })
      .select('close_price volume')
      .lean();
  }

  return {
    id: alert._id.toString(),
    symbol: alert.stock_id ? alert.stock_id.symbol : null,
    company_name: alert.stock_id ? alert.stock_id.company_name : null,
    alert_type: alert.alert_type,
    threshold: alert.threshold,
    status: alert.status,
    triggered_at: alert.triggered_at,
    triggered_value: alert.triggered_value,
    latest_price: latestPrice ? {
      close_price: latestPrice.close_price,
      volume: latestPrice.volume
    } : null,
    created_at: alert.created_at,
    updated_at: alert.updated_at
  };
};

const updateAlert = async (userId, alertId, updates) => {
  const alert = await alertsRepository.findUserAlertById(alertId, userId);
  if (!alert) {
    const err = new Error('Alert not found');
    err.statusCode = 404;
    throw err;
  }

  // Build allowed updates
  const allowed = {};
  if (updates.threshold !== undefined) {
    allowed.threshold = updates.threshold;
  }
  if (updates.status !== undefined) {
    // Allow: ACTIVE ↔ DISABLED toggle, and resetting TRIGGERED → ACTIVE
    const validTransitions = {
      'ACTIVE': ['DISABLED'],
      'DISABLED': ['ACTIVE'],
      'TRIGGERED': ['ACTIVE']
    };
    const allowedNext = validTransitions[alert.status] || [];
    if (!allowedNext.includes(updates.status)) {
      const err = new Error(`Cannot transition from ${alert.status} to ${updates.status}`);
      err.statusCode = 400;
      throw err;
    }
    allowed.status = updates.status;
    // If re-enabling from TRIGGERED, clear triggered fields
    if (updates.status === 'ACTIVE' && alert.status === 'TRIGGERED') {
      allowed.triggered_at = null;
      allowed.triggered_value = null;
    }
  }

  if (Object.keys(allowed).length === 0) {
    const err = new Error('No valid updates provided');
    err.statusCode = 400;
    throw err;
  }

  const updated = await alertsRepository.updateAlert(alertId, userId, allowed);
  return {
    id: updated._id.toString(),
    symbol: updated.stock_id ? updated.stock_id.symbol : null,
    company_name: updated.stock_id ? updated.stock_id.company_name : null,
    alert_type: updated.alert_type,
    threshold: updated.threshold,
    status: updated.status,
    triggered_at: updated.triggered_at,
    triggered_value: updated.triggered_value,
    created_at: updated.created_at,
    updated_at: updated.updated_at
  };
};

const deleteAlert = async (userId, alertId) => {
  const alert = await alertsRepository.findUserAlertById(alertId, userId);
  if (!alert) {
    const err = new Error('Alert not found');
    err.statusCode = 404;
    throw err;
  }

  await alertsRepository.deleteAlert(alertId, userId);
  return true;
};

module.exports = {
  createAlert,
  getUserAlerts,
  getAlertDetail,
  updateAlert,
  deleteAlert
};
