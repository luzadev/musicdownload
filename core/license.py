"""Gestione licenze MusicTools.

Flusso:
1. L'utente compra su musictools.djluza.com -> riceve license_key via email.
2. Al primo avvio l'app mostra schermata bloccante: chiede email + key.
3. activate() chiama POST {LICENSE_API_URL}/api/license/activate
   passando key, email, device_id (+ device_name). Il server:
   - verifica che la key esista e non abbia superato max attivazioni;
   - registra il device_id come attivo;
   - ritorna un JWT con claims {sub: license_id, exp, email, key_id}.
4. Il token viene salvato in config.json. Il client lo considera valido
   per LICENSE_REVALIDATE_DAYS senza ricontrollare il server; oltre
   LICENSE_GRACE_DAYS chiede sempre nuova validazione online.
5. validate() chiama POST /api/license/validate con {token, device_id}
   in background. Il server puo' revocare (refund, abuse) ritornando
   401 -> il client cancella il token e torna a schermata attivazione.

Nota: non verifichiamo la firma JWT lato client (servirebbe la public
key). Ci fidiamo del token perche' e' uscito dal server al momento
dell'attivazione, e ogni N giorni lo facciamo rivalidare. Per i refund
non immediati basta il check periodico.
"""

from __future__ import annotations

import base64
import json
import platform
import time
import urllib.error
import urllib.request
import uuid
from typing import Optional

from core.config import (
    LICENSE_API_URL,
    LICENSE_GRACE_DAYS,
    LICENSE_REVALIDATE_DAYS,
    VERSION,
    load_config,
    save_config,
)


_HTTP_TIMEOUT = 15  # secondi


# ============================================================
# Errori
# ============================================================
class LicenseError(Exception):
    """Errore di attivazione/validazione licenza."""


class LicenseNetworkError(LicenseError):
    """Impossibile raggiungere il server (offline, DNS, ecc.)."""


# ============================================================
# Utility
# ============================================================
def _now() -> int:
    return int(time.time())


def _ensure_device_id(config: dict) -> str:
    """Garantisce che config abbia un device_id stabile e univoco."""
    did = (config.get("device_id") or "").strip()
    if not did:
        did = str(uuid.uuid4())
        config["device_id"] = did
        save_config(config)
    return did


def _device_name() -> str:
    """Nome leggibile per identificare il device lato server (UI utente)."""
    try:
        return f"{platform.node() or 'device'} ({platform.system()})"
    except Exception:
        return "device"


def _decode_jwt_claims(token: str) -> dict:
    """Decodifica i claims di un JWT senza verificare la firma.

    Ritorna {} se il token e' malformato. La verifica vera e' fatta
    dal server quando rivalidiamo online; qui ci serve solo leggere
    exp/email per la UI.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return {}
        payload = parts[1]
        # base64url -> base64 standard (padding)
        payload += "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _http_post(path: str, body: dict) -> dict:
    """POST JSON verso LICENSE_API_URL{path}. Ritorna il JSON di risposta.

    Solleva LicenseNetworkError per problemi di rete e LicenseError
    per risposte HTTP 4xx/5xx (con messaggio dal server quando disponibile).
    """
    url = LICENSE_API_URL.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"MusicTools/{VERSION}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_data = json.loads(err_body)
            msg = err_data.get("error") or err_data.get("message") or e.reason
        except Exception:
            msg = e.reason or f"HTTP {e.code}"
        raise LicenseError(str(msg))
    except urllib.error.URLError as e:
        raise LicenseNetworkError(str(e.reason) if hasattr(e, "reason") else str(e))
    except (TimeoutError, OSError) as e:
        raise LicenseNetworkError(str(e))


# ============================================================
# API pubblica
# ============================================================
def get_status(config: Optional[dict] = None) -> dict:
    """Ritorna lo stato corrente della licenza per la UI.

    Chiavi: licensed (bool), reason (str), email, key, activated_at,
    last_validated_at, days_since_validation, expires_soon (bool),
    needs_revalidation (bool).
    """
    cfg = config or load_config()
    token = (cfg.get("license_token") or "").strip()
    key = (cfg.get("license_key") or "").strip()
    email = (cfg.get("license_email") or "").strip()
    activated = int(cfg.get("license_activated_at") or 0)
    last_val = int(cfg.get("last_validated_at") or 0)

    if not token or not key:
        return {
            "licensed": False,
            "reason": "not_activated",
            "email": "",
            "key": "",
            "activated_at": 0,
            "last_validated_at": 0,
            "days_since_validation": 0,
            "needs_revalidation": False,
        }

    days_since = (_now() - last_val) // 86400 if last_val else 999
    needs_reval = days_since >= LICENSE_REVALIDATE_DAYS
    grace_expired = days_since >= LICENSE_GRACE_DAYS

    if grace_expired:
        return {
            "licensed": False,
            "reason": "grace_expired",
            "email": email,
            "key": key,
            "activated_at": activated,
            "last_validated_at": last_val,
            "days_since_validation": days_since,
            "needs_revalidation": True,
        }

    return {
        "licensed": True,
        "reason": "ok",
        "email": email,
        "key": key,
        "activated_at": activated,
        "last_validated_at": last_val,
        "days_since_validation": days_since,
        "needs_revalidation": needs_reval,
    }


def is_licensed() -> bool:
    """Helper rapido per gating delle azioni."""
    return get_status()["licensed"]


def activate(license_key: str, email: str) -> dict:
    """Attiva una licenza contro il server. Salva token su success.

    Ritorna dict con le chiavi di get_status(). Solleva LicenseError
    o LicenseNetworkError in caso di fallimento.
    """
    key = (license_key or "").strip()
    mail = (email or "").strip().lower()
    if not key or not mail:
        raise LicenseError("Inserisci email e chiave di licenza.")

    cfg = load_config()
    device_id = _ensure_device_id(cfg)

    resp = _http_post("/api/license/activate", {
        "key": key,
        "email": mail,
        "device_id": device_id,
        "device_name": _device_name(),
        "app_version": VERSION,
    })

    token = (resp.get("token") or "").strip()
    if not token:
        raise LicenseError(resp.get("error") or "Risposta server non valida.")

    now = _now()
    cfg["license_key"] = key
    cfg["license_email"] = mail
    cfg["license_token"] = token
    cfg["license_activated_at"] = int(resp.get("activated_at") or now)
    cfg["last_validated_at"] = now
    save_config(cfg)
    return get_status(cfg)


def validate() -> dict:
    """Rivalida il token corrente contro il server (background).

    Aggiorna last_validated_at su success. Su 401 (revoca/refund)
    azzera il token cosi' la prossima get_status ritorna not_activated.
    Su errori di rete non fa nulla (resta valido fino al grace).
    """
    cfg = load_config()
    token = (cfg.get("license_token") or "").strip()
    if not token:
        return get_status(cfg)

    device_id = _ensure_device_id(cfg)
    try:
        resp = _http_post("/api/license/validate", {
            "token": token,
            "device_id": device_id,
            "app_version": VERSION,
        })
    except LicenseNetworkError:
        return get_status(cfg)
    except LicenseError:
        # Server ha risposto 4xx -> token non piu valido
        cfg["license_token"] = ""
        cfg["last_validated_at"] = 0
        save_config(cfg)
        return get_status(cfg)

    # Server puo' inviare un token rinnovato (rotazione)
    new_token = (resp.get("token") or "").strip()
    if new_token:
        cfg["license_token"] = new_token
    cfg["last_validated_at"] = _now()
    save_config(cfg)
    return get_status(cfg)


def deactivate(release_remote: bool = True) -> dict:
    """Disattiva la licenza su questo device.

    Se release_remote, notifica il server cosi' libera lo slot
    di attivazione (utile per spostare l'app su un altro device).
    Sempre azzera i campi licenza locali, anche se il server e' offline.
    """
    cfg = load_config()
    token = (cfg.get("license_token") or "").strip()
    device_id = (cfg.get("device_id") or "").strip()

    if release_remote and token and device_id:
        try:
            _http_post("/api/license/deactivate", {
                "token": token,
                "device_id": device_id,
            })
        except (LicenseError, LicenseNetworkError):
            # Lo facciamo local-only se il server non risponde.
            pass

    cfg["license_key"] = ""
    cfg["license_email"] = ""
    cfg["license_token"] = ""
    cfg["license_activated_at"] = 0
    cfg["last_validated_at"] = 0
    save_config(cfg)
    return get_status(cfg)
