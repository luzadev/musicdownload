/**
 * Quota giornaliera per piano.
 *
 * Il client chiama:
 *  - GET /api/usage/status   (Bearer JWT) -> solo lettura, no incremento
 *  - POST /api/usage/consume (Bearer JWT) -> +1 al contatore, ritorna esito
 *
 * Il "giorno" e' YYYY-MM-DD nella timezone Europe/Rome. In questo modo
 * tutti i clienti hanno lo stesso reset (mezzanotte di Roma) — semplifica
 * il marketing ("10 download al giorno, resettati a mezzanotte").
 */

import { one, exec } from "./db.js";
import { licenseFromToken } from "./license.js";
import { getPlan, planSnapshot } from "./plans.js";

const now = () => Math.floor(Date.now() / 1000);

/** YYYY-MM-DD nella timezone Europe/Rome, partendo da un istante epoch. */
export function romeDay(epochSeconds = Math.floor(Date.now() / 1000)) {
  const d = new Date(epochSeconds * 1000);
  // Intl con time zone -> formatta in YYYY-MM-DD senza problemi DST.
  const fmt = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Rome",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  // en-CA -> "2026-06-09"
  return fmt.format(d);
}

function bearer(req) {
  const auth = req.get("Authorization") || "";
  return auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
}

async function loadAuthorized(req, res) {
  const token = bearer(req) || String(req.body?.token || "");
  if (!token) {
    res.status(401).json({ error: "Missing token" });
    return null;
  }
  const auth = await licenseFromToken(token);
  if (!auth) {
    res.status(401).json({ error: "Licenza non valida o scaduta" });
    return null;
  }
  return auth;
}

/** Risposta compatta usata da entrambi gli endpoint. */
function buildResponse(plan, limit, used) {
  const remaining = limit === null ? null : Math.max(0, limit - used);
  return {
    plan,
    used,
    limit,                // null = illimitato
    remaining,            // null = illimitato
    day: romeDay(),
  };
}

/** Quanti download ha gia' fatto la licenza oggi (Europe/Rome). */
async function readUsedToday(licenseId, day) {
  const row = await one(
    "SELECT count FROM daily_usage WHERE license_id=? AND day=?",
    [licenseId, day],
  );
  return Number(row?.count || 0);
}

export async function status(req, res) {
  const auth = await loadAuthorized(req, res);
  if (!auth) return;
  const { license } = auth;
  const plan = planSnapshot(license.plan);
  const limit = plan?.daily_limit ?? null;
  const day = romeDay();
  const used = limit === null ? 0 : await readUsedToday(license.id, day);
  res.json(buildResponse(plan, limit, used));
}

/**
 * Incrementa di 1 il contatore del giorno corrente per la licenza,
 * rifiutando con 429 se gia' al limite. Lo facciamo con una UPDATE
 * condizionale + INSERT-or-no-op cosi' e' atomico anche sotto carico.
 */
export async function consume(req, res) {
  const auth = await loadAuthorized(req, res);
  if (!auth) return;
  const { license } = auth;
  const plan = planSnapshot(license.plan);
  if (!plan) return res.status(403).json({ error: "Piano non riconosciuto" });

  // (Opzionale) il client puo' passare {feature: "video"} per chiarezza,
  // ma noi gating-amo gia' lato client e basta avere un piano valido qui.
  const feature = String(req.body?.feature || "").trim();
  if (feature && !plan.features.includes(feature)) {
    return res.status(403).json({
      error: `Il piano ${plan.name} non include questa funzione.`,
      plan,
    });
  }

  const limit = plan.daily_limit;
  const day = romeDay();
  const t = now();

  // Unlimited (annual): nessun gate, conta comunque per le statistiche.
  if (limit === null) {
    await exec(
      `INSERT INTO daily_usage (license_id, day, count, updated_at)
            VALUES (?, ?, 1, ?)
       ON DUPLICATE KEY UPDATE count = count + 1, updated_at = VALUES(updated_at)`,
      [license.id, day, t],
    );
    const used = await readUsedToday(license.id, day);
    return res.json({ ...buildResponse(plan, limit, used), allowed: true });
  }

  // Limited: prova incremento condizionato. Se la riga non esiste,
  // INSERT iniziale (count=1). Se esiste e count<limit -> +1, altrimenti
  // affectedRows=0 e ritorniamo 429.
  const upd = await exec(
    `UPDATE daily_usage
        SET count = count + 1, updated_at = ?
      WHERE license_id = ? AND day = ? AND count < ?`,
    [t, license.id, day, limit],
  );

  if (upd.affectedRows === 0) {
    // Due casi: riga non esiste (mai usato oggi) oppure gia' al limite.
    const existing = await one(
      "SELECT count FROM daily_usage WHERE license_id=? AND day=?",
      [license.id, day],
    );
    if (!existing) {
      try {
        await exec(
          `INSERT INTO daily_usage (license_id, day, count, updated_at)
                VALUES (?, ?, 1, ?)`,
          [license.id, day, t],
        );
        return res.json({ ...buildResponse(plan, limit, 1), allowed: true });
      } catch (e) {
        if (e?.code !== "ER_DUP_ENTRY") throw e;
        // race: qualcun altro l'ha inserita -> rileggi
      }
    }
    const used = await readUsedToday(license.id, day);
    return res.status(429).json({
      ...buildResponse(plan, limit, used),
      allowed: false,
      error: `Limite giornaliero raggiunto (${limit}/${limit}). Riprova dopo mezzanotte o passa a un piano superiore.`,
    });
  }

  const used = await readUsedToday(license.id, day);
  res.json({ ...buildResponse(plan, limit, used), allowed: true });
}
