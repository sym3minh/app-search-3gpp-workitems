"""
3GPP Change Request (CR) Metadata Extractor
============================================
Extracts structured metadata from 3GPP CR Word documents (.docx / .doc).

Supports:
  - Modern .docx  (CR-Form v12+)  via python-docx   (pip install python-docx)
  - Legacy  .doc  (CR-Form v11-)  via olefile        (pip install olefile)

Extracted fields:
    ts_number, work_item, title, reason_for_change,
    summary_of_change, consequences_if_not_approved, other_comments

Usage — single file:
    from cr_extractor import extract_cr_metadata
    meta = extract_cr_metadata("R4-146562.doc")   # auto-saves .txt cung thu muc

Usage — batch:
    from cr_extractor import batch_extract
    results = batch_extract("./cr_folder/", output_dir="./extracted/")
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field ordering & display labels
# ---------------------------------------------------------------------------

FIELDS_ORDER = [
    "ts_number",
    "work_item",
    "title",
    "reason_for_change",
    "summary_of_change",
    "consequences_if_not_approved",
    "other_comments",
]

FIELD_LABELS = {
    "ts_number":                    "TS Number",
    "work_item":                    "Work Item",
    "title":                        "Title",
    "reason_for_change":            "Reason for Change",
    "summary_of_change":            "Summary of Change",
    "consequences_if_not_approved": "Consequences if Not Approved",
    "other_comments":               "Other Comments",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_cr_metadata(
    filepath: str | Path,
    output_txt: Optional[str | Path] = None,
) -> dict[str, Optional[str]]:
    """
    Trich xuat metadata tu mot file CR 3GPP (.docx hoac .doc).

    Parameters
    ----------
    filepath   : duong dan toi file .docx / .doc
    output_txt : - None  -> tu dong tao .txt cung thu muc, cung ten voi docx
                 - False -> khong ghi file, chi tra ve dict
                 - Path  -> ghi ra path chi dinh
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    raw_text = _read_as_text(path)
    meta = _parse_cr_fields(raw_text, source_path=path)

    if output_txt is not False:
        txt_path = Path(output_txt) if output_txt else path.with_suffix(".txt")
        _write_txt(meta, source_filename=path.name, output_path=txt_path)

    return meta


def batch_extract(
    folder: str | Path,
    output_dir: Optional[str | Path] = None,
    recursive: bool = False,
    ignore_errors: bool = True,
) -> list[dict]:
    """
    Trich xuat metadata tu tat ca .docx / .doc trong mot thu muc.

    Parameters
    ----------
    folder      : thu muc chua cac file CR
    output_dir  : thu muc xuat .txt. Neu None -> cung thu muc voi file nguon.
    recursive   : quet ca thu muc con
    ignore_errors : neu True, file loi bi bo qua (warning duoc log)
    """
    folder = Path(folder)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    pattern = "**/*" if recursive else "*"
    files = sorted(
        p for p in folder.glob(pattern)
        if p.suffix.lower() in {".docx", ".doc"}
    )

    results = []
    for f in files:
        txt_path = (
            Path(output_dir) / (f.stem + ".txt") if output_dir
            else f.with_suffix(".txt")
        )
        try:
            meta = extract_cr_metadata(f, output_txt=txt_path)
            meta["filepath"]   = str(f)
            meta["output_txt"] = str(txt_path)
            results.append(meta)
            print(f"  OK   {f.name}")
        except Exception as exc:
            if ignore_errors:
                logger.warning("Skipped %s - %s", f.name, exc)
                print(f"  SKIP {f.name}  ({exc})")
            else:
                raise

    print(f"\nDone: {len(results)}/{len(files)} files extracted.")
    return results


# ---------------------------------------------------------------------------
# Reading layer
# ---------------------------------------------------------------------------

def _read_as_text(path: Path) -> str:
    """Chuyen file thanh plain text. Dispatch theo extension."""
    if path.suffix.lower() == ".doc":
        return _read_doc_via_olefile(path)
    return _read_docx_via_python_docx(path)


# ── .doc (OLE2 binary) via olefile ───────────────────────────────────────────

def _read_doc_via_olefile(path: Path) -> str:
    """
    Doc file .doc (OLE2/binary format) bang olefile.

    Giai phap: doc truc tiep WordDocument stream, decode cp1252,
    extract cac printable text run (>= 6 ky tu), noi lai thanh
    mot chuoi text thuan de parse.

    Uu diem so voi antiword:
    - Khong can cai tool ngoai
    - Label va value nam tren cac run rieng biet -> parse don gian hon
    - Giu nguyen toan bo noi dung cell, khong bi split dong
    """
    try:
        import olefile
    except ImportError:
        raise ImportError(
            "olefile chua duoc cai dat. Chay: pip install olefile"
        )

    ole = olefile.OleFileIO(str(path))
    try:
        stream = ole.openstream("WordDocument").read()
    finally:
        ole.close()

    # Decode toan bo stream bang cp1252 (encoding chuan cua Word 97-2003)
    raw = stream.decode("cp1252", errors="replace")

    # Extract cac printable text run: do dai >= 6, chi chua ky tu ASCII in duoc
    # va mot so ky tu dac biet hop le (tab, newline)
    runs = re.findall(r"[\x09\x0a\x0d\x20-\x7e]{6,}", raw)

    # Noi cac run bang newline, cat tai "Start of Change"
    text = "\n".join(runs)
    cut = re.search(r"Start\s+of\s+Change", text, re.IGNORECASE)
    if cut:
        text = text[: cut.start()]

    return text[:12_000]


# ── .docx ─────────────────────────────────────────────────────────────────────

def _read_docx_via_python_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    lines: list[str] = []
    char_count = 0
    MAX_CHARS = 8_000

    for block in _iter_blocks(doc):
        if isinstance(block, str):
            lines.append(block)
            char_count += len(block)
        else:
            row_text = " | ".join(cell.strip() for cell in block)
            lines.append(f"| {row_text} |")
            char_count += len(row_text)

        if "start of change" in lines[-1].lower():
            break
        if char_count >= MAX_CHARS:
            break

    return "\n".join(lines)


def _iter_blocks(doc):
    body = doc.element.body
    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if tag == "p":
            yield _para_text(child)
        elif tag == "tbl":
            yield from _table_rows(child)


def _para_text(xml_para) -> str:
    parts = []
    for node in xml_para.iter():
        local = node.tag.split("}")[-1] if "}" in node.tag else node.tag
        if local == "t" and node.text:
            parts.append(node.text)
        elif local == "br":
            parts.append("\n")
    return "".join(parts)


def _table_rows(tbl_xml):
    for tr in tbl_xml:
        if tr.tag.split("}")[-1] != "tr":
            continue
        cells = []
        for tc in tr:
            if tc.tag.split("}")[-1] != "tc":
                continue
            cells.append(" ".join(_para_text(p) for p in tc).strip())
        if cells:
            yield cells


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_MD_NOISE = re.compile(r"\*+")
# Noise characters trong CR-Form v10: tab, dau ngoac don mo dau dong, ky tu dac biet
_FORM_NOISE = re.compile(r"[\t\(\\\x00-\x1f]+")

def _clean(s: str) -> str:
    """Xoa markdown noise, form noise va khoang trang thua."""
    s = _MD_NOISE.sub("", s)
    s = _FORM_NOISE.sub(" ", s)
    return s.strip()


# Label regex cho tung truong — dung chung cho ca 2 format
_LABEL_RE: dict[str, str] = {
    "title":                        r"title\s*:",
    "reason_for_change":            r"reason\s+for\s+change\s*:",
    "summary_of_change":            r"summary\s+of\s+change\s*:",
    "consequences_if_not_approved": r"consequences\s+if\s+not\s+approved\s*:",
    "other_comments":               r"other\s+comments\s*:",
    "work_item":                    r"work\s+item(\s+code)?\s*:",
}

# TS number: hang dac biet trong docx  |  | 38.863 | CR | 0037 | rev | ...
_TS_ROW_RE = re.compile(
    r"\|\s*\|?\s*\**(?P<ts>\d{2}\.\d{3})\**\s*\|\s*\**CR\**\s*\|",
    re.IGNORECASE,
)

# TS number trong run-based text (doc):  "36.143\nCR\n57\nrev"  hoac  "36.143 CR 57 rev"
_TS_RUN_RE = re.compile(
    r"\b(?P<ts>\d{2}\.\d{3})\b[\s\S]{0,20}?\bCR\b[\s\S]{0,20}?\brev\b",
    re.IGNORECASE,
)

# Cac gia tri boilerplate can bo qua
_BOILERPLATE_RE = re.compile(
    r"^(use one of the following"
    r"|rel-\d+\s*\(release"
    r"|f\s+\(correction\)"
    r"|a\s+\(mirror"
    r"|http)",
    re.IGNORECASE,
)


def _parse_cr_fields(
    text: str,
    source_path: Optional[Path] = None,
) -> dict[str, Optional[str]]:
    """
    Parse metadata tu text da duoc chuan hoa boi _read_as_text().

    Ho tro 2 format dau vao:
      - docx (pipe-table): | ***Label:*** | Value |
      - doc  (run-based) : "Label:\nValue text\n..."
    """
    result: dict[str, Optional[str]] = {k: None for k in FIELDS_ORDER}

    is_doc = source_path is not None and source_path.suffix.lower() == ".doc"

    if is_doc:
        _parse_from_runs(text, result)
    else:
        _parse_from_pipe_table(text, result)

    return result


# ── Parser cho .docx (pipe-table format) ─────────────────────────────────────

def _parse_from_pipe_table(text: str, result: dict) -> None:
    """Parse format v12: | ***Label:*** | Value |"""
    lines = text.splitlines()

    # TS number
    for line in lines:
        m = _TS_ROW_RE.search(_clean(line))
        if m:
            result["ts_number"] = m.group("ts").strip()
            break

    # Cac truong con lai
    for line in lines:
        if "|" not in line:
            continue
        for field, pat in _LABEL_RE.items():
            if result[field] is not None:
                continue
            val = _cell_value_after_label(line, pat)
            if val and not _BOILERPLATE_RE.match(val.lower()):
                result[field] = val


def _cell_value_after_label(line: str, label_re: str) -> Optional[str]:
    """Tra ve gia tri cua cell ngay sau cell chua label_re."""
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    for i, cell in enumerate(cells):
        if re.search(label_re, _clean(cell), re.IGNORECASE):
            for j in range(i + 1, len(cells)):
                val = _clean(cells[j])
                if val:
                    return val
    return None


# ── Parser cho .doc (run-based format) ───────────────────────────────────────

def _parse_from_runs(text: str, result: dict) -> None:
    """
    Parse format v11 doc: olefile tra ve cac text run rieng biet,
    moi run tren 1 dong. Label va value nam tren 2 run ke nhau:

        "Reason for change:"      <- run label
        "Operating bands ..."     <- run value (co the nhieu run)

    TS number nam o run ngay sau 'CHANGE REQUEST', vi du:
        "CHANGE REQUEST"
        "36.143"          <- ts number
        "Current version:"
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # --- Tien xu ly: gop cac partial label bi tach doi (CR-Form v10) ---
    # "Consequences if \t(" + "not approved:" -> "Consequences if not approved:"
    merged_lines: list[str] = []
    i = 0
    while i < len(lines):
        run = lines[i]
        if (_PARTIAL_LABEL_RE.match(_clean(run))
                and not _ALL_LABEL_RE.match(_clean(run))   # chua co ':' -> bi tach
                and i + 1 < len(lines)):
            next_run = lines[i + 1]
            # Ghep 2 run thanh 1 label day du
            merged = _clean(run) + " " + _clean(next_run)
            merged_lines.append(merged)
            i += 2
        else:
            merged_lines.append(run)
            i += 1
    lines = merged_lines

    # --- TS number ---
    # Trong v11: nam o run sau "CHANGE REQUEST" va truoc "Current version:"
    for i, line in enumerate(lines):
        if line.upper() == "CHANGE REQUEST" and i + 1 < len(lines):
            candidate = lines[i + 1]
            m = re.match(r"^(\d{2}\.\d{3})$", candidate.strip())
            if m:
                result["ts_number"] = m.group(1)
                break

    # --- Cac truong con lai ---
    # Danh sach cac run dung lai (stop words): label khac, hoac bat dau phan body
    STOP_WORDS_RE = re.compile(
        r"^\d+\s*(references|definitions|symbols|abbreviations"
        r"|scope|normative|annex|table|figure)",
        re.IGNORECASE,
    )
    # Run trong nhu so ngay thang, so version, etc. — chi gom 1 run cho work_item
    DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    i = 0
    while i < len(lines):
        run = lines[i]

        for field, pat in _LABEL_RE.items():
            if result[field] is not None:
                continue
            if not re.search(pat, _clean(run), re.IGNORECASE):
                continue

            # Tim value: gop cac run ke tiep cho den khi gap label moi hoac stop word
            value_parts = []
            j = i + 1
            while j < len(lines):
                next_run = lines[j]
                if _is_any_label(next_run):       # gap label khac -> dung
                    break
                if STOP_WORDS_RE.match(next_run): # gap phan body -> dung
                    break
                if DATE_RE.match(next_run):       # gap date (co the o cung hang work_item) -> dung
                    break
                if not _BOILERPLATE_RE.match(next_run.lower()):
                    value_parts.append(next_run)
                j += 1

            if value_parts:
                value = " ".join(value_parts)
                # Bo qua neu value chi la ky tu nhieu (dau tich checkbox, v.v.)
                if len(value.strip()) > 2:
                    result[field] = value
            break

        i += 1


# Tat ca label day du (ket thuc bang ':') — dung lam stop marker chinh
_ALL_LABEL_RE = re.compile(
    r"^(title|reason\s+for(\s+change)?|summary\s+of(\s+change)?"
    r"|consequences\s+if(\s+not\s+approved)?"
    r"|other\s+comments|work\s+item(\s+code)?"
    r"|source\s+to\s+(wg|tsg)|clauses?\s+affected"
    r"|category|release|date|other\s+specs|proposed\s+change"
    r"|cr'?s?\s+revision\s+history)\s*:",
    re.IGNORECASE,
)

# Label bi tach doi (CR-Form v10): run chi chua phan dau cua label, chua co ':'
# Vi du: "Consequences if \t(" -> phan sau "not approved:" la run tiep theo
# Nhan dien bang cach match phan dau cua cac label dai
_PARTIAL_LABEL_RE = re.compile(
    r"^(consequences\s+if"
    r"|reason\s+for"
    r"|summary\s+of"
    r"|work\s+item"
    r"|source\s+to"
    r"|other\s+(comments|specs)"
    r"|clauses?\s+affected"
    r"|cr'?s?\s+revision"
    r"|proposed\s+change"
    r")\b",
    re.IGNORECASE,
)


def _is_any_label(run: str) -> bool:
    """
    Kiem tra run co phai la label CR hay khong.
    Nhan ca 2 truong hop:
      - Label day du: "Consequences if not approved:"
      - Label bi tach (v10): "Consequences if \t("  <- chua co ':'
    """
    cleaned = _clean(run)
    return bool(_ALL_LABEL_RE.match(cleaned) or _PARTIAL_LABEL_RE.match(cleaned))


# ---------------------------------------------------------------------------
# Output — ghi file .txt
# ---------------------------------------------------------------------------

def _write_txt(
    meta: dict[str, Optional[str]],
    source_filename: str,
    output_path: Path,
) -> None:
    """
    Ghi metadata ra file .txt voi dinh dang de doc.

    Vi du:
    ====================================================================
    Source : R4-146562.doc
    ====================================================================

    TS Number                        : 36.143
    Work Item                        : LTE_UTRA_SDL_BandL, ...

    Title
    -----
    Update with regard to operating bands of TS36.143

    Reason for Change
    -----------------
    Operating bands 26/XXVI to 32/XXXII ...
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    SEP = "=" * 68
    INLINE_FIELDS = {"ts_number", "work_item"}

    lines = [SEP, f"Source : {source_filename}", SEP, ""]

    for field in FIELDS_ORDER:
        label = FIELD_LABELS[field]
        value = meta.get(field) or "(not found)"

        if field in INLINE_FIELDS:
            lines.append(f"{label:<32}: {value}")
        else:
            lines.append("")
            lines.append(label)
            lines.append("-" * len(label))
            lines.append(value)

    lines += ["", SEP]
    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  # Mot file (.docx hoac .doc)")
        print("  python cr_extractor.py file.doc")
        print()
        print("  # Toan bo thu muc -> txt vao ./extracted/")
        print("  python cr_extractor.py folder/ --batch --out ./extracted/")
        sys.exit(1)

    if "--batch" in sys.argv:
        folder_arg = sys.argv[1]
        out_idx = sys.argv.index("--out") if "--out" in sys.argv else None
        out_arg = sys.argv[out_idx + 1] if out_idx else None
        batch_extract(folder_arg, output_dir=out_arg, recursive=True)
    else:
        for fp in sys.argv[1:]:
            print(f"\n{'='*68}")
            print(f"File: {fp}")
            try:
                meta = extract_cr_metadata(fp)
                for field in FIELDS_ORDER:
                    label = FIELD_LABELS[field]
                    val   = meta.get(field) or "(not found)"
                    print(f"  {label:<32}: {val[:120]}")
                txt = Path(fp).with_suffix(".txt")
                print(f"\n  -> Saved: {txt}")
            except Exception as e:
                print(f"  ERROR: {e}")
