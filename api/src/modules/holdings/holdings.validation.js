const { body, param, query, validationResult } = require('express-validator');
const { error } = require('../../common/utils/response.util');

const validate = (req, res, next) => {
  const errors = validationResult(req);
  if (errors.isEmpty()) {
    return next();
  }

  const extractedErrors = errors.array().map((err) => ({
    field: err.path,
    message: err.msg
  }));

  return error(res, 'Validation failed', extractedErrors, 400);
};

const symbolValidation = param('symbol')
  .exists({ checkFalsy: true })
  .withMessage('INVALID_STOCK_SYMBOL')
  .bail()
  .isString()
  .withMessage('INVALID_STOCK_SYMBOL')
  .bail()
  .trim()
  .toUpperCase()
  .isLength({ min: 1, max: 10 })
  .withMessage('INVALID_STOCK_SYMBOL')
  .bail()
  .matches(/^[A-Z0-9]+$/)
  .withMessage('INVALID_STOCK_SYMBOL');

const getMyHoldingsValidation = [
  query('status')
    .optional()
    .trim()
    .toUpperCase()
    .isIn(['ACTIVE', 'REMOVED', 'ALL'])
    .withMessage('status must be ACTIVE, REMOVED, or ALL'),
  query('page')
    .optional()
    .isInt({ min: 1 })
    .withMessage('page must be a positive integer')
    .toInt(),
  query('limit')
    .optional()
    .isInt({ min: 1, max: 100 })
    .withMessage('limit must be between 1 and 100')
    .toInt()
];

const getMyHoldingDetailValidation = [symbolValidation];

const saveHoldingValidation = [
  symbolValidation,
  body('average_cost')
    .notEmpty()
    .withMessage('average_cost is required')
    .bail()
    .isFloat({ gt: 0 })
    .withMessage('average_cost must be greater than 0')
    .toFloat(),
  body('quantity')
    .notEmpty()
    .withMessage('quantity is required')
    .bail()
    .isInt({ min: 1 })
    .withMessage('quantity must be a positive integer')
    .toInt(),
  body('holding_date')
    .notEmpty()
    .withMessage('holding_date is required')
    .bail()
    .isISO8601()
    .withMessage('holding_date must be a valid date')
    .toDate(),
  body('note')
    .optional()
    .isString()
    .withMessage('note must be a string')
    .trim()
];

const updateHoldingValidation = [...saveHoldingValidation];
const removeHoldingValidation = [symbolValidation];

const recordTransactionValidation = [
  symbolValidation,
  body('transaction_type')
    .notEmpty()
    .withMessage('transaction_type is required')
    .bail()
    .trim()
    .toUpperCase()
    .isIn(['BUY', 'SELL'])
    .withMessage('transaction_type must be BUY or SELL'),
  body('trade_date')
    .notEmpty()
    .withMessage('trade_date is required')
    .bail()
    .isISO8601()
    .withMessage('trade_date must be a valid date')
    .toDate(),
  body('quantity')
    .notEmpty()
    .withMessage('quantity is required')
    .bail()
    .isInt({ min: 1 })
    .withMessage('quantity must be a positive integer')
    .toInt(),
  body('price')
    .notEmpty()
    .withMessage('price is required')
    .bail()
    .isFloat({ gt: 0 })
    .withMessage('price must be greater than 0')
    .toFloat(),
  body('fee')
    .optional()
    .isFloat({ min: 0 })
    .withMessage('fee must be greater than or equal to 0')
    .toFloat(),
  body('tax')
    .optional()
    .isFloat({ min: 0 })
    .withMessage('tax must be greater than or equal to 0')
    .toFloat(),
  body('note')
    .optional()
    .isString()
    .withMessage('note must be a string')
    .trim()
];

const getTransactionsValidation = [
  symbolValidation,
  query('status')
    .optional()
    .trim()
    .toUpperCase()
    .isIn(['ACTIVE', 'VOIDED', 'ALL'])
    .withMessage('status must be ACTIVE, VOIDED, or ALL'),
  query('page')
    .optional()
    .isInt({ min: 1 })
    .withMessage('page must be a positive integer')
    .toInt(),
  query('limit')
    .optional()
    .isInt({ min: 1, max: 100 })
    .withMessage('limit must be between 1 and 100')
    .toInt()
];

module.exports = {
  validate,
  getMyHoldingsValidation,
  getMyHoldingDetailValidation,
  saveHoldingValidation,
  updateHoldingValidation,
  removeHoldingValidation,
  recordTransactionValidation,
  getTransactionsValidation
};
