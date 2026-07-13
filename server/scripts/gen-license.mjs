#!/usr/bin/env node
// Genera una licenza nel DB delle licenze MusicTools.
//
// Da eseguire SUL SERVER (musictools@musictools.djluza.com) dentro ~/api/:
//   node scripts/gen-license.mjs <email> [plan]
//
// plan: annual (default, "full" — no limite, no scadenza)
//       basic | pro | premium (con daily_limit e period_end mensile)
//
// Da locale, usare lo script wrapper: server/scripts/gen-license.sh

import { generateLicenseKey } from "../src/license.js";
import { getPlan } from "../src/plans.js";
import mysql from "mysql2/promise";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const envPath = path.resolve(__dirname, "..", ".env");
fs.readFileSync(envPath, "utf-8").split("\n").forEach((l) => {
  const m = l.match(/^([A-Z_]+)=(.*)$/);
  if (m) process.env[m[1]] = m[2];
});

const [, , emailArg, planArg] = process.argv;
if (!emailArg) {
  console.error("Uso: node scripts/gen-license.mjs <email> [plan]");
  console.error("plan: annual (default) | basic | pro | premium");
  process.exit(1);
}

const email = emailArg.trim().toLowerCase();
const planCode = (planArg || "annual").trim().toLowerCase();
const plan = getPlan(planCode);
if (!plan) {
  console.error(`Piano sconosciuto: ${planCode}`);
  console.error("Validi: annual, basic, pro, premium");
  process.exit(1);
}

const pool = mysql.createPool({
  host: "127.0.0.1",
  user: process.env.DB_USER,
  password: process.env.DB_PASS,
  database: process.env.DB_NAME,
});

const key = generateLicenseKey();
const now = Math.floor(Date.now() / 1000);

const isAnnual = planCode === "annual";
const dailyLimit = plan.dailyLimit ?? null;
const expiresAt = isAnnual ? null : null;
const periodEnd = isAnnual ? null : now + 30 * 24 * 3600;

await pool.execute(
  `INSERT INTO licenses
     (license_key, email, status, plan, daily_limit, source,
      subscription_id, current_period_end,
      expires_at, created_at, updated_at)
   VALUES (?, ?, 'active', ?, ?, 'manual', NULL, ?, ?, ?, ?)`,
  [key, email, planCode, dailyLimit, periodEnd, expiresAt, now, now],
);

console.log(JSON.stringify({
  key,
  email,
  plan: planCode,
  daily_limit: dailyLimit,
  expires_at: expiresAt,
  current_period_end: periodEnd,
}, null, 2));

await pool.end();
