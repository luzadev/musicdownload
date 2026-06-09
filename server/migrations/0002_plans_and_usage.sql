SET NAMES utf8mb4;

ALTER TABLE licenses
  ADD COLUMN plan VARCHAR(16) NULL AFTER status,
  ADD COLUMN daily_limit INT UNSIGNED NULL AFTER plan,
  ADD COLUMN subscription_id VARCHAR(64) NULL AFTER daily_limit,
  ADD COLUMN current_period_end BIGINT UNSIGNED NULL AFTER subscription_id,
  ADD COLUMN expires_at BIGINT UNSIGNED NULL AFTER current_period_end;

UPDATE licenses
   SET plan = 'annual',
       daily_limit = NULL,
       expires_at = NULL
 WHERE plan IS NULL;

ALTER TABLE licenses
  ADD KEY idx_licenses_plan (plan),
  ADD KEY idx_licenses_sub (subscription_id);

CREATE TABLE IF NOT EXISTS daily_usage (
  license_id   INT UNSIGNED NOT NULL,
  day          CHAR(10) NOT NULL,
  count        INT UNSIGNED NOT NULL DEFAULT 0,
  updated_at   BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (license_id, day),
  CONSTRAINT fk_daily_usage_license
    FOREIGN KEY (license_id) REFERENCES licenses(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
