const User = require('../../database/models/user.model');
const SubscriptionTransaction = require('../../database/models/subscription-transaction.model');
const payosService = require('./payos.service');
const { SUBSCRIPTION_PRICE, SUBSCRIPTION_DURATION_DAYS } = require('../../config/plan.config');
const env = require('../../config/env.config');

/**
 * Create a payment request for subscription upgrade
 * @param {string} userId - User ID
 * @returns {Promise<Object>} - { checkoutUrl, orderCode, paymentLinkId, amount }
 */
const createPayment = async (userId) => {
    const user = await User.findById(userId);
    if (!user) {
        const error = new Error('User not found');
        error.statusCode = 404;
        throw error;
    }

    // Check if user is already PRO
    if (user.plan === 'PRO' && user.subscription_status === 'ACTIVE') {
        const error = new Error('User is already on PRO plan');
        error.statusCode = 400;
        throw error;
    }

    // Generate unique order code: seconds timestamp + userId hash + random (stays within MAX_SAFE_INTEGER)
    // Use last 6 digits of userId to avoid overflow while maintaining uniqueness
    const userIdHash = parseInt(userId.toString().slice(-6), 10) || 0;
    const orderCode = Math.floor(Date.now() / 1000) * 1000000 + userIdHash * 100 + Math.floor(Math.random() * 100);

    // Build items array (required by PayOS)
    const items = [
        {
            name: 'Gói PRO 30 ngày',
            quantity: 1,
            price: SUBSCRIPTION_PRICE
        }
    ];

    // Get URLs from env
    const returnUrl = env.PAYOS_RETURN_URL || 'http://localhost:3000/payment/success';
    const cancelUrl = env.PAYOS_CANCEL_URL || 'http://localhost:3000/payment/cancel';

    // Create payment request
    const paymentResult = await payosService.createPaymentRequest({
        orderCode,
        amount: SUBSCRIPTION_PRICE,
        description: 'Nâng cấp PRO',
        returnUrl,
        cancelUrl,
        items
    });

    // Save PayOS data on user document
    user.payos_order_code = orderCode;
    user.payos_payment_link_id = paymentResult.paymentLinkId;
    await user.save();

    return {
        checkoutUrl: paymentResult.checkoutUrl,
        orderCode: paymentResult.orderCode,
        paymentLinkId: paymentResult.paymentLinkId,
        amount: SUBSCRIPTION_PRICE
    };
};

/**
 * Handle PayOS webhook callback
 * @param {Object} webhookPayload - Verified webhook payload
 * @returns {Promise<Object>} - Updated user subscription info
 */
const handlePaymentWebhook = async (webhookPayload) => {
    const { orderCode, code } = webhookPayload;

    // Find user by order code
    const user = await User.findOne({ payos_order_code: orderCode });
    if (!user) {
        const error = new Error('User not found for this payment');
        error.statusCode = 404;
        throw error;
    }

    // Only process successful payments (PayOS data.code = "00", test payload uses status = "PAID")
    if (code !== '00' && webhookPayload.status !== 'PAID') {
        return {
            userId: user._id,
            plan: user.plan,
            subscriptionStatus: user.subscription_status
        };
    }

    // Calculate expiry date
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + SUBSCRIPTION_DURATION_DAYS);

    // Capture previous plan/expiry before updating
    const previousPlan = user.plan;
    const previousExpiresAt = user.subscription_expires_at;

    // Upgrade user
    user.plan = 'PRO';
    user.subscription_status = 'ACTIVE';
    user.subscription_expires_at = expiresAt;
    await user.save();

    // Record transaction
    await SubscriptionTransaction.create({
        user_id: user._id,
        transaction_type: 'PAYOS_PAYMENT',
        payos_order_code: orderCode,
        payos_payment_link_id: user.payos_payment_link_id,
        amount: SUBSCRIPTION_PRICE,
        status: 'PAID',
        previous_plan: previousPlan,
        new_plan: 'PRO',
        previous_expires_at: previousExpiresAt,
        new_expires_at: expiresAt,
        notes: 'PayOS payment completed'
    });

    return {
        userId: user._id,
        plan: user.plan,
        subscriptionStatus: user.subscription_status,
        subscriptionExpiresAt: user.subscription_expires_at
    };
};

/**
 * Get current subscription status for a user
 * @param {string} userId - User ID
 * @returns {Promise<Object>}
 */
const getSubscriptionStatus = async (userId) => {
    const user = await User.findById(userId);
    if (!user) {
        const error = new Error('User not found');
        error.statusCode = 404;
        throw error;
    }

    return {
        plan: user.plan || 'FREE',
        subscriptionStatus: user.subscription_status || 'NONE',
        subscriptionExpiresAt: user.subscription_expires_at || null
    };
};

/**
 * Get transaction history for the current user
 * @param {string} userId - User ID
 * @param {Object} queries - { page, limit }
 * @returns {Promise<Object>} - { items, pagination }
 */
const getMyTransactions = async (userId, queries) => {
    const page = parseInt(queries.page || '1', 10);
    const limit = parseInt(queries.limit || '20', 10);
    const skip = (page - 1) * limit;

    const filter = { user_id: userId };

    const items = await SubscriptionTransaction.find(filter)
        .sort({ created_at: -1 })
        .skip(skip)
        .limit(limit);

    const total_items = await SubscriptionTransaction.countDocuments(filter);
    const total_pages = Math.ceil(total_items / limit);

    return {
        items: items.map(t => ({
            id: t._id.toString(),
            type: t.transaction_type,
            amount: t.amount,
            status: t.status,
            notes: t.notes,
            created_at: t.created_at
        })),
        pagination: { page, limit, total_items, total_pages }
    };
};

module.exports = {
    createPayment,
    handlePaymentWebhook,
    getSubscriptionStatus,
    getMyTransactions
};