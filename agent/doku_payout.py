"""
agent/doku_payout.py
DOKU RDL Disbursement → GoPay (Fixed & Rebuilt)

FIXES:
- [x] hmac.new() → hmac.new() tidak ada di Python stdlib.
      Yang benar: hmac.new(key, msg, digestmod) ← ini sebenarnya valid,
      tapi nama variabel bentrok dengan builtin. Diubah ke nama yang jelas.
- [x] Timestamp format dipastikan ISO8601 UTC dengan Z suffix
- [x] Error handling lebih lengkap
- [x] Logging lebih informatif untuk debugging
"""

import base64
import hashlib
import hmac as hmac_lib   # alias agar tidak bentrok dengan variabel lokal
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx

# ====================== CONFIG ======================
DOKU_CLIENT_ID  = os.getenv("DOKU_CLIENT_ID", "")
DOKU_SECRET_KEY = os.getenv("DOKU_SECRET_KEY", "")
DOKU_ENV        = os.getenv("DOKU_ENV", "sandbox")

BASE_URL = (
    "https://api-sandbox.doku.com"
    if DOKU_ENV == "sandbox"
    else "https://api.doku.com"
)
ENDPOINT = "/sac-rdl/v1/rdl-disbursements"


# ====================== SIGNATURE ======================

def _minify_json(body: dict) -> str:
    """Minify JSON body tanpa spasi — sesuai requirement DOKU."""
    return json.dumps(body, separators=(',', ':'), ensure_ascii=False)


def _generate_signature(
    client_id: str,
    request_id: str,
    timestamp: str,
    request_target: str,
    body: dict,
) -> str:
    """
    Generate HMAC-SHA256 signature sesuai dokumentasi DOKU RDL.

    Format string_to_sign:
        Client-Id:{client_id}\\n
        Request-Id:{request_id}\\n
        Request-Timestamp:{timestamp}\\n
        Request-Target:{request_target}\\n
        Digest:{digest_base64}
    """
    # Step 1: SHA256 body → base64
    minified_body = _minify_json(body)
    body_digest   = hashlib.sha256(minified_body.encode("utf-8")).digest()
    digest_b64    = base64.b64encode(body_digest).decode("utf-8")

    # Step 2: Susun string komponen
    string_to_sign = (
        f"Client-Id:{client_id}\n"
        f"Request-Id:{request_id}\n"
        f"Request-Timestamp:{timestamp}\n"
        f"Request-Target:{request_target}\n"
        f"Digest:{digest_b64}"
    )

    # Step 3: HMAC-SHA256 — FIX: gunakan hmac_lib alias, bukan hmac.new() yang ambigu
    secret_bytes = DOKU_SECRET_KEY.encode("utf-8")
    message_bytes = string_to_sign.encode("utf-8")

    mac       = hmac_lib.new(secret_bytes, message_bytes, hashlib.sha256)
    signature = base64.b64encode(mac.digest()).decode("utf-8")

    return f"HMACSHA256={signature}"


# ====================== MAIN FUNCTION ======================

async def doku_rdl_payout_to_gopay(
    amount_idr: int,
    gopay_phone: str,
    user_id: Optional[int] = None,
    notes: str = "Reward Zilf.ai",
) -> Dict:
    """
    Kirim payout via DOKU RDL Disbursement ke GoPay.

    Args:
        amount_idr:   Jumlah dalam Rupiah (integer)
        gopay_phone:  Nomor HP GoPay (08xxxxxxxxxx)
        user_id:      ID pengguna (opsional, untuk referensi)
        notes:        Deskripsi transaksi

    Returns:
        Dict berisi response DOKU + status_code + request_id

    Raises:
        ValueError: Jika DOKU_CLIENT_ID atau DOKU_SECRET_KEY belum di-set
    """
    if not DOKU_CLIENT_ID or not DOKU_SECRET_KEY:
        raise ValueError(
            "DOKU_CLIENT_ID dan DOKU_SECRET_KEY belum dikonfigurasi. "
            "Tambahkan ke environment variables di Railway."
        )

    request_id = str(uuid.uuid4())

    # FIX: Format timestamp ISO8601 UTC dengan Z suffix (bukan +00:00)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Transaction ID yang unik
    tx_id = f"zilf_payout_{int(datetime.now(timezone.utc).timestamp())}"
    if user_id:
        tx_id = f"{tx_id}_u{user_id}"

    # Payload DOKU RDL Disbursement
    payload = {
        "transaction": {
            "id": tx_id,
            "amount": amount_idr,
            "description": notes,
        },
        "account_destination": {
            "code": "07",                       # Kode channel GoPay di DOKU
            "account_bank_number": gopay_phone,  # Nomor HP tujuan GoPay
            "account_bank_name": "GoPay",
            "address": "Indonesia",
        },
    }

    signature = _generate_signature(
        client_id=DOKU_CLIENT_ID,
        request_id=request_id,
        timestamp=timestamp,
        request_target=ENDPOINT,
        body=payload,
    )

    headers = {
        "Client-Id": DOKU_CLIENT_ID,
        "Request-Id": request_id,
        "Request-Timestamp": timestamp,
        "Signature": signature,
        "Content-Type": "application/json",
    }

    url = f"{BASE_URL}{ENDPOINT}"

    print(f"[DOKU] Sending payout | URL: {url} | Amount: Rp{amount_idr:,} | To: {gopay_phone} | Req-ID: {request_id}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            return {
                "status_code": 408,
                "request_id": request_id,
                "error": "Request timeout ke DOKU API",
            }
        except httpx.RequestError as e:
            return {
                "status_code": 503,
                "request_id": request_id,
                "error": f"Koneksi ke DOKU gagal: {str(e)}",
            }

        # Parse response
        try:
            result = response.json()
        except Exception:
            result = {"raw": response.text}

        result["status_code"] = response.status_code
        result["request_id"]  = request_id

        print(
            f"[DOKU] Response | Status: {response.status_code} | "
            f"Req-ID: {request_id} | Body: {json.dumps(result, ensure_ascii=False)[:300]}"
        )

        return result