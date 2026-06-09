import crypto from "node:crypto";
import { one, exec } from "./db.js";
import { signJwt, verifyJwt } from "./jwt.js";
import { getPlan, planSnapshot } from "./plans.js";

const MAX_ACTIVATIONS = Number(process.env.MAX_ACTIVATIONS || 3);
const TOKEN_TTL_DAYS = Number(process.env.TOKEN_TTL_DAYS || 30);

const now = () => Math.floor(Date.now() / 1000);
const normEmail = (s) => String(s || "").trim().toLowerCase();
const normKey = (s) => String(s || "").trim().toUpperCase();

/**
 * Verifica che una licenza sia ancora "utilizzabile" oggi.
 * Ritorna { ok: true } oppure { ok: false, error: "..." }.
 *
 * Casi gestiti:
 *  - annual one-time scaduto (expires_at < now)
 *  - subscription scaduta (current_period_end < now)
 */
function checkLicenseValidity(license, t = now()) {
  if (license.status !== "active") {
    return { ok: false, error: "Licenza non piu' valida (rimborsata o revocata)." };
  }
  if (license.expires_at && Number(license.expires_at) < t) {
    return { ok: false, error: "L'abbonamento annuale e' scaduto. Riacquista per continuare." };
  }
  if (license.current_period_end && Number(license.current_period_end) < t) {
    return { ok: false, error: "L'abbonamento e' scaduto o e' fallito il rinnovo. Verifica su Lemon Squeezy." };
  }
  return { ok: true };
}

async function issueToken(license, deviceId) {
  const t = now();
  const plan = planSnapshot(license.plan);
  const claims = {
    sub: String(license.id),
    key_id: license.license_key,
    email: license.email,
    device_id: deviceId,
    iat: t,
    exp: t + TOKEN_TTL_DAYS * 86400,
  };
  if (plan) {
    claims.plan = plan.code;
    claims.plan_name = plan.name;
    claims.daily_limit = plan.daily_limit;
    claims.features = plan.features;
    claims.is_subscription = plan.is_subscription;
  }
  if (license.expires_at) claims.expires_at = Number(license.expires_at);
  if (license.current_period_end) claims.period_end = Number(license.current_period_end);
  return signJwt(claims, process.env.JWT_SECRET);
}

const LICENSE_COLUMNS =
  "id, license_key, email, status, plan, daily_limit, " +
  "subscription_id, current_period_end, expires_at";

export async function activate(req, res) {
  const { key, email, device_id, device_name, app_version } = req.body || {};
  const K = normKey(key), E = normEmail(email);
  const D = String(device_id || "").trim();
  if (!K || !E || !D) {
    return res.status(400).json({ error: "Missing key, email or device_id" });
  }

  const license = await one(
    `SELECT ${LICENSE_COLUMNS} FROM licenses
      WHERE license_key=? AND email=? LIMIT 1`,
    [K, E],
  );
  if (!license) {
    return res.status(404).json({ error: "Chiave o email non corrispondono a un acquisto." });
  }
  const check = checkLicenseValidity(license);
  if (!check.ok) return res.status(403).json({ error: check.error });

  const t = now();
  const existing = await one(
    "SELECT id FROM activations WHERE license_id=? AND device_id=? LIMIT 1",
    [license.id, D],
  );

  if (existing) {
    await exec(
      `UPDATE activations SET app_version=?, device_name=?, last_seen_at=?, revoked_at=NULL
       WHERE id=?`,
      [app_version || null, device_name || null, t, existing.id],
    );
  } else {
    const row = await one(
      "SELECT COUNT(*) AS n FROM activations WHERE license_id=? AND revoked_at IS NULL",
      [license.id],
    );
    if ((row?.n || 0) >= MAX_ACTIVATIONS) {
      return res.status(409).json({
        error: `Hai gia attivato la licenza su ${MAX_ACTIVATIONS} dispositivi. Disattivane uno per usarla qui.`,
      });
    }
    await exec(
      `INSERT INTO activations
        (license_id, device_id, device_name, app_version, activated_at, last_seen_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [license.id, D, device_name || null, app_version || null, t, t],
    );
  }

  const token = await issueToken(license, D);
  const plan = planSnapshot(license.plan);
  res.json({
    token,
    activated_at: t,
    email: license.email,
    plan,
    expires_at: license.expires_at ? Number(license.expires_at) : null,
    period_end: license.current_period_end ? Number(license.current_period_end) : null,
  });
}

export async function validate(req, res) {
  const { token, device_id, app_version } = req.body || {};
  const T = String(token || "").trim();
  const D = String(device_id || "").trim();
  if (!T || !D) return res.status(400).json({ error: "Missing token or device_id" });

  const claims = verifyJwt(T, process.env.JWT_SECRET);
  if (!claims) return res.status(401).json({ error: "Token invalido o scaduto" });
  if (claims.device_id !== D) return res.status(401).json({ error: "device_id mismatch" });

  const license = await one(
    `SELECT ${LICENSE_COLUMNS} FROM licenses WHERE id=?`,
    [claims.sub],
  );
  if (!license) return res.status(401).json({ error: "Licenza non trovata" });

  const check = checkLicenseValidity(license);
  if (!check.ok) return res.status(401).json({ error: check.error });

  const act = await one(
    "SELECT id, revoked_at FROM activations WHERE license_id=? AND device_id=?",
    [license.id, D],
  );
  if (!act || act.revoked_at !== null) {
    return res.status(401).json({ error: "Attivazione non trovata o revocata" });
  }

  await exec(
    "UPDATE activations SET last_seen_at=?, app_version=? WHERE id=?",
    [now(), app_version || null, act.id],
  );

  const fresh = await issueToken(license, D);
  const plan = planSnapshot(license.plan);
  res.json({
    token: fresh,
    email: license.email,
    plan,
    expires_at: license.expires_at ? Number(license.expires_at) : null,
    period_end: license.current_period_end ? Number(license.current_period_end) : null,
  });
}

export async function deactivate(req, res) {
  const { token, device_id } = req.body || {};
  const T = String(token || "").trim();
  const D = String(device_id || "").trim();
  if (!T || !D) return res.status(400).json({ error: "Missing token or device_id" });

  const claims = verifyJwt(T, process.env.JWT_SECRET);
  if (!claims) return res.status(401).json({ error: "Token invalido" });
  if (claims.device_id !== D) return res.status(401).json({ error: "device_id mismatch" });

  await exec(
    `UPDATE activations SET revoked_at=?
     WHERE license_id=? AND device_id=? AND revoked_at IS NULL`,
    [now(), claims.sub, D],
  );
  res.json({ ok: true });
}

/**
 * Helper interno: dato un token JWT valido, ritorna la riga licenze
 * fresca dal DB (per quota checks, downloads, ecc.). Ritorna null se
 * il token e' invalido o la licenza non e' piu' attiva.
 */
export async function licenseFromToken(token) {
  const claims = verifyJwt(String(token || ""), process.env.JWT_SECRET);
  if (!claims) return null;
  const lic = await one(
    `SELECT ${LICENSE_COLUMNS} FROM licenses WHERE id=?`,
    [claims.sub],
  );
  if (!lic) return null;
  const check = checkLicenseValidity(lic);
  if (!check.ok) return null;
  return { license: lic, claims };
}

// Esposto per uso interno (es. webhook genera chiave nuova)
export function generateLicenseKey() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const buf = crypto.randomBytes(16);
  const chars = Array.from(buf, (b) => alphabet[b % alphabet.length]);
  return [chars.slice(0,4), chars.slice(4,8), chars.slice(8,12), chars.slice(12,16)]
    .map((g) => g.join("")).join("-");
}
