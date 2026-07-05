const mongoose = require('mongoose');

const UserStockHoldingSchema = new mongoose.Schema(
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
    average_cost: {
      type: Number,
      required: true,
      min: 0
    },
    quantity: {
      type: Number,
      required: true,
      min: 1
    },
    holding_date: {
      type: Date,
      required: true
    },
    note: {
      type: String,
      trim: true,
      default: ''
    },
    status: {
      type: String,
      enum: ['ACTIVE', 'REMOVED'],
      default: 'ACTIVE',
      required: true
    },
    removed_at: {
      type: Date,
      default: null
    }
  },
  {
    timestamps: {
      createdAt: 'created_at',
      updatedAt: 'updated_at'
    },
    collection: 'userStockHoldings'
  }
);

UserStockHoldingSchema.index({ user_id: 1, stock_id: 1 }, { unique: true });
UserStockHoldingSchema.index({ user_id: 1, status: 1 });

module.exports = mongoose.model('UserStockHolding', UserStockHoldingSchema);
