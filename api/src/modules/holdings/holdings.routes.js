const express = require('express');
const holdingsController = require('./holdings.controller');
const authMiddleware = require('../../common/middlewares/auth.middleware');
const roleMiddleware = require('../../common/middlewares/role.middleware');
const {
  validate,
  getMyHoldingsValidation,
  getMyHoldingDetailValidation,
  saveHoldingValidation,
  updateHoldingValidation,
  removeHoldingValidation
} = require('./holdings.validation');

const router = express.Router({ strict: true });

/**
 * @openapi
 * tags:
 *   - name: Personal Holdings Tracker
 *     description: Manage the authenticated user's current stock holdings
 */

/**
 * @openapi
 * components:
 *   schemas:
 *     HoldingStock:
 *       type: object
 *       properties:
 *         _id:
 *           type: string
 *           example: 6868f4c7f82f7d4a9210a001
 *         symbol:
 *           type: string
 *           example: FPT
 *         company_name:
 *           type: string
 *           example: FPT Corporation
 *         market:
 *           type: string
 *           nullable: true
 *           example: HOSE
 *     HoldingItem:
 *       type: object
 *       properties:
 *         holding_id:
 *           type: string
 *           example: 6868f4c7f82f7d4a9210b001
 *         stock:
 *           $ref: '#/components/schemas/HoldingStock'
 *         average_cost:
 *           type: number
 *           format: float
 *           example: 24500.5
 *         quantity:
 *           type: integer
 *           example: 100
 *         holding_date:
 *           type: string
 *           format: date
 *           example: 2026-06-01
 *         latest_market_price:
 *           type: number
 *           nullable: true
 *           example: 27800
 *         note:
 *           type: string
 *           example: Long-term holding
 *         status:
 *           type: string
 *           enum: [ACTIVE, REMOVED]
 *           example: ACTIVE
 *         created_at:
 *           type: string
 *           format: date-time
 *           example: 2026-07-05T03:00:00.000Z
 *         updated_at:
 *           type: string
 *           format: date-time
 *           example: 2026-07-05T03:10:00.000Z
 *     SaveHoldingRequest:
 *       type: object
 *       required:
 *         - average_cost
 *         - quantity
 *         - holding_date
 *       properties:
 *         average_cost:
 *           type: number
 *           format: float
 *           example: 24500.5
 *           description: User-entered average cost, must be greater than 0
 *         quantity:
 *           type: integer
 *           example: 100
 *           description: Current holding quantity, must be a positive integer
 *         holding_date:
 *           type: string
 *           format: date
 *           example: 2026-06-01
 *           description: Must be a past date
 *         note:
 *           type: string
 *           example: Long-term holding
 *     ValidationErrorResponse:
 *       type: object
 *       properties:
 *         success:
 *           type: boolean
 *           example: false
 *         message:
 *           type: string
 *           example: Validation failed
 *         errors:
 *           type: array
 *           items:
 *             type: object
 *             properties:
 *               field:
 *                 type: string
 *                 example: quantity
 *               message:
 *                 type: string
 *                 example: quantity must be a positive integer
 *     AppErrorResponse:
 *       type: object
 *       properties:
 *         success:
 *           type: boolean
 *           example: false
 *         message:
 *           type: string
 *           example: HOLDING_NOT_FOUND
 *         code:
 *           type: string
 *           nullable: true
 *           example: HOLDING_NOT_FOUND
 *         details:
 *           nullable: true
 *           example: null
 *         errors:
 *           nullable: true
 *           example: null
 */

/**
 * @openapi
 * /api/me/holdings:
 *   get:
 *     summary: Get my holdings list
 *     description: Returns the authenticated user's holdings with latest market price for display only.
 *     tags: [Personal Holdings Tracker]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: query
 *         name: status
 *         schema:
 *           type: string
 *           enum: [ACTIVE, REMOVED, ALL]
 *           default: ACTIVE
 *         description: Filter holdings by status
 *       - in: query
 *         name: page
 *         schema:
 *           type: integer
 *           minimum: 1
 *           default: 1
 *       - in: query
 *         name: limit
 *         schema:
 *           type: integer
 *           minimum: 1
 *           maximum: 100
 *           default: 20
 *     responses:
 *       200:
 *         description: Holdings retrieved successfully
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
 *                   example: Holdings retrieved successfully
 *                 data:
 *                   type: object
 *                   properties:
 *                     items:
 *                       type: array
 *                       items:
 *                         $ref: '#/components/schemas/HoldingItem'
 *                     pagination:
 *                       type: object
 *                       properties:
 *                         page:
 *                           type: integer
 *                           example: 1
 *                         limit:
 *                           type: integer
 *                           example: 20
 *                         total:
 *                           type: integer
 *                           example: 1
 *       400:
 *         description: Invalid query parameters
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/ValidationErrorResponse'
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       500:
 *         description: Internal server error
 */

router.get(
  '/holdings',
  authMiddleware,
  roleMiddleware(['USER']),
  getMyHoldingsValidation,
  validate,
  holdingsController.getMyHoldings
);

/**
 * @openapi
 * /api/me/holdings/{symbol}:
 *   get:
 *     summary: Get holding detail by stock symbol
 *     description: Returns one holding for the authenticated user. The `symbol` path param is the stock symbol sent by frontend, such as `FPT` or `ACB`.
 *     tags: [Personal Holdings Tracker]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *         description: Stock symbol, trimmed and uppercased by backend before lookup
 *         example: FPT
 *     responses:
 *       200:
 *         description: Holding detail retrieved successfully
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
 *                   example: Holding detail retrieved successfully
 *                 data:
 *                   $ref: '#/components/schemas/HoldingItem'
 *       400:
 *         description: Invalid stock symbol
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/ValidationErrorResponse'
 *                 - $ref: '#/components/schemas/AppErrorResponse'
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       404:
 *         description: Stock or holding not found
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/AppErrorResponse'
 *       500:
 *         description: Internal server error
 */

router.get(
  '/holdings/:symbol',
  authMiddleware,
  roleMiddleware(['USER']),
  getMyHoldingDetailValidation,
  validate,
  holdingsController.getMyHoldingDetail
);

/**
 * @openapi
 * /api/me/holdings/{symbol}:
 *   post:
 *     summary: Create or reactivate a holding
 *     description: Creates a new holding for the authenticated user and stock symbol, or reactivates an existing removed holding. No transaction history is used in this MVP.
 *     tags: [Personal Holdings Tracker]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *         example: FPT
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/SaveHoldingRequest'
 *     responses:
 *       201:
 *         description: Holding saved successfully
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
 *                   example: Holding saved successfully
 *                 data:
 *                   type: object
 *                   properties:
 *                     holding:
 *                       $ref: '#/components/schemas/HoldingItem'
 *       400:
 *         description: Validation or business rule error
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/ValidationErrorResponse'
 *                 - $ref: '#/components/schemas/AppErrorResponse'
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       404:
 *         description: Stock not found
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/AppErrorResponse'
 *       409:
 *         description: Stock is inactive
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/AppErrorResponse'
 *       500:
 *         description: Internal server error
 */

router.post(
  '/holdings/:symbol',
  authMiddleware,
  roleMiddleware(['USER']),
  saveHoldingValidation,
  validate,
  holdingsController.saveHolding
);

/**
 * @openapi
 * /api/me/holdings/{symbol}:
 *   put:
 *     summary: Update an existing holding
 *     description: Updates the authenticated user's current holding for the given stock symbol.
 *     tags: [Personal Holdings Tracker]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *         example: FPT
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             $ref: '#/components/schemas/SaveHoldingRequest'
 *     responses:
 *       200:
 *         description: Holding updated successfully
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
 *                   example: Holding updated successfully
 *                 data:
 *                   type: object
 *                   properties:
 *                     holding:
 *                       $ref: '#/components/schemas/HoldingItem'
 *       400:
 *         description: Validation or business rule error
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/ValidationErrorResponse'
 *                 - $ref: '#/components/schemas/AppErrorResponse'
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       404:
 *         description: Stock or holding not found
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/AppErrorResponse'
 *       409:
 *         description: Stock is inactive
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/AppErrorResponse'
 *       500:
 *         description: Internal server error
 */

router.put(
  '/holdings/:symbol',
  authMiddleware,
  roleMiddleware(['USER']),
  updateHoldingValidation,
  validate,
  holdingsController.updateHolding
);

/**
 * @openapi
 * /api/me/holdings/{symbol}:
 *   delete:
 *     summary: Soft remove a holding
 *     description: Marks the authenticated user's holding as `REMOVED` and sets `removed_at`. This does not hard delete the record.
 *     tags: [Personal Holdings Tracker]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *         example: FPT
 *     responses:
 *       200:
 *         description: Holding removed successfully
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
 *                   example: Holding removed successfully
 *                 data:
 *                   type: object
 *                   properties:
 *                     holding_id:
 *                       type: string
 *                       example: 6868f4c7f82f7d4a9210b001
 *                     status:
 *                       type: string
 *                       enum: [REMOVED]
 *                       example: REMOVED
 *       400:
 *         description: Invalid stock symbol
 *         content:
 *           application/json:
 *             schema:
 *               oneOf:
 *                 - $ref: '#/components/schemas/ValidationErrorResponse'
 *                 - $ref: '#/components/schemas/AppErrorResponse'
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       404:
 *         description: Stock or holding not found
 *         content:
 *           application/json:
 *             schema:
 *               $ref: '#/components/schemas/AppErrorResponse'
 *       500:
 *         description: Internal server error
 */

router.delete(
  '/holdings/:symbol',
  authMiddleware,
  roleMiddleware(['USER']),
  removeHoldingValidation,
  validate,
  holdingsController.removeHolding
);

module.exports = router;
