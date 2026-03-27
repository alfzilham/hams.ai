"""
agent/dashboard_routes.py
Dashboard Observability zilf.ai 2026 — PostgreSQL Version (Fixed & Rebuilt)

FIXES:
- [x] import json ditambahkan (was missing, caused NameError on payout)
- [x] DASHBOARD_ACCESS_TOKEN dibaca lazy (tiap request), bukan saat module load
- [x] require_dashboard_token sekarang raise error yang jelas & konsisten
- [x] db pool dibuat dengan error handling yang proper
- [x] Semua endpoint diproteksi dengan benar
"""

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

# ====================== CONFIG ======================
DATABASE_URL = os.getenv("DATABASE_URL")
REVENUE_PER_USER = 20000  # Rp20.000 per pengguna

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
payout_router = APIRouter(prefix="/api/payout", tags=["payout"])


# ====================== AUTH MIDDLEWARE ======================
# FIX: Token dibaca LAZY (tiap request), bukan saat module load.
# Dulu token dibaca sekali saat import → kalau env belum ada saat boot, token = ""
# dan semua request ditolak meski token sudah benar.

async def require_dashboard_token(request: Request) -> str:
    """
    Middleware autentikasi dashboard via header X-Dashboard-Token.
    Token dibaca dari env tiap request agar selalu up-to-date.
    """
    token_from_env = os.getenv("DASHBOARD_ACCESS_TOKEN", "").strip()

    # Jika token belum di-set di env (development mode), izinkan akses
    # Tapi di production (Railway) wajib ada
    if not token_from_env:
        # Cek apakah ini environment production
        railway_env = os.getenv("RAILWAY_ENVIRONMENT", "")
        if railway_env:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="DASHBOARD_ACCESS_TOKEN belum dikonfigurasi di environment variables."
            )
        # Local dev: bypass auth
        return "dev-mode"

    provided = request.headers.get("X-Dashboard-Token", "").strip()

    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header X-Dashboard-Token wajib disertakan."
        )

    if provided != token_from_env:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token tidak valid."
        )

    return provided


# ====================== DB HELPER ======================
_db_pool: Optional[asyncpg.Pool] = None


async def get_db() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        if not DATABASE_URL:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DATABASE_URL belum dikonfigurasi. Pastikan PostgreSQL sudah terhubung di Railway."
            )
        try:
            _db_pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Gagal konek ke database: {str(e)}"
            )
    return _db_pool


async def db_fetch(query: str, *args):
    pool = await get_db()
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)


async def db_fetchrow(query: str, *args):
    pool = await get_db()
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)


async def db_execute(query: str, *args):
    pool = await get_db()
    async with pool.acquire() as conn:
        await conn.execute(query, *args)


# ====================== INIT TABEL POSTGRESQL ======================
# Tabel yang dibutuhkan dashboard (jalankan sekali saat startup)

CREATE_TABLES_SQL = """
-- Tabel users (jika belum ada)
CREATE TABLE IF NOT EXISTS users (
    id                SERIAL PRIMARY KEY,
    name              TEXT NOT NULL,
    username          TEXT NOT NULL UNIQUE,
    email             TEXT NOT NULL UNIQUE,
    password          TEXT NOT NULL,
    google_id         TEXT DEFAULT NULL,
    avatar_url        TEXT DEFAULT NULL,
    plan              TEXT NOT NULL DEFAULT 'free',
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,
    revenue_credited  BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at     TIMESTAMPTZ DEFAULT NULL,
    reset_token       TEXT DEFAULT NULL,
    reset_expires     TIMESTAMPTZ DEFAULT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tabel model_logs (log penggunaan AI)
CREATE TABLE IF NOT EXISTS model_logs (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    model_name    TEXT,
    total_tokens  BIGINT DEFAULT 0,
    cost_idr      NUMERIC(12,2) DEFAULT 0,
    latency_ms    INTEGER DEFAULT 0,
    logged_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tabel payout_requests (riwayat GoPay payout)
CREATE TABLE IF NOT EXISTS payout_requests (
    id            TEXT PRIMARY KEY,
    provider      TEXT NOT NULL DEFAULT 'doku_rdl',
    to_account    TEXT NOT NULL,
    amount_idr    BIGINT NOT NULL,
    total_users   INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'pending',
    doku_response JSONB DEFAULT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index untuk performa query dashboard
CREATE INDEX IF NOT EXISTS idx_users_email       ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_created_at  ON users(created_at);
CREATE INDEX IF NOT EXISTS idx_model_logs_user   ON model_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_model_logs_logged ON model_logs(logged_at);
"""


async def init_dashboard_tables():
    """Buat tabel yang dibutuhkan dashboard jika belum ada."""
    try:
        pool = await get_db()
        async with pool.acquire() as conn:
            await conn.execute(CREATE_TABLES_SQL)
        print("[DASHBOARD] Tabel PostgreSQL berhasil diinisialisasi.")
    except Exception as e:
        print(f"[DASHBOARD] Warning: Gagal init tabel: {e}")


# ====================== ENDPOINTS DASHBOARD ======================

@dashboard_router.get("/summary")
async def dashboard_summary(_: str = Depends(require_dashboard_token)):
    """Ringkasan utama: total users, DAU, MAU, revenue, latency."""
    row = await db_fetchrow("""
        SELECT
            COUNT(DISTINCT u.id)                                                    AS total_users,
            COUNT(DISTINCT CASE WHEN u.created_at::date = CURRENT_DATE
                                THEN u.id END)                                      AS new_users_today,
            COUNT(DISTINCT CASE WHEN u.created_at >= DATE_TRUNC('month', NOW())
                                THEN u.id END)                                      AS new_users_this_month,
            COUNT(DISTINCT CASE WHEN ml.logged_at::date = CURRENT_DATE
                                THEN ml.user_id END)                                AS dau,
            COUNT(DISTINCT CASE WHEN ml.logged_at >= DATE_TRUNC('month', NOW())
                                THEN ml.user_id END)                                AS mau,
            COALESCE(ROUND(AVG(ml.latency_ms)::numeric, 2), 0)                     AS avg_latency_ms,
            COALESCE(SUM(ml.total_tokens), 0)                                       AS total_tokens_used,
            COUNT(DISTINCT CASE WHEN u.revenue_credited THEN u.id END) * $1        AS total_revenue_idr,
            COUNT(DISTINCT CASE WHEN u.created_at >= DATE_TRUNC('month', NOW())
                                     AND u.revenue_credited THEN u.id END) * $1    AS revenue_this_month_idr,
            COALESCE(SUM(ml.cost_idr), 0)                                           AS total_cost_idr,
            COALESCE(
                ROUND(AVG(ml.cost_idr)::numeric, 0), 0
            )                                                                        AS avg_cost_per_req_idr
        FROM users u
        LEFT JOIN model_logs ml ON u.id = ml.user_id
        WHERE u.is_active = TRUE
    """, REVENUE_PER_USER)

    return dict(row) if row else {
        "total_users": 0,
        "new_users_today": 0,
        "new_users_this_month": 0,
        "dau": 0,
        "mau": 0,
        "avg_latency_ms": 0,
        "total_tokens_used": 0,
        "total_revenue_idr": 0,
        "revenue_this_month_idr": 0,
        "total_cost_idr": 0,
        "avg_cost_per_req_idr": 0,
    }


@dashboard_router.get("/users")
async def dashboard_users(_: str = Depends(require_dashboard_token)):
    """Daftar semua pengguna aktif beserta statistik penggunaan."""
    rows = await db_fetch("""
        SELECT
            u.id,
            u.username,
            u.email,
            u.plan,
            u.created_at,
            u.last_login_at,
            u.revenue_credited,
            COUNT(ml.id)                                  AS total_requests,
            COALESCE(SUM(ml.total_tokens), 0)             AS total_tokens,
            ROUND(COALESCE(SUM(ml.cost_idr), 0)::numeric, 0) AS total_cost_idr
        FROM users u
        LEFT JOIN model_logs ml ON u.id = ml.user_id
        WHERE u.is_active = TRUE
        GROUP BY u.id
        ORDER BY u.created_at DESC
        LIMIT 500
    """)
    return {"users": [dict(r) for r in rows]}


@dashboard_router.get("/revenue")
async def dashboard_revenue(_: str = Depends(require_dashboard_token)):
    """Ringkasan revenue + status payout GoPay."""
    rev = await db_fetchrow("""
        SELECT
            COUNT(*)                                                                AS total_users,
            COUNT(CASE WHEN revenue_credited THEN 1 END)                           AS revenue_users,
            COUNT(CASE WHEN revenue_credited THEN 1 END) * $1                      AS total_revenue_idr,
            COUNT(CASE WHEN created_at::date = CURRENT_DATE THEN 1 END)            AS new_users_today,
            COUNT(CASE WHEN created_at >= DATE_TRUNC('month', NOW()) THEN 1 END)   AS new_users_this_month,
            COUNT(CASE WHEN created_at >= DATE_TRUNC('month', NOW())
                            AND revenue_credited THEN 1 END) * $1                  AS revenue_this_month_idr
        FROM users WHERE is_active = TRUE
    """, REVENUE_PER_USER)

    payout = await db_fetchrow("""
        SELECT
            COALESCE(SUM(CASE WHEN status = 'success' THEN amount_idr END), 0)  AS paid_idr,
            COALESCE(SUM(CASE WHEN status != 'success' THEN amount_idr END), 0) AS pending_idr
        FROM payout_requests
    """)

    return {**(dict(rev) if rev else {}), **(dict(payout) if payout else {})}


@dashboard_router.get("/performance")
async def dashboard_performance(_: str = Depends(require_dashboard_token)):
    """Statistik performa: latency per model, error rate, TPS."""
    rows = await db_fetch("""
        SELECT
            model_name,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latency_ms)::numeric, 0) AS p50,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 0) AS p95,
            COUNT(*) AS total_calls
        FROM model_logs
        WHERE logged_at >= NOW() - INTERVAL '30 days'
        GROUP BY model_name
        ORDER BY total_calls DESC
    """)

    daily = await db_fetch("""
        SELECT
            logged_at::date                                            AS day,
            ROUND(AVG(latency_ms)::numeric, 0)                        AS avg_latency,
            COUNT(*)                                                   AS total_calls
        FROM model_logs
        WHERE logged_at >= NOW() - INTERVAL '7 days'
        GROUP BY logged_at::date
        ORDER BY day ASC
    """)

    return {
        "models": [r["model_name"] for r in rows] or ["zilf-max"],
        "p50": [int(r["p50"] or 0) for r in rows] or [0],
        "p95": [int(r["p95"] or 0) for r in rows] or [0],
        "days": [str(r["day"]) for r in daily],
        "error_rate": [0] * len(daily),   # Tambahkan kolom error di model_logs jika perlu
        "tps": [int(r["total_calls"] or 0) for r in daily],
    }


@dashboard_router.get("/quality")
async def dashboard_quality(_: str = Depends(require_dashboard_token)):
    """Placeholder kualitas model — bisa diisi dari tabel evaluasi."""
    return {
        "radar": [0.85, 0.82, 0.80, 0.83, 0.78, 0.84],
        "days": ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"],
        "data_drift": [0.08, 0.09, 0.10, 0.09, 0.08, 0.07, 0.09],
        "concept_drift": [0.05, 0.06, 0.07, 0.06, 0.05, 0.04, 0.06],
        "trust": [0.84, 0.85, 0.83, 0.86, 0.87, 0.88, 0.86],
        "hallucination": [3.0, 2.8, 3.2, 2.9, 2.6, 2.4, 2.7],
        "toxicity": [0.7, 0.6, 1.0, 0.8, 0.6, 0.5, 0.7],
    }


@dashboard_router.get("/cost-per-user")
async def dashboard_cost_per_user(_: str = Depends(require_dashboard_token)):
    """Top 20 user berdasarkan biaya tertinggi."""
    rows = await db_fetch("""
        SELECT
            u.email,
            COUNT(ml.id)                                          AS total_requests,
            COALESCE(SUM(ml.total_tokens), 0)                    AS total_tokens,
            ROUND(COALESCE(SUM(ml.cost_idr), 0)::numeric, 0)    AS total_cost_idr,
            ROUND(COALESCE(AVG(ml.cost_idr), 0)::numeric, 0)    AS avg_cost_per_request_idr
        FROM users u
        LEFT JOIN model_logs ml ON u.id = ml.user_id
        WHERE u.is_active = TRUE
        GROUP BY u.id, u.email
        ORDER BY total_cost_idr DESC
        LIMIT 20
    """)
    return {"users": [dict(r) for r in rows]}


@dashboard_router.get("/security")
async def dashboard_security(_: str = Depends(require_dashboard_token)):
    """Log ancaman keamanan (dari tabel security_logs jika ada)."""
    try:
        rows = await db_fetch("""
            SELECT detected_at, email, owasp_category, owasp_label,
                   severity, action_taken, pii_detected
            FROM security_logs
            ORDER BY detected_at DESC
            LIMIT 50
        """)
        return {"logs": [dict(r) for r in rows]}
    except Exception:
        # Tabel belum ada → return kosong
        return {"logs": []}


@dashboard_router.get("/pii")
async def dashboard_pii(_: str = Depends(require_dashboard_token)):
    """Statistik deteksi PII (dari tabel security_logs jika ada)."""
    try:
        row = await db_fetchrow("""
            SELECT
                COUNT(CASE WHEN detected_at::date = CURRENT_DATE THEN 1 END) AS today,
                COUNT(CASE WHEN action_taken = 'blocked' THEN 1 END)          AS blocked,
                MODE() WITHIN GROUP (ORDER BY pii_type)                       AS top_type
            FROM security_logs
            WHERE pii_detected = TRUE
        """)
        return dict(row) if row else {"today": 0, "blocked": 0, "top_type": "email"}
    except Exception:
        return {"today": 0, "blocked": 0, "top_type": "email"}


# ====================== PAYOUT DOKU RDL → GoPay ======================

class GoPayPayoutIn(BaseModel):
    gopay_phone: str


@payout_router.post("/gopay/request")
async def payout_gopay_request(
    payload: GoPayPayoutIn,
    _: str = Depends(require_dashboard_token)
):
    """Proses payout ke GoPay via DOKU RDL Disbursement."""
    phone = payload.gopay_phone.strip()
    if not phone or not phone.startswith("08") or len(phone) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nomor GoPay tidak valid. Format: 08xxxxxxxxxx"
        )

    # Hitung total berdasarkan pengguna aktif
    row = await db_fetchrow(
        "SELECT COUNT(*) AS total_users FROM users WHERE is_active = TRUE AND revenue_credited = TRUE"
    )
    total_users = row["total_users"] if row else 0
    amount_idr = total_users * REVENUE_PER_USER

    if amount_idr <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak ada saldo yang bisa ditarik."
        )

    # Simpan record payout ke DB terlebih dahulu
    payout_id = f"zilf-{uuid.uuid4().hex[:12]}"
    await db_execute("""
        INSERT INTO payout_requests (id, provider, to_account, amount_idr, total_users, status)
        VALUES ($1, 'doku_rdl', $2, $3, $4, 'pending')
    """, payout_id, phone, amount_idr, total_users)

    # Jalankan DOKU RDL
    try:
        from agent.doku_payout import doku_rdl_payout_to_gopay
        result = await doku_rdl_payout_to_gopay(
            amount_idr=amount_idr,
            gopay_phone=phone,
            notes=f"Zilf.ai payout — {total_users} users"
        )
        payout_status = "success" if result.get("status_code") in (200, 201) else "pending"
    except ValueError as e:
        # DOKU belum dikonfigurasi
        result = {"error": str(e), "info": "DOKU_CLIENT_ID/DOKU_SECRET_KEY belum di-set"}
        payout_status = "recorded"
    except Exception as e:
        result = {"error": str(e)}
        payout_status = "failed"

    # Update status di DB — FIX: json.dumps sekarang bisa dipakai karena json sudah diimport
    await db_execute(
        "UPDATE payout_requests SET status = $1, doku_response = $2, updated_at = NOW() WHERE id = $3",
        payout_status,
        json.dumps(result),
        payout_id
    )

    return {
        "status": payout_status,
        "reference_id": payout_id,
        "amount_idr": amount_idr,
        "total_users": total_users,
        "doku_response": result,
    }


@payout_router.get("/history")
async def payout_history(_: str = Depends(require_dashboard_token)):
    """Riwayat semua payout yang pernah dilakukan."""
    rows = await db_fetch("""
        SELECT id, to_account, amount_idr, total_users, status, created_at
        FROM payout_requests
        ORDER BY created_at DESC
        LIMIT 50
    """)
    return {"history": [dict(r) for r in rows]}