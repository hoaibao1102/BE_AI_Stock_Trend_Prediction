const express = require('express');
const portfolioController = require('./portfolio.controller');
const authMiddleware = require('../../common/middlewares/auth.middleware');
const roleMiddleware = require('../../common/middlewares/role.middleware');

const router = express.Router({ strict: true });

/**
 * @openapi
 * tags:
 *   - name: Portfolio Analysis
 *     description: Unrealized profit/loss analysis over the authenticated user's active holdings
 */

/**
 * @openapi
 * components:
 *   schemas:
 *     PortfolioPricePoint:
 *       type: object
 *       properties:
 *         date:
 *           type: string
 *           format: date
 *           example: 2026-07-07
 *         open: { type: number, nullable: true, example: 26500 }
 *         high: { type: number, nullable: true, example: 27000 }
 *         low: { type: number, nullable: true, example: 26300 }
 *         close: { type: number, nullable: true, example: 27150 }
 *         volume: { type: number, nullable: true, example: 12500000 }
 *         pe: { type: number, nullable: true, example: 8.5 }
 *         pb: { type: number, nullable: true, example: 1.2 }
 *         roe: { type: number, nullable: true, example: 14.5 }
 *     PortfolioPnlItem:
 *       type: object
 *       properties:
 *         holding_id: { type: string, example: 6868f4c7f82f7d4a9210b001 }
 *         symbol: { type: string, example: HPG }
 *         company_name: { type: string, example: Hoa Phat Group }
 *         exchange: { type: string, nullable: true, example: HOSE }
 *         average_cost: { type: number, example: 25000 }
 *         quantity: { type: integer, example: 1000 }
 *         holding_date: { type: string, format: date, example: 2026-01-15 }
 *         close_price: { type: number, nullable: true, example: 27150 }
 *         price_change: { type: number, nullable: true, example: 350 }
 *         price_change_percent: { type: number, nullable: true, example: 1.31 }
 *         cost: { type: number, nullable: true, example: 25000000 }
 *         market_value: { type: number, nullable: true, example: 27150000 }
 *         unrealized_pnl: { type: number, nullable: true, example: 2150000 }
 *         unrealized_pnl_pct: { type: number, nullable: true, example: 8.6 }
 *         status:
 *           type: string
 *           enum: [PROFIT, LOSS, UNKNOWN]
 *           example: PROFIT
 *         pnl_signal:
 *           type: string
 *           nullable: true
 *           enum: [CONSIDER_TAKING_PROFIT, STRONG_PROFIT_HOLD, MODERATE_PROFIT_HOLD, BREAKEVEN_WATCH, MODERATE_LOSS_HOLD, SIGNIFICANT_LOSS_REVIEW]
 *           example: MODERATE_PROFIT_HOLD
 *         prices_7d:
 *           type: array
 *           items:
 *             $ref: '#/components/schemas/PortfolioPricePoint'
 *         note: { type: string, example: Long-term holding }
 *         price_as_of: { type: string, format: date, nullable: true, example: 2026-07-07 }
 *     PortfolioSummary:
 *       type: object
 *       nullable: true
 *       properties:
 *         total_cost: { type: number, example: 220000000 }
 *         total_market_value: { type: number, example: 247500000 }
 *         total_unrealized_pnl: { type: number, example: 27500000 }
 *         total_unrealized_pnl_pct: { type: number, nullable: true, example: 12.5 }
 *         count_total: { type: integer, example: 3 }
 *         count_priced: { type: integer, example: 3 }
 *         count_profit: { type: integer, example: 2 }
 *         count_loss: { type: integer, example: 1 }
 */

/**
 * @openapi
 * /api/portfolio/pnl:
 *   get:
 *     summary: Get unrealized P&L for all active holdings
 *     description: >
 *       Computes cost, market value and unrealized profit/loss for every ACTIVE holding of the
 *       authenticated user, plus a portfolio-level summary and the last 7 price points per stock.
 *       Read-only aggregation over existing data; no AI or external calls, so it returns fast and
 *       is safe to poll. Pair with the analyse service holdings-advice endpoint for AI recommendations.
 *     tags: [Portfolio Analysis]
 *     security:
 *       - bearerAuth: []
 *     responses:
 *       200:
 *         description: Portfolio P&L retrieved successfully
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success: { type: boolean, example: true }
 *                 message: { type: string, example: Portfolio P&L retrieved successfully }
 *                 data:
 *                   type: object
 *                   properties:
 *                     generated_at: { type: string, format: date-time }
 *                     data_as_of: { type: string, format: date, nullable: true, example: 2026-07-07 }
 *                     portfolio_summary:
 *                       $ref: '#/components/schemas/PortfolioSummary'
 *                     items:
 *                       type: array
 *                       items:
 *                         $ref: '#/components/schemas/PortfolioPnlItem'
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       500:
 *         description: Internal server error
 */
router.get(
  '/pnl',
  authMiddleware,
  roleMiddleware(['USER']),
  portfolioController.getPortfolioPnl
);

/**
 * @openapi
 * /api/portfolio/holdings-advice:
 *   get:
 *     summary: Get hybrid holdings advice for active positions
 *     description: >
 *       Combines unrealized P&L, 7-day price trend, and recent Analyse history for each active holding.
 *       This is a read-only endpoint designed for the portfolio popup and avoids re-running analysis on every click.
 *     tags: [Portfolio Analysis]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: query
 *         name: forceRefresh
 *         schema: { type: boolean, default: false }
 *         description: Bypass the in-memory advice cache and recompute the recommendation payload.
 *     responses:
 *       200:
 *         description: Portfolio holdings advice retrieved successfully
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success: { type: boolean, example: true }
 *                 message: { type: string, example: Portfolio holdings advice retrieved successfully }
 *                 data:
 *                   type: object
 *                   properties:
 *                     generated_at: { type: string, format: date-time }
 *                     data_as_of: { type: string, format: date, nullable: true }
 *                     portfolio_summary:
 *                       type: object
 *                       nullable: true
 *                     items:
 *                       type: array
 *                       items:
 *                         type: object
 *                         properties:
 *                           symbol: { type: string }
 *                           recommendation: { type: string, enum: [BUY, HOLD, SELL] }
 *                           explanation: { type: string }
 *                           trend_7d_pct: { type: number }
 *                           ai_context:
 *                             type: object
 *                             properties:
 *                               available: { type: boolean }
 *                               count: { type: integer }
 *                               latest_decision_label: { type: string, nullable: true }
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 */
router.get(
  '/holdings-advice',
  authMiddleware,
  roleMiddleware(['USER']),
  portfolioController.getPortfolioHoldingsAdvice
);

/**
 * @openapi
 * /api/portfolio/watchlist/batch:
 *   get:
 *     summary: Get batch watchlist analysis for the full table view
 *     description: >
 *       Returns one row per stock in the authenticated user's watchlist, including P&L, recommendation,
 *       explanation, trend, and optional Analyse context. This is the primary endpoint for the FE table.
 *     tags: [Portfolio Analysis]
 *     security:
 *       - bearerAuth: []
 *     responses:
 *       200:
 *         description: Portfolio watchlist batch retrieved successfully
 */
router.get(
  '/watchlist/batch',
  authMiddleware,
  roleMiddleware(['USER']),
  portfolioController.getPortfolioWatchlistBatch
);

/**
 * @openapi
 * /api/portfolio/watchlist/:symbol/detail:
 *   get:
 *     summary: Get detailed insight for one watchlist stock
 *     description: >
 *       Returns the popup detail payload for a single stock, including recommendation, explanation,
 *       7-day price history, and optional Analyse context.
 *     tags: [Portfolio Analysis]
 *     security:
 *       - bearerAuth: []
 */
router.get(
  '/watchlist/:symbol/detail',
  authMiddleware,
  roleMiddleware(['USER']),
  portfolioController.getPortfolioWatchlistDetail
);

module.exports = router;
