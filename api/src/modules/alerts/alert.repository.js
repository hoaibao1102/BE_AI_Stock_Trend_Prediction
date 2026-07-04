const Alert = require('../../database/models/alert.model');

const findUserAlerts = async (userId) => {
  return Alert.find({ user_id: userId })
    .populate({
      path: 'stock_id',
      select: '_id symbol company_name'
    })
    .sort({ created_at: -1 })
    .lean();
};

const findUserAlertById = async (alertId, userId) => {
  return Alert.findOne({ _id: alertId, user_id: userId })
    .populate({
      path: 'stock_id',
      select: '_id symbol company_name'
    })
    .lean();
};

const countUserAlerts = async (userId) => {
  return Alert.countDocuments({ user_id: userId });
};

const countUserActiveAlerts = async (userId) => {
  return Alert.countDocuments({ user_id: userId, status: 'ACTIVE' });
};

const countAlertsForStock = async (userId, stockId) => {
  return Alert.countDocuments({ user_id: userId, stock_id: stockId });
};

const countActiveAlertsForStock = async (userId, stockId) => {
  return Alert.countDocuments({ user_id: userId, stock_id: stockId, status: 'ACTIVE' });
};

const findAlertStocksForUser = async (userId) => {
  return Alert.distinct('stock_id', { user_id: userId });
};

const findActiveAlertsForStock = async (stockId) => {
  return Alert.find({ stock_id: stockId, status: 'ACTIVE' })
    .populate({
      path: 'user_id',
      select: '_id email full_name plan'
    })
    .lean();
};

const createAlert = async (data) => {
  return Alert.create(data);
};

const updateAlert = async (alertId, userId, updates) => {
  return Alert.findOneAndUpdate(
    { _id: alertId, user_id: userId },
    { $set: updates },
    { new: true, runValidators: true }
  ).populate({
    path: 'stock_id',
    select: '_id symbol company_name'
  }).lean();
};

const deleteAlert = async (alertId, userId) => {
  return Alert.deleteOne({ _id: alertId, user_id: userId });
};

const markTriggered = async (alertId, triggeredAt, triggeredValue) => {
  return Alert.findByIdAndUpdate(
    alertId,
    { $set: { status: 'TRIGGERED', triggered_at: triggeredAt, triggered_value: triggeredValue } },
    { new: true }
  ).populate({
    path: 'user_id',
    select: '_id email full_name'
  }).populate({
    path: 'stock_id',
    select: '_id symbol company_name'
  }).lean();
};

module.exports = {
  findUserAlerts,
  findUserAlertById,
  countUserAlerts,
  countUserActiveAlerts,
  countAlertsForStock,
  countActiveAlertsForStock,
  findAlertStocksForUser,
  findActiveAlertsForStock,
  createAlert,
  updateAlert,
  deleteAlert,
  markTriggered
};
