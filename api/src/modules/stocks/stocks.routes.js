const express = require('express');
const router = express.Router();
const adminRouter = express.Router();

const stocksController = require('./stocks.controller');
const authMiddleware = require('../../common/middlewares/auth.middleware');
const roleMiddleware = require('../../common/middlewares/role.middleware');
const {
  validate,
  getStocksValidation,
  getChartValidation,
  getAnalysisDataValidation,
  createStockValidation,
  updateStockValidation
} = require('./stocks.validation');

/**
 * @openapi
 * tags:
 *   - name: Stocks
 *     description: Stock information and price history charts
 *   - name: Admin Stocks
 *     description: Administrative stock catalog management
 */

/**
 * @openapi
 * /api/stocks:
 *   get:
 *     summary: Retrieve stock catalog
 *     description: Retrieve list of registered stocks supporting keyword search, exchange filtering, and pagination.
 *     tags: [Stocks]
 *     parameters:
 *       - in: query
 *         name: page
 *         schema:
 *           type: integer
 *           default: 1
 *         description: Page index
 *       - in: query
 *         name: limit
 *         schema:
 *           type: integer
 *           default: 10
 *         description: Records count per page
 *       - in: query
 *         name: keyword
 *         schema:
 *           type: string
 *         description: Search keyword for stock symbol or company name
 *       - in: query
 *         name: market
 *         schema:
 *           type: string
 *           example: HOSE
 *         description: Stock exchange code (e.g. HOSE, HNX)
 *     responses:
 *       200:
 *         description: List of stocks retrieved successfully.
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success:
 *                   type: boolean
 *                   example: true
 *                 message:
 *                   type: string
 *                   example: Get stocks successfully
 *                 data:
 *                   type: object
 *                   properties:
 *                     items:
 *                       type: array
 *                       items:
 *                         type: object
 *                         properties:
 *                           id:
 *                             type: string
 *                             example: 665f1a2b9c1e2a0012a99999
 *                           symbol:
 *                             type: string
 *                             example: FPT
 *                           company_name:
 *                             type: string
 *                             example: Công ty Cổ phần FPT
 *                           market_code:
 *                             type: string
 *                             example: HOSE
 *                           status:
 *                             type: string
 *                             example: ACTIVE
 *                     pagination:
 *                       type: object
 *                       properties:
 *                         page:
 *                           type: integer
 *                           example: 1
 *                         limit:
 *                           type: integer
 *                           example: 10
 *                         total_items:
 *                           type: integer
 *                           example: 1
 *                         total_pages:
 *                           type: integer
 *                           example: 1
 */
router.get('/', getStocksValidation, validate, stocksController.getStocks);

/**
 * @openapi
 * /api/stocks/{symbol}/analysis-data:
 *   get:
 *     summary: Retrieve normalized stock analysis payload for analyse service
 *     description: Retrieve latest market data, chart history, financial statements, market context, peers, and data-quality diagnostics in a stable contract for the Python analyse service.
 *     tags: [Stocks]
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *           example: FPT
 *       - in: query
 *         name: exchange
 *         schema:
 *           type: string
 *           example: HOSE
 *       - in: query
 *         name: quarters
 *         schema:
 *           type: integer
 *           default: 6
 *       - in: query
 *         name: chartRange
 *         schema:
 *           type: string
 *           enum: [7d, 1m, 3m, 6m, 1y, all]
 *           default: 3m
 *       - in: query
 *         name: includePeers
 *         schema:
 *           type: boolean
 *           default: true
 *       - in: query
 *         name: includeMarketContext
 *         schema:
 *           type: boolean
 *           default: true
 *     responses:
 *       200:
 *         description: Analysis payload retrieved successfully.
 *       404:
 *         description: Stock symbol not found.
 */
router.get('/:symbol/analysis-data', getAnalysisDataValidation, validate, stocksController.getStockAnalysisData);

/**
 * @openapi
 * /api/stocks/{symbol}:
 *   get:
 *     summary: Retrieve stock detailed information
 *     description: Retrieve basic profile of a stock alongside its latest price metrics.
 *     tags: [Stocks]
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *           example: FPT
 *         description: The uppercase stock symbol
 *     responses:
 *       200:
 *         description: Stock details retrieved successfully.
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success:
 *                   type: boolean
 *                   example: true
 *                 message:
 *                   type: string
 *                   example: Get stock detail successfully
 *                 data:
 *                   type: object
 *                   properties:
 *                     id:
 *                       type: string
 *                       example: 665f1a2b9c1e2a0012a99999
 *                     symbol:
 *                       type: string
 *                       example: FPT
 *                     company_name:
 *                       type: string
 *                       example: Công ty Cổ phần FPT
 *                     market_code:
 *                       type: string
 *                       example: HOSE
 *                     status:
 *                       type: string
 *                       example: ACTIVE
 *                     listed_date:
 *                       type: string
 *                       format: date-time
 *                       example: 2006-12-13T00:00:00.000Z
 *                     latest_price:
 *                       type: object
 *                       properties:
 *                         open_price:
 *                           type: number
 *                           example: 133500
 *                         high_price:
 *                           type: number
 *                           example: 136000
 *                         low_price:
 *                           type: number
 *                           example: 133000
 *                         close_price:
 *                           type: number
 *                           example: 135000
 *                         volume:
 *                           type: number
 *                           example: 2500000
 *                         bid_volume:
 *                           type: number
 *                           example: 120000
 *                         ask_volume:
 *                           type: number
 *                           example: 150000
 *                         foreign_buy:
 *                           type: number
 *                           example: 45000
 *                         foreign_sell:
 *                           type: number
 *                           example: 30000
 *                         foreign_net:
 *                           type: number
 *                           example: 15000
 *                         market_cap:
 *                           type: number
 *                           example: 170000000000000
 *                         eps:
 *                           type: number
 *                           example: 5400
 *                         pe:
 *                           type: number
 *                           example: 25.0
 *                         forward_pe:
 *                           type: number
 *                           example: 22.5
 *                         bvps:
 *                           type: number
 *                           example: 32000
 *                         pb:
 *                           type: number
 *                           example: 4.2
 *                         beta:
 *                           type: number
 *                           example: 1.15
 *                         ros:
 *                           type: number
 *                           example: 0.12
 *                         roe:
 *                           type: number
 *                           example: 0.24
 *                         roaa:
 *                           type: number
 *                           example: 0.08
 *                         price_change:
 *                           type: number
 *                           example: 1500
 *                         price_change_percent:
 *                           type: number
 *                           example: 1.12
 *                         time_id:
 *                           type: integer
 *                           example: 20260601
 *                         crawled_at:
 *                           type: string
 *                           format: date-time
 *                           example: 2026-06-01T15:30:00.000Z
 *       404:
 *         description: Stock symbol not found.
 */
router.get('/:symbol', getChartValidation, validate, stocksController.getStockDetail);

/**
 * @openapi
 * /api/stocks/{symbol}/chart:
 *   get:
 *     summary: Retrieve stock historical pricing (chart)
 *     description: Retrieve listing of daily OHLCV prices for chart visualization.
 *     tags: [Stocks]
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *           example: FPT
 *         description: The uppercase stock symbol
 *       - in: query
 *         name: range
 *         schema:
 *           type: string
 *           enum: [7d, 1m, 3m, 6m, 1y, all]
 *           default: 1m
 *         description: Historical window range
 *     responses:
 *       200:
 *         description: Historical n-candles array retrieved successfully.
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success:
 *                   type: boolean
 *                   example: true
 *                 message:
 *                   type: string
 *                   example: Get price history successfully
 *                 data:
 *                   type: array
 *                   items:
 *                     type: object
 *                     properties:
 *                       time:
 *                         type: string
 *                         example: "2026-06-01"
 *                       open:
 *                         type: number
 *                         example: 133500
 *                       high:
 *                         type: number
 *                         example: 136000
 *                       low:
 *                         type: number
 *                         example: 133000
 *                       close:
 *                         type: number
 *                         example: 135000
 *                       volume:
 *                         type: number
 *                         example: 2500000
 *       404:
 *         description: Stock symbol not found.
 */
router.get('/:symbol/chart', getChartValidation, validate, stocksController.getStockChart);

/**
 * @openapi
 * /api/stocks/{symbol}/analysis-history:
 *   get:
 *     summary: Retrieve stock analysis report history from Python service
 *     tags: [Stocks]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *           example: FPT
 *         description: The uppercase stock symbol
 *       - in: query
 *         name: exchange
 *         schema:
 *           type: string
 *           example: HOSE
 *         description: Stock exchange code (e.g. HOSE, HNX)
 *       - in: query
 *         name: days
 *         schema:
 *           type: integer
 *           default: 3
 *         description: Number of past days to filter report history
 *     responses:
 *       200:
 *         description: Stock analysis history retrieved successfully.
 */
router.get('/:symbol/analysis-history', authMiddleware, stocksController.getStockAnalysisHistory);

// Admin Routes (mounted at /api/admin/stocks)

/**
 * @openapi
 * /api/admin/stocks:
 *   post:
 *     summary: Create a new stock catalog entry
 *     description: Add a new master stock definition. Restricted to administrator.
 *     tags: [Admin Stocks]
 *     security:
 *       - bearerAuth: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             required:
 *               - symbol
 *               - company_name
 *               - market_id
 *             properties:
 *               symbol:
 *                 type: string
 *                 example: FPT
 *               company_name:
 *                 type: string
 *                 example: Công ty Cổ phần FPT
 *               market_id:
 *                 type: string
 *                 description: ObjectId referencing dimMarkets collection
 *                 example: 665f1a2b9c1e2a0012a99001
 *               industry_id:
 *                 type: string
 *                 description: ObjectId referencing dimIndustries collection (optional)
 *                 example: 665f1a2b9c1e2a0012a99002
 *               status:
 *                 type: string
 *                 enum: [ACTIVE, DELISTED, SUSPENDED]
 *                 default: ACTIVE
 *               listed_date:
 *                 type: string
 *                 format: date
 *                 example: 2006-12-13
 *     responses:
 *       201:
 *         description: Stock created successfully.
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success:
 *                   type: boolean
 *                   example: true
 *                 message:
 *                   type: string
 *                   example: Create stock master successfully
 *                 data:
 *                   type: object
 *                   properties:
 *                     id:
 *                       type: string
 *                     symbol:
 *                       type: string
 *                     company_name:
 *                       type: string
 *                     market_id:
 *                       type: string
 *                       description: ObjectId of the market this stock belongs to
 *                     market_code:
 *                       type: string
 *                       description: Exchange code (e.g. HOSE, HNX)
 *                     status:
 *                       type: string
 *       400:
 *         description: Stock symbol already exists or validation failed.
 *       401:
 *         description: Unauthorized. Invalid access token.
 *       403:
 *         description: Forbidden. Insufficient permission.
 */
adminRouter.post('/', authMiddleware, roleMiddleware(['ADMIN']), createStockValidation, validate, stocksController.createStockMaster);

/**
 * @openapi
 * /api/admin/stocks/{id}:
 *   put:
 *     summary: Update stock catalog details
 *     description: Modify master profile details of a stock. Restricted to administrator.
 *     tags: [Admin Stocks]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: string
 *         description: Mongoose ObjectId of the stock
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               company_name:
 *                 type: string
 *                 example: Công ty Cổ phần FPT Việt Nam
 *               market_id:
 *                 type: string
 *                 description: ObjectId referencing dimMarkets (optional, to re-assign market)
 *                 example: 665f1a2b9c1e2a0012a99001
 *               industry_id:
 *                 type: string
 *                 description: ObjectId referencing dimIndustries (optional)
 *                 example: 665f1a2b9c1e2a0012a99002
 *               status:
 *                 type: string
 *                 enum: [ACTIVE, DELISTED, SUSPENDED]
 *               listed_date:
 *                 type: string
 *                 format: date
 *     responses:
 *       200:
 *         description: Stock updated successfully.
 *       400:
 *         description: Validation failed.
 *       401:
 *         description: Unauthorized.
 *       403:
 *         description: Forbidden.
 *       404:
 *         description: Stock not found.
 */
adminRouter.put('/:id', authMiddleware, roleMiddleware(['ADMIN']), updateStockValidation, validate, stocksController.updateStockMaster);

module.exports = {
  stocksRouter: router,
  adminStocksRouter: adminRouter
};
