-- Schema iniziale licenze MusicTools

CREATE TABLE IF NOT EXISTS licenses (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  license_key  TEXT NOT NULL UNIQUE,
  email        TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'active',  -- active | revoked | refunded
  source       TEXT,                            -- es. 'lemonsqueezy', 'manual'
  order_id     TEXT,                            -- id dell'ordine LS
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_licenses_email ON licenses(email);

CREATE TABLE IF NOT EXISTS activations (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  license_id   INTEGER NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
  device_id    TEXT NOT NULL,
  device_name  TEXT,
  app_version  TEXT,
  activated_at INTEGER NOT NULL,
  last_seen_at INTEGER NOT NULL,
  revoked_at   INTEGER,
  UNIQUE (license_id, device_id)
);

CREATE INDEX IF NOT EXISTS idx_activations_license ON activations(license_id);

CREATE TABLE IF NOT EXISTS releases (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  version      TEXT NOT NULL,
  platform     TEXT NOT NULL,            -- macos | windows
  r2_key       TEXT NOT NULL,            -- chiave dentro il bucket R2
  size_bytes   INTEGER,
  sha256       TEXT,
  notes        TEXT,
  published_at INTEGER NOT NULL,
  UNIQUE (version, platform)
);

CREATE INDEX IF NOT EXISTS idx_releases_platform_pub ON releases(platform, published_at DESC);
