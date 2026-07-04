const express = require('express');
const router = express.Router();

const mockDataController = require('./mock-data.controller');
const authMiddleware = require('../../common/middlewares/auth.middleware');
const roleMiddleware = require('../../common/middlewares/role.middleware');

// All mock-data routes require auth + ADMIN or STAFF role
router.use(authMiddleware);
router.use(roleMiddleware(['ADMIN', 'STAFF']));

/**
 * @openapi
 * tags:
 *   - name: Staff Mock Data
 *     description: (DEV only) In-memory mock stock price simulation for alert demo. No DB writes.
 */

/**
 * @openapi
 * /api/staff/mock-data/start:
 *   post:
 *     summary: Start a mock price simulation session
 *     description: >
 *       Generate N ticks of realistic price/volume data in server memory.
 *       The stock detail/chart endpoints will return mock data while this session is active.
 *       No data written to database. Admin or Staff authentication required.
 *     tags: [Staff Mock Data]
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
 *               - alertType
 *               - threshold
 *             properties:
 *               symbol:
 *                 type: string
 *                 example: FPT
 *                 description: Stock symbol (uppercase)
 *               alertType:
 *                 type: string
 *                 enum: [PRICE_ABOVE, PRICE_BELOW, VOLUME_SPIKE]
 *                 example: PRICE_ABOVE
 *                 description: Alert type the demo will trigger
 *               threshold:
 *                 type: number
 *                 example: 150000
 *                 description: Target price (VND) or volume multiplier to cross
 *               tickCount:
 *                 type: integer
 *                 example: 15
 *                 default: 15
 *                 description: Number of simulated ticks (candles)
 *               notifyEmail:
 *                 type: string
 *                 format: email
 *                 example: youremail@gmail.com
 *                 description: Optional — override email recipient for alert notification. Uses alert owner's email if omitted.
 *     responses:
 *       201:
 *         description: Mock session started
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success:
 *                   type: boolean
 *                 message:
 *                   type: string
 *                 data:
 *                   type: object
 *                   properties:
 *                     symbol:
 *                       type: string
 *                     totalTicks:
 *                       type: integer
 *                     alertType:
 *                       type: string
 *                     threshold:
 *                       type: number
 *                     status:
 *                       type: string
 *       400:
 *         description: No price data for this stock
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       404:
 *         description: Stock symbol not found
 */
router.post('/start', mockDataController.start);

/**
 * @openapi
 * /api/staff/mock-data:
 *   get:
 *     summary: List all active mock sessions
 *     description: Returns all currently running in-memory mock simulation sessions.
 *     tags: [Staff Mock Data]
 *     security:
 *       - bearerAuth: []
 *     responses:
 *       200:
 *         description: Active sessions list
 *         content:
 *           application/json:
 *             schema:
 *               type: object
 *               properties:
 *                 success:
 *                   type: boolean
 *                 message:
 *                   type: string
 *                 data:
 *                   type: array
 *                   items:
 *                     type: object
 *                     properties:
 *                       symbol:
 *                         type: string
 *                       stockId:
 *                         type: string
 *                       alertType:
 *                         type: string
 *                       threshold:
 *                         type: number
 *                       progress:
 *                         type: string
 *                         example: "5/15"
 *                       totalTicks:
 *                         type: integer
 *                       alertFired:
 *                         type: boolean
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 */
router.get('/', mockDataController.list);

/**
 * @openapi
 * /api/staff/mock-data/{symbol}:
 *   delete:
 *     summary: Stop a mock simulation session
 *     description: Immediately stop and clean up a running mock session. Stock detail API returns real DB data again.
 *     tags: [Staff Mock Data]
 *     security:
 *       - bearerAuth: []
 *     parameters:
 *       - in: path
 *         name: symbol
 *         required: true
 *         schema:
 *           type: string
 *         example: FPT
 *         description: Stock symbol to stop mock for
 *     responses:
 *       200:
 *         description: Mock session stopped
 *       401:
 *         description: Unauthorized
 *       403:
 *         description: Forbidden
 *       404:
 *         description: No active session for this symbol
 */
router.delete('/:symbol', mockDataController.remove);

module.exports = router;
