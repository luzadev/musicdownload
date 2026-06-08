/**
 * Webhook Lemon Squeezy.
 * URL pubblico: https://musictools.djluza.com/api/webhook/lemonsqueezy
 * Eventi gestiti: order_created, order_refunded.
 */

import crypto from "node:crypto";
import { one, exec } from "./db.js";
import { generateLicenseKey } from "./license.js";
import { sendLicenseEmail } from "./email.js";

const now = () => Math.floor(Date.now() / 1000);

function hmacHex(secret, data) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}

function timingSafe(a, b) {
  if (a.length !== b.length) return false;
  const A = Buffer.from(a), B = Buffer.from(b);
  return crypto.timingSafeEqual(A, B);
}

export async function webhook(req, res) {
  // express.raw() salva il body come Buffer in req.body
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
  const email = String(attrs.user_email || "").trim().toLowerCase();
  const orderId = String(payload?.data?.id || attrs.order_number || "");
  if (!email || !orderId) {
    return res.status(400).json({ error: "Missing email or order_id" });
  }

  const t = now();

  if (eventName === "order_created") {
    const key = generateLicenseKey();
    try {
      await exec(
        `INSERT INTO licenses
           (license_key, email, status, source, order_id, created_at, updated_at)
         VALUES (?, ?, 'active', 'lemonsqueezy', ?, ?, ?)`,
        [key, email, orderId, t, t],
      );
    } catch (e) {
      // duplicate webhook delivery
      if (e?.code === "ER_DUP_ENTRY") {
        return res.json({ ok: true, duplicate: true });
      }
      throw e;
    }
    try {
      await sendLicenseEmail(email, key);
    } catch (e) {
      console.error("[email] send failed:", e?.message || e);
    }
    return res.json({ ok: true });
  }

  if (eventName === "order_refunded") {
    await exec(
      `UPDATE licenses SET status='refunded', updated_at=? WHERE order_id=?`,
      [t, orderId],
    );
    return res.json({ ok: true });
  }

  res.json({ ok: true, ignored: eventName });
}
