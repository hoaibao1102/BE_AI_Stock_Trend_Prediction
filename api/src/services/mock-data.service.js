/**
 * Mock Data Service — in-memory price tick generation for demo.
 * No DB writes. Used only in development via Swagger staff endpoints.
 */
const env = require('../config/env.config');

// In-memory store: Map<symbol, MockSession>
const sessions = new Map();

/** Random normal-ish value (Box-Muller) */
const randn = (mean = 0, std = 1) => {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return mean + std * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
};

/** Clamp */
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** YYYYMMDD from a Date */
const toTimeId = (d) =>
  parseInt(`${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`, 10);

/** Format time_id to "YYYY-MM-DD" */
const formatTimeId = (id) => {
  const s = String(id);
  return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
};

const priceChange = (prevClose, currClose) => currClose - prevClose;
const priceChangePct = (prevClose, currClose) =>
  prevClose ? Number((((currClose - prevClose) / prevClose) * 100).toFixed(2)) : 0;

class MockSession {
  constructor({ symbol, stockId, currentPrice, avgVolume, alertType, threshold, tickCount, lastTimeId, notifyEmail }) {
    this.symbol = symbol;
    this.stockId = stockId;
    this.notifyEmail = notifyEmail || null;
    this.alertType = alertType;
    this.threshold = threshold;
    this.tickCount = tickCount;
    this.cursor = 0;
    this.alertFired = false;
    this.ticks = this._generateTicks(currentPrice, avgVolume, lastTimeId);
  }

  _generateTicks(startPrice, avgVolume, lastTimeId) {
    const isVolume = this.alertType === 'VOLUME_SPIKE';
    const targetPrice = isVolume
      ? startPrice * (0.95 + Math.random() * 0.1)
      : this.alertType === 'PRICE_ABOVE'
        ? Math.max(startPrice * 1.02, this.threshold * 1.03 + 1000)
        : Math.min(startPrice * 0.98, this.threshold * 0.97 - 1000);

    let lastClose = startPrice;
    let lastTimeIdNum = lastTimeId || 20260701;
    const ticks = [];
    let crossed = false;

    for (let day = 0; day < this.tickCount; day++) {
      const progress = day / Math.max(this.tickCount - 1, 1);
      lastTimeIdNum++; // sequential time_ids instead of real dates

      let closePrice, volume;

      if (isVolume) {
        // Price: slight random walk
        const noise = startPrice * 0.012 * randn(0, 1);
        closePrice = Math.round(clamp(lastClose + noise, startPrice * 0.85, startPrice * 1.15) / 100) * 100;

        // Volume: spike around 55-75% progress
        const spikeWindowStart = 0.55;
        const spikeWindowEnd = 0.75;
        const inWindow = progress >= spikeWindowStart && progress <= spikeWindowEnd;

        if (inWindow && !crossed) {
          volume = Math.round(avgVolume * this.threshold * (1.1 + Math.random() * 0.3));
          crossed = true;
        } else if (crossed && day - this._spikeDay <= 3) {
          const decay = Math.max(0.3, 1 - (day - this._spikeDay) * 0.25);
          volume = Math.round(avgVolume * (0.8 + Math.random() * 0.5) * (1 + (this.threshold - 1) * decay * 0.5));
        } else {
          volume = Math.round(avgVolume * (0.6 + Math.random() * 0.8));
        }

        if (inWindow && !this._spikeDay) this._spikeDay = day;
      } else {
        // Price: drift toward target with noise
        const direction = targetPrice - startPrice;
        const drift = direction * (1 / (this.tickCount - day));
        const noisePct = 0.025 - progress * 0.012;
        const noise = startPrice * noisePct * randn(0, 1);
        let raw = lastClose + drift + noise;

        // Force threshold crossing at 65-80% progress if not already there
        if (!crossed && progress >= 0.65) {
          if (this.alertType === 'PRICE_ABOVE' && raw < this.threshold) {
            raw = this.threshold * (1.01 + Math.random() * 0.015);
          } else if (this.alertType === 'PRICE_BELOW' && raw > this.threshold) {
            raw = this.threshold * (0.985 - Math.random() * 0.015);
          }
        }

        closePrice = Math.round(clamp(raw, 100, 10000000) / 100) * 100;

        if (!crossed) {
          if (this.alertType === 'PRICE_ABOVE' && closePrice >= this.threshold) crossed = true;
          else if (this.alertType === 'PRICE_BELOW' && closePrice <= this.threshold) crossed = true;
        }

        volume = Math.round(avgVolume * (0.3 + Math.random() * 0.7));
      }

      // OHLC
      const absChange = Math.abs(closePrice - lastClose);
      const buffer = Math.max(absChange * 0.1, closePrice * 0.005);
      const high = Math.round(Math.max(lastClose, closePrice) + buffer * (0.5 + Math.random() * 0.5));
      const low = Math.round(Math.min(lastClose, closePrice) + buffer * (0.5 - Math.random() * 0.5));

      ticks.push({
        time_id: lastTimeIdNum,
        time: String(lastTimeIdNum),
        open_price: lastClose,
        high_price: high,
        low_price: low,
        close_price: closePrice,
        volume,
        price_change: priceChange(lastClose, closePrice),
        price_change_percent: priceChangePct(lastClose, closePrice),
        bid_volume: null,
        ask_volume: null,
        foreign_buy: null,
        foreign_sell: null,
        foreign_net: null,
        market_cap: null,
        eps: null,
        pe: null,
        forward_pe: null,
        bvps: null,
        pb: null,
        beta: null,
        roe: null,
        ros: null,
        roaa: null,
        crawled_at: new Date().toISOString(),
        _mock: true,
        _crossesThreshold: crossed && !(this._firstCrossedTick !== undefined),
        _done: day === this.tickCount - 1,
      });

      if (crossed && this._firstCrossedTick === undefined) {
        this._firstCrossedTick = ticks.length - 1;
      }

      lastClose = closePrice;
    }

    return ticks;
  }

  /** Get next tick and advance cursor. Returns null if exhausted. */
  nextTick() {
    if (this.cursor >= this.ticks.length) return null;
    const tick = this.ticks[this.cursor];
    this.cursor++;
    tick._cursor = this.cursor;
    tick._remaining = this.ticks.length - this.cursor;
    return tick;
  }

  /** Get all ticks emitted so far (for chart replay) */
  getEmittedTicks() {
    return this.ticks.slice(0, this.cursor);
  }

  /** Peek current tick without advancing */
  peekCurrent() {
    if (this.cursor >= this.ticks.length) return null;
    return this.ticks[this.cursor];
  }

  isActive() {
    return this.cursor < this.ticks.length;
  }

  getProgress() {
    return `${this.cursor}/${this.ticks.length}`;
  }
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Start a mock session.
 * @returns {Object} session info
 */
const startSession = async ({ symbol, stockId, currentPrice, avgVolume, alertType, threshold, tickCount, lastTimeId, notifyEmail }) => {
  // Clean existing session for this symbol if any
  sessions.delete(symbol.toUpperCase());

  const session = new MockSession({
    symbol: symbol.toUpperCase(),
    stockId,
    currentPrice,
    avgVolume,
    alertType,
    threshold,
    tickCount,
    lastTimeId,
    notifyEmail,
  });

  sessions.set(session.symbol, session);
  return {
    symbol: session.symbol,
    totalTicks: session.tickCount,
    alertType: session.alertType,
    threshold: session.threshold,
    status: 'started',
  };
};

/**
 * Get active session for a symbol (or null).
 */
const getActiveSession = (symbol) => {
  return sessions.get(symbol.toUpperCase()) || null;
};

/**
 * Stop and remove a session.
 */
const stopSession = (symbol) => {
  const key = symbol.toUpperCase();
  const existed = sessions.has(key);
  sessions.delete(key);
  return existed;
};

/**
 * List all active sessions.
 */
const listSessions = () => {
  const result = [];
  for (const [symbol, session] of sessions) {
    result.push({
      symbol,
      stockId: session.stockId,
      alertType: session.alertType,
      threshold: session.threshold,
      progress: session.getProgress(),
      totalTicks: session.tickCount,
      alertFired: session.alertFired,
    });
  }
  return result;
};

/**
 * Mark that alert has been fired for a session.
 */
const markAlertFired = (symbol) => {
  const session = sessions.get(symbol.toUpperCase());
  if (session) session.alertFired = true;
};

module.exports = {
  startSession,
  getActiveSession,
  stopSession,
  listSessions,
  markAlertFired,
};
