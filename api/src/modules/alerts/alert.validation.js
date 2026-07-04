const { body, param, validationResult } = require('express-validator');
const { error } = require('../../common/utils/response.util');

const validate = (req, res, next) => {
  const errors = validationResult(req);
  if (errors.isEmpty()) {
    return next();
  }
  const extractedErrors = errors.array().map(err => ({
    field: err.path,
    message: err.msg
  }));
  return error(res, 'Validation failed', extractedErrors, 400);
};

const createAlertValidation = [
  body('symbol')
    .notEmpty().withMessage('Symbol is required')
    .trim()
    .toUpperCase()
    .isLength({ min: 3, max: 10 }).withMessage('Symbol must be between 3 and 10 characters'),
  body('alert_type')
    .notEmpty().withMessage('Alert type is required')
    .isIn(['PRICE_ABOVE', 'PRICE_BELOW', 'VOLUME_SPIKE']).withMessage('Alert type must be PRICE_ABOVE, PRICE_BELOW, or VOLUME_SPIKE'),
  body('threshold')
    .notEmpty().withMessage('Threshold is required')
    .isFloat({ gt: 0 }).withMessage('Threshold must be a positive number')
];

const updateAlertValidation = [
  param('id')
    .notEmpty().withMessage('Alert ID is required')
    .isMongoId().withMessage('Invalid alert ID'),
  body('threshold')
    .optional()
    .isFloat({ gt: 0 }).withMessage('Threshold must be a positive number'),
  body('status')
    .optional()
    .isIn(['ACTIVE', 'DISABLED', 'TRIGGERED']).withMessage('Status must be ACTIVE, DISABLED, or TRIGGERED')
];

const alertIdValidation = [
  param('id')
    .notEmpty().withMessage('Alert ID is required')
    .isMongoId().withMessage('Invalid alert ID')
];

module.exports = {
  validate,
  createAlertValidation,
  updateAlertValidation,
  alertIdValidation
};
