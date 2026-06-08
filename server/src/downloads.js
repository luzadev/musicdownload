/**
 * Endpoint "1-click download" per i clienti.
 *
 * URL: GET /api/download/:platform?key=XXXX&email=YYY
 *
 * Verifica la coppia (key, email) contro la tabella licenses, recupera
 * l'ultima release attiva per la piattaforma, genera un signed URL e
 * fa redirect 302. Il link nell'email viene cliccato dall'utente: con
 * un click parte il download.
 *
 * Sicurezza:
 *  - Niente token sulla URL: la chiave e' gia "il segreto"
 *  - URL signed con scadenza breve (default 5 min)
 *  - Nessuna info di licenza leakata in risposta (ritorna solo redirect o 401/404)
 */

import crypto from "node:crypto";
import { one } from "./db.js";

const DOWNLOAD_TTL = Number(process.env.DOWNLOAD_URL_TTL_SECONDS || 300);
const PUBLIC_BASE = process.env.PUBLIC_BASE_URL || "https://musictools.djluza.com";

function signPayload(payload, secret) {
  return crypto.createHmac("sha256", secret).update(payload).digest("base64url");
}

const normEmail = (s) => String(s || "").trim().toLowerCase();
const normKey = (s) => String(s || "").trim().toUpperCase();

export async function downloadByKey(req, res) {
  const platform = String(req.params.platform || "").toLowerCase();
  if (platform !== "macos" && platform !== "windows") {
    return res.status(400).type("text/plain")
      .send("Piattaforma non valida. Usa /api/download/macos o /api/download/windows.");
  }

  const key = normKey(req.query.key);
  const email = normEmail(req.query.email);
  if (!key || !email) {
    return res.status(400).type("text/plain")
      .send("Mancano email o chiave. Controlla il link nella tua email di acquisto.");
  }

  const license = await one(
    "SELECT id, status FROM licenses WHERE license_key=? AND email=? LIMIT 1",
    [key, email],
  );
  if (!license) {
    return res.status(401).type("text/plain")
      .send("Email o chiave non valide. Verifica il link nell'email o scrivici a info@djluza.com.");
  }
  if (license.status !== "active") {
    return res.status(403).type("text/plain")
      .send("Licenza non piu' attiva (rimborsata o revocata).");
  }

  const release = await one(
    `SELECT file_path FROM releases
     WHERE platform=? ORDER BY published_at DESC LIMIT 1`,
    [platform],
  );
  if (!release) {
    return res.status(503).type("text/plain")
      .send(`Build ${platform} non ancora disponibile. Riprova fra qualche ora o scrivici a info@djluza.com.`);
  }

  const exp = Math.floor(Date.now() / 1000) + DOWNLOAD_TTL;
  const sig = signPayload(`${release.file_path}.${exp}`, process.env.JWT_SECRET);
  const url = `${PUBLIC_BASE}/api/download?file=${encodeURIComponent(release.file_path)}&exp=${exp}&sig=${sig}`;
  res.redirect(302, url);
}
