"""
agent/doku_payout.py
DOKU RDL Disbursement — Fixed & Extended

FIXES v2:
- [x] Tambah source_account.account_id di payload (wajib, sebelumnya missing)
- [x] Ganti kode bank "07" → Swift/BIC code yang benar (DOKU standard)
- [x] Tambah fungsi get_payout_status() untuk cek status async
- [x] Tambah fungsi register_rdl_account() untuk dapat account_id pertama kali
"""

import base64
import hashlib
import hmac as hmac_lib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

import httpx

# ====================== CONFIG ======================
DOKU_CLIENT_ID      = os.getenv("DOKU_CLIENT_ID", "")
DOKU_SECRET_KEY     = os.getenv("DOKU_SECRET_KEY", "")
DOKU_ENV            = os.getenv("DOKU_ENV", "sandbox")
DOKU_SOURCE_ACCOUNT = os.getenv("DOKU_SOURCE_ACCOUNT", "")
DOKU_WALLET_PHONE   = os.getenv("DOKU_WALLET_PHONE", "")

BASE_URL = (
    "https://api-sandbox.doku.com"
    if DOKU_ENV == "sandbox"
    else "https://api.doku.com"
)

ENDPOINT_DISBURSE = "/sac-rdl/v1/rdl-disbursements"
ENDPOINT_CUSTOMER = "/sac-rdl/v1/rdl-customers"

# Swift/BIC codes yang valid di DOKU RDL
# Ref: https://dashboard.doku.com/docs/docs/jokul-rdl/section/rdl-disbursements/
BANK_CODES = {
    "BNI":     "BNINIDJA",
    "CENA":    "CENAIDJA",   # CIMB Niaga
    "BCA":     "CENAIDJA",   # konfirmasi ke DOKU support
    "MANDIRI": "BMRIIDJA",
    "BRI":     "BRINIDJA",
    "DOKU":   "DOKU",
}


# ====================== SIGNATURE (tidak berubah) ======================

def _minify_json(body: dict) -> str:
    return json.dumps(body, separators=(',', ':'), ensure_ascii=False)


def _generate_signature(
    client_id: str,
    request_id: str,
    timestamp: str,
    request_target: str,
    body: dict,
) -> str:
    minified_body = _minify_json(body)
    body_digest   = hashlib.sha256(minified_body.encode("utf-8")).digest()
    digest_b64    = base64.b64encode(body_digest).decode("utf-8")

    string_to_sign = (
        f"Client-Id:{client_id}\n"
        f"Request-Id:{request_id}\n"
        f"Request-Timestamp:{timestamp}\n"
        f"Request-Target:{request_target}\n"
        f"Digest:{digest_b64}"
    )

    mac       = hmac_lib.new(DOKU_SECRET_KEY.encode(), string_to_sign.encode(), hashlib.sha256)
    signature = base64.b64encode(mac.digest()).decode("utf-8")
    return f"HMACSHA256={signature}"


def _build_headers(request_target: str, body: dict) -> dict:
    request_id = str(uuid.uuid4())
    timestamp  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signature  = _generate_signature(DOKU_CLIENT_ID, request_id, timestamp, request_target, body)
    return {
        "Client-Id":          DOKU_CLIENT_ID,
        "Request-Id":         request_id,
        "Request-Timestamp":  timestamp,
        "Signature":          signature,
        "Content-Type":       "application/json",
    }, request_id  # return request_id juga untuk logging


# ====================== FUNGSI 1: PAYOUT ======================

async def doku_payout_to_wallet(
    amount_idr: int,
    notes: str = "Reward Zilf.ai",
) -> Dict:
    """
    Kirim payout ke DOKU Wallet via RDL Disbursement.
    Target wallet diambil dari env DOKU_WALLET_ID (email wallet kamu).
    """
    _validate_config()

    if not DOKU_WALLET_PHONE:
        raise ValueError(
            "DOKU_WALLET_PHONE belum diset. Isi dengan nomor HP DOKU Wallet kamu (format: 628xxx) di .env"
            )

    tx_id = f"zilf_payout_{int(datetime.now(timezone.utc).timestamp())}"

    payload = {
        "transaction": {
            "id":          tx_id,
            "amount":      amount_idr,
            "description": notes,
        },
        "source_account": {
            "account_id": DOKU_SOURCE_ACCOUNT,
        },
        "account_destination": {
            "code":                "DOKU",        # ← kode DOKU Wallet di RDL
            "account_bank_number": DOKU_WALLET_PHONE,  # phone number wallet kamu
            "account_bank_name":   "DOKU Wallet",
            "address":             "Indonesia",
        },
    }

    headers, request_id = _build_headers(ENDPOINT_DISBURSE, payload)
    return await _post(BASE_URL + ENDPOINT_DISBURSE, payload, headers, request_id)


# ====================== FUNGSI 2: CEK STATUS (BARU) ======================

async def get_payout_status(transaction_id: str) -> Dict:
    """
    Cek status disbursement berdasarkan transaction_id.

    DOKU payout bersifat async — response awal selalu PENDING.
    Panggil fungsi ini setelah beberapa detik, atau dari webhook callback.

    Status kemungkinan: PENDING | SUCCESS | FAILED
    """
    _validate_config()

    endpoint = f"{ENDPOINT_DISBURSE}/{transaction_id}"
    # GET request — body kosong untuk signature
    empty_body = {}
    headers, request_id = _build_headers(endpoint, empty_body)

    print(f"[DOKU] Checking status | tx_id: {transaction_id} | req_id: {request_id}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                BASE_URL + endpoint,
                headers=headers,
            )
        except httpx.TimeoutException:
            return {"status_code": 408, "request_id": request_id, "error": "Timeout"}
        except httpx.RequestError as e:
            return {"status_code": 503, "request_id": request_id, "error": str(e)}

        result = _parse_response(response)
        result["request_id"] = request_id
        print(f"[DOKU] Status result | {json.dumps(result, ensure_ascii=False)[:300]}")
        return result


# ====================== FUNGSI 3: REGISTER RDL (untuk dapat account_id) =====

async def register_rdl_and_get_account_id(
    customer_id: str,
    customer_name: str,
    email: str,
    phone: str,
) -> Dict:
    """
    Register RDL customer untuk mendapat account_id.

    Jalankan sekali saja → simpan account_id yang dikembalikan ke .env
    sebagai DOKU_SOURCE_ACCOUNT_ID.

    Ini adalah rekening "dompet" sumber dana payout Zilf.ai.
    """
    _validate_config()

    payload = {
        "rdl_customer": {
            "customer_id":          customer_id,   # e.g. "ZILF-MERCHANT-001"
            "customer_name":        customer_name,
            "email":                email,
            "mobile_phone_number":  phone,
            "company_id":           "DOKU",
            # Field lain bisa diisi minimal untuk sandbox
            "gender":               "MALE",
            "nationality":          "ID",
            "address_city":         "Jakarta",
            "address_province":     "DKI Jakarta",
            "zip_code":             "10110",
            "job_code":             "ENTREPRENEUR",
            "source_of_fund":       "SALARY",
            "open_account_reason":  "INVESTMENT",
            "monthly_income":       1,
        }
    }

    headers, request_id = _build_headers(ENDPOINT_CUSTOMER, payload)
    result = await _post(BASE_URL + ENDPOINT_CUSTOMER, payload, headers, request_id)

    # Ekstrak account_id dari response
    account_id = (
        result.get("rdl_customer", {}).get("account_id")
        or result.get("account_id")
    )
    if account_id:
        print(f"\n✅ account_id berhasil didapat: {account_id}")
        print(f"👉 Simpan ke .env: DOKU_SOURCE_ACCOUNT_ID={account_id}\n")
        result["_account_id_to_save"] = str(account_id)

    return result


# ====================== HELPERS ======================

def _validate_config():
    if not DOKU_CLIENT_ID or not DOKU_SECRET_KEY:
        raise ValueError(
            "DOKU_CLIENT_ID dan DOKU_SECRET_KEY belum dikonfigurasi di environment variables."
        )


async def _post(url: str, payload: dict, headers: dict, request_id: str) -> Dict:
    print(f"[DOKU] POST {url} | req_id: {request_id}")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            return {"status_code": 408, "request_id": request_id, "error": "Timeout"}
        except httpx.RequestError as e:
            return {"status_code": 503, "request_id": request_id, "error": str(e)}

        result = _parse_response(response)
        result["request_id"] = request_id
        print(f"[DOKU] Response {response.status_code} | {json.dumps(result, ensure_ascii=False)[:300]}")
        return result


def _parse_response(response) -> Dict:
    try:
        result = response.json()
    except Exception:
        result = {"raw": response.text}
    result["status_code"] = response.status_code
    return result