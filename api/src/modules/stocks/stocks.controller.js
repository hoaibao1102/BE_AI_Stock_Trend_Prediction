const stocksService = require('./stocks.service');
const { success } = require('../../common/utils/response.util');

const logStockEndpointError = (req, error) => {
  const statusCode = error.statusCode || 500;
  if (statusCode < 500) return;

  const payload = {
    endpoint: req.originalUrl,
    symbol: req.params?.symbol,
    query: req.query,
    errorName: error.name,
    errorMessage: error.message
  };

  if (process.env.NODE_ENV !== 'production') {
    payload.stack = error.stack;
  }

  console.error('[StocksController] Stock endpoint failed', payload);
};

const getStocks = async (req, res, next) => {
  try {
    const { keyword, market, page, limit } = req.query;
    const result = await stocksService.getStocksList({ keyword, market, page, limit });
    return success(res, 'Get stocks successfully', result);
  } catch (error) {
    next(error);
  }
};

const getStockDetail = async (req, res, next) => {
  try {
    const { symbol } = req.params;
    const result = await stocksService.getStockDetail(symbol);
    return success(res, 'Get stock detail successfully', result);
  } catch (error) {
    logStockEndpointError(req, error);
    next(error);
  }
};

const getStockChart = async (req, res, next) => {
  try {
    const { symbol } = req.params;
    const { range } = req.query;
    const result = await stocksService.getStockChart(symbol, range);
    return success(res, 'Get price history successfully', result);
  } catch (error) {
    logStockEndpointError(req, error);
    next(error);
  }
};

const getStockAnalysisData = async (req, res, next) => {
  try {
    const { symbol } = req.params;
    const {
      quarters,
      chartRange,
      includePeers,
      includeMarketContext
    } = req.query;
    const result = await stocksService.getStockAnalysisData(symbol, {
      quarters,
      chartRange,
      includePeers,
      includeMarketContext
    });
    return success(res, 'Get stock analysis data successfully', result);
  } catch (error) {
    logStockEndpointError(req, error);
    next(error);
  }
};

const createStockMaster = async (req, res, next) => {
  try {
    const result = await stocksService.createStockMaster(req.body);
    return success(res, 'Create stock master successfully', result, 201);
  } catch (error) {
    next(error);
  }
};

const updateStockMaster = async (req, res, next) => {
  try {
    const { id } = req.params;
    const result = await stocksService.updateStockMaster(id, req.body);
    return success(res, 'Update stock master successfully', result);
  } catch (error) {
    next(error);
  }
};

const getStockAnalysisHistory = async (req, res, next) => {
  try {
    const { symbol } = req.params;
    const { exchange, days } = req.query;
    const authToken = req.get('authorization') || null;
    const result = await stocksService.getStockAnalysisHistory(symbol, { exchange, days, authToken });
    return success(res, 'Get stock analysis history successfully', result);
  } catch (error) {
    logStockEndpointError(req, error);
    next(error);
  }
};

module.exports = {
  getStocks,
  getStockDetail,
  getStockChart,
  getStockAnalysisData,
  createStockMaster,
  updateStockMaster,
  getStockAnalysisHistory
};
