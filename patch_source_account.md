# ============================================================
# 1. PATCH DOKU SOURCE ACCOUNT - doku_payout.py
# ============================================================

$content = Get-Content "agent\doku_payout.py" -Raw

# Tambah validasi DOKU_SOURCE_ACCOUNT di fungsi payout
$validateBlock = @'
    if not DOKU_SOURCE_ACCOUNT:
        raise ValueError(
            "DOKU_SOURCE_ACCOUNT belum diset di Railway.\n"
            "Isi dengan account_id yang diberikan DOKU (contoh: RDL-XXXXXXXXXXXXXXX)"
        )
'@

$content = $content -replace 'async def doku_payout_to_wallet\(amount_idr: int, notes: str = "Reward Zilf.ai"\) -> Dict:', @"
async def doku_payout_to_wallet(amount_idr: int, notes: str = "Reward Zilf.ai") -> Dict:
    # VALIDASI SOURCE ACCOUNT (baru diaktifkan)
    $validateBlock
"@

# Update komentar di bagian CONFIG agar jelas
$content = $content -replace 'DOKU_SOURCE_ACCOUNT = os\.getenv\("DOKU_SOURCE_ACCOUNT", ""\)', 'DOKU_SOURCE_ACCOUNT = os.getenv("DOKU_SOURCE_ACCOUNT", "")  # ← WAJIB diisi setelah DOKU memberikan account_id'

$content | Set-Content "agent\doku_payout.py" -NoNewline

Write-Host "[✅] doku_payout.py patched - validasi SOURCE ACCOUNT sudah aktif"


# ============================================================
# PATCH DOKU SOURCE ACCOUNT - dashboard_routes.py
# ============================================================

$content = Get-Content "agent\dashboard_routes.py" -Raw

$content = $content -replace 'except ValueError as e:', @'
except ValueError as e:
    if "DOKU_SOURCE_ACCOUNT" in str(e):
        result = {"error": str(e), "info": "Source Account belum diisi di Railway Environment Variables"}
        payout_status = "config_missing"
    else:
        result = {"error": str(e)}
        payout_status = "failed"
'@

$content = $content -replace 'provider      TEXT NOT NULL DEFAULT .doku_rdl.', 'provider      TEXT NOT NULL DEFAULT ''doku_wallet''  -- sudah diganti ke DOKU Wallet'

$content | Set-Content "agent\dashboard_routes.py" -NoNewline

Write-Host "[✅] dashboard_routes.py patched - error handling SOURCE ACCOUNT sudah diperbaiki"


# ============================================================
# PATCH DOKU SOURCE ACCOUNT - dashboard.html
# ============================================================

$content = Get-Content "agent\templates\dashboard.html" -Raw

$content = $content -replace 'Akan aktif setelah DOKU_WALLET_PHONE dikonfigurasi di .env.', 'Source Account sudah siap? Payout akan langsung masuk ke DOKU Wallet Anda.'

$content = $content -replace 'Permintaan payout .* sedang diproses.', 'Permintaan payout Rp${fmtRp(total)} ke DOKU Wallet <b>${phone}</b> sedang diproses oleh DOKU.'

$content | Set-Content "agent\templates\dashboard.html" -NoNewline

Write-Host "[✅] dashboard.html patched - UI sudah siap pakai SOURCE ACCOUNT"


# ============================================================
# PATCH DOKU SOURCE ACCOUNT - api.py (hapus endpoint register lama jika masih ada)
# ============================================================

$content = Get-Content "agent\api.py" -Raw
$content = $content -replace '(?s)@app\.post\("/admin/doku/register-rdl".*?return result\s*\n', ''
$content | Set-Content "agent\api.py" -NoNewline

Write-Host "[✅] api.py cleaned - endpoint register-rdl sementara sudah dihapus"


# ============================================================
# PATCH #5 — Tampilkan Status SOURCE ACCOUNT di Dashboard
# ============================================================

# 1. Update dashboard_routes.py (tambah endpoint kecil untuk cek status)
$content = Get-Content "agent\dashboard_routes.py" -Raw

$statusEndpoint = @'
# ====================== STATUS SOURCE ACCOUNT ======================
@dashboard_router.get("/source-account-status")
async def source_account_status(_: str = Depends(require_dashboard_token)):
    """Cek apakah DOKU_SOURCE_ACCOUNT sudah diisi (hanya status, tidak tampilkan ID)"""
    source = os.getenv("DOKU_SOURCE_ACCOUNT", "").strip()
    if source and len(source) > 8:  # minimal RDL-xxx
        return {"status": "ready", "message": "✅ Source Account sudah terhubung"}
    else:
        return {
            "status": "missing",
            "message": "⚠️ DOKU_SOURCE_ACCOUNT belum diisi di Railway",
            "action": "Isi di Railway → Variables → DOKU_SOURCE_ACCOUNT"
        }
'@

# Tambahkan endpoint ini sebelum akhir file (sebelum if __name__ atau di bawah payout_router)
if $content -notmatch "source-account-status" {
    $content = $content -replace '(@payout_router\.get\("/history"\))', @"
$statusEndpoint

@payout_router.get("/history")
"@
}

$content | Set-Content "agent\dashboard_routes.py" -NoNewline
Write-Host "[✅] dashboard_routes.py — endpoint /source-account-status ditambahkan"


# 2. Update dashboard.html (tampilkan badge status + pesan di modal)
$content = Get-Content "agent\templates\dashboard.html" -Raw

# Tambah badge di Revenue Banner
$content = $content -replace '<button class="payout-btn" onclick="openPayoutModal\(\)">', @'
<div id="sourceStatusBadge" style="display:inline-flex;align-items:center;gap:6px;background:rgba(245,158,11,0.15);color:#f59e0b;border:1px solid #f59e0b;border-radius:9999px;padding:4px 12px;font-size:0.8rem;margin-right:12px;">
  <span id="sourceDot" class="status-dot" style="background:#f59e0b"></span>
  <span id="sourceText">Cek Source Account...</span>
</div>
<button class="payout-btn" onclick="openPayoutModal()">
'@

# Update modal payout supaya ada info status
$content = $content -replace '<div id="payoutResult"></div>', @'
<div id="payoutResult"></div>
<div id="sourceAccountWarning" class="result-pending" style="display:none;margin-top:12px;font-size:0.82rem;">
  <i class="bi bi-exclamation-triangle-fill"></i> <strong>Source Account belum siap.</strong><br>
  Silakan isi <code>DOKU_SOURCE_ACCOUNT</code> di Railway terlebih dahulu.
</div>
'@

$content | Set-Content "agent\templates\dashboard.html" -NoNewline
Write-Host "[✅] dashboard.html — badge status SOURCE ACCOUNT + warning sudah ditambahkan"


# 3. Tambah JS di dashboard.html untuk fetch status
$jsBlock = @'
    // Fetch status SOURCE ACCOUNT
    async function checkSourceAccountStatus() {
      try {
        const r = await apiFetch('/api/dashboard/source-account-status');
        const data = await r.json();
        const badge = document.getElementById('sourceStatusBadge');
        const text = document.getElementById('sourceText');
        const dot = document.getElementById('sourceDot');

        if (data.status === "ready") {
          badge.style.background = 'rgba(16,185,129,0.15)';
          badge.style.borderColor = '#10b981';
          badge.style.color = '#10b981';
          dot.style.background = '#10b981';
          text.innerHTML = '✅ Source Account Ready';
        } else {
          badge.style.background = 'rgba(245,158,11,0.15)';
          badge.style.borderColor = '#f59e0b';
          badge.style.color = '#f59e0b';
          dot.style.background = '#f59e0b';
          text.innerHTML = '⚠️ Source Account Missing';
        }
      } catch(e) {}
    }
'@

$content = Get-Content "agent\templates\dashboard.html" -Raw
$content = $content -replace 'function initDashboard\(\) \{', "function initDashboard() {`n    checkSourceAccountStatus();"
$content = $content -replace 'async function submitPayout\(\) \{', @"
async function submitPayout() {
    // Cek dulu status source account
    const statusCheck = await apiFetch('/api/dashboard/source-account-status').then(r => r.json()).catch(() => ({status:"missing"}));
    if (statusCheck.status === "missing") {
        const warn = document.getElementById('sourceAccountWarning');
        warn.style.display = 'block';
        return;
    }
"@
$content | Set-Content "agent\templates\dashboard.html" -NoNewline
Write-Host "[✅] JS status checker sudah ditambahkan"





TEMPAT YANG HARUS KAMU GANTI DENGAN SOURCE ACCOUNT
Tidak ada di patch di atas (patch hanya mengaktifkan kode).
Yang harus kamu isi adalah di Railway:

Buka Railway → Service zilf-ai → Variables
Tambah / Edit variable:
Key: DOKU_SOURCE_ACCOUNT
Value: RDL-XXXXXXXXXXXXXXXX ← GANTI INI dengan nilai yang DOKU berikan lewat email


Setelah diisi → Restart / Redeploy service Railway.

Cara pakai setelah ini:

Jalankan ke-4 patch di atas.
Isi DOKU_SOURCE_ACCOUNT di Railway.
Redeploy.
Buka dashboard → Revenue → klik Tarik via DOKU → seharusnya langsung jalan tanpa error.