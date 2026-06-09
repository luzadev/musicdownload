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
import urllib.parse
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
def _plan_snapshot(cfg: dict) -> dict:
    """Estrae i dati del piano dal config (popolati da activate/validate)."""
    code = (cfg.get("plan_code") or "").strip()
    if not code:
        return {}
    return {
        "code": code,
        "name": (cfg.get("plan_name") or "").strip() or code.title(),
        "features": list(cfg.get("plan_features") or []),
        "daily_limit": cfg.get("plan_daily_limit"),  # puo' essere None
        "is_subscription": bool(cfg.get("plan_is_subscription")),
        "expires_at": int(cfg.get("plan_expires_at") or 0),
        "period_end": int(cfg.get("plan_period_end") or 0),
    }


def has_feature(name: str, config: Optional[dict] = None) -> bool:
    """True se il piano corrente include la feature richiesta."""
    cfg = config or load_config()
    plan = _plan_snapshot(cfg)
    if not plan:
        return False
    return name in (plan.get("features") or [])


def get_plan(config: Optional[dict] = None) -> dict:
    """Ritorna il dict del piano corrente, oppure {} se non noto."""
    return _plan_snapshot(config or load_config())


def get_status(config: Optional[dict] = None) -> dict:
    """Ritorna lo stato corrente della licenza per la UI.

    Chiavi: licensed (bool), reason (str), email, key, activated_at,
    last_validated_at, days_since_validation, expires_soon (bool),
    needs_revalidation (bool), plan (dict).
    """
    cfg = config or load_config()
    token = (cfg.get("license_token") or "").strip()
    key = (cfg.get("license_key") or "").strip()
    email = (cfg.get("license_email") or "").strip()
    activated = int(cfg.get("license_activated_at") or 0)
    last_val = int(cfg.get("last_validated_at") or 0)
    plan = _plan_snapshot(cfg)

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
            "plan": plan,
        }

    # Scadenza locale derivata dai claims (best-effort: la verita' e' sul server).
    t = _now()
    expires_at = plan.get("expires_at") or 0
    period_end = plan.get("period_end") or 0
    if expires_at and expires_at < t:
        return {
            "licensed": False, "reason": "plan_expired", "email": email, "key": key,
            "activated_at": activated, "last_validated_at": last_val,
            "days_since_validation": 0, "needs_revalidation": True, "plan": plan,
        }
    if period_end and period_end < t:
        return {
            "licensed": False, "reason": "subscription_expired", "email": email, "key": key,
            "activated_at": activated, "last_validated_at": last_val,
            "days_since_validation": 0, "needs_revalidation": True, "plan": plan,
        }

    days_since = (t - last_val) // 86400 if last_val else 999
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
            "plan": plan,
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
        "plan": plan,
    }


def is_licensed() -> bool:
    """Helper rapido per gating delle azioni."""
    return get_status()["licensed"]


def _store_plan_from_response(cfg: dict, resp: dict, token: str) -> None:
    """Aggiorna il config con i campi del piano estratti dalla risposta API.

    Server risposta puo' contenere:
      - plan: {code, name, daily_limit, features, is_subscription}
      - expires_at: epoch (annual)
      - period_end: epoch (subscription)
    Come fallback decodifica i claims dal JWT.
    """
    plan = resp.get("plan") if isinstance(resp.get("plan"), dict) else None
    claims = _decode_jwt_claims(token) if token else {}

    code = ""
    name = ""
    features = []
    daily_limit = None
    is_sub = False
    if plan:
        code = (plan.get("code") or "").strip()
        name = (plan.get("name") or "").strip()
        features = list(plan.get("features") or [])
        daily_limit = plan.get("daily_limit")
        is_sub = bool(plan.get("is_subscription"))
    else:
        code = (claims.get("plan") or "").strip()
        name = (claims.get("plan_name") or "").strip()
        features = list(claims.get("features") or [])
        daily_limit = claims.get("daily_limit")
        is_sub = bool(claims.get("is_subscription"))

    cfg["plan_code"] = code
    cfg["plan_name"] = name
    cfg["plan_features"] = features
    cfg["plan_daily_limit"] = daily_limit  # None ammesso (unlimited)
    cfg["plan_is_subscription"] = is_sub
    cfg["plan_expires_at"] = int(resp.get("expires_at") or claims.get("expires_at") or 0)
    cfg["plan_period_end"] = int(resp.get("period_end") or claims.get("period_end") or 0)


def _clear_plan(cfg: dict) -> None:
    cfg["plan_code"] = ""
    cfg["plan_name"] = ""
    cfg["plan_features"] = []
    cfg["plan_daily_limit"] = None
    cfg["plan_is_subscription"] = False
    cfg["plan_expires_at"] = 0
    cfg["plan_period_end"] = 0


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
    _store_plan_from_response(cfg, resp, token)
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
        _clear_plan(cfg)
        save_config(cfg)
        return get_status(cfg)

    # Server puo' inviare un token rinnovato (rotazione)
    new_token = (resp.get("token") or "").strip()
    if new_token:
        cfg["license_token"] = new_token
    cfg["last_validated_at"] = _now()
    _store_plan_from_response(cfg, resp, cfg.get("license_token", ""))
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
    _clear_plan(cfg)
    save_config(cfg)
    return get_status(cfg)


# ============================================================
# Quota giornaliera
# ============================================================
def _http_json(method: str, path: str, body: Optional[dict] = None,
               token: Optional[str] = None, timeout: int = 10) -> dict:
    """Helper unificato per GET/POST con Authorization Bearer."""
    url = LICENSE_API_URL.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "User-Agent": f"MusicTools/{VERSION}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_data = json.loads(err_body) if err_body else {}
        except Exception:
            err_data = {}
        err_data.setdefault("error", e.reason or f"HTTP {e.code}")
        err_data["_status"] = e.code
        return err_data
    except urllib.error.URLError as e:
        raise LicenseNetworkError(str(e.reason) if hasattr(e, "reason") else str(e))
    except (TimeoutError, OSError) as e:
        raise LicenseNetworkError(str(e))


def get_quota_status() -> dict:
    """Legge lo stato quota dal server. Ritorna dict con plan/used/limit/remaining.

    Solleva LicenseError se il server rifiuta (401/403); LicenseNetworkError
    in caso di problemi di rete.
    """
    cfg = load_config()
    token = (cfg.get("license_token") or "").strip()
    if not token:
        raise LicenseError("Licenza non attivata.")
    resp = _http_json("GET", "/api/usage/status", token=token)
    if resp.get("_status") and resp["_status"] >= 400:
        raise LicenseError(resp.get("error") or "Errore stato quota.")
    return resp


def consume_quota(feature: str = "") -> dict:
    """Incrementa la quota giornaliera prima di un download.

    Ritorna {allowed, used, limit, remaining, plan, day}.
    Se il server risponde 429 -> allowed=False (l'utente ha raggiunto il limite).
    Per i piani unlimited (annual), allowed=True sempre.
    Solleva LicenseError per 401/403; LicenseNetworkError per problemi di rete.
    """
    cfg = load_config()
    token = (cfg.get("license_token") or "").strip()
    if not token:
        raise LicenseError("Licenza non attivata.")
    body = {"feature": feature} if feature else {}
    resp = _http_json("POST", "/api/usage/consume", body=body, token=token)
    status_code = resp.pop("_status", 0)
    if status_code == 401 or status_code == 403:
        raise LicenseError(resp.get("error") or "Licenza non valida.")
    if status_code == 429:
        # Limite raggiunto, ma e' una risposta strutturata: ritorniamo
        # il dict cosi' la UI puo' mostrare i numeri.
        resp.setdefault("allowed", False)
        return resp
    if status_code and status_code >= 400:
        raise LicenseError(resp.get("error") or f"Errore quota ({status_code}).")
    resp.setdefault("allowed", True)
    return resp
