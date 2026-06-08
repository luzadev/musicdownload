# MusicTools — License & Update API

Backend Node.js per gestire attivazione licenze, validazione e distribuzione binari MusicTools.

## Stack

- **Node.js 20 + Express 4**
- **MariaDB 10.11** (locale, localhost:3306)
- **PM2** per process management
- **Apache 2.4** come reverse proxy verso `127.0.0.1:4002`
- **Resend** per email transazionali
- **Lemon Squeezy** per i pagamenti (webhook -> `/api/webhook/lemonsqueezy`)

Tutto gira sull'hosting esistente (`musictools@musictools.djluza.com`), zero costi aggiuntivi.

## Struttura

```
server/
  src/
    server.js        # Express app
    db.js            # pool mysql2
    license.js       # activate / validate / deactivate
    updates.js       # /api/latest + /api/download
    lemonsqueezy.js  # webhook ordini
    email.js         # Resend client
    jwt.js           # JWT HS256 senza dipendenze
    migrate.js       # runner SQL idempotente
  migrations/
    0001_init.sql    # schema licenses / activations / releases
  ecosystem.config.cjs   # PM2
  .env.example
  package.json
```

## Setup iniziale sul server

Una volta sola, da SSH `musictools@musictools.djluza.com`:

### 1) Crea database e utente MariaDB

Sul server (richiede root o l'utente master DB del tuo hosting — di solito Virtualmin lo crea per te dal pannello "Edit Databases"):

```sql
CREATE DATABASE musictools_licenses CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'musictools'@'localhost' IDENTIFIED BY 'PASSWORD_FORTE';
GRANT ALL PRIVILEGES ON musictools_licenses.* TO 'musictools'@'localhost';
FLUSH PRIVILEGES;
```

In alternativa via Virtualmin: **Edit Databases → Create a new database**, poi tab **Manage** → crea utente con password.

### 2) Clona o sincronizza il codice

Due opzioni:

**A. Via git** (consigliato):
```bash
cd ~
git clone https://github.com/luzadev/musicdownload.git app-src
ln -s app-src/server api
cd api
npm install --production
```

**B. Via rsync da locale** (più semplice se preferisci non lasciare codice client sul server):
```bash
# Da Mac:
rsync -avz --exclude node_modules /Users/luciano/Downloads/Progetti2026/MusicDownload/server/ musictools@musictools.djluza.com:~/api/
# Poi SSH e:
cd ~/api && npm install --production
```

### 3) Configura .env

```bash
cd ~/api
cp .env.example .env
nano .env   # compila tutti i valori — vedi sotto
```

Per generare `JWT_SECRET`:
```bash
openssl rand -base64 32
```

### 4) Migrate

```bash
cd ~/api
npm run migrate
```

Output atteso:
```
[migrate] applico 0001_init.sql
[migrate] ok 0001_init.sql
[migrate] done
```

### 5) Avvia con PM2

```bash
cd ~/api
mkdir -p logs
pm2 start ecosystem.config.cjs
pm2 save
# Test:
curl -s http://127.0.0.1:4002/api/health
# -> {"ok":true,"version":"v1.5.2"}
```

### 6) Apache reverse proxy

Devi dire ad Apache che le richieste a `musictools.djluza.com/api/*` vanno a `127.0.0.1:4002`.

**Via Virtualmin** (consigliato):

1. Vai su **Webmin → Servers → Apache Webserver**
2. Clicca sul VirtualHost di `musictools.djluza.com` (porta 443)
3. Sezione **Aliases and redirects** o **Edit Directives**, aggiungi prima di `</VirtualHost>`:

```apache
# MusicTools API
ProxyPreserveHost On
ProxyRequests Off

# Webhook: passa raw body senza alterazioni
<Location /api/>
    ProxyPass http://127.0.0.1:4002/api/
    ProxyPassReverse http://127.0.0.1:4002/api/
</Location>
```

4. Apply changes.

**Verifica moduli Apache attivi** (da SSH se hai sudo):
```bash
apache2ctl -M | grep -E 'proxy|proxy_http'
# Devono comparire proxy_module e proxy_http_module
```
Se mancano, abilitali (sudo richiesto):
```bash
sudo a2enmod proxy proxy_http
sudo systemctl reload apache2
```

### 7) Verifica end-to-end

Da qualsiasi posto:
```bash
curl -s https://musictools.djluza.com/api/health
# -> {"ok":true,"version":"v1.5.2"}
```

## Workflow pubblicazione release

1. GitHub Actions builda i due zip (gia in place).
2. Carica gli zip sul server in `~/builds/<version>/`:
   ```bash
   ssh musictools@musictools.djluza.com 'mkdir -p ~/builds/v1.5.3'
   scp MusicTools-macOS.zip   musictools@musictools.djluza.com:~/builds/v1.5.3/
   scp MusicTools-Windows.zip musictools@musictools.djluza.com:~/builds/v1.5.3/
   ```
3. Inserisci il record in MariaDB:
   ```bash
   ssh musictools@musictools.djluza.com 'mariadb musictools_licenses' <<SQL
   INSERT INTO releases (version, platform, file_path, size_bytes, sha256, notes, published_at)
   VALUES ('v1.5.3', 'macos',   'v1.5.3/MusicTools-macOS.zip',   12345, '<sha256>', 'Note...', UNIX_TIMESTAMP()),
          ('v1.5.3', 'windows', 'v1.5.3/MusicTools-Windows.zip', 67890, '<sha256>', 'Note...', UNIX_TIMESTAMP());
   SQL
   ```
4. Aggiorna `LATEST_VERSION` nel `.env` e `pm2 reload musictools-api`.

In futuro: script o workflow GitHub Actions che fa tutto in automatico.

## Operazioni quotidiane

| Cosa | Comando |
|---|---|
| Reload codice dopo deploy | `pm2 reload musictools-api` |
| Vedere log live | `pm2 logs musictools-api` |
| Stato | `pm2 status` |
| Errori recenti | `pm2 logs musictools-api --err --lines 100` |
| Restart hard | `pm2 restart musictools-api` |
| Stop | `pm2 stop musictools-api` |
| Console DB | `mariadb -u musictools -p musictools_licenses` |

## Endpoints

| Metodo | Path | Auth | Descrizione |
|---|---|---|---|
| POST | `/api/license/activate` | — | Attiva licenza, ritorna JWT |
| POST | `/api/license/validate` | — (token nel body) | Rivalida + ruota token |
| POST | `/api/license/deactivate` | — (token nel body) | Libera uno slot |
| GET  | `/api/latest?platform=…` | Bearer token (opzionale) | Versione + URL download firmato |
| GET  | `/api/download?file=…&exp=…&sig=…` | Firma HMAC | Stream del binario |
| POST | `/api/webhook/lemonsqueezy` | X-Signature HMAC | Crea licenza dopo ordine |
| GET  | `/api/health` | — | Healthcheck |

## Backup

Aggiungi un cronjob daily:

```bash
# crontab -e
0 4 * * * mariadb-dump musictools_licenses | gzip > ~/backups/musictools-$(date +\%F).sql.gz && find ~/backups -name 'musictools-*.sql.gz' -mtime +30 -delete
```

## Costi

- **Hosting**: gia pagato (server condiviso esistente)
- **Lemon Squeezy**: 5% + $0.50 per transazione = ~5 EUR su un acquisto da 39,90 EUR
- **Resend**: free fino a 3k email/mese (= ~3k licenze/mese, oltre serve piano $20)
- **Totale fisso**: 0 EUR/mese
