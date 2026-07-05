const mongoose = require('mongoose');

const UserStockTransactionSchema = new mongoose.Schema(
  {
    user_id: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'User',
      required: true
    },
    stock_id: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'DimStock',
      required: true
    },
    transaction_type: {
      type: String,
      enum: ['BUY', 'SELL'],
      required: true
    },
    trade_date: {
      type: Date,
      required: true
    },
    quantity: {
      type: Number,
      required: true,
      min: 1
    },
    price: {
      type: Number,
      required: true,
      min: 0
    },
    fee: {
      type: Number,
      required: true,
      default: 0,
      min: 0
    },
    tax: {
      type: Number,
      required: true,
      default: 0,
      min: 0
    },
    note: {
      type: String,
      trim: true,
      default: ''
    },
    source: {
      type: String,
      enum: ['MANUAL'],
      default: 'MANUAL',
      required: true
    },
    status: {
      type: String,
      enum: ['ACTIVE', 'VOIDED'],
      default: 'ACTIVE',
      required: true
    }
  },
  {
    timestamps: {
      createdAt: 'created_at',
      updatedAt: 'updated_at'
    },
    collection: 'userStockTransactions'
  }
);

UserStockTransactionSchema.index({ user_id: 1, stock_id: 1, trade_date: 1, created_at: 1 });
UserStockTransactionSchema.index({ user_id: 1, stock_id: 1, status: 1 });
UserStockTransactionSchema.index({ user_id: 1, transaction_type: 1 });

module.exports = mongoose.model('UserStockTransaction', UserStockTransactionSchema);
