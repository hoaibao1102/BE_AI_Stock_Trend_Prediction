const nodemailer = require('nodemailer');
const env = require('../config/env.config');

const isConfigured = () => !!(env.SMTP_HOST && env.SMTP_USER && env.SMTP_PASS);

let transporter = null;

const initTransporter = () => {
  if (!isConfigured()) {
    console.warn('[Email] SMTP not configured — email sending disabled');
    return null;
  }
  transporter = nodemailer.createTransport({
    host: env.SMTP_HOST,
    port: env.SMTP_PORT,
    secure: env.SMTP_PORT === 465,
    auth: {
      user: env.SMTP_USER,
      pass: env.SMTP_PASS
    }
  });
  return transporter;
};

const sendAlertEmail = async (to, subject, html) => {
  if (!transporter) {
    console.warn(`[Email] Skipping send — SMTP not configured. Would send to ${to}: ${subject}`);
    return;
  }

  try {
    const info = await transporter.sendMail({
      from: env.EMAIL_FROM,
      to,
      subject,
      html
    });
    console.log(`[Email] Alert sent to ${to}: ${info.messageId}`);
  } catch (err) {
    console.error(`[Email] Failed to send to ${to}: ${err.message}`);
  }
};

const buildPriceAlertHtml = (userName, symbol, companyName, alertType, threshold, currentPrice) => {
  const direction = alertType === 'PRICE_ABOVE' ? 'above' : 'below';
  return `
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background: #f9fafb; border-radius: 8px;">
      <h2 style="color: #1f2937;">Price Alert Triggered</h2>
      <p style="color: #374151;">Hi ${userName},</p>
      <p style="color: #374151;">Your alert for <strong>${symbol}</strong> (${companyName}) has been triggered:</p>
      <table style="width: 100%; border-collapse: collapse; margin: 16px 0; background: white; border-radius: 6px; overflow: hidden;">
        <tr>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; color: #6b7280;">Alert Type</td>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; font-weight: 600;">Price ${direction.toUpperCase()} ${threshold.toLocaleString()} VND</td>
        </tr>
        <tr>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; color: #6b7280;">Current Price</td>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; font-weight: 600;">${currentPrice.toLocaleString()} VND</td>
        </tr>
        <tr>
          <td style="padding: 10px 16px; color: #6b7280;">Stock</td>
          <td style="padding: 10px 16px; font-weight: 600;">${symbol} — ${companyName}</td>
        </tr>
      </table>
      <p style="color: #9ca3af; font-size: 12px;">This is a one-time alert. Re-enable it in your Alerts settings.</p>
    </div>
  `;
};

const buildVolumeAlertHtml = (userName, symbol, companyName, threshold, currentVolume, avgVolume) => {
  return `
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background: #f9fafb; border-radius: 8px;">
      <h2 style="color: #1f2937;">Volume Spike Alert Triggered</h2>
      <p style="color: #374151;">Hi ${userName},</p>
      <p style="color: #374151;">Your volume alert for <strong>${symbol}</strong> (${companyName}) has been triggered:</p>
      <table style="width: 100%; border-collapse: collapse; margin: 16px 0; background: white; border-radius: 6px; overflow: hidden;">
        <tr>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; color: #6b7280;">Alert Type</td>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; font-weight: 600;">Volume Spike (≥ ${threshold}x average)</td>
        </tr>
        <tr>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; color: #6b7280;">Current Volume</td>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; font-weight: 600;">${currentVolume.toLocaleString()}</td>
        </tr>
        <tr>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; color: #6b7280;">Average Volume (20-day)</td>
          <td style="padding: 10px 16px; border-bottom: 1px solid #e5e7eb; font-weight: 600;">${avgVolume.toLocaleString()}</td>
        </tr>
        <tr>
          <td style="padding: 10px 16px; color: #6b7280;">Stock</td>
          <td style="padding: 10px 16px; font-weight: 600;">${symbol} — ${companyName}</td>
        </tr>
      </table>
      <p style="color: #9ca3af; font-size: 12px;">This is a one-time alert. Re-enable it in your Alerts settings.</p>
    </div>
  `;
};

module.exports = {
  initTransporter,
  sendAlertEmail,
  buildPriceAlertHtml,
  buildVolumeAlertHtml
};
