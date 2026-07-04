const mongoose = require('mongoose');

const AlertSchema = new mongoose.Schema(
  {
    user_id: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'User',
      required: true,
      index: true,
    },
    stock_id: {
      type: mongoose.Schema.Types.ObjectId,
      ref: 'DimStock',
      required: true,
      index: true,
    },
    alert_type: {
      type: String,
      enum: ['PRICE_ABOVE', 'PRICE_BELOW', 'VOLUME_SPIKE'],
      required: true,
    },
    threshold: {
      type: Number,
      required: true,
    },
    status: {
      type: String,
      enum: ['ACTIVE', 'TRIGGERED', 'DISABLED'],
      default: 'ACTIVE',
    },
    triggered_at: {
      type: Date,
      default: null,
    },
    triggered_value: {
      type: Number,
      default: null,
    },
  },
  {
    timestamps: {
      createdAt: 'created_at',
      updatedAt: 'updated_at',
    },
    collection: 'alerts',
  }
);

AlertSchema.index({ user_id: 1, status: 1 });
AlertSchema.index({ stock_id: 1, status: 1 });

module.exports = mongoose.model('Alert', AlertSchema);
