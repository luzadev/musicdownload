/**
 * PM2 ecosystem per il backend MusicTools.
 *
 * Avvio:    pm2 start ecosystem.config.cjs --env production
 * Reload:   pm2 reload musictools-api
 * Logs:     pm2 logs musictools-api
 * Save:     pm2 save && pm2 startup    (al primo deploy, una sola volta)
 */

module.exports = {
  apps: [
    {
      name: "musictools-api",
      script: "src/server.js",
      cwd: __dirname,
      exec_mode: "fork",       // 1 processo, basta per i nostri volumi
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      max_memory_restart: "256M",
      env: {
        NODE_ENV: "production",
      },
      // Le env sensibili stanno in .env: dotenv le carica al boot
      out_file: "logs/out.log",
      error_file: "logs/err.log",
      merge_logs: true,
      time: true,
    },
  ],
};
