/**
 * Applica i file SQL in migrations/ in ordine alfabetico.
 * Tiene traccia dei file gia eseguiti in una tabella `schema_migrations`.
 *
 * Run: npm run migrate
 */

import "dotenv/config";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pool, { query, exec } from "./db.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MIG_DIR = path.resolve(__dirname, "../migrations");

async function ensureMigrationsTable() {
  await exec(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      filename VARCHAR(255) NOT NULL PRIMARY KEY,
      applied_at BIGINT UNSIGNED NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
  `);
}

async function run() {
  await ensureMigrationsTable();
  const applied = new Set(
    (await query("SELECT filename FROM schema_migrations")).map((r) => r.filename),
  );

  const files = fs.readdirSync(MIG_DIR)
    .filter((f) => f.endsWith(".sql"))
    .sort();

  for (const f of files) {
    if (applied.has(f)) {
      console.log(`[migrate] skip ${f} (gia applicato)`);
      continue;
    }
    const sql = fs.readFileSync(path.join(MIG_DIR, f), "utf-8");
    console.log(`[migrate] applico ${f}`);
    // mysql2 supporta multipleStatements ma e' rischioso; splittiamo manualmente.
    const statements = sql
      .split(/;\s*\n/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && !s.startsWith("--"));
    for (const stmt of statements) {
      await exec(stmt);
    }
    await exec(
      "INSERT INTO schema_migrations (filename, applied_at) VALUES (?, ?)",
      [f, Math.floor(Date.now() / 1000)],
    );
    console.log(`[migrate] ok ${f}`);
  }

  await pool.end();
  console.log("[migrate] done");
}

run().catch((e) => {
  console.error("[migrate] errore:", e);
  process.exit(1);
});
