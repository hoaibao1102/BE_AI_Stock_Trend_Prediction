const cron = require('node-cron');
const User = require('../database/models/user.model');
const UserStockHolding = require('../database/models/user-stock-holding.model');
const portfolioService = require('../modules/portfolio/portfolio.service');
const { generateAccessToken } = require('../common/utils/jwt.util');

const SCHEDULE = '0 7 * * *'; // Run at 07:00 every day

const preheatPortfolioAnalysis = async () => {
  console.log('[PortfolioAnalysisScheduler] Starting daily portfolio pre-analysis...');

  try {
    // 1. Find all user IDs with active stock holdings
    const activeUserIds = await UserStockHolding.distinct('user_id', { status: 'ACTIVE' });
    if (activeUserIds.length === 0) {
      console.log('[PortfolioAnalysisScheduler] No users with active holdings found.');
      return;
    }

    console.log(`[PortfolioAnalysisScheduler] Found ${activeUserIds.length} users with active holdings.`);

    // 2. Fetch User documents
    const users = await User.find({ _id: { $in: activeUserIds } }).lean();

    const analyseBaseUrl = process.env.ANALYSE_BASE_URL || process.env.ANALYSE_API_BASE_URL || 'http://localhost:5100';
    const adviceUrl = `${analyseBaseUrl.replace(/\/$/, '')}/api/ai-reports/holdings-advice`;

    // 3. Process each user
    for (const user of users) {
      try {
        console.log(`[PortfolioAnalysisScheduler] Prefetching advice for user: ${user.email} (${user._id})`);

        // Compute current P&L metrics
        const pnlData = await portfolioService.getPortfolioPnl(user._id);
        if (!pnlData.items || pnlData.items.length === 0) {
          console.log(`[PortfolioAnalysisScheduler] No holdings items for user ${user.email}, skipping.`);
          continue;
        }

        // Map items to Python service request format
        const items = pnlData.items.map(item => ({
          symbol: item.symbol,
          exchange: item.exchange || 'HOSE',
          company_name: item.company_name,
          average_cost: item.average_cost || 0,
          quantity: item.quantity || 1,
          close_price: item.close_price,
          market_value: item.market_value,
          cost: item.cost,
          allocation_pct: item.allocation_pct,
          unrealized_pnl: item.unrealized_pnl,
          unrealized_pnl_pct: item.unrealized_pnl_pct,
          status: item.status
        }));

        // Map summary
        const portfolioSummary = pnlData.portfolio_summary ? {
          totalCost: pnlData.portfolio_summary.total_cost,
          totalMarketValue: pnlData.portfolio_summary.total_market_value,
          totalUnrealizedPnl: pnlData.portfolio_summary.total_unrealized_pnl,
          totalUnrealizedPnlPct: pnlData.portfolio_summary.total_unrealized_pnl_pct,
          positionCount: pnlData.portfolio_summary.position_count,
          countProfit: pnlData.portfolio_summary.count_profit,
          countLoss: pnlData.portfolio_summary.count_loss
        } : undefined;

        // Generate JWT token for this user to authorize the request
        const token = generateAccessToken(user);

        // Call the holdings-advice endpoint with forceRefresh: true to trigger fresh LLM run and update daily advice cache
        const response = await fetch(adviceUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'application/json',
            Authorization: `Bearer ${token}`
          },
          body: JSON.stringify({
            items,
            portfolioSummary,
            forceRefresh: true
          }),
          // Timeout signal
          signal: AbortSignal.timeout(180000) // 3 minutes timeout for LLM generation
        });

        const resData = await response.json();

        if (response.ok && resData.success) {
          const stats = resData.data || {};
          console.log(`[PortfolioAnalysisScheduler] Successfully prefetched advice for user ${user.email}. (Total: ${stats.total_items}, Cached: ${stats.cached_count}, Generated: ${stats.generated_count})`);
        } else {
          console.error(`[PortfolioAnalysisScheduler] Failed to prefetch advice for user ${user.email}:`, resData.message || 'Unknown error');
        }
      } catch (userErr) {
        console.error(`[PortfolioAnalysisScheduler] Error prefetching for user ${user.email}:`, userErr.message);
      }
    }
  } catch (err) {
    console.error('[PortfolioAnalysisScheduler] Critical scheduler error:', err.message);
  }

  console.log('[PortfolioAnalysisScheduler] Daily portfolio pre-analysis completed.');
};

const start = () => {
  console.log(`[PortfolioAnalysisScheduler] Scheduler started — ${SCHEDULE}`);
  cron.schedule(SCHEDULE, () => {
    preheatPortfolioAnalysis().catch(err => console.error('[PortfolioAnalysisScheduler] Cron job error:', err.message));
  });
};

module.exports = {
  start,
  preheatPortfolioAnalysis
};
