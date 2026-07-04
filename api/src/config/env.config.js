const path = require('path');
const dotenv = require('dotenv');

// Load env files
// Check services/.env (which is 1 level above api: services/api/src/config/../../.env)
dotenv.config({ path: path.resolve(__dirname, '../../.env'), override: true });
// Fallback to standard dotenv load
dotenv.config({ override: true });

const parseCorsOrigins = () => {
  const raw = process.env.CORS_ORIGINS;
  if (!raw || !String(raw).trim()) return null;
  return String(raw)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
};

/** Trim .env values — trailing spaces in GOOGLE_CALLBACK_URL cause redirect_uri_mismatch. */
const trimStr = (v, fallback = '') => {
  if (v == null || v === '') return fallback;
  return String(v).trim();
};

const env = {
  NODE_ENV: process.env.NODE_ENV || 'development',
  PORT: parseInt(process.env.PORT || '5000', 10),
  MONGODB_URI: process.env.MONGODB_URI || 'mongodb://localhost:27017/aistock',
  JWT_ACCESS_SECRET: process.env.JWT_ACCESS_SECRET || 'default_access_secret_key_1234567890',
  JWT_REFRESH_SECRET: process.env.JWT_REFRESH_SECRET || 'default_refresh_secret_key_1234567890',
  JWT_ACCESS_EXPIRES_IN: process.env.JWT_ACCESS_EXPIRES_IN || '15m',
  JWT_REFRESH_EXPIRES_IN: process.env.JWT_REFRESH_EXPIRES_IN || '7d',
  BCRYPT_SALT_ROUNDS: parseInt(process.env.BCRYPT_SALT_ROUNDS || '10', 10),
  CORS_ORIGINS: parseCorsOrigins(),
  SESSION_SECRET: process.env.SESSION_SECRET || 'dev_session_secret_change_me',
  GOOGLE_CLIENT_ID: trimStr(process.env.GOOGLE_CLIENT_ID, ''),
  GOOGLE_CLIENT_SECRET: trimStr(process.env.GOOGLE_CLIENT_SECRET, ''),
  GOOGLE_CALLBACK_URL:
    trimStr(process.env.GOOGLE_CALLBACK_URL) ||
    'http://localhost:5000/api/auth/google/callback',
  /** Frontend URL to receive ?code= after Google login (exchange via POST /oauth/exchange). */
  GOOGLE_OAUTH_SUCCESS_REDIRECT:
    trimStr(process.env.GOOGLE_OAUTH_SUCCESS_REDIRECT) || 'http://localhost:3000',
  GOOGLE_OAUTH_FAILURE_REDIRECT: trimStr(process.env.GOOGLE_OAUTH_FAILURE_REDIRECT, ''),
  // PayOS Configuration
  PAYOS_CLIENT_ID: trimStr(process.env.PAYOS_CLIENT_ID, ''),
  PAYOS_API_KEY: trimStr(process.env.PAYOS_API_KEY, ''),
  PAYOS_CHECKSUM_KEY: trimStr(process.env.PAYOS_CHECKSUM_KEY, ''),
  PAYOS_RETURN_URL: trimStr(process.env.PAYOS_RETURN_URL, ''),
  PAYOS_CANCEL_URL: trimStr(process.env.PAYOS_CANCEL_URL, ''),
  PAYOS_PRO_PRICE: parseInt(process.env.PAYOS_PRO_PRICE || '50000', 10),

  // Email (SMTP)
  SMTP_HOST: trimStr(process.env.SMTP_HOST, ''),
  SMTP_PORT: parseInt(process.env.SMTP_PORT || '587', 10),
  SMTP_USER: trimStr(process.env.SMTP_USER, ''),
  SMTP_PASS: trimStr(process.env.SMTP_PASS, ''),
  EMAIL_FROM: trimStr(process.env.EMAIL_FROM, 'noreply@aistocktrend.com')
};


module.exports = env;
