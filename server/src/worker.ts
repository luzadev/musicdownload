/**
 * MusicTools License & Update API
 *
 * Endpoints:
 *   POST /api/license/activate    body: { key, email, device_id, device_name, app_version }
 *   POST /api/license/validate    body: { token, device_id, app_version }
 *   POST /api/license/deactivate  body: { token, device_id }
 *   GET  /api/latest?platform=macos|windows&current=v1.5.2     [Authorization: Bearer <token>]
 *   POST /api/webhook/lemonsqueezy   (firmato HMAC, crea licenza dopo ordine)
 *
 * Auth model:
 *   - L'app non ha account: la "verita" e' (license_key, email).
 *   - Dopo activate(), il server emette un JWT HMAC con claims
 *     { sub: license_id, key_id, email, device_id, iat, exp }.
 *     Il client lo salva e lo manda a ogni revalidate / /api/latest.
 *   - revoke = update licenses.status='revoked' + tutti i validate falliscono.
 */

import { handleActivate, handleValidate, handleDeactivate } from "./license";
import { handleLatest } from "./updates";
import { handleLemonSqueezyWebhook } from "./lemonsqueezy";
import { json, methodNotAllowed, notFound } from "./http";

export interface Env {
  DB: D1Database;
  BUILDS: R2Bucket;
  JWT_SECRET: string;
  LEMONSQUEEZY_SIGNING_SECRET: string;
  RESEND_API_KEY: string;
  LATEST_VERSION: string;
  MAX_ACTIVATIONS: string;
  TOKEN_TTL_DAYS: string;
  DOWNLOAD_URL_TTL_SECONDS: string;
}

export default {
  async fetch(req: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(req.url);
    const path = url.pathname;
    const method = req.method.toUpperCase();

    // CORS (utile se in futuro vuoi chiamare l'API dalla landing page)
    if (method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
          "Access-Control-Allow-Headers": "Content-Type,Authorization",
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    try {
      if (path === "/api/license/activate") {
        if (method !== "POST") return methodNotAllowed();
        return await handleActivate(req, env);
      }
      if (path === "/api/license/validate") {
        if (method !== "POST") return methodNotAllowed();
        return await handleValidate(req, env);
      }
      if (path === "/api/license/deactivate") {
        if (method !== "POST") return methodNotAllowed();
        return await handleDeactivate(req, env);
      }
      if (path === "/api/latest") {
        if (method !== "GET") return methodNotAllowed();
        return await handleLatest(req, env);
      }
      if (path === "/api/webhook/lemonsqueezy") {
        if (method !== "POST") return methodNotAllowed();
        return await handleLemonSqueezyWebhook(req, env);
      }
      if (path === "/api/health") {
        return json({ ok: true, version: env.LATEST_VERSION });
      }
      return notFound();
    } catch (err) {
      console.error("Unhandled error:", err);
      return json({ error: "Internal error" }, 500);
    }
  },
};
