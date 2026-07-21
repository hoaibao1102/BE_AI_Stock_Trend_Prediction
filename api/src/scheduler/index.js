const alertChecker = require('./alert-checker.scheduler');
const portfolioAnalysis = require('./portfolio-analysis.scheduler');

const startAllSchedulers = () => {
  alertChecker.start();
  portfolioAnalysis.start();
};

const stopAllSchedulers = () => {
  // node-cron tasks are stopped via destroy() if needed
  console.log('[Scheduler] All schedulers stopped');
};

module.exports = {
  startAllSchedulers,
  stopAllSchedulers
};
