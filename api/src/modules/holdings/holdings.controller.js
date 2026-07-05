const holdingsService = require('./holdings.service');
const { success } = require('../../common/utils/response.util');

const getMyHoldings = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const result = await holdingsService.getMyHoldings(userId, req.query);
    return success(res, 'Holdings retrieved successfully', result);
  } catch (error) {
    next(error);
  }
};

const getMyHoldingDetail = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const result = await holdingsService.getHoldingDetail(userId, req.params.symbol);
    return success(res, 'Holding detail retrieved successfully', result);
  } catch (error) {
    next(error);
  }
};

const saveHolding = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const result = await holdingsService.saveHolding(userId, req.params.symbol, req.body);
    return success(res, 'Holding saved successfully', result, 201);
  } catch (error) {
    next(error);
  }
};

const updateHolding = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const result = await holdingsService.updateHolding(userId, req.params.symbol, req.body);
    return success(res, 'Holding updated successfully', result);
  } catch (error) {
    next(error);
  }
};

const removeHolding = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id || req.user.user_id;
    const result = await holdingsService.removeHolding(userId, req.params.symbol);
    return success(res, 'Holding removed successfully', result);
  } catch (error) {
    next(error);
  }
};

module.exports = {
  getMyHoldings,
  getMyHoldingDetail,
  saveHolding,
  updateHolding,
  removeHolding
};
