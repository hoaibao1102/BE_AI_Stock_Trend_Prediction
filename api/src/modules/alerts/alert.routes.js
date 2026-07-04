const express = require('express');
const router = express.Router();

const alertsController = require('./alert.controller');
const authMiddleware = require('../../common/middlewares/auth.middleware');
const { checkSubscriptionExpiry } = require('../../common/middlewares/subscription.middleware');
const {
  validate,
  createAlertValidation,
  updateAlertValidation,
  alertIdValidation
} = require('./alert.validation');

/**
 * @openapi
 * tags:
 *   - name: Alerts
 *     description: User alert management (price & volume alerts)
 */

/**
 * @openapi
 * /api/alerts:
 *   get:
 *     summary: Retrieve user's alerts
 *     description: Retrieve all alerts configured by the authorized user, with stock info and latest price.
 *     tags: [Alerts]
 *     security:
 *       - bearerAuth: []
 *     responses:
 *       200:
 *         description: Alerts retrieved successfully.
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
 *                   example: Get alerts successfully
 *                 data:
 *                   type: array
 *                   items:
 *                     type: object
 *                     properties:
 *                       id:
 *                         type: string
 *                         example: 665f1a2b9c1e2a0012a99991
 *                       symbol:
 *                         type: string
 *                         example: FPT
 *                       company_name:
 *                         type: string
 *                         example: Công ty Cổ phần FPT
 *                       alert_type:
 *                         type: string
 *                         enum: [PRICE_ABOVE, PRICE_BELOW, VOLUME_SPIKE]
 *                         example: PRICE_ABOVE
 *                       threshold:
 *                         type: number
 *                         example: 140000
 *                       status:
 *                         type: string
 *                         enum: [ACTIVE, TRIGGERED, DISABLED]
 *                         example: ACTIVE
 *                       triggered_at:
 *                         type: string
 *                         nullable: true
 *                         format: date-time
 *                       triggered_value:
 *                         type: number
 *                         nullable: true
 *                       latest_price:
 *                         type: object
 *                         nullable: true
 *                         properties:
 *                           close_price:
 *                             type: number
 *                           volume:
 *                             type: number
 *                       created_at:
 *                         type: string
 *                         format: date-time
 *                       updated_at:
 *                         type: string
 *                         format: date-time
 *       401:
 *         description: Unauthorized.
 */
router.get('/', authMiddleware, checkSubscriptionExpiry, alertsController.list);

/**
 * @openapi
 * /api/alerts:
 *   post:
 *     summary: Create a new alert
 *     description: Create a price or volume alert for a stock in the user's watchlist.
 *     tags: [Alerts]
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
 *               - alert_type
 *               - threshold
 *             properties:
 *               symbol:
 *                 type: string
 *                 example: FPT
 *               alert_type:
 *                 type: string
 *                 enum: [PRICE_ABOVE, PRICE_BELOW, VOLUME_SPIKE]
 *                 example: PRICE_ABOVE
 *               threshold:
 *                 type: number
 *                 example: 140000
 *     responses:
 *       201:
 *         description: Alert created successfully.
 *       400:
 *         description: Plan limit exceeded or validation failed.
 *       401:
 *         description: Unauthorized.
 *       404:
 *         description: Stock symbol not found.
 */
router.post('/', authMiddleware, checkSubscriptionExpiry, createAlertValidation, validate, alertsController.create);

/**
 * @openapi
 * /api/alerts/{id}:
 *   get:
 *     summary: Get a single alert
 *     description: Retrieve details of a specific alert by ID.
 *     tags: [Alerts]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: string
 *         description: Alert ID
 *     responses:
 *       200:
 *         description: Alert retrieved successfully.
 *       401:
 *         description: Unauthorized.
 *       404:
 *         description: Alert not found.
 */
router.get('/:id', authMiddleware, checkSubscriptionExpiry, alertIdValidation, validate, alertsController.getById);

/**
 * @openapi
 * /api/alerts/{id}:
 *   put:
 *     summary: Update an alert
 *     description: Update alert threshold or toggle status (ACTIVE ↔ DISABLED, or reset TRIGGERED → ACTIVE).
 *     tags: [Alerts]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: string
 *         description: Alert ID
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               threshold:
 *                 type: number
 *                 example: 145000
 *               status:
 *                 type: string
 *                 enum: [ACTIVE, DISABLED]
 *                 example: DISABLED
 *     responses:
 *       200:
 *         description: Alert updated successfully.
 *       400:
 *         description: Invalid status transition.
 *       401:
 *         description: Unauthorized.
 *       404:
 *         description: Alert not found.
 */
router.put('/:id', authMiddleware, checkSubscriptionExpiry, updateAlertValidation, validate, alertsController.update);

/**
 * @openapi
 * /api/alerts/{id}:
 *   delete:
 *     summary: Delete an alert
 *     description: Permanently delete an alert by ID.
 *     tags: [Alerts]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: id
 *         required: true
 *         schema:
 *           type: string
 *         description: Alert ID
 *     responses:
 *       200:
 *         description: Alert deleted successfully.
 *       401:
 *         description: Unauthorized.
 *       404:
 *         description: Alert not found.
 */
router.delete('/:id', authMiddleware, checkSubscriptionExpiry, alertIdValidation, validate, alertsController.remove);

module.exports = router;
