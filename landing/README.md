# MusicTools — Landing page

Sito vetrina + checkout per MusicTools, deployato su Cloudflare Pages al dominio `musictools.djluza.com`.

## Struttura

```
landing/
  index.html           # landing principale
  css/style.css        # tema dark coerente con l'app
  js/main.js           # FAQ accordion, animazioni scroll, hook Lemon Squeezy
  assets/              # favicon, immagini eventuali
  legal/
    terms.html         # termini di servizio
    privacy.html       # informativa privacy GDPR
    refund.html        # politica rimborsi
  _headers             # security + cache (Cloudflare Pages syntax)
  _redirects           # redirect rules
```

Nessun build step. Tutto e' HTML/CSS/JS statico servito così com'è.

## Anteprima locale

```bash
cd landing
python3 -m http.server 8080
# apri http://localhost:8080
```

Su `file://` Lemon Squeezy overlay non funziona — ma il sito si vede tutto.

## Deploy su Cloudflare Pages

**Una volta sola:**

1. Vai su <https://dash.cloudflare.com> → **Workers & Pages** → **Create application** → **Pages** → **Connect to Git**.
2. Scegli il repo `luzadev/musicdownload`.
3. Configura:
   - **Production branch**: `main`
   - **Build command**: *(lascia vuoto)*
   - **Build output directory**: `landing`
   - **Root directory**: *(lascia vuoto)*
4. Salva. La build parte automatica — l'URL iniziale sara' `<project>.pages.dev`.
5. Una volta verde, vai su **Custom domains** → **Set up a custom domain** → digita `musictools.djluza.com` → conferma.
6. Cloudflare crea automaticamente il CNAME se il dominio e' gia su Cloudflare DNS.

Ogni `git push origin main` rilancia la build di Pages — push-to-deploy gratis.

## Routing /api/* vs landing

Il Worker di `server/` deve essere associato alla route `musictools.djluza.com/api/*` (vedi `server/README.md`).
Pages serve tutto il resto. Verifica nel dashboard:

- **Workers & Pages** → `musictools-api` → **Settings** → **Triggers**:
  - Aggiungi route `musictools.djluza.com/api/*`
- **Pages** → `musictools-landing` (o nome che scegli) → **Custom domains**:
  - `musictools.djluza.com`

Cloudflare applica prima la regola del Worker (path-specific) e poi quella di Pages (catch-all).

## Da fare prima del lancio

- [ ] Sostituisci `REPLACE_WITH_LS_PRODUCT_URL` in `index.html` con l'URL prodotto Lemon Squeezy
- [ ] Crea immagine OG 1200x630 e referenziarla nei meta `og:image`
- [ ] Aggiungi screenshot reali (sostituiscono il mockup CSS nell'hero se preferisci)
- [ ] Verifica i tre documenti legali con un consulente fiscale se vendi in regime di forfettario / partita IVA italiana
- [ ] Aggiungi Google Search Console (verification meta) per indicizzazione

## Analytics

Puoi aggiungere Cloudflare Web Analytics (gratuito, no cookie) dal dashboard Pages → Analytics. Si attiva con un click — niente codice da incollare.
