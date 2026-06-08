/**
 * Webhook Lemon Squeezy.
 *
 * Configurazione:
 *   - Crea il webhook dal dashboard LS (My Store > Settings > Webhooks)
 *   - URL: https://musictools.djluza.com/api/webhook/lemonsqueezy
 *   - Eventi: order_created, subscription_payment_success (per future estensioni),
 *             order_refunded
 *   - Secret: salvalo come "LEMONSQUEEZY_SIGNING_SECRET" (wrangler secret put)
 *
 * Flusso order_created:
 *   1. Verifica firma X-Signature == HMAC-SHA256(secret, raw_body)
 *   2. Estrai email cliente + order_id
 *   3. Genera license_key (XXXX-XXXX-XXXX-XXXX), insert in 'licenses'
 *   4. Invia email all'utente via Resend con la chiave
 */

import { json, now } from "./http";
import type { Env } from "./worker";

interface LSPayload {
  meta?: { event_name?: string; custom_data?: Record<string, unknown> };
  data?: {
    id?: string;
    type?: string;
    attributes?: {
      user_email?: string;
      order_number?: number | string;
      refunded?: boolean;
      status?: string;
    };
  };
}

export async function handleLemonSqueezyWebhook(req: Request, env: Env): Promise<Response> {
  const raw = await req.text();
  const sig = req.headers.get("X-Signature") || "";
  if (!sig || !env.LEMONSQUEEZY_SIGNING_SECRET) {
    return json({ error: "Missing signature" }, 400);
  }

  const expected = await hmacHex(env.LEMONSQUEEZY_SIGNING_SECRET, raw);
  if (!timingSafeEqual(sig, expected)) {
    return json({ error: "Invalid signature" }, 401);
  }

  let payload: LSPayload;
  try {
    payload = JSON.parse(raw) as LSPayload;
  } catch {
    return json({ error: "Invalid JSON" }, 400);
  }

  const eventName = payload.meta?.event_name || "";
  const attrs = payload.data?.attributes || {};
  const email = (attrs.user_email || "").trim().toLowerCase();
  const orderId = String(payload.data?.id || attrs.order_number || "");

  if (!email || !orderId) {
    return json({ error: "Missing email or order_id" }, 400);
  }

  const t = now();

  if (eventName === "order_created") {
    const key = generateLicenseKey();
    try {
      await env.DB.prepare(
        `INSERT INTO licenses (license_key, email, status, source, order_id, created_at, updated_at)
         VALUES (?1, ?2, 'active', 'lemonsqueezy', ?3, ?4, ?4)`
      ).bind(key, email, orderId, t).run();
    } catch (e) {
      // unique violation (webhook duplicato): no-op
      console.warn("Insert license failed (probabile duplicato):", e);
      return json({ ok: true, duplicate: true });
    }
    await sendLicenseEmail(env, email, key);
    return json({ ok: true, license_key_masked: key.slice(0, 4) + "..." });
  }

  if (eventName === "order_refunded") {
    await env.DB.prepare(
      `UPDATE licenses SET status='refunded', updated_at=?1
       WHERE order_id=?2`
    ).bind(t, orderId).run();
    return json({ ok: true });
  }

  return json({ ok: true, ignored: eventName });
}

function generateLicenseKey(): string {
  // 16 caratteri base32 (no I/O/0/1 ambigui), in 4 gruppi da 4.
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const buf = new Uint8Array(16);
  crypto.getRandomValues(buf);
  const chars = Array.from(buf, (b) => alphabet[b % alphabet.length]);
  return [chars.slice(0, 4), chars.slice(4, 8), chars.slice(8, 12), chars.slice(12, 16)]
    .map((g) => g.join("")).join("-");
}

async function hmacHex(secret: string, data: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
  return Array.from(new Uint8Array(sig)).map(b => b.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function sendLicenseEmail(env: Env, email: string, key: string): Promise<void> {
  if (!env.RESEND_API_KEY) {
    console.warn("RESEND_API_KEY non impostata, skip invio email");
    return;
  }
  const body = {
    from: "MusicTools <noreply@djluza.com>",
    to: [email],
    subject: "La tua licenza MusicTools",
    html: `
      <div style="font-family:-apple-system,Segoe UI,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111">
        <h1 style="color:#1db954">Grazie per aver scelto MusicTools!</h1>
        <p>Ecco la tua chiave di licenza:</p>
        <p style="font-size:22px;letter-spacing:2px;font-family:monospace;background:#f4f4f4;padding:14px;border-radius:8px;text-align:center">
          ${key}
        </p>
        <p>Per attivarla:</p>
        <ol>
          <li>Scarica MusicTools per <a href="https://musictools.djluza.com/download/macos">macOS</a> o <a href="https://musictools.djluza.com/download/windows">Windows</a></li>
          <li>Apri l'app: ti chiedera' email e chiave</li>
          <li>Inserisci questa email (<code>${email}</code>) e la chiave qui sopra</li>
        </ol>
        <p>Puoi attivare la licenza fino a 3 dispositivi.</p>
        <hr/>
        <p style="color:#666;font-size:12px">Hai problemi? Scrivici a info@djluza.com</p>
      </div>
    `,
  };
  const resp = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.RESEND_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    console.error("Resend error:", await resp.text());
  }
}
