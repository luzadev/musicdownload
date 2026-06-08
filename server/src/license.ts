import { json, badRequest, unauthorized, readJson, now } from "./http";
import { signJwt, verifyJwt } from "./jwt";
import type { Env } from "./worker";

interface LicenseRow {
  id: number;
  license_key: string;
  email: string;
  status: string;
}

interface ActivationRow {
  id: number;
  license_id: number;
  device_id: string;
  device_name: string | null;
  app_version: string | null;
  activated_at: number;
  last_seen_at: number;
  revoked_at: number | null;
}

function normalizeEmail(s: string): string {
  return (s || "").trim().toLowerCase();
}

function normalizeKey(s: string): string {
  return (s || "").trim().toUpperCase();
}

async function getLicense(env: Env, key: string, email: string): Promise<LicenseRow | null> {
  const stmt = env.DB.prepare(
    `SELECT id, license_key, email, status FROM licenses
     WHERE license_key = ?1 AND email = ?2 LIMIT 1`
  ).bind(key, email);
  return await stmt.first<LicenseRow>();
}

async function countActiveActivations(env: Env, licenseId: number): Promise<number> {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS n FROM activations
     WHERE license_id = ?1 AND revoked_at IS NULL`
  ).bind(licenseId).first<{ n: number }>();
  return row?.n ?? 0;
}

async function findActivation(env: Env, licenseId: number, deviceId: string): Promise<ActivationRow | null> {
  return await env.DB.prepare(
    `SELECT * FROM activations
     WHERE license_id = ?1 AND device_id = ?2 LIMIT 1`
  ).bind(licenseId, deviceId).first<ActivationRow>();
}

async function issueToken(env: Env, license: LicenseRow, deviceId: string): Promise<string> {
  const ttlDays = parseInt(env.TOKEN_TTL_DAYS || "30", 10);
  const t = now();
  return signJwt({
    sub: String(license.id),
    key_id: license.license_key,
    email: license.email,
    device_id: deviceId,
    iat: t,
    exp: t + ttlDays * 86400,
  }, env.JWT_SECRET);
}

// ============================================================
// POST /api/license/activate
// ============================================================
export async function handleActivate(req: Request, env: Env): Promise<Response> {
  const body = await readJson<{
    key?: string; email?: string; device_id?: string;
    device_name?: string; app_version?: string;
  }>(req);

  const key = normalizeKey(body.key || "");
  const email = normalizeEmail(body.email || "");
  const deviceId = (body.device_id || "").trim();
  if (!key || !email || !deviceId) {
    return badRequest("Missing key, email or device_id");
  }

  const license = await getLicense(env, key, email);
  if (!license) {
    return json({ error: "Chiave o email non corrispondono a un acquisto." }, 404);
  }
  if (license.status !== "active") {
    return json({ error: "Licenza non piu' valida (rimborsata o revocata)." }, 403);
  }

  const max = parseInt(env.MAX_ACTIVATIONS || "3", 10);
  const t = now();

  const existing = await findActivation(env, license.id, deviceId);
  if (existing) {
    // Re-attivazione sullo stesso device: aggiorna last_seen.
    await env.DB.prepare(
      `UPDATE activations
       SET app_version=?1, device_name=?2, last_seen_at=?3, revoked_at=NULL
       WHERE id=?4`
    ).bind(body.app_version || null, body.device_name || null, t, existing.id).run();
  } else {
    const active = await countActiveActivations(env, license.id);
    if (active >= max) {
      return json({
        error: `Hai gia attivato la licenza su ${max} dispositivi. Disattivane uno per usarla qui.`,
      }, 409);
    }
    await env.DB.prepare(
      `INSERT INTO activations
        (license_id, device_id, device_name, app_version, activated_at, last_seen_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?5)`
    ).bind(license.id, deviceId, body.device_name || null, body.app_version || null, t).run();
  }

  const token = await issueToken(env, license, deviceId);
  return json({
    token,
    activated_at: t,
    email: license.email,
  });
}

// ============================================================
// POST /api/license/validate
// ============================================================
export async function handleValidate(req: Request, env: Env): Promise<Response> {
  const body = await readJson<{ token?: string; device_id?: string; app_version?: string }>(req);
  const token = (body.token || "").trim();
  const deviceId = (body.device_id || "").trim();
  if (!token || !deviceId) return badRequest("Missing token or device_id");

  const claims = await verifyJwt(token, env.JWT_SECRET);
  if (!claims) return unauthorized("Token invalido o scaduto");
  if (claims.device_id !== deviceId) {
    return unauthorized("device_id mismatch");
  }

  const license = await env.DB.prepare(
    `SELECT id, license_key, email, status FROM licenses WHERE id = ?1`
  ).bind(claims.sub).first<LicenseRow>();
  if (!license || license.status !== "active") {
    return unauthorized("Licenza non attiva");
  }

  const act = await findActivation(env, license.id, deviceId);
  if (!act || act.revoked_at !== null) {
    return unauthorized("Attivazione non trovata o revocata");
  }

  await env.DB.prepare(
    `UPDATE activations SET last_seen_at=?1, app_version=?2 WHERE id=?3`
  ).bind(now(), body.app_version || act.app_version, act.id).run();

  // Rotazione token: ne emettiamo uno nuovo per estendere l'exp
  const fresh = await issueToken(env, license, deviceId);
  return json({ token: fresh, email: license.email });
}

// ============================================================
// POST /api/license/deactivate
// ============================================================
export async function handleDeactivate(req: Request, env: Env): Promise<Response> {
  const body = await readJson<{ token?: string; device_id?: string }>(req);
  const token = (body.token || "").trim();
  const deviceId = (body.device_id || "").trim();
  if (!token || !deviceId) return badRequest("Missing token or device_id");

  const claims = await verifyJwt(token, env.JWT_SECRET);
  if (!claims) return unauthorized("Token invalido");
  if (claims.device_id !== deviceId) return unauthorized("device_id mismatch");

  await env.DB.prepare(
    `UPDATE activations SET revoked_at=?1
     WHERE license_id=?2 AND device_id=?3 AND revoked_at IS NULL`
  ).bind(now(), claims.sub, deviceId).run();

  return json({ ok: true });
}
