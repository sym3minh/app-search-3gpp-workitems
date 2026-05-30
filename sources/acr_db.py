"""
acr_db.py — Build database 3gpp_cr_approved.db từ file Excel của 3GPP.

Import: config
Pipeline hoàn chỉnh: scrape ZIP URL → download/cache Excel → filter approved → lưu SQLite.
"""

import re, ssl, sqlite3, zipfile, io
import urllib.request
from pathlib import Path

from config import (
    ACR_CACHE_DIR, ACR_DB_FILE,
    CR_DB_BASE_URL, HDRS,
    TDOC_FETCH_OK, PANDAS_OK,
    ACR_EXPECTED_COLUMNS,
)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _acr_find_zip_url(log_fn=None) -> str:
    """Scrape trang listing 3GPP để tìm URL file .zip mới nhất. Có fallback regex scan."""
    def log(m):
        if log_fn:
            log_fn(m)

    if not TDOC_FETCH_OK:
        raise RuntimeError("pip install requests beautifulsoup4")

    log(f"Đang lấy danh sách file từ {CR_DB_BASE_URL} ...")

    import requests as _req
    import urllib3 as _u3
    from bs4 import BeautifulSoup
    _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)
    headers = {"User-Agent": HDRS["User-Agent"]}

    html_text = None
    # Strategy 1: requests
    try:
        resp = _req.get(CR_DB_BASE_URL, headers=headers, timeout=30, verify=False)
        resp.raise_for_status()
        html_text = resp.text
        log(f"HTTP {resp.status_code} — nhận {len(html_text)} ký tự")
    except Exception as e:
        log(f"[WARN] requests thất bại: {e} — thử urllib...")

    # Strategy 2: urllib fallback (sometimes requests SSL handshake fails on FTP-over-HTTP)
    if not html_text:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(CR_DB_BASE_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
                html_text = r.read().decode("utf-8", errors="replace")
            log(f"urllib OK — nhận {len(html_text)} ký tự")
        except Exception as e2:
            raise RuntimeError(f"Không thể kết nối tới {CR_DB_BASE_URL}: {e2}")

    snippet = html_text[:400].replace('\n', ' ').strip()
    log(f"[DEBUG] HTML đầu: {snippet}")

    # Strategy A: BeautifulSoup link scan
    soup = BeautifulSoup(html_text, "html.parser")
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.lower().endswith(".zip"):
            url = href if href.startswith("http") else CR_DB_BASE_URL.rstrip("/") + "/" + href.lstrip("/")
            log(f"Tìm thấy ZIP: {url}")
            return url

    # Strategy B: regex scan (handles cases where BeautifulSoup misses relative links)
    log("[DEBUG] Không tìm thấy qua BeautifulSoup, thử regex...")
    for line in html_text.splitlines():
        if ".zip" in line.lower():
            m = re.search(r'href=["\']([^"\']*\.zip)["\']', line, re.IGNORECASE)
            if m:
                href = m.group(1)
                url = href if href.startswith("http") else CR_DB_BASE_URL.rstrip("/") + "/" + href.lstrip("/")
                log(f"Tìm thấy ZIP (regex): {url}")
                return url

    # Strategy C: bare filename pattern in raw text
    log("[DEBUG] Thử tìm pattern tên file .zip trong raw text...")
    m = re.search(r'([\w\-]+\.zip)', html_text, re.IGNORECASE)
    if m:
        zip_name = m.group(1)
        url = CR_DB_BASE_URL.rstrip("/") + "/" + zip_name
        log(f"Tìm thấy ZIP (pattern): {url}")
        return url

    raise FileNotFoundError(
        f"Không tìm thấy file .zip nào trong trang listing. HTML: {html_text[:300]}"
    )


def _acr_get_excel(zip_url: str, log_fn=None):
    """
    Download ZIP và extract Excel vào ACR_CACHE_DIR nếu cần.

    Returns:
        (excel_path: Path, was_downloaded: bool)
        was_downloaded=True  → Excel mới tải (DB phải rebuild)
        was_downloaded=False → Excel cũ khớp ZIP stem (cache hit)
    """
    def log(m):
        if log_fn:
            log_fn(m)

    ACR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    zip_stem = Path(zip_url.split("?")[0]).stem

    # Find existing Excel in the folder
    existing = None
    for ext in ("*.xlsx", "*.xls", "*.xlsm"):
        found = list(ACR_CACHE_DIR.glob(ext))
        if found:
            existing = found[0]
            break

    if existing and existing.stem == zip_stem:
        log(f"⏭  Bỏ qua download — đã có file: {existing.name}")
        return existing, False  # cache hit

    if existing:
        log(f"File cũ ({existing.name}) khác với ZIP ({zip_stem}.zip) → xóa và tải mới...")
        existing.unlink()

    # Download ZIP
    import requests as _req
    import urllib3 as _u3
    _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)
    log(f"Đang tải {zip_url} ...")
    headers = {"User-Agent": HDRS["User-Agent"]}
    resp = _req.get(zip_url, headers=headers, timeout=300, stream=True, verify=False)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    chunks = []; downloaded = 0
    for chunk in resp.iter_content(chunk_size=1024 * 256):
        chunks.append(chunk)
        downloaded += len(chunk)
        if total:
            pct = downloaded / total * 100
            log(f"  {downloaded/1024/1024:.1f} / {total/1024/1024:.1f} MB  ({pct:.0f}%)")
    zip_bytes = b"".join(chunks)
    log(f"Tải xong: {len(zip_bytes)/1024/1024:.1f} MB")

    # Extract Excel from ZIP
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        excel_files = [n for n in zf.namelist()
                       if n.lower().endswith((".xlsx", ".xls", ".xlsm"))]
        if not excel_files:
            raise FileNotFoundError("Không có file Excel trong ZIP.")
        log(f"Excel trong ZIP: {excel_files}")
        excel_name     = excel_files[0]
        extracted_path = ACR_CACHE_DIR / Path(excel_name).name
        with zf.open(excel_name) as fin:
            extracted_path.write_bytes(fin.read())
        log(f"Đã giải nén: {extracted_path.name}")

    return extracted_path, True  # fresh download


# ── Public API ────────────────────────────────────────────────────────────────

def acr_update_db(log_fn=None) -> int:
    """
    Public API chính.  Pipeline đầy đủ:
        scrape → download → filter approved → lưu SQLite.

    Cache thông minh:
        was_downloaded=False AND DB exists  → return count hiện tại (không làm gì)
        was_downloaded=False AND DB missing → chỉ rebuild DB từ Excel đã có
        was_downloaded=True                 → rebuild DB từ Excel mới

    Returns: số hàng 'approved' trong DB.
    Raises on error.
    """
    def log(m):
        if log_fn:
            log_fn(m)

    if not PANDAS_OK:
        raise RuntimeError("pip install pandas openpyxl")

    # 1. Find ZIP URL
    zip_url = _acr_find_zip_url(log_fn=log_fn)
    log(f"ZIP URL: {zip_url}")

    # 2. Get Excel (cached or fresh)
    excel_path, was_downloaded = _acr_get_excel(zip_url, log_fn=log_fn)

    # 3. Skip DB rebuild if Excel unchanged AND DB already exists
    if not was_downloaded and ACR_DB_FILE.exists():
        conn = sqlite3.connect(str(ACR_DB_FILE))
        n = conn.execute("SELECT COUNT(*) FROM cr_approved").fetchone()[0]
        conn.close()
        log(f"✅ Không cần update — Excel chưa thay đổi và DB đã có {n:,} hàng.")
        return n

    if not was_downloaded:
        log("Excel không thay đổi nhưng DB chưa tồn tại → tiến hành tạo DB...")
    else:
        log("Excel mới tải về → tiến hành rebuild DB...")

    # 4. Read Excel
    import pandas as _pd
    log(f"Đang đọc {excel_path.name} ...")
    df = _pd.read_excel(str(excel_path), dtype=str)
    log(f"  {len(df):,} hàng, {len(df.columns)} cột")

    # 5. Normalise column names
    df.columns = [c.strip() for c in df.columns]
    rename_map = {}
    for col in df.columns:
        col_n = col.lower().replace("-", " ").replace("_", " ")
        for exp in ACR_EXPECTED_COLUMNS:
            if col_n == exp.lower().replace("-", " ").replace("_", " ") and col != exp:
                rename_map[col] = exp
                break
    if rename_map:
        log(f"  Đổi tên cột: {rename_map}")
        df.rename(columns=rename_map, inplace=True)

    # 6. Filter approved
    STATUS_COL = "TSG-level status"
    if STATUS_COL not in df.columns:
        avail = [c for c in df.columns if "status" in c.lower() or "tsg" in c.lower()]
        raise KeyError(f"Không tìm thấy cột '{STATUS_COL}'. Có: {avail}")
    mask = df[STATUS_COL].fillna("").str.strip().str.lower() == "approved"
    approved_df = df[mask].copy()
    log(f"Rows TSG-level status='approved': {len(approved_df):,} / {len(df):,}")

    # 7. Save to SQLite
    ACR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ACR_DB_FILE))
    try:
        approved_df.to_sql("cr_approved", conn, if_exists="replace", index=False)
        conn.commit()
    finally:
        conn.close()
    log(f"Đã lưu {len(approved_df):,} hàng vào {ACR_DB_FILE.name}")

    # 8. Quick verify
    conn = sqlite3.connect(str(ACR_DB_FILE))
    n = conn.execute("SELECT COUNT(*) FROM cr_approved").fetchone()[0]
    conn.close()
    log(f"[Xác nhận] cr_approved: {n:,} hàng ✓")
    return n
