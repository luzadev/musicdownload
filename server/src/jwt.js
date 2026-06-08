/**
 * JWT HS256 minimale (niente dipendenze). Stessa logica del worker
 * Cloudflare precedente: stesso token formato, stessa firma, stessa
 * verifica. L'app desktop non distingue.
 */

import crypto from "node:crypto";

function b64url(buf) {
  return Buffer.from(buf).toString("base64")
    .replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function b64urlDecode(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  s += "=".repeat((4 - (s.length % 4)) % 4);
  return Buffer.from(s, "base64");
}

function hmac(secret, data) {
  return crypto.createHmac("sha256", secret).update(data).digest();
}

export function signJwt(claims, secret) {
  const head = b64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = b64url(JSON.stringify(claims));
  const sig = b64url(hmac(secret, `${head}.${body}`));
  return `${head}.${body}.${sig}`;
}

export function verifyJwt(token, secret) {
  if (typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [head, body, sig] = parts;
  const expected = b64url(hmac(secret, `${head}.${body}`));
  // confronto a tempo costante
  if (sig.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < sig.length; i++) diff |= sig.charCodeAt(i) ^ expected.charCodeAt(i);
  if (diff !== 0) return null;
  try {
    const claims = JSON.parse(b64urlDecode(body).toString("utf-8"));
    if (typeof claims.exp === "number" && claims.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return claims;
  } catch {
    return null;
  }
}
