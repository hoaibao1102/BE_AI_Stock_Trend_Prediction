const app = require('./app');
const appConfig = require('./config/app.config');
const env = require('./config/env.config');
const connectDB = require('./config/database.config');
const seedRolesAndUsers = require('./database/seeds/seed-roles');
const seedDataSources = require('./database/seeds/seed-data-sources');
const { startAllSchedulers } = require('./scheduler');

const startServer = async () => {
  try {
    // 1. Connect to Database
    await connectDB();

    // 2. Auto-run Role/User Seeding on Startup
    console.log('[Server] Verifying default roles and user accounts...');
    await seedRolesAndUsers();

    // 3. Auto-run Data Sources Seeding
    console.log('[Server] Verifying default data sources...');
    await seedDataSources();

    // 3. Start Schedulers (alert checker, etc.)
    console.log('[Server] Starting background schedulers...');
    startAllSchedulers();

    // 4. Start Listening
    const server = app.listen(appConfig.port, () => {
      console.log(`[Server] API server running on port ${appConfig.port} in [${appConfig.env}] mode`);
      if (env.GOOGLE_CLIENT_ID && env.GOOGLE_CLIENT_SECRET) {
        console.log(
          `[Server] Google OAuth: add this EXACT string to Google Cloud → Credentials → Authorized redirect URIs:\n` +
          `       ${env.GOOGLE_CALLBACK_URL}`
        );
      }
    });

    // 4. Graceful Shutdown
    const exitHandler = () => {
      if (server) {
        server.close(() => {
          console.log('[Server] HTTP server closed.');
          process.exit(0);
        });
      } else {
        process.exit(0);
      }
    };

    process.on('SIGTERM', () => {
      console.info('[Server] SIGTERM signal received. Initiating graceful shutdown...');
      exitHandler();
    });

    process.on('SIGINT', () => {
      console.info('[Server] SIGINT signal received. Initiating graceful shutdown...');
      exitHandler();
    });

  } catch (error) {
    console.error(`[Server] Critical failure during startup: ${error.message}`);
    process.exit(1);
  }
};

startServer();
