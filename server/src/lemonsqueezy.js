/**
 * Webhook Lemon Squeezy.
 * URL pubblico: https://musictools.djluza.com/api/webhook/lemonsqueezy
 *
 * Eventi gestiti:
 *  - order_created           : crea licenza ANNUAL (one-time) con expires_at = now+365d.
 *                              Per le subscription ignora: il record nasce da subscription_created.
 *  - order_refunded          : status -> refunded.
 *  - subscription_created    : crea licenza con plan, subscription_id, current_period_end.
 *  - subscription_updated    : aggiorna current_period_end e plan se cambiato.
 *  - subscription_payment_success : estende current_period_end al nuovo renews_at.
 *  - subscription_payment_failed  : (no-op qui) lasciamo scadere current_period_end.
 *  - subscription_cancelled  : niente, il periodo corrente resta valido fino a current_period_end.
 *  - subscription_expired    : status -> revoked, l'utente perde l'accesso.
 *
 * Tutto idempotente: ogni evento si puo' rispedire senza spaccare nulla.
 */

import crypto from "node:crypto";
import { one, exec } from "./db.js";
import { generateLicenseKey } from "./license.js";
import { sendLicenseEmail } from "./email.js";
import { planByVariantId, getPlan, ANNUAL_TTL_SECONDS } from "./plans.js";

const now = () => Math.floor(Date.now() / 1000);

function hmacHex(secret, data) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}

function timingSafe(a, b) {
  if (a.length !== b.length) return false;
  const A = Buffer.from(a), B = Buffer.from(b);
  return crypto.timingSafeEqual(A, B);
}

/** Converte una data ISO (es. "2026-07-09T13:24:00Z") in epoch seconds, o null. */
function isoToEpoch(iso) {
  if (!iso) return null;
  const t = Date.parse(String(iso));
  if (Number.isNaN(t)) return null;
  return Math.floor(t / 1000);
}

/** Estrae variant_id dal payload, gestendo le diverse forme degli eventi. */
function extractVariantId(payload, attrs) {
  // subscription_*: attrs.variant_id (diretto)
  if (attrs.variant_id != null) return String(attrs.variant_id);
  // order_created: attrs.first_order_item.variant_id
  const item = attrs.first_order_item;
  if (item && item.variant_id != null) return String(item.variant_id);
  // alcune forme passano da relationships
  const rel = payload?.data?.relationships?.variant?.data?.id;
  if (rel) return String(rel);
  return "";
}

/** Email cliente: nei subscription_* puo' essere customer_email. */
function extractEmail(attrs) {
  const e = attrs.user_email || attrs.customer_email || attrs.email || "";
  return String(e).trim().toLowerCase();
}

// ---- Handlers per famiglia evento -----------------------------------------

async function handleOrderCreated(payload, attrs, t) {
  const email = extractEmail(attrs);
  const orderId = String(payload?.data?.id || attrs.order_number || "");
  if (!email || !orderId) {
    return { status: 400, body: { error: "Missing email or order_id" } };
  }
  const variantId = extractVariantId(payload, attrs);
  const planCode = planByVariantId(variantId);
  const plan = planCode ? getPlan(planCode) : null;

  // Se l'order e' gia stato processato (lo riconosciamo dall'order_id),
  // non duplichiamo licenza ne' email — ack 200 e basta.
  const existing = await one(
    "SELECT id FROM licenses WHERE order_id=? LIMIT 1",
    [orderId],
  );
  if (existing) {
    return { status: 200, body: { ok: true, duplicate: true } };
  }

  // Piano non mappato -> fallback annual cosi' non blocchiamo l'utente
  // che ha gia pagato (la licenza sara' usabile anche se non sappiamo
  // i limiti esatti del piano comprato).
  const planForRecord = plan?.code || "annual";
  const planMeta = plan || getPlan("annual");
  const limit = planMeta?.daily_limit ?? null;

  // Annual one-time: settiamo expires_at = now + 365d.
  // Subscription mensili: NON settiamo current_period_end qui — lo fara'
  // subscription_created/subscription_payment_success quando arriva.
  // Se quell'evento non arrivasse mai (perche' non abilitato in LS
  // dashboard), la licenza resta utilizzabile (current_period_end NULL
  // = no scadenza imposta lato server: la sottoscrizione vivra' o
  // morira' su LS, e i webhook successivi aggiorneranno lo status).
  const expiresAt = planMeta?.is_subscription ? null : t + ANNUAL_TTL_SECONDS;
  const key = generateLicenseKey();

  try {
    await exec(
      `INSERT INTO licenses
         (license_key, email, status, plan, daily_limit,
          source, order_id, expires_at, created_at, updated_at)
       VALUES (?, ?, 'active', ?, ?, 'lemonsqueezy', ?, ?, ?, ?)`,
      [key, email, planForRecord, limit, orderId, expiresAt, t, t],
    );
  } catch (e) {
    if (e?.code === "ER_DUP_ENTRY") {
      return { status: 200, body: { ok: true, duplicate: true } };
    }
    throw e;
  }

  try {
    await sendLicenseEmail(email, key, {
      plan: planForRecord,
      expiresAt: expiresAt,
    });
  } catch (e) {
    console.error("[email] send failed:", e?.message || e);
  }

  return { status: 200, body: { ok: true, plan: planForRecord } };
}

async function handleOrderRefunded(payload, attrs, t) {
  const orderId = String(payload?.data?.id || attrs.order_number || "");
  if (!orderId) return { status: 400, body: { error: "Missing order_id" } };
  await exec(
    `UPDATE licenses SET status='refunded', updated_at=? WHERE order_id=?`,
    [t, orderId],
  );
  return { status: 200, body: { ok: true } };
}

async function handleSubscriptionCreated(payload, attrs, t) {
  const email = extractEmail(attrs);
  const subId = String(payload?.data?.id || attrs.subscription_id || "");
  const variantId = extractVariantId(payload, attrs);
  const planCode = planByVariantId(variantId);
  if (!email || !subId) {
    return { status: 400, body: { error: "Missing email or subscription_id" } };
  }
  if (!planCode) {
    // Niente mapping -> non sappiamo che limiti applicare. Logghiamo e
    // ritorniamo 200 cosi' LS non rispedisce all'infinito.
    console.warn("[ls] subscription_created variant non mappato:", variantId, "email=", email);
    return { status: 200, body: { ok: true, ignored: "unknown_variant" } };
  }
  const plan = getPlan(planCode);
  const periodEnd = isoToEpoch(attrs.renews_at) || isoToEpoch(attrs.ends_at);
  const orderId = String(attrs.order_id || "");
  const key = generateLicenseKey();

  // Idempotenza: se ricevo lo stesso subscription_created due volte,
  // riuso la licenza esistente.
  const existing = await one(
    "SELECT id, license_key FROM licenses WHERE subscription_id=? LIMIT 1",
    [subId],
  );
  if (existing) {
    await exec(
      `UPDATE licenses
          SET status='active', plan=?, daily_limit=?, current_period_end=?, updated_at=?
        WHERE id=?`,
      [planCode, plan.daily_limit, periodEnd, t, existing.id],
    );
    return { status: 200, body: { ok: true, duplicate: true } };
  }

  // Caso normale ora: la licenza e' gia stata creata da order_created
  // (con subscription_id NULL). La aggiorno con subscription_id e
  // current_period_end senza generare una nuova chiave ne' una nuova email.
  const byOrder = orderId
    ? await one(
        `SELECT id FROM licenses
          WHERE order_id=? AND subscription_id IS NULL LIMIT 1`,
        [orderId],
      )
    : null;
  if (byOrder) {
    await exec(
      `UPDATE licenses
          SET subscription_id=?, current_period_end=?, plan=?, daily_limit=?,
              updated_at=?
        WHERE id=?`,
      [subId, periodEnd, planCode, plan.daily_limit, t, byOrder.id],
    );
    return { status: 200, body: { ok: true, attached_subscription: subId } };
  }

  // Fallback: nessuna licenza esistente -> ne creiamo una nuova
  // (puo' succedere se order_created non e' arrivato per qualche motivo).
  try {
    await exec(
      `INSERT INTO licenses
         (license_key, email, status, plan, daily_limit,
          source, order_id, subscription_id, current_period_end,
          created_at, updated_at)
       VALUES (?, ?, 'active', ?, ?, 'lemonsqueezy', ?, ?, ?, ?, ?)`,
      [key, email, planCode, plan.daily_limit, orderId || null, subId, periodEnd, t, t],
    );
  } catch (e) {
    if (e?.code === "ER_DUP_ENTRY") {
      return { status: 200, body: { ok: true, duplicate: true } };
    }
    throw e;
  }

  try {
    await sendLicenseEmail(email, key, { plan: planCode, periodEnd });
  } catch (e) {
    console.error("[email] send failed:", e?.message || e);
  }
  return { status: 200, body: { ok: true, plan: planCode } };
}

async function handleSubscriptionUpdated(payload, attrs, t) {
  const subId = String(payload?.data?.id || "");
  if (!subId) return { status: 400, body: { error: "Missing subscription_id" } };
  const variantId = extractVariantId(payload, attrs);
  const planCode = planByVariantId(variantId);
  const periodEnd = isoToEpoch(attrs.renews_at) || isoToEpoch(attrs.ends_at);

  if (planCode) {
    const plan = getPlan(planCode);
    await exec(
      `UPDATE licenses
          SET plan=?, daily_limit=?, current_period_end=?, updated_at=?
        WHERE subscription_id=?`,
      [planCode, plan.daily_limit, periodEnd, t, subId],
    );
  } else if (periodEnd) {
    await exec(
      `UPDATE licenses SET current_period_end=?, updated_at=? WHERE subscription_id=?`,
      [periodEnd, t, subId],
    );
  }
  return { status: 200, body: { ok: true } };
}

async function handleSubscriptionPaymentSuccess(payload, attrs, t) {
  // L'evento di pagamento riferisce alla subscription via attrs.subscription_id
  const subId = String(attrs.subscription_id || payload?.data?.id || "");
  if (!subId) return { status: 400, body: { error: "Missing subscription_id" } };

  // Quando un rinnovo va a buon fine LS sposta avanti renews_at.
  // Per essere sicuri leggiamo l'evento PIU' recente (subscription_updated
  // viene inviato a stretto giro), oppure deduciamo: +30 giorni.
  const periodEnd = isoToEpoch(attrs.renews_at)
    || isoToEpoch(attrs.created_at)
    || (t + 30 * 24 * 3600);

  await exec(
    `UPDATE licenses
        SET status='active', current_period_end=?, updated_at=?
      WHERE subscription_id=?`,
    [periodEnd, t, subId],
  );
  return { status: 200, body: { ok: true } };
}

async function handleSubscriptionExpired(payload, attrs, t) {
  const subId = String(payload?.data?.id || attrs.subscription_id || "");
  if (!subId) return { status: 400, body: { error: "Missing subscription_id" } };
  await exec(
    `UPDATE licenses SET status='revoked', updated_at=? WHERE subscription_id=?`,
    [t, subId],
  );
  return { status: 200, body: { ok: true } };
}

// ---- Entry point ----------------------------------------------------------

export async function webhook(req, res) {
  const raw = req.body instanceof Buffer ? req.body.toString("utf-8") : "";
  const sig = req.get("X-Signature") || "";
  const secret = process.env.LEMONSQUEEZY_SIGNING_SECRET;
  if (!sig || !secret) return res.status(400).json({ error: "Missing signature" });

  const expected = hmacHex(secret, raw);
  if (!timingSafe(sig, expected)) {
    return res.status(401).json({ error: "Invalid signature" });
  }

  let payload;
  try { payload = JSON.parse(raw); }
  catch { return res.status(400).json({ error: "Invalid JSON" }); }

  const eventName = payload?.meta?.event_name || "";
  const attrs = payload?.data?.attributes || {};
  const t = now();

  let out;
  try {
    switch (eventName) {
      case "order_created":
        out = await handleOrderCreated(payload, attrs, t);
        break;
      case "order_refunded":
        out = await handleOrderRefunded(payload, attrs, t);
        break;
      case "subscription_created":
        out = await handleSubscriptionCreated(payload, attrs, t);
        break;
      case "subscription_updated":
      case "subscription_resumed":
      case "subscription_unpaused":
        out = await handleSubscriptionUpdated(payload, attrs, t);
        break;
      case "subscription_payment_success":
        out = await handleSubscriptionPaymentSuccess(payload, attrs, t);
        break;
      case "subscription_expired":
        out = await handleSubscriptionExpired(payload, attrs, t);
        break;
      case "subscription_cancelled":
      case "subscription_paused":
      case "subscription_payment_failed":
      case "subscription_payment_refunded":
        // No-op: il record resta com'e' fino al prossimo evento che cambia stato.
        out = { status: 200, body: { ok: true, ignored: eventName } };
        break;
      default:
        out = { status: 200, body: { ok: true, ignored: eventName } };
    }
  } catch (e) {
    console.error("[ls] handler error", eventName, e?.message || e);
    return res.status(500).json({ error: "Internal error" });
  }

  return res.status(out.status).json(out.body);
}
