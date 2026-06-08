/**
 * Minimal JWT HS256 implementation using Web Crypto (available in Workers).
 * We don't pull in a library to keep the worker bundle tiny.
 */

function b64url(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

function b64urlDecode(s: string): Uint8Array {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  s += "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function hmac(secret: string, data: string): Promise<ArrayBuffer> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
  return crypto.subtle.sign("HMAC", key, new TextEncoder().encode(data));
}

export interface JwtClaims {
  sub: string;          // license_id
  key_id: string;       // license_key (mascherata o intera)
  email: string;
  device_id: string;
  iat: number;
  exp: number;
  [k: string]: unknown;
}

export async function signJwt(claims: JwtClaims, secret: string): Promise<string> {
  const header = { alg: "HS256", typ: "JWT" };
  const head = b64url(new TextEncoder().encode(JSON.stringify(header)));
  const body = b64url(new TextEncoder().encode(JSON.stringify(claims)));
  const sig = b64url(await hmac(secret, `${head}.${body}`));
  return `${head}.${body}.${sig}`;
}

export async function verifyJwt(token: string, secret: string): Promise<JwtClaims | null> {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  const [head, body, sig] = parts;
  const expected = b64url(await hmac(secret, `${head}.${body}`));
  if (expected !== sig) return null;
  try {
    const claims = JSON.parse(new TextDecoder().decode(b64urlDecode(body))) as JwtClaims;
    if (typeof claims.exp === "number" && claims.exp < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return claims;
  } catch {
    return null;
  }
}
