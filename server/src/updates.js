import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { one } from "./db.js";
import { verifyJwt } from "./jwt.js";

const BUILDS_DIR = process.env.BUILDS_DIR || path.resolve(process.cwd(), "../builds");
const DOWNLOAD_TTL = Number(process.env.DOWNLOAD_URL_TTL_SECONDS || 300);
const PUBLIC_BASE = process.env.PUBLIC_BASE_URL || "https://musictools.djluza.com";

function signPayload(payload, secret) {
  return crypto.createHmac("sha256", secret).update(payload).digest("base64url");
}

function buildDownloadUrl(filePath) {
  const exp = Math.floor(Date.now() / 1000) + DOWNLOAD_TTL;
  const sig = signPayload(`${filePath}.${exp}`, process.env.JWT_SECRET);
  return `${PUBLIC_BASE}/api/download?file=${encodeURIComponent(filePath)}&exp=${exp}&sig=${sig}`;
}

// GET /api/latest?platform=macos|windows&current=v1.5.2
export async function latest(req, res) {
  const platform = String(req.query.platform || "").toLowerCase();
  if (platform !== "macos" && platform !== "windows") {
    return res.status(400).json({ error: "platform must be macos or windows" });
  }

  const row = await one(
    `SELECT version, platform, file_path, size_bytes, sha256, notes, published_at
     FROM releases
     WHERE platform=?
     ORDER BY published_at DESC
     LIMIT 1`,
    [platform],
  );

  if (!row) {
    return res.json({
      version: process.env.LATEST_VERSION || "",
      notes: "",
      download_url: "",
      requires_license: true,
    });
  }

  // Auth opzionale (Bearer): senza, niente download URL
  const auth = req.get("Authorization") || "";
  let licensed = false;
  if (auth.startsWith("Bearer ")) {
    const claims = verifyJwt(auth.slice(7).trim(), process.env.JWT_SECRET);
    licensed = !!claims;
  }

  res.json({
    version: row.version,
    notes: row.notes || "",
    sha256: row.sha256 || "",
    size_bytes: Number(row.size_bytes || 0),
    download_url: licensed ? buildDownloadUrl(row.file_path) : "",
    requires_license: !licensed,
  });
}

// GET /api/download?file=...&exp=...&sig=...
// Verifica firma e stream del file da disco.
export async function download(req, res) {
  const file = String(req.query.file || "");
  const exp = Number(req.query.exp || 0);
  const sig = String(req.query.sig || "");
  if (!file || !exp || !sig) return res.status(400).send("Missing params");

  const expected = signPayload(`${file}.${exp}`, process.env.JWT_SECRET);
  const a = Buffer.from(sig), b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
    return res.status(401).send("Invalid signature");
  }
  if (exp < Math.floor(Date.now() / 1000)) {
    return res.status(410).send("URL expired");
  }

  // Sicurezza path: il file deve trovarsi sotto BUILDS_DIR.
  // 'file' arriva come "v1.5.3/MusicTools-macOS.zip"
  const abs = path.resolve(BUILDS_DIR, file);
  if (!abs.startsWith(path.resolve(BUILDS_DIR) + path.sep)) {
    return res.status(403).send("Forbidden");
  }
  if (!fs.existsSync(abs)) {
    return res.status(404).send("File not found");
  }

  const name = path.basename(abs);
  const ext = path.extname(name).toLowerCase();
  const contentType = ext === ".dmg"
    ? "application/x-apple-diskimage"
    : ext === ".exe"
      ? "application/vnd.microsoft.portable-executable"
      : "application/zip";
  res.setHeader("Content-Type", contentType);
  res.setHeader("Content-Disposition", `attachment; filename="${name}"`);
  fs.createReadStream(abs).pipe(res);
}
