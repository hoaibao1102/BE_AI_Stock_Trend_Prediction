/**
 * Global unhandled error handling middleware
 */
const errorMiddleware = (err, req, res, next) => {
  console.error('[Unhandled Error]', err);

  const statusCode = err.statusCode || 500;
  const message = err.message || 'Internal Server Error';
  const payload = {
    success: false,
    message
  };

  if (err.code) {
    payload.code = err.code;
  }

  if (err.details) {
    payload.details = err.details;
  }

  if (err.errors) {
    payload.errors = err.errors;
  }

  return res.status(statusCode).json(payload);
};

module.exports = errorMiddleware;
