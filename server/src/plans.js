/**
 * Source of truth per i piani MusicTools.
 *
 * Mappa anche i variant_id di Lemon Squeezy -> plan code, cosi' il
 * webhook puo' capire quale piano e' stato comprato senza if/else sparsi.
 *
 * I variant_id si trovano nel dashboard LS: Products -> click sul prodotto
 * -> Variants -> "Edit" -> URL contiene /variants/<id>. Vanno messi in
 * .env (LS_VARIANT_*); qui li leggiamo con fallback null.
 *
 * NOTA su 'features': non e' un set di "tab" ma un set di capability
 * lato server. Il client mostra/nasconde le tab in base a queste.
 *  - "audio"    : download brani (tab Brani)
 *  - "video"    : download video YouTube/TikTok/IG/FB (tab Video)
 *  - "record"   : registrazione audio (tab Registra)
 *  - "metadata" : editor metadati (tab Metadati)
 *  - "upgrade"  : upgrade qualita' libreria (tab Upgrade)
 *
 * Limiti giornalieri (daily_limit, null = unlimited): contiamo come "uso"
 * ogni avvio di un job di download (1 chiamata a /api/usage/consume) E
 * ogni salvataggio metadati. La registrazione e' un'azione bound a 1
 * file/giorno: pure 1.
 */

export const PLANS = {
  basic: {
    code: "basic",
    name: "Basic",
    price_eur: 2.99,
    interval: "monthly",
    daily_limit: 10,
    features: ["audio"],
    is_subscription: true,
    ls_variant_env: "LS_VARIANT_BASIC",
  },
  pro: {
    code: "pro",
    name: "Pro",
    price_eur: 5.99,
    interval: "monthly",
    daily_limit: 30,
    features: ["audio", "video", "record", "metadata", "upgrade"],
    is_subscription: true,
    ls_variant_env: "LS_VARIANT_PRO",
  },
  premium: {
    code: "premium",
    name: "Premium",
    price_eur: 9.99,
    interval: "monthly",
    daily_limit: 150,
    features: ["audio", "video", "record", "metadata", "upgrade"],
    is_subscription: true,
    ls_variant_env: "LS_VARIANT_PREMIUM",
  },
  annual: {
    code: "annual",
    name: "Annual",
    price_eur: 49.90,
    interval: "annual_one_time",
    daily_limit: null,
    features: ["audio", "video", "record", "metadata", "upgrade"],
    is_subscription: false,
    ls_variant_env: "LS_VARIANT_ANNUAL",
  },
};

export const PLAN_CODES = Object.keys(PLANS);

/** Ritorna il plan code mappato a un LS variant_id, o null se non noto. */
export function planByVariantId(variantId) {
  const vid = String(variantId || "").trim();
  if (!vid) return null;
  for (const code of PLAN_CODES) {
    const envName = PLANS[code].ls_variant_env;
    const mapped = String(process.env[envName] || "").trim();
    if (mapped && mapped === vid) return code;
  }
  return null;
}

export function getPlan(code) {
  return PLANS[code] || null;
}

/** Forma stabile per inclusione nei JWT claims / risposte API. */
export function planSnapshot(code) {
  const p = getPlan(code);
  if (!p) return null;
  return {
    code: p.code,
    name: p.name,
    daily_limit: p.daily_limit,
    features: p.features.slice(),
    is_subscription: p.is_subscription,
  };
}

export function hasFeature(code, feature) {
  const p = getPlan(code);
  return !!(p && p.features.includes(feature));
}

/** Durata annual one-time in secondi (365 giorni). */
export const ANNUAL_TTL_SECONDS = 365 * 24 * 3600;
