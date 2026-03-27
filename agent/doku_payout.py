import httpx
import hashlib
import hmac
import base64
import json
import uuid
from datetime import datetime, timezone
import os
from typing import Optional, Dict

DOKU_CLIENT_ID = os.getenv("DOKU_CLIENT_ID")
DOKU_SECRET_KEY = os.getenv("DOKU_SECRET_KEY")
DOKU_ENV = os.getenv("DOKU_ENV", "sandbox")

BASE_URL = "https://api-sandbox.doku.com" if DOKU_ENV == "sandbox" else "https://api.doku.com"
ENDPOINT = "/sac-rdl/v1/rdl-disbursements"

def _minify_json(body: dict) -> str:
    """Hilangkan whitespace ekstra sesuai doc DOKU"""
    return json.dumps(body, separators=(',', ':'), ensure_ascii=False)

def _generate_signature(client_id: str, request_id: str, timestamp: str, request_target: str, body: dict) -> str:
    """Generate Signature sesuai dokumentasi DOKU RDL yang kamu berikan"""
    # Tahap 1: Digest Body
    minified = _minify_json(body)
    digest_sha256 = hashlib.sha256(minified.encode('utf-8')).digest()
    digest_base64 = base64.b64encode(digest_sha256).decode('utf-8')

    # Tahap 2: String komponen
    string_to_sign = f"""Client-Id:{client_id}
Request-Id:{request_id}
Request-Timestamp:{timestamp}
Request-Target:{request_target}
Digest:{digest_base64}"""

    # Tahap 3: HMAC-SHA256 + prefix
    hmac_obj = hmac.new(
        DOKU_SECRET_KEY.encode('utf-8'),
        string_to_sign.encode('utf-8'),
        hashlib.sha256
    )
    signature = base64.b64encode(hmac_obj.digest()).decode('utf-8')
    return f"HMACSHA256={signature}"

async def doku_rdl_payout_to_gopay(
    amount_idr: int,
    gopay_phone: str,
    user_id: Optional[int] = None,
    notes: str = "Reward Zilf.ai"
) -> Dict:
    """Kirim payout via DOKU RDL Disbursement ke GoPay"""
    if not DOKU_CLIENT_ID or not DOKU_SECRET_KEY:
        raise ValueError("DOKU_CLIENT_ID atau DOKU_SECRET_KEY belum di-set di environment variables")

    request_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # Format ISO8601 UTC

    # Payload sesuai RDL Disbursement (sesuaikan jika DOKU minta format GoPay spesifik)
    payload = {
        "transaction": {
            "id": f"zilf_payout_{int(datetime.now().timestamp())}",
            "amount": amount_idr,
            "description": notes
        },
        "account_destination": {
            "code": "07",                    # Channel code untuk e-wallet (GoPay biasanya 07 atau spesifik)
            "account_bank_number": gopay_phone,   # Nomor HP GoPay
            "account_bank_name": "GoPay",
            "address": "Indonesia"
        }
    }

    request_target = ENDPOINT
    signature = _generate_signature(DOKU_CLIENT_ID, request_id, timestamp, request_target, payload)

    headers = {
        "Client-Id": DOKU_CLIENT_ID,
        "Request-Id": request_id,
        "Request-Timestamp": timestamp,
        "Signature": signature,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BASE_URL}{ENDPOINT}",
            json=payload,
            headers=headers
        )

        try:
            result = response.json()
        except Exception:
            result = {"raw": response.text}

        result["status_code"] = response.status_code
        result["request_id"] = request_id

        # Log untuk debugging
        print(f"[DOKU RDL Payout] Status: {response.status_code} | Request ID: {request_id} | Response: {result}")

        return result