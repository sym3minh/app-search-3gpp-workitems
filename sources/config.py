"""
config.py — Hằng số toàn cục cho 3GPP Search Tool.

Đây là file duy nhất được phép import bởi tất cả module khác.
Không chứa logic, chỉ định nghĩa các giá trị cấu hình tập trung.
Không import bất kỳ module nội bộ nào.

Optional dependency flags:
  Dùng importlib.util.find_spec() thay vì import thật sự — chỉ kiểm tra
  package có tồn tại không, không load package vào bộ nhớ. Điều này giúp
  startup không bị block bởi các package nặng (sentence_transformers,
  chromadb, pandas…).

  Các package nặng chỉ được import lazy bên trong hàm thật sự cần chúng.
"""

import importlib.util
import warnings
from pathlib import Path


# ── Suppress InsecureRequestWarning (urllib3) — không cần import urllib3 ──────
# Áp dụng sớm để mọi request sau này (qua requests/urllib) đều bị suppress.
warnings.filterwarnings(
    "ignore",
    message="Unverified HTTPS request",
    category=Warning,
)

# ── Optional dependency flags ─────────────────────────────────────────────────
# find_spec() chỉ kiểm tra package có được cài không — không load vào memory.
# Các package nặng (sentence_transformers, chromadb, pandas…) sẽ được import
# lazy bên trong hàm thật sự cần chúng, không phải lúc app khởi động.

def _pkg(*names: str) -> bool:
    """Trả về True nếu tất cả package trong *names đều được cài đặt."""
    return all(importlib.util.find_spec(n) is not None for n in names)


TDOC_FETCH_OK = _pkg("requests", "bs4", "urllib3")
TDOC_DOCX_OK  = _pkg("docx")
PANDAS_OK     = _pkg("pandas")
RAG_OK        = _pkg("sentence_transformers", "chromadb")

# ── Paths ─────────────────────────────────────────────────────────────────────
APP_DIR                = Path(__file__).parent        # .../3gpp_app/
ROOT_DIR               = APP_DIR.parent               # .../ (chứa .cache, data, output)

CACHE_DIR              = ROOT_DIR / ".cache"
CACHE_FILE             = CACHE_DIR / "workplan.xlsx"
DB_FILE                = CACHE_DIR / "cr_titles.db"
ACR_CACHE_DIR          = CACHE_DIR / "3gpp_cr_approved"
ACR_DB_FILE            = ACR_CACHE_DIR / "3gpp_cr_approved.db"
OUTPUT_DIR             = ROOT_DIR / "output"
EXCELS_DIR             = ROOT_DIR / "excels"
DATA_DIR               = ROOT_DIR / "data"
DOWNLOAD_ZIP_DIR       = DATA_DIR / "downloads" / "Zip"
DOWNLOAD_EXTRACTED_DIR = DATA_DIR / "downloads" / "Extracted"
SUMMARY_OUT_DIR        = DATA_DIR / "outputs" / "summary"
CLUSTERING_OUT_DIR     = DATA_DIR / "outputs" / "clustering"

# ── URLs ──────────────────────────────────────────────────────────────────────
WORKPLAN_INDEX = "https://www.3gpp.org/ftp/Information/WORK_PLAN/"
PORTAL_BASE    = "https://portal.3gpp.org"
CR_DB_BASE_URL = "https://www.3gpp.org/ftp/Information/Databases/Change_Request/"

# ── HTTP ──────────────────────────────────────────────────────────────────────
HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_MAX_DAYS = 30

# ── Themes ────────────────────────────────────────────────────────────────────
THEMES = {
    "dark": {
        "BG":       "#0F1117",
        "BG2":      "#1A1D27",
        "BG3":      "#22263A",
        "ACCENT":   "#4F8EF7",
        "SUCCESS":  "#2DD4A5",
        "WARN":     "#F7A74F",
        "ERROR":    "#F75F5F",
        "FG":       "#E8EAF6",
        "FG2":      "#9BA3C9",
        "BORDER":   "#2E3356",
        "LINK":     "#7EB8F7",
        "SCROLLBG": "#1A1D27",
        "SCROLLFG": "#3A3F5C",
        "SCROLLHO": "#4F8EF7",
        "TAB_SEL":  "#22263A",
        "TAB_BG":   "#1A1D27",
    },
    "light": {
        "BG":       "#F5F6FA",
        "BG2":      "#FFFFFF",
        "BG3":      "#E8EBF5",
        "ACCENT":   "#2563EB",
        "SUCCESS":  "#059669",
        "WARN":     "#D97706",
        "ERROR":    "#DC2626",
        "FG":       "#1E1E2E",
        "FG2":      "#4B5280",
        "BORDER":   "#CBD5E1",
        "LINK":     "#1D4ED8",
        "SCROLLBG": "#E8EBF5",
        "SCROLLFG": "#94A3B8",
        "SCROLLHO": "#2563EB",
        "TAB_SEL":  "#FFFFFF",
        "TAB_BG":   "#E8EBF5",
    },
}

# ── Fonts ─────────────────────────────────────────────────────────────────────
FONT_MONO  = ("Consolas",  10)
FONT_UI    = ("Segoe UI",  10)
FONT_BOLD  = ("Segoe UI",  10, "bold")
FONT_H1    = ("Segoe UI",  15, "bold")
FONT_SMALL = ("Segoe UI",   9)

# ── Output headers ────────────────────────────────────────────────────────────
WI_OUTPUT_HEADER = [
    "Unique_ID", "Name", "Acronym", "Release", "Start", "Finish",
    "Completion", "Impacted_TSs_and_TRs", "CR_Link", "Spec_Link",
]
CR_OUTPUT_HEADER_FULL   = ["Title", "Workitem_ID", "Release",  "Portal_Link"]
CR_OUTPUT_HEADER_WIONLY = ["Title", "Workitem_ID", "WI_Name",  "Portal_Link"]

ACR_EXPECTED_COLUMNS = [
    "Spec number", "CR number", "Revision", "Subject",
    "Meeting WG-level", "WG-level status", "Meeting TSG-level", "TSG-level status",
    "WGSourceOrganizations", "TSGSourceOrganizations", "WG Tdoc", "Category",
    "Release", "Version-current", "Version-new", "Date", "TSG Tdoc", "Work items",
]
