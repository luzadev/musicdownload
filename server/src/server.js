import "dotenv/config";
import express from "express";

import * as license from "./license.js";
import * as updates from "./updates.js";
import * as ls from "./lemonsqueezy.js";

const app = express();

// L'app sta dietro Apache reverse proxy: fidati di X-Forwarded-* dal localhost.
app.set("trust proxy", "loopback");
app.disable("x-powered-by");

// CORS minimale (solo per /api/*)
app.use("/api", (req, res, next) => {
  res.set("Access-Control-Allow-Origin", "*");
  res.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.set("Access-Control-Allow-Headers", "Content-Type,Authorization");
  if (req.method === "OPTIONS") return res.status(204).end();
  next();
});

// Health check (no body parser necessario)
app.get("/api/health", (_req, res) => {
  res.json({ ok: true, version: process.env.LATEST_VERSION || "" });
});

// WEBHOOK Lemon Squeezy: deve ricevere il body RAW per verificare la firma.
// Va registrato PRIMA del json parser globale.
app.post(
  "/api/webhook/lemonsqueezy",
  express.raw({ type: "application/json", limit: "1mb" }),
  ls.webhook,
);

// JSON parser per tutti gli altri endpoint
app.use(express.json({ limit: "128kb" }));

// Licenze
app.post("/api/license/activate",   license.activate);
app.post("/api/license/validate",   license.validate);
app.post("/api/license/deactivate", license.deactivate);

// Aggiornamenti + download firmato
app.get("/api/latest",   updates.latest);
app.get("/api/download", updates.download);

// 404 JSON solo per /api/*
app.use("/api", (_req, res) => res.status(404).json({ error: "Not found" }));

// Error handler
app.use((err, _req, res, _next) => {
  console.error("[unhandled]", err);
  if (res.headersSent) return;
  res.status(500).json({ error: "Internal error" });
});

const PORT = Number(process.env.PORT || 4002);
const HOST = process.env.HOST || "127.0.0.1";
app.listen(PORT, HOST, () => {
  console.log(`[musictools-api] listening on ${HOST}:${PORT}`);
});
