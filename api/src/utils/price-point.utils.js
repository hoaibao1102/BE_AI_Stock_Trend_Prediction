/**
 * Shared helpers for normalizing market price rows into chart points.
 * Used by holdings and portfolio modules for consistent 7D sparklines.
 */

const formatTimeId = (timeId) => {
  const raw = String(timeId ?? '');
  if (raw.length !== 8) return raw || null;
  return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
};

const toNumber = (value) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (value == null) return null;
  if (typeof value === 'object' && value != null && typeof value.toString === 'function') {
    const parsed = Number(value.toString());
    return Number.isFinite(parsed) ? parsed : null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const buildPricePoint = (price) => ({
  date: formatTimeId(price.time_id ?? price.date),
  open: toNumber(price.open_price ?? price.open),
  high: toNumber(price.high_price ?? price.high),
  low: toNumber(price.low_price ?? price.low),
  close: toNumber(price.close_price ?? price.close),
  volume: toNumber(price.volume),
  pe: toNumber(price.pe),
  pb: toNumber(price.pb),
  roe: toNumber(price.roe)
});

const normalizePrices7d = (prices = []) => {
  if (!Array.isArray(prices)) return [];

  const normalized = prices
    .map((price) => buildPricePoint(price))
    .filter((point) => point.close != null);

  if (normalized.length === 1) {
    return [normalized[0], { ...normalized[0] }];
  }

  return normalized;
};

module.exports = {
  formatTimeId,
  toNumber,
  buildPricePoint,
  normalizePrices7d
};
