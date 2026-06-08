import crypto from "node:crypto";
import { one, exec } from "./db.js";
import { signJwt, verifyJwt } from "./jwt.js";

const MAX_ACTIVATIONS = Number(process.env.MAX_ACTIVATIONS || 3);
const TOKEN_TTL_DAYS = Number(process.env.TOKEN_TTL_DAYS || 30);

const now = () => Math.floor(Date.now() / 1000);
const normEmail = (s) => String(s || "").trim().toLowerCase();
const normKey = (s) => String(s || "").trim().toUpperCase();

async function issueToken(license, deviceId) {
  const t = now();
  return signJwt({
    sub: String(license.id),
    key_id: license.license_key,
    email: license.email,
    device_id: deviceId,
    iat: t,
    exp: t + TOKEN_TTL_DAYS * 86400,
  }, process.env.JWT_SECRET);
}

export async function activate(req, res) {
  const { key, email, device_id, device_name, app_version } = req.body || {};
  const K = normKey(key), E = normEmail(email);
  const D = String(device_id || "").trim();
  if (!K || !E || !D) {
    return res.status(400).json({ error: "Missing key, email or device_id" });
  }

  const license = await one(
    "SELECT id, license_key, email, status FROM licenses WHERE license_key=? AND email=? LIMIT 1",
    [K, E],
  );
  if (!license) {
    return res.status(404).json({ error: "Chiave o email non corrispondono a un acquisto." });
  }
  if (license.status !== "active") {
    return res.status(403).json({ error: "Licenza non piu' valida (rimborsata o revocata)." });
  }

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
  res.json({ token, activated_at: t, email: license.email });
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
    "SELECT id, license_key, email, status FROM licenses WHERE id=?",
    [claims.sub],
  );
  if (!license || license.status !== "active") {
    return res.status(401).json({ error: "Licenza non attiva" });
  }
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
  res.json({ token: fresh, email: license.email });
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

// Esposto per uso interno (es. webhook genera chiave nuova)
export function generateLicenseKey() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const buf = crypto.randomBytes(16);
  const chars = Array.from(buf, (b) => alphabet[b % alphabet.length]);
  return [chars.slice(0,4), chars.slice(4,8), chars.slice(8,12), chars.slice(12,16)]
    .map((g) => g.join("")).join("-");
}
