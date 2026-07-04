/**
 * Mock Stock Movement — generate realistic price data that walks toward a target
 * to trigger alerts.
 *
 * Usage:
 *   node scripts/mock-stock-movement.js <symbol> <alertType> <threshold> [days]
 *
 * Examples:
 *   node scripts/mock-stock-movement.js FPT PRICE_ABOVE 150000    # price moves up to 150k
 *   node scripts/mock-stock-movement.js VNM PRICE_BELOW 70000 20  # price drops to 70k in 20 days
 *   node scripts/mock-stock-movement.js HPG VOLUME_SPIKE 3.0 10   # volume spikes 3x avg in 10 days
 *
 * The script:
 *   1. Reads last known price from fact_market_prices
 *   2. Generates N days of realistic OHLCV data walking from current → target
 *   3. Creates dimTime entries as needed (YYYYMMDD time_id)
 *   4. Inserts into factMarketPrices collection
 *   5. After each day, optionally runs the alert checker to verify triggering
 */
const path = require('path');
const dotenv = require('dotenv');
dotenv.config({ path: path.resolve(__dirname, '..', '.env'), override: true });

const mongoose = require('mongoose');
const DimStock = require('../src/database/models/dim-stock.model');
const DimMarket = require('../src/database/models/dim-market.model');
const DimTime = require('../src/database/models/dim-time.model');
const DimStockDataSource = require('../src/database/models/dim-stock-data-source.model');
const FactMarketPrice = require('../src/database/models/fact-market-price.model');

// ── Parse CLI args ────────────────────────────────────────────────────────────
const [symbolRaw, alertType, thresholdRaw, daysRaw] = process.argv.slice(2);
const symbol = (symbolRaw || '').toUpperCase().trim();
const THRESHOLD = parseFloat(thresholdRaw);
const ALERT_TYPE = (alertType || 'PRICE_ABOVE').toUpperCase();
const TOTAL_DAYS = parseInt(daysRaw, 10) || Math.floor(Math.random() * 16) + 15; // 15-30

if (!symbol || !THRESHOLD || !['PRICE_ABOVE', 'PRICE_BELOW', 'VOLUME_SPIKE'].includes(ALERT_TYPE)) {
  console.error(`
Usage: node scripts/mock-stock-movement.js <symbol> <alertType> <threshold> [days]

  symbol      Stock symbol (e.g. FPT, VNM, HPG)
  alertType   PRICE_ABOVE | PRICE_BELOW | VOLUME_SPIKE
  threshold   Target price (VND) or volume multiplier
  days        Optional: number of trading days to simulate (default: 15-30 random)

Examples:
  node scripts/mock-stock-movement.js FPT PRICE_ABOVE 150000
  node scripts/mock-stock-movement.js VNM PRICE_BELOW 70000 20
  node scripts/mock-stock-movement.js HPG VOLUME_SPIKE 3.0 10
`);
  process.exit(1);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

/** YYYYMMDD integer for a Date object */
const toTimeId = (d) => parseInt(`${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`, 10);

/** Next weekday (Mon-Fri) from a date */
const nextWeekday = (d) => {
  const next = new Date(d);
  next.setDate(next.getDate() + 1);
  while (next.getDay() === 0 || next.getDay() === 6) next.setDate(next.getDate() + 1);
  return next;
};

/** Random normal-ish value Box-Muller */
const randn = (mean = 0, std = 1) => {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return mean + std * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
};

/** Clamp a number between min and max */
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// ── Main ──────────────────────────────────────────────────────────────────────
const run = async () => {
  console.log(`\n=== Mock Stock Movement ===`);
  console.log(`  Symbol:     ${symbol}`);
  console.log(`  Alert Type: ${ALERT_TYPE}`);
  console.log(`  Threshold:  ${THRESHOLD.toLocaleString()}`);
  console.log(`  Days:       ${TOTAL_DAYS}\n`);

  // 1. Connect
  const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/aistock';
  console.log(`[1/5] Connecting to MongoDB...`);
  await mongoose.connect(MONGODB_URI);
  console.log(`      Connected to ${MONGODB_URI}`);

  // 2. Look up stock
  console.log(`\n[2/5] Looking up stock "${symbol}"...`);
  const stock = await DimStock.findOne({ symbol });
  if (!stock) {
    console.error(`      Error: Stock "${symbol}" not found in dim_stocks`);
    await mongoose.disconnect();
    process.exit(1);
  }
  console.log(`      Found: ${stock.company_name} (market: ${stock.market_id})`);

  // 3. Get last price data
  console.log(`\n[3/5] Getting last known price...`);
  const lastPrice = await FactMarketPrice.findOne({ stock_id: stock._id })
    .sort({ time_id: -1 })
    .select('time_id close_price volume open_price high_price low_price')
    .lean();

  let currentPrice, lastTimeId, lastVolume, avgVolume;

  if (lastPrice) {
    currentPrice = lastPrice.close_price;
    lastTimeId = lastPrice.time_id;
    lastVolume = lastPrice.volume || 1000000;
    console.log(`      Last close: ${currentPrice?.toLocaleString()} VND (time_id: ${lastTimeId})`);
    console.log(`      Last volume: ${lastVolume?.toLocaleString()}`);
  } else {
    console.log(`      No existing data — using defaults`);
    currentPrice = 50000;
    lastTimeId = 20260601;
    lastVolume = 1000000;
  }

  // Calculate average volume from last 20 records
  const recentPrices = await FactMarketPrice.find({ stock_id: stock._id })
    .sort({ time_id: -1 })
    .limit(20)
    .select('volume')
    .lean();
  avgVolume = recentPrices.length > 0
    ? recentPrices.reduce((s, p) => s + (p.volume || 0), 0) / recentPrices.length
    : lastVolume;
  console.log(`      20-day avg volume: ${Math.round(avgVolume).toLocaleString()}`);

  // 4. Resolve data_source_id and market_id for insert
  const dataSource = await DimStockDataSource.findOne({ stock_id: stock._id });
  const dataSourceId = dataSource?._id;
  if (!dataSourceId) {
    console.error(`      Error: No data source config for stock ${symbol} in dimStockDataSources`);
    await mongoose.disconnect();
    process.exit(1);
  }

  // 5. Generate price path
  console.log(`\n[4/5] Generating ${TOTAL_DAYS} days of price data...`);

  // Determine target price/volume and ensure it crosses the threshold
  let targetPrice;
  let isVolumeMock = ALERT_TYPE === 'VOLUME_SPIKE';

  if (isVolumeMock) {
    // Price stays near current, volume will spike
    targetPrice = currentPrice * (0.95 + Math.random() * 0.1); // ±5%
  } else if (ALERT_TYPE === 'PRICE_ABOVE') {
    // Target must be ABOVE threshold — aim for threshold + 3%
    targetPrice = Math.max(currentPrice * 1.05, THRESHOLD * 1.03 + 1000);
  } else {
    // PRICE_BELOW — target must be BELOW threshold
    targetPrice = Math.min(currentPrice * 0.95, THRESHOLD * 0.97 - 1000);
  }

  console.log(`      Current price: ${currentPrice.toLocaleString()} VND`);
  console.log(`      Target price:  ${targetPrice.toLocaleString()} VND`);

  // Build date sequence starting from last known date
  let cursorDate;
  if (lastPrice) {
    const lastDate = new Date(
      Math.floor(lastTimeId / 10000),
      Math.floor((lastTimeId % 10000) / 100) - 1,
      lastTimeId % 100
    );
    cursorDate = nextWeekday(lastDate);
  } else {
    cursorDate = new Date(2026, 5, 1); // June 1, 2026
    while (cursorDate.getDay() === 0 || cursorDate.getDay() === 6) cursorDate.setDate(cursorDate.getDate() + 1);
  }

  let inserted = 0;
  let skipped = 0;
  let hitTargetDay = -1;
  let lastClose = currentPrice;

  for (let day = 0; day < TOTAL_DAYS; day++) {
    const timeId = toTimeId(cursorDate);

    // Ensure dimTime exists
    const dimTime = await DimTime.findOne({ time_id: timeId });
    if (!dimTime) {
      await DimTime.create({
        time_id: timeId,
        full_date: cursorDate,
        day: cursorDate.getDate(),
        month: cursorDate.getMonth() + 1,
        quarter: Math.floor(cursorDate.getMonth() / 3) + 1,
        year: cursorDate.getFullYear(),
        week_of_year: Math.ceil((cursorDate.getTime() - new Date(cursorDate.getFullYear(), 0, 1).getTime()) / 86400000 / 7),
        weekday: cursorDate.getDay(),
        is_trading_day: true,
      });
    }

    // Check if this time_id already exists
    const exists = await FactMarketPrice.findOne({
      stock_id: stock._id,
      time_id: timeId,
      data_source_id: dataSourceId,
    });
    if (exists) {
      console.log(`      Day ${day + 1}/${TOTAL_DAYS}: time_id ${timeId} exists, skipping`);
      skipped++;
      cursorDate = nextWeekday(cursorDate);
      continue;
    }

    // ── Generate realistic price/volume ──────────────────────────────────
    let closePrice, generatedVolume;
    const progress = day / (TOTAL_DAYS - 1); // 0 → 1

    if (isVolumeMock) {
      // Price: random walk with slight mean reversion
      const priceNoisePct = 0.015; // 1.5% daily noise
      closePrice = lastClose * (1 + randn(0, priceNoisePct));
      closePrice = Math.round(closePrice / 100) * 100; // round to 100 VND

      // Volume: normal days then spike around day 60-80% progress
      const spikeDay = 0.6 + Math.random() * 0.2; // between 60-80% of the way
      const isSpikeDay = progress >= spikeDay && hitTargetDay === -1;

      if (isSpikeDay) {
        // Volume must exceed threshold * avg
        generatedVolume = Math.round(avgVolume * THRESHOLD * (1.05 + Math.random() * 0.2));
        hitTargetDay = day;
        // Optional: continue for a few more days with elevated but decreasing volume
      } else if (hitTargetDay >= 0 && day - hitTargetDay <= 3) {
        // Post-spike days — decreasing from spike
        const decayFactor = Math.max(0.3, 1 - (day - hitTargetDay) * 0.25);
        generatedVolume = Math.round(avgVolume * (0.8 + Math.random() * 0.5) * (1 + (THRESHOLD - 1) * decayFactor * 0.5));
      } else {
        // Normal day — volume around average with ±30% noise
        generatedVolume = Math.round(avgVolume * (0.7 + Math.random() * 0.6));
      }
    } else {
      // Price mock: walk from currentPrice toward targetPrice with noise
      const direction = targetPrice - currentPrice;
      const drift = direction * (1 / (TOTAL_DAYS - day)); // ensure we reach target
      const noisePct = 0.02 - progress * 0.01; // 2% early → 1% late
      const noise = currentPrice * noisePct * randn(0, 1);

      let raw = lastClose + drift + noise;

      // Ensure we cross the threshold at some point
      if (ALERT_TYPE === 'PRICE_ABOVE' && raw < THRESHOLD && progress >= 0.7 && hitTargetDay === -1) {
        // Push it over the threshold
        raw = THRESHOLD * (1.01 + Math.random() * 0.02);
        hitTargetDay = day;
      } else if (ALERT_TYPE === 'PRICE_BELOW' && raw > THRESHOLD && progress >= 0.7 && hitTargetDay === -1) {
        raw = THRESHOLD * (0.98 - Math.random() * 0.02);
        hitTargetDay = day;
      }

      closePrice = Math.round(clamp(raw, 1000, 10000000) / 100) * 100;

      // Track if we first crossed the threshold (if not already tracked and the direction is right)
      if (hitTargetDay === -1) {
        if (ALERT_TYPE === 'PRICE_ABOVE' && closePrice >= THRESHOLD) hitTargetDay = day;
        else if (ALERT_TYPE === 'PRICE_BELOW' && closePrice <= THRESHOLD) hitTargetDay = day;
      }

      // Volume: moderate, with occasional spikes
      const volNoise = 0.3 + Math.random() * 0.7; // 0.3x - 1.3x
      generatedVolume = Math.round(avgVolume * volNoise);
    }

    // Generate OHLC from closePrice
    const openPrice = lastClose;
    const absChange = Math.abs(closePrice - openPrice);
    const buffer = Math.max(absChange * 0.1, closePrice * 0.005);
    const highPrice = Math.round(Math.max(openPrice, closePrice) + buffer * (0.5 + Math.random() * 0.5));
    const lowPrice = Math.round(Math.min(openPrice, closePrice) - buffer * (0.5 + Math.random() * 0.5));

    try {
      await FactMarketPrice.create({
        stock_id: stock._id,
        market_id: stock.market_id,
        industry_id: stock.industry_id || undefined,
        data_source_id: dataSourceId,
        time_id: timeId,
        open_price: openPrice,
        high_price: highPrice,
        low_price: lowPrice,
        close_price: closePrice,
        volume: generatedVolume,
        crawled_at: new Date(),
      });
      inserted++;
    } catch (err) {
      console.error(`      Day ${day + 1}: insert error — ${err.message}`);
      skipped++;
    }

    // Log progress
    const crossing = hitTargetDay === day ? ' ◀── CROSSED THRESHOLD!' : '';
    const volLabel = isVolumeMock ? ` vol:${generatedVolume.toLocaleString()}` : '';
    console.log(`      Day ${day + 1}/${TOTAL_DAYS}   time_id:${timeId}   close:${closePrice.toLocaleString()} VND${volLabel}${crossing}`);

    lastClose = closePrice;
    cursorDate = nextWeekday(cursorDate);
    await sleep(50); // small delay to avoid overwhelming the DB
  }

  // ── Summary ───────────────────────────────────────────────────────────
  console.log(`\n[5/5] Simulation complete.`);
  console.log(`      Inserted: ${inserted} days`);
  console.log(`      Skipped:  ${skipped} days (already exist)`);

  if (hitTargetDay >= 0) {
    console.log(`      ✅ Threshold crossed on day ${hitTargetDay + 1}`);
  } else {
    console.log(`      ⚠️  Threshold NOT crossed during simulation`);
    if (isVolumeMock) {
      console.log(`         Try reducing the threshold multiplier or increasing days`);
    } else {
      console.log(`         Target was ${targetPrice.toLocaleString()} VND, threshold: ${THRESHOLD.toLocaleString()} VND`);
      console.log(`         Try increasing days or adjusting the threshold`);
    }
  }

  console.log(`\nNow run the alert checker to trigger alerts:`);
  console.log(`   node -e "require('./src/scheduler/alert-checker.scheduler').checkAlerts()"`);
  console.log(`\nOr check the data:`);
  console.log(`   mongosh --quiet --eval 'db.factMarketPrices.find({stock_id: ObjectId("${stock._id}")},{close_price:1,volume:1,time_id:1}).sort({time_id:-1}).limit(5)'`);

  await mongoose.disconnect();
  console.log(`\nDone.`);
};

run().catch(async (err) => {
  console.error(`Fatal: ${err.message}`);
  await mongoose.disconnect();
  process.exit(1);
});
