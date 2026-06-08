-- Schema MariaDB iniziale per MusicTools licenze.
-- Tutto utf8mb4 + InnoDB con FK abilitate.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS licenses (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  license_key   VARCHAR(64) NOT NULL,
  email         VARCHAR(255) NOT NULL,
  status        ENUM('active','revoked','refunded') NOT NULL DEFAULT 'active',
  source        VARCHAR(32) NULL,
  order_id      VARCHAR(64) NULL,
  created_at    BIGINT UNSIGNED NOT NULL,
  updated_at    BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_licenses_key (license_key),
  KEY idx_licenses_email (email),
  KEY idx_licenses_order_id (order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS activations (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  license_id    INT UNSIGNED NOT NULL,
  device_id     VARCHAR(64) NOT NULL,
  device_name   VARCHAR(255) NULL,
  app_version   VARCHAR(32) NULL,
  activated_at  BIGINT UNSIGNED NOT NULL,
  last_seen_at  BIGINT UNSIGNED NOT NULL,
  revoked_at    BIGINT UNSIGNED NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_activations_lic_dev (license_id, device_id),
  KEY idx_activations_license (license_id),
  CONSTRAINT fk_activations_license
    FOREIGN KEY (license_id) REFERENCES licenses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS releases (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  version       VARCHAR(32) NOT NULL,
  platform      ENUM('macos','windows') NOT NULL,
  file_path     VARCHAR(512) NOT NULL,
  size_bytes    BIGINT UNSIGNED NULL,
  sha256        CHAR(64) NULL,
  notes         TEXT NULL,
  published_at  BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_releases_ver_plat (version, platform),
  KEY idx_releases_platform_pub (platform, published_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
