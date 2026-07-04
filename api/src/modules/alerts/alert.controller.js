const alertsService = require('./alert.service');
const { success } = require('../../common/utils/response.util');

const list = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id;
    const result = await alertsService.getUserAlerts(userId);
    return success(res, 'Get alerts successfully', result);
  } catch (error) {
    next(error);
  }
};

const create = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id;
    const userPlan = req.user.plan || 'FREE';
    const { symbol, alert_type, threshold } = req.body;
    const result = await alertsService.createAlert(userId, symbol, alert_type, threshold, userPlan);
    return success(res, 'Create alert successfully', result, 201);
  } catch (error) {
    next(error);
  }
};

const getById = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id;
    const { id } = req.params;
    const result = await alertsService.getAlertDetail(userId, id);
    return success(res, 'Get alert successfully', result);
  } catch (error) {
    next(error);
  }
};

const update = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id;
    const { id } = req.params;
    const result = await alertsService.updateAlert(userId, id, req.body);
    return success(res, 'Update alert successfully', result);
  } catch (error) {
    next(error);
  }
};

const remove = async (req, res, next) => {
  try {
    const userId = req.user._id || req.user.id;
    const { id } = req.params;
    await alertsService.deleteAlert(userId, id);
    return success(res, 'Delete alert successfully');
  } catch (error) {
    next(error);
  }
};

module.exports = {
  list,
  create,
  getById,
  update,
  remove
};
