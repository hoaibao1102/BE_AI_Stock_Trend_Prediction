/**
 * Mock Data Controller — Swagger-only staff endpoints for demo price simulation.
 */
const mockDataService = require('../../services/mock-data.service');
const DimStock = require('../../database/models/dim-stock.model');
const DimStockDataSource = require('../../database/models/dim-stock-data-source.model');
const FactMarketPrice = require('../../database/models/fact-market-price.model');
const { success } = require('../../common/utils/response.util');

const start = async (req, res, next) => {
  try {
    const { symbol: rawSymbol, alertType, threshold, tickCount, notifyEmail } = req.body;
    const symbol = (rawSymbol || '').toUpperCase().trim();

    // Look up stock
    const stock = await DimStock.findOne({ symbol }).lean();
    if (!stock) {
      return res.status(404).json({ success: false, message: 'Stock symbol not found' });
    }

    // Get last price for baseline
    const lastPrice = await FactMarketPrice.findOne({ stock_id: stock._id })
      .sort({ time_id: -1 })
      .select('close_price volume time_id')
      .lean();

    if (!lastPrice) {
      return res.status(400).json({ success: false, message: 'No price data found for this stock. Cannot start mock.' });
    }

    // Get avg volume (last 20 records)
    const recentPrices = await FactMarketPrice.find({ stock_id: stock._id })
      .sort({ time_id: -1 })
      .limit(20)
      .select('volume')
      .lean();
    const avgVolume = recentPrices.length > 0
      ? recentPrices.reduce((s, p) => s + (p.volume || 0), 0) / recentPrices.length
      : lastPrice.volume || 1000000;

    const result = await mockDataService.startSession({
      symbol,
      stockId: stock._id,
      currentPrice: lastPrice.close_price,
      avgVolume: Math.round(avgVolume),
      alertType,
      threshold,
      tickCount: tickCount || 15,
      lastTimeId: lastPrice.time_id,
      notifyEmail: notifyEmail || null,
    });

    return success(res, 'Mock data session started', result, 201);
  } catch (error) {
    next(error);
  }
};

const list = async (req, res, next) => {
  try {
    const sessions = mockDataService.listSessions();
    return success(res, 'Active mock sessions', sessions);
  } catch (error) {
    next(error);
  }
};

const remove = async (req, res, next) => {
  try {
    const { symbol } = req.params;
    const existed = mockDataService.stopSession(symbol);
    if (!existed) {
      return res.status(404).json({ success: false, message: 'No active mock session for this symbol' });
    }
    return success(res, `Mock session for ${symbol.toUpperCase()} stopped`);
  } catch (error) {
    next(error);
  }
};

module.exports = {
  start,
  list,
  remove,
};
