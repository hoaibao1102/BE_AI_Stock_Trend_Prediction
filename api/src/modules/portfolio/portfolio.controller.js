const portfolioService = require('./portfolio.service');
const { success } = require('../../common/utils/response.util');

const getPortfolioPnl = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const result = await portfolioService.getPortfolioPnl(userId);
    return success(res, 'Portfolio P&L retrieved successfully', result);
  } catch (error) {
    next(error);
  }
};

const getPortfolioHoldingsAdvice = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const authToken = req.get('authorization') || null;
    const forceRefresh = req.query?.forceRefresh === 'true' || req.query?.forceRefresh === true;
    const result = await portfolioService.getPortfolioHoldingsAdvice(userId, { authToken, forceRefresh });
    return success(res, 'Portfolio holdings advice retrieved successfully', result);
  } catch (error) {
    next(error);
  }
};

const getPortfolioWatchlistBatch = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const authToken = req.get('authorization') || null;
    const includeAi = req.query?.includeAi === 'true';
    const result = await portfolioService.getPortfolioWatchlistBatch(userId, { authToken, includeAi });
    return success(res, 'Portfolio watchlist batch retrieved successfully', result);
  } catch (error) {
    next(error);
  }
};

const getPortfolioWatchlistDetail = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const authToken = req.get('authorization') || null;
    const includeAi = req.query?.includeAi === 'true';
    const result = await portfolioService.getPortfolioWatchlistDetail(userId, req.params.symbol, { authToken, includeAi });
    return success(res, 'Portfolio watchlist detail retrieved successfully', result);
  } catch (error) {
    next(error);
  }
};

module.exports = {
  getPortfolioPnl,
  getPortfolioHoldingsAdvice,
  getPortfolioWatchlistBatch,
  getPortfolioWatchlistDetail
};
