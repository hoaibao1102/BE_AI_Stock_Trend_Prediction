const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const session = require('express-session');
const passport = require('passport');
const appConfig = require('./config/app.config');
const configurePassport = require('./config/passport.config');
const errorMiddleware = require('./common/middlewares/error.middleware');
const authRouter = require('./modules/auth/auth.routes');
const { usersRouter, adminUsersRouter } = require('./modules/users/users.routes');
const { stocksRouter, adminStocksRouter } = require('./modules/stocks/stocks.routes');
const watchlistsRouter = require('./modules/watchlists/watchlists.routes');
const { dashboardRouter } = require('./modules/dashboard/dashboard.routes');
const subscriptionsRouter = require('./modules/subscriptions/subscriptions.routes');
const adminSubscriptionsRouter = require('./modules/admin-subscriptions/admin-subscriptions.routes');
const staffSubscriptionsRouter = require('./modules/staff-subscriptions/staff-subscriptions.routes');
const dataSourcesRouter = require('./modules/data-sources/data-sources.routes');
const crawlJobsRouter = require('./modules/crawl-jobs/crawl-jobs.routes');
const crawlLogsRouter = require('./modules/crawl-logs/crawl-logs.routes');
const dataQualityRouter = require('./modules/data-quality/data-quality.routes');
const alertsRouter = require('./modules/alerts/alert.routes');
const mockDataRouter = require('./modules/mock-data/mock-data.routes');
const { error } = require('./common/utils/response.util');

const swaggerUi = require('swagger-ui-express');
const swaggerSpec = require('./config/swagger.config');

const app = express();
app.set('etag', false);

configurePassport();


// Set security HTTP headers (disable Content Security Policy to allow Swagger UI inline assets)
app.use(helmet({
  contentSecurityPolicy: false
}));

// Enable CORS
app.use(cors(appConfig.corsOptions));

// HTTP request logging
app.use(morgan(appConfig.env === 'development' ? 'dev' : 'combined'));

// Session for Passport OAuth state (short-lived cookie)
app.use(
  session({
    secret: appConfig.sessionSecret,
    resave: false,
    // Passport OAuth2 stores `state` in session before redirecting to Google; must allow saving new sessions.
    saveUninitialized: true,
    cookie: {
      secure: appConfig.isProduction,
      httpOnly: true,
      maxAge: 15 * 60 * 1000,
      sameSite: 'lax'
    }
  })
);
app.use(passport.initialize());
app.use(passport.session());

// Raw body parser for PayOS webhook (must be BEFORE express.json so it gets the raw buffer)
app.use('/api/subscriptions/webhook', express.raw({ type: 'application/json', limit: '10mb' }));

// Parse JSON and urlencoded request bodies
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Disable caching for API routes to prevent 304 Not Modified status codes
app.use((req, res, next) => {
  res.set('Cache-Control', 'no-store, no-cache, must-revalidate, private');
  next();
});


// Swagger API Documentation
app.use('/api-docs', swaggerUi.serve, swaggerUi.setup(swaggerSpec));

// API Routes
app.use('/api/auth', authRouter);
app.use('/api/users', usersRouter);
app.use('/api/admin/users', adminUsersRouter);
app.use('/api/stocks', stocksRouter);
app.use('/api/admin/stocks', adminStocksRouter);
app.use('/api/watchlists', watchlistsRouter);
app.use('/api/dashboard', dashboardRouter);
app.use('/api/subscriptions', subscriptionsRouter);
app.use('/api/admin/subscriptions', adminSubscriptionsRouter);
app.use('/api/staff/subscriptions', staffSubscriptionsRouter);
app.use('/api/staff/data-sources', dataSourcesRouter);
app.use('/api/staff/crawl-jobs', crawlJobsRouter);
app.use('/api/staff/crawl-logs', crawlLogsRouter);
app.use('/api/staff/data-quality', dataQualityRouter);
app.use('/api/staff/mock-data', mockDataRouter);
app.use('/api/alerts', alertsRouter);

// Health check endpoint
app.get('/', (req, res) => {
  res.json({ message: 'AI Stock Trend Prediction API is running' });
});

// Send back a 404 error for any unknown api request
app.use((req, res, next) => {
  return error(res, `Route ${req.originalUrl} not found`, null, 404);
});

// Global error handler
app.use(errorMiddleware);

module.exports = app;
