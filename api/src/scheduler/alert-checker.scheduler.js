const cron = require('node-cron');
const alertsRepository = require('../modules/alerts/alert.repository');
const FactMarketPrice = require('../database/models/fact-market-price.model');
const watchlistsRepository = require('../modules/watchlists/watchlists.repository');
const emailService = require('../services/email.service');

const SCHEDULE = '0 17 * * 1-5'; // Weekdays at 17:00

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

const checkAlerts = async () => {
  console.log('[AlertChecker] Starting alert check...');

  // Find all ACTIVE alerts with stock_id populated
  // We do a raw lookup; since repository helpers need userId, we query Alert directly
  const Alert = require('../database/models/alert.model');
  const alerts = await Alert.find({ status: 'ACTIVE' })
    .populate({
      path: 'stock_id',
      select: '_id symbol company_name'
    })
    .populate({
      path: 'user_id',
      select: '_id email full_name'
    })
    .lean();

  if (alerts.length === 0) {
    console.log('[AlertChecker] No active alerts found');
    return;
  }

  // Group alerts by stock_id for efficient price fetching
  const alertsByStock = {};
  for (const alert of alerts) {
    if (!alert.stock_id) continue;
    const stockId = alert.stock_id._id.toString();
    if (!alertsByStock[stockId]) {
      alertsByStock[stockId] = { stock: alert.stock_id, alerts: [] };
    }
    alertsByStock[stockId].alerts.push(alert);
  }

  const stockIds = Object.keys(alertsByStock);
  console.log(`[AlertChecker] Checking ${alerts.length} alerts across ${stockIds.length} stocks`);

  // Fetch latest price for each stock
  const latestPrices = {};
  for (const stockId of stockIds) {
    const price = await FactMarketPrice.findOne({ stock_id: stockId })
      .sort({ time_id: -1 })
      .select('close_price volume')
      .lean();
    if (price) {
      latestPrices[stockId] = price;
    }
  }

  // Fetch 20-day average volumes for stocks with VOLUME_SPIKE alerts
  const volumeSpikeStockIds = stockIds.filter(sid =>
    alertsByStock[sid].alerts.some(a => a.alert_type === 'VOLUME_SPIKE')
  );
  const avgVolumes = {};
  for (const stockId of volumeSpikeStockIds) {
    const result = await FactMarketPrice.aggregate([
      { $match: { stock_id: require('mongoose').Types.ObjectId.createFromHexString(stockId) } },
      { $sort: { time_id: -1 } },
      { $limit: 20 },
      { $group: { _id: null, avgVolume: { $avg: '$volume' } } }
    ]);
    avgVolumes[stockId] = result.length > 0 ? result[0].avgVolume : 0;
  }

  // Evaluate each alert
  const triggered = [];
  for (const stockId of stockIds) {
    const price = latestPrices[stockId];
    if (!price) {
      console.log(`[AlertChecker] No price data for stock ${stockId}, skipping`);
      continue;
    }

    const { alerts: stockAlerts, stock } = alertsByStock[stockId];

    for (const alert of stockAlerts) {
      let shouldTrigger = false;
      let triggeredValue = null;

      switch (alert.alert_type) {
        case 'PRICE_ABOVE':
          if (price.close_price >= alert.threshold) {
            shouldTrigger = true;
            triggeredValue = price.close_price;
          }
          break;
        case 'PRICE_BELOW':
          if (price.close_price <= alert.threshold) {
            shouldTrigger = true;
            triggeredValue = price.close_price;
          }
          break;
        case 'VOLUME_SPIKE': {
          const avgVol = avgVolumes[stockId];
          if (avgVol > 0 && price.volume / avgVol >= alert.threshold) {
            shouldTrigger = true;
            triggeredValue = price.volume;
          }
          break;
        }
      }

      if (shouldTrigger) {
        // Check stock is still in user's watchlist before triggering
        const watchlistEntry = await watchlistsRepository.findWatchlistEntry(
          alert.user_id._id,
          alert.stock_id._id
        );
        if (!watchlistEntry) {
          console.log(`[AlertChecker] Skipping alert ${alert._id} — stock no longer in user's watchlist`);
          continue;
        }

        triggered.push({ alert, triggeredValue, price });
      }
    }
  }

  // Mark triggered and send emails in batches
  console.log(`[AlertChecker] ${triggered.length} alerts triggered`);
  const BATCH_SIZE = 10;
  for (let i = 0; i < triggered.length; i += BATCH_SIZE) {
    const batch = triggered.slice(i, i + BATCH_SIZE);
    await Promise.allSettled(batch.map(async ({ alert, triggeredValue, price }) => {
      try {
        await alertsRepository.markTriggered(alert._id, new Date(), triggeredValue);

        if (!alert.user_id || !alert.user_id.email) {
          console.log(`[AlertChecker] Alert ${alert._id}: user has no email, skipping notification`);
          return;
        }

        let subject, html;

        if (alert.alert_type === 'VOLUME_SPIKE') {
          const avgVol = avgVolumes[alert.stock_id._id.toString()] || 0;
          subject = `[AI Stock Trend] Volume Spike Alert: ${alert.stock_id.symbol}`;
          html = emailService.buildVolumeAlertHtml(
            alert.user_id.full_name || 'User',
            alert.stock_id.symbol,
            alert.stock_id.company_name,
            alert.threshold,
            triggeredValue,
            Math.round(avgVol)
          );
        } else {
          const direction = alert.alert_type === 'PRICE_ABOVE' ? 'surpassed' : 'dropped below';
          subject = `[AI Stock Trend] Price Alert: ${alert.stock_id.symbol} ${direction} ${alert.threshold.toLocaleString()} VND`;
          html = emailService.buildPriceAlertHtml(
            alert.user_id.full_name || 'User',
            alert.stock_id.symbol,
            alert.stock_id.company_name,
            alert.alert_type,
            alert.threshold,
            triggeredValue
          );
        }

        await emailService.sendAlertEmail(alert.user_id.email, subject, html);
      } catch (err) {
        console.error(`[AlertChecker] Error processing alert ${alert._id}: ${err.message}`);
      }
    }));

    if (i + BATCH_SIZE < triggered.length) {
      await sleep(2000);
    }
  }

  console.log('[AlertChecker] Alert check complete');
};

/**
 * Check alerts for a single stock (used in dev mock mode).
 * Only checks ACTIVE alerts for the given stock, no batch delay.
 */
/**
 * Check alerts for a single stock (used in dev mock mode).
 * @param {ObjectId} stockId
 * @param {Object} [opts] - { notifyEmail: string, mockPrice: {close_price, volume} }
 *   When mockPrice is provided it's used instead of querying the DB.
 */
const checkAlertsForStock = async (stockId, opts = {}) => {
  const Alert = require('../database/models/alert.model');
  const alerts = await Alert.find({ stock_id: stockId, status: 'ACTIVE' })
    .populate({
      path: 'stock_id',
      select: '_id symbol company_name'
    })
    .populate({
      path: 'user_id',
      select: '_id email full_name plan'
    })
    .lean();

  if (alerts.length === 0) return;

  // Use provided mock price if available, otherwise query DB
  const price = opts.mockPrice || await FactMarketPrice.findOne({ stock_id: stockId })
    .sort({ time_id: -1 })
    .select('close_price volume')
    .lean();

  if (!price) return;

  // Calculate avg volume for VOLUME_SPIKE checks
  let avgVolume = 0;
  const hasVolumeAlerts = alerts.some(a => a.alert_type === 'VOLUME_SPIKE');
  if (hasVolumeAlerts) {
    const result = await FactMarketPrice.aggregate([
      { $match: { stock_id: require('mongoose').Types.ObjectId.createFromHexString(stockId.toString()) } },
      { $sort: { time_id: -1 } },
      { $limit: 20 },
      { $group: { _id: null, avgVolume: { $avg: '$volume' } } }
    ]);
    avgVolume = result.length > 0 ? result[0].avgVolume : 0;
  }

  const env = require('../config/env.config');
  const isDev = env.NODE_ENV === 'development';

  for (const alert of alerts) {
    let shouldTrigger = false;
    let triggeredValue = null;

    switch (alert.alert_type) {
      case 'PRICE_ABOVE':
        if (price.close_price >= alert.threshold) { shouldTrigger = true; triggeredValue = price.close_price; }
        break;
      case 'PRICE_BELOW':
        if (price.close_price <= alert.threshold) { shouldTrigger = true; triggeredValue = price.close_price; }
        break;
      case 'VOLUME_SPIKE':
        if (avgVolume > 0 && price.volume / avgVolume >= alert.threshold) { shouldTrigger = true; triggeredValue = price.volume; }
        break;
    }

    if (!shouldTrigger) continue;

    // Skip watchlist check in dev mode (demo convenience)
    if (!isDev) {
      const watchlistEntry = await watchlistsRepository.findWatchlistEntry(alert.user_id._id, alert.stock_id._id);
      if (!watchlistEntry) {
        console.log(`[AlertChecker] Skipping alert ${alert._id} — stock no longer in user's watchlist`);
        continue;
      }
    }

    try {
      await alertsRepository.markTriggered(alert._id, new Date(), triggeredValue);
      console.log(`[AlertChecker] Alert ${alert._id} TRIGGERED (${alert.alert_type})`);

      // Determine email recipient: override via opts.notifyEmail, else alert owner
      const emailTo = opts.notifyEmail || (alert.user_id && alert.user_id.email);

      if (emailTo) {
        let subject, html;
        if (alert.alert_type === 'VOLUME_SPIKE') {
          subject = `[AI Stock Trend] Volume Spike Alert: ${alert.stock_id.symbol}`;
          html = emailService.buildVolumeAlertHtml(
            alert.user_id.full_name || 'User', alert.stock_id.symbol, alert.stock_id.company_name,
            alert.threshold, triggeredValue, Math.round(avgVolume)
          );
        } else {
          const direction = alert.alert_type === 'PRICE_ABOVE' ? 'surpassed' : 'dropped below';
          subject = `[AI Stock Trend] Price Alert: ${alert.stock_id.symbol} ${direction} ${alert.threshold.toLocaleString()} VND`;
          html = emailService.buildPriceAlertHtml(
            alert.user_id.full_name || 'User', alert.stock_id.symbol, alert.stock_id.company_name,
            alert.alert_type, alert.threshold, triggeredValue
          );
        }
        await emailService.sendAlertEmail(emailTo, subject, html);
      }
    } catch (err) {
      console.error(`[AlertChecker] Error processing alert ${alert._id}: ${err.message}`);
    }
  }
};

const start = () => {
  emailService.initTransporter();
  console.log(`[AlertChecker] Scheduler started — ${SCHEDULE}`);
  cron.schedule(SCHEDULE, () => {
    checkAlerts().catch(err => console.error('[AlertChecker] Cron job error:', err.message));
  });
};

module.exports = {
  start,
  checkAlerts,
  checkAlertsForStock
};
