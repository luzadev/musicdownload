import { json, badRequest, unauthorized } from "./http";
import { verifyJwt } from "./jwt";
import type { Env } from "./worker";

interface ReleaseRow {
  version: string;
  platform: string;
  r2_key: string;
  size_bytes: number | null;
  sha256: string | null;
  notes: string | null;
  published_at: number;
}

/**
 * GET /api/latest?platform=macos|windows&current=v1.5.2
 * Authorization: Bearer <token> (opzionale ma necessario per ricevere download_url)
 *
 * Risposta:
 *   {
 *     version, notes, sha256,
 *     download_url (firmato, scade in DOWNLOAD_URL_TTL_SECONDS) -- solo se token valido
 *   }
 */
export async function handleLatest(req: Request, env: Env): Promise<Response> {
  const url = new URL(req.url);
  const platform = (url.searchParams.get("platform") || "").toLowerCase();
  if (platform !== "macos" && platform !== "windows") {
    return badRequest("platform must be macos or windows");
  }

  const row = await env.DB.prepare(
    `SELECT version, platform, r2_key, size_bytes, sha256, notes, published_at
     FROM releases
     WHERE platform = ?1
     ORDER BY published_at DESC
     LIMIT 1`
  ).bind(platform).first<ReleaseRow>();

  if (!row) {
    return json({
      version: env.LATEST_VERSION || "",
      notes: "",
      download_url: "",
      requires_license: true,
    });
  }

  // Auth opzionale: senza token rispondiamo solo con metadata (version + notes).
  const auth = req.headers.get("Authorization") || "";
  let licensed = false;
  if (auth.startsWith("Bearer ")) {
    const token = auth.slice(7).trim();
    const claims = await verifyJwt(token, env.JWT_SECRET);
    licensed = !!claims;
  }

  let downloadUrl = "";
  if (licensed) {
    // R2 non genera URL firmati nativi via Workers SDK in modo semplice.
    // Soluzione: serviamo il file via questo Worker su un path firmato HMAC
    // con scadenza. /api/download?key=<r2_key>&exp=<ts>&sig=<hmac>
    downloadUrl = await signDownloadUrl(env, row.r2_key);
  }

  return json({
    version: row.version,
    notes: row.notes || "",
    sha256: row.sha256 || "",
    size_bytes: row.size_bytes || 0,
    download_url: downloadUrl,
    requires_license: !licensed,
  });
}

async function signDownloadUrl(env: Env, r2Key: string): Promise<string> {
  // Implementazione minima: torniamo un URL relativo che un altro endpoint
  // /api/download verifichera prima di servire il file da R2.
  // Per ora restituisco un placeholder; vai a implementare /api/download
  // in un secondo passaggio se vuoi servire i binari dietro firma.
  const ttl = parseInt(env.DOWNLOAD_URL_TTL_SECONDS || "300", 10);
  const exp = Math.floor(Date.now() / 1000) + ttl;
  const payload = `${r2Key}.${exp}`;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(env.JWT_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false, ["sign"],
  );
  const sigBuf = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(payload));
  const sig = btoa(String.fromCharCode(...new Uint8Array(sigBuf)))
    .replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `https://musictools.djluza.com/api/download?key=${encodeURIComponent(r2Key)}&exp=${exp}&sig=${sig}`;
}
