# MusicTools License & Update API

Cloudflare Worker che gestisce attivazione licenze, validazione e distribuzione binari MusicTools.

## Stack
- **Cloudflare Workers** (compute serverless, free tier 100k req/giorno)
- **Cloudflare D1** (sqlite gestito, free tier 5GB)
- **Cloudflare R2** (storage zip binari, free tier 10GB)
- **Lemon Squeezy** (Merchant of Record per i pagamenti, gestisce IVA UE)
- **Resend** (invio email license-key, free tier 3k email/mese)

## Setup iniziale

Una volta sola, da terminale dentro `server/`:

```bash
npm install
npx wrangler login                        # autenticati a Cloudflare

# 1. Crea il database D1
npx wrangler d1 create musictools-licenses
# -> copia il database_id stampato nel wrangler.toml

# 2. Applica lo schema
npm run db:migrate:prod

# 3. Crea il bucket R2 per i binari
npx wrangler r2 bucket create musictools-builds

# 4. Imposta i secret (NON in chiaro nel wrangler.toml)
npx wrangler secret put JWT_SECRET                   # > openssl rand -base64 32
npx wrangler secret put LEMONSQUEEZY_SIGNING_SECRET  # > dal dashboard LS
npx wrangler secret put RESEND_API_KEY               # > dal dashboard Resend

# 5. Deploy
npm run deploy
```

## DNS

Su Cloudflare Dashboard > djluza.com > DNS aggiungi:

```
musictools  CNAME  <subdomain-worker>.workers.dev   proxied
```

Poi vai su Workers & Pages > musictools-api > Settings > Triggers > Custom Domains
e aggiungi `musictools.djluza.com`.

## Endpoints

| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| POST | `/api/license/activate` | — | Attiva licenza, ritorna JWT |
| POST | `/api/license/validate` | — (token nel body) | Rivalida + ruota token |
| POST | `/api/license/deactivate` | — (token nel body) | Libera uno slot |
| GET  | `/api/latest?platform=…` | Bearer token (opzionale) | Versione + URL download firmato |
| POST | `/api/webhook/lemonsqueezy` | X-Signature HMAC | Crea licenza dopo ordine |
| GET  | `/api/health` | — | Healthcheck |

## Workflow pubblicazione release

1. GitHub Actions builda macOS e Windows zip (gia in place).
2. Step manuale (per ora): scarica i due zip, caricali su R2:
   ```bash
   npx wrangler r2 object put musictools-builds/v1.5.3/MusicTools-macOS.zip --file=MusicTools-macOS.zip
   npx wrangler r2 object put musictools-builds/v1.5.3/MusicTools-Windows.zip --file=MusicTools-Windows.zip
   ```
3. Inserisci il record `releases`:
   ```sql
   INSERT INTO releases (version, platform, r2_key, size_bytes, sha256, notes, published_at)
   VALUES ('v1.5.3', 'macos', 'v1.5.3/MusicTools-macOS.zip', 12345, '<sha256>', 'Note...', strftime('%s','now'));
   ```
   (eseguibile da `npx wrangler d1 execute musictools-licenses --remote --command "..."`)

In futuro: workflow GitHub Actions che fa upload R2 + insert D1 in automatico.

## TODO

- [ ] Implementare `/api/download` che verifica firma e fa stream da R2
- [ ] Endpoint admin per emettere licenze a mano (es. recensori, refund)
- [ ] Rate limiting con KV su `/api/license/activate` (anti brute-force)
- [ ] Cron worker giornaliero che marca le licenze inattive da > 1 anno

## Costi

A 0 vendite: **0€/mese** (tutto in free tier).
A 100 vendite/mese: ~5€ Lemon Squeezy commission + 0€ Cloudflare = ~5€.
