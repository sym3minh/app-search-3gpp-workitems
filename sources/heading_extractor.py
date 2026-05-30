"""
3GPP CR Heading Extractor
=========================
Duyệt đệ quy thư mục Input/, tìm tất cả file .docx, extract các heading
nằm trong vùng change content (giữa Start of change / End of change).

Track Changes được xử lý đúng:
  - Bỏ qua <w:del> (text bị xóa)
  - Giữ lại <w:ins> (text được thêm mới)
  - Giữ lại text thường (không có track change)

Extraction strategy (theo thứ tự ưu tiên):
  1. Marker-based  : lấy heading giữa "Start/End of change"
  2. Post-CR-form  : không có marker -> lấy heading sau bảng CR form
                     (bảng chứa "CHANGE REQUEST")
  3. All headings  : không có CR form -> lấy tất cả heading trong file

Kết quả ghi ra Output/summary.txt.

Usage:
    python heading_extractor.py
    python heading_extractor.py --input ./MyDocs --output ./out.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# XML namespace helper
# ---------------------------------------------------------------------------

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


# ---------------------------------------------------------------------------
# Track-Change-aware text extraction
# ---------------------------------------------------------------------------

def _collect_text(node, parts: list[str]) -> None:
    """
    Duyệt đệ quy XML node, thu thập text đã resolve track changes:
      - <w:del>  -> bỏ qua toàn bộ nhánh (text bị xóa)
      - <w:ins>  -> đệ quy bình thường (text mới)
      - <w:t>    -> lấy text
      - <w:tab>  -> thêm space (3GPP dùng tab giữa clause number và title)
      - <w:br>   -> thêm newline
    """
    local = node.tag.split("}")[-1] if "}" in node.tag else node.tag

    if local == "del":
        return

    if local == "t" and node.text:
        parts.append(node.text)
    elif local == "tab":
        parts.append(" ")
    elif local == "br":
        parts.append("\n")

    for child in node:
        _collect_text(child, parts)


def _para_text_resolved(xml_para) -> str:
    parts: list[str] = []
    _collect_text(xml_para, parts)
    return "".join(parts).strip()


# ---------------------------------------------------------------------------
# Heading style detection
# ---------------------------------------------------------------------------

def _build_style_heading_map(doc) -> dict[str, int]:
    """
    Đọc styles.xml -> {styleId: heading_level}.

    Cần thiết vì nhiều file 3GPP dùng style ID dạng số
    ("3"->Heading 1, "4"->Heading 2, ...) thay vì tên chuẩn.
    """
    mapping: dict[str, int] = {}
    for style in doc.styles:
        name = style.name or ""
        m = re.match(r"[Hh]eading\s+(\d+)", name)
        if m:
            mapping[style.style_id] = int(m.group(1))
    return mapping


def _get_heading_level(xml_para, style_map: dict[str, int]) -> Optional[int]:
    """
    Trả về heading level (1-9) hoặc None nếu không phải heading.

    Kiểm tra theo thứ tự:
      1. <w:pStyle> tra trong style_map  (C1-246946 style: ID số "3","4",...)
      2. <w:pStyle> regex fallback        (style ID dạng "Heading1")
      3. <w:outlineLvl>                   (C4-245533 style: không có pStyle,
                                           chỉ set outlineLvl trực tiếp)
    """
    pPr = xml_para.find(_w("pPr"))
    if pPr is None:
        return None

    # --- Cách 1 & 2: pStyle ---
    pStyle = pPr.find(_w("pStyle"))
    if pStyle is not None:
        style_val = pStyle.get(_w("val"), "")

        if style_val in style_map:
            return style_map[style_val]

        m = re.match(r"[Hh]eading\s*(\d+)", style_val)
        if m:
            return int(m.group(1))

    # --- Cách 3: outlineLvl trực tiếp trên paragraph ---
    # Word dùng <w:outlineLvl w:val="N"/> để đánh dấu heading khi không
    # gán Heading style. Navigation Pane và TOC đều đọc từ đây.
    # val là 0-based: 0=Heading1, 1=Heading2, ..., 8=Heading9
    outline = pPr.find(_w("outlineLvl"))
    if outline is not None:
        val = outline.get(_w("val"), "")
        if val.isdigit() and int(val) <= 8:
            return int(val) + 1  # chuyển sang 1-based

    return None


# ---------------------------------------------------------------------------
# Change section boundary detection
# ---------------------------------------------------------------------------

# 3GPP dùng nhiều dạng marker:
#   "***** Start of change *****"
#   "---Start of the 1st Change---"
#   "* * * First Change * * *"       "* * * * 4th Changes * * * *"
#   "2nd Changes"                    "3rd change"
_START_RE = re.compile(
    r"(start\s+(of\s+)?(the\s+)?(\d+(st|nd|rd|th)\s+|first\s+|second\s+|third\s+)?changes?"
    r"|[\*\-\s]*(first|second|third|\d+(st|nd|rd|th))\s+changes?[\*\-\s]*$"
    r"|^[\*\-\s]*(\d+(st|nd|rd|th))\s+changes?[\*\-\s]*$)",
    re.IGNORECASE,
)

_END_RE = re.compile(
    r"(end\s+(of\s+)?(the\s+)?(\d+(st|nd|rd|th)\s+|first\s+|second\s+|third\s+)?changes?"
    r"|end\s+of\s+changes?)",
    re.IGNORECASE,
)

# Pattern dùng để lọc marker text ra khỏi danh sách heading
# (trường hợp marker paragraph có heading style/outlineLvl)
_MARKER_RE = re.compile(
    r"(((?:(?:start|end)(?:\s+of)?\s+)?(?:the\s+)?(?:first|second|third|next|\w+th|\d+(?:st|nd|rd|th)))\s+changes?"
    r"|^\s*([*><\s]+?)\s*(.*?)\s*([*><\s]+?)\s*$)",
    re.IGNORECASE,
)

# Nhận diện bảng CR form: cell đầu tiên chứa "CHANGE REQUEST" hoặc "CR-Form"
_CR_FORM_RE = re.compile(r"(CHANGE\s+REQUEST|CR-Form)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helper: collect headings từ một list các body children
# ---------------------------------------------------------------------------

def _headings_from_children(children, style_map: dict[str, int]) -> list[tuple[int, str]]:
    """Lấy tất cả heading có style từ danh sách XML children."""
    headings = []
    for child in children:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "p":
            level = _get_heading_level(child, style_map)
            if level is not None:
                text = _para_text_resolved(child)
                if text:
                    clean = re.sub(r"\s+", " ", text).strip()
                    if not _MARKER_RE.search(clean):
                        headings.append((level, clean))
    return headings


# ---------------------------------------------------------------------------
# Strategy 1: Marker-based
# ---------------------------------------------------------------------------

def _extract_marker_based(
    body_children: list,
    style_map: dict[str, int],
) -> list[tuple[int, str]]:
    """
    Lấy heading nằm giữa Start/End of change marker.
    Trả về list rỗng nếu không tìm thấy marker nào.
    """
    headings = []
    in_change = False
    found_any_marker = False

    for child in body_children:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if local == "p":
            text = _para_text_resolved(child)

            if _START_RE.search(text):
                in_change = True
                found_any_marker = True
                continue

            if _END_RE.search(text):
                in_change = False
                continue

            if in_change:
                level = _get_heading_level(child, style_map)
                if level is not None and text:
                    clean = re.sub(r"\s+", " ", text).strip()
                    # Loại bỏ nếu text chính là marker (paragraph có cả
                    # heading style lẫn marker content)
                    if not _MARKER_RE.search(clean):
                        headings.append((level, clean))

        elif local == "tbl":
            # Marker đôi khi nằm trong cell bảng
            for para in child.iter(_w("p")):
                cell_text = _para_text_resolved(para)
                if _START_RE.search(cell_text):
                    in_change = True
                    found_any_marker = True
                if _END_RE.search(cell_text):
                    in_change = False

    if not found_any_marker:
        return []  # báo hiệu "không có marker" để fallback

    return headings


# ---------------------------------------------------------------------------
# Strategy 2: Post-CR-form (fallback khi không có marker)
# ---------------------------------------------------------------------------

def _find_last_cr_form_index(body_children: list) -> int:
    """
    Tìm index của bảng CR form cuối cùng trong body.
    CR form được nhận diện bằng cell chứa "CHANGE REQUEST" hoặc "CR-Form".
    Trả về -1 nếu không tìm thấy.
    """
    last_idx = -1
    for i, child in enumerate(body_children):
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "tbl":
            # Lấy text của tất cả cell trong bảng
            for para in child.iter(_w("p")):
                cell_text = _para_text_resolved(para)
                if _CR_FORM_RE.search(cell_text):
                    last_idx = i
                    break
    return last_idx


def _extract_post_cr_form(
    body_children: list,
    style_map: dict[str, int],
) -> tuple[list[tuple[int, str]], str]:
    """
    Fallback strategy 2: lấy heading sau bảng CR form cuối cùng.
    Trả về (headings, strategy_note).
    """
    cr_form_idx = _find_last_cr_form_index(body_children)

    if cr_form_idx >= 0:
        after_cr_form = body_children[cr_form_idx + 1:]
        headings = _headings_from_children(after_cr_form, style_map)
        return headings, "fallback: no change markers — extracted headings after CR form table"
    else:
        # Strategy 3: không có CR form table -> lấy tất cả
        headings = _headings_from_children(body_children, style_map)
        return headings, "fallback: no change markers, no CR form table — extracted all headings"


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_headings_from_docx(
    filepath: Path,
) -> tuple[list[tuple[int, str]], str]:
    """
    Trích xuất heading từ file .docx.

    Returns
    -------
    (headings, strategy_note)
      headings      : list of (level, text)
      strategy_note : mô tả strategy đã dùng
    """
    from docx import Document

    doc = Document(str(filepath))
    body = doc.element.body
    style_map = _build_style_heading_map(doc)
    body_children = list(body)

    # Strategy 1: marker-based
    headings = _extract_marker_based(body_children, style_map)
    if headings or _has_any_start_marker(body_children):
        # Có marker (dù có thể không có heading trong vùng change)
        return headings, "marker-based"

    # Strategy 2 & 3: fallback
    return _extract_post_cr_form(body_children, style_map)


def _has_any_start_marker(body_children: list) -> bool:
    """Kiểm tra có tồn tại bất kỳ start marker nào không."""
    for child in body_children:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "p":
            if _START_RE.search(_para_text_resolved(child)):
                return True
        elif local == "tbl":
            for para in child.iter(_w("p")):
                if _START_RE.search(_para_text_resolved(para)):
                    return True
    return False


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_input_folder(input_dir: Path, output_file: Path) -> None:
    """
    Duyệt đệ quy input_dir, xử lý tất cả .docx, ghi summary.txt.

    Cấu trúc thư mục:
        input_dir/
            c1-12345/file.docx
            c2-67890/file.docx
    """
    docx_files = sorted(input_dir.rglob("*.docx"))

    if not docx_files:
        print(f"Không tìm thấy file .docx nào trong: {input_dir}")
        return

    output_file.parent.mkdir(parents=True, exist_ok=True)

    SEP_MAJOR = "=" * 72
    SEP_MINOR = "-" * 72

    lines: list[str] = []
    lines.append(SEP_MAJOR)
    lines.append("3GPP CR HEADING EXTRACTION SUMMARY")
    lines.append(f"Input folder : {input_dir.resolve()}")
    lines.append(f"Files found  : {len(docx_files)}")
    lines.append(SEP_MAJOR)

    ok_count = 0
    skip_count = 0

    for docx_path in docx_files:
        try:
            rel = docx_path.relative_to(input_dir)
        except ValueError:
            rel = docx_path

        lines.append("")
        lines.append(SEP_MINOR)
        lines.append(f"File     : {rel}")

        try:
            headings, strategy = extract_headings_from_docx(docx_path)
            lines.append(f"Strategy : {strategy}")

            if headings:
                lines.append(f"Headings : {len(headings)} found")
                lines.append("")
                min_level = min(lvl for lvl, _ in headings)
                for level, text in headings:
                    indent = "  " * (level - min_level)
                    lines.append(f"{indent}{text}")
            else:
                lines.append("Headings : (none found)")

            ok_count += 1

        except Exception as exc:
            lines.append(f"ERROR    : {exc}")
            skip_count += 1

    lines.append("")
    lines.append(SEP_MAJOR)
    lines.append(f"Done: {ok_count} OK, {skip_count} errors, {len(docx_files)} total")
    lines.append(SEP_MAJOR)

    output_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"Summary written -> {output_file}")
    print(f"  {ok_count} OK, {skip_count} errors, {len(docx_files)} total files")


# ---------------------------------------------------------------------------
# Step 2: Filter headings  (strip clause numbers + drop generic titles)
# ---------------------------------------------------------------------------

# Clause-number prefix patterns:
#   5.5.4.1.2   Y.1.2   8.2.26.x   42.3.xx.1   6X.23.3.34
_CLAUSE_RE = re.compile(
    r"^\s*(?:[^\s]*[\d.:_][^\s]*|[a-zA-Z0-9])\s+",
    re.IGNORECASE,
)

# Exact titles to drop (case-sensitive, full-string match after stripping clause number)
_DROP_EXACT: frozenset[str] = frozenset({"General", "General aspects", "Overview"})


def filter_headings(summary_file: Path, filtered_file: Path) -> None:
    """
    Đọc summary.txt, áp dụng bước 2 cho mỗi heading line:

      1. Bỏ clause-number prefix ở đầu (vd: "5.5.4.1.2 ", "Y.1.2 ", "8.2.26.x ").
      2. Bỏ dòng nếu phần còn lại (sau khi strip) khớp chính xác (case-sensitive)
         với một trong: "General", "General aspects", "Overview".

    Tất cả các dòng không phải heading (header/separator/metadata) được giữ nguyên.
    Kết quả ghi ra filtered_file.

    Một "heading line" trong summary.txt là dòng KHÔNG bắt đầu bằng:
      - "=" hoặc "-"  (separator)
      - "File", "Strategy", "Headings", "ERROR", "Done", "Input", "Files",
        "3GPP"         (metadata keywords)
      - khoảng trắng hoàn toàn (empty)
    Những dòng bắt đầu bằng khoảng trắng (indented headings) cũng là heading line.
    """
    if not summary_file.exists():
        print(f"ERROR: summary file not found: {summary_file}")
        return

    raw_lines = summary_file.read_text(encoding="utf-8").splitlines()

    # Metadata prefixes that are NOT heading content
    _META_PREFIXES = (
        "=", "-",
        "File", "Strategy", "Headings", "ERROR", "Done",
        "Input folder", "Files found", "3GPP",
    )

    filtered: list[str] = []

    for line in raw_lines:
        stripped_line = line.strip()

        # Pass-through: empty lines and metadata/separator lines
        if not stripped_line or any(stripped_line.startswith(p) for p in _META_PREFIXES):
            filtered.append(line)
            continue

        # ---- This is a heading line ----
        # Preserve leading indentation so the tree structure stays intact
        leading_ws = len(line) - len(line.lstrip())
        indent = line[:leading_ws]
        content = line[leading_ws:]  # text without indentation

        # Step 2a: strip clause-number prefix
        content = _CLAUSE_RE.sub("", content).strip()

        # Step 2b: drop if exact match (case-sensitive)
        if content in _DROP_EXACT:
            continue  # skip this heading entirely

        # Re-attach indentation and keep
        filtered.append(indent + content)

    filtered_file.parent.mkdir(parents=True, exist_ok=True)
    filtered_file.write_text("\n".join(filtered), encoding="utf-8")
    print(f"Filtered headings written -> {filtered_file}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract headings from 3GPP CR .docx files"
    )
    parser.add_argument("--input",  "-i", default="Input",
                        help="Root input folder (default: Input/)")
    parser.add_argument("--output", "-o", default="Output/summary.txt",
                        help="Output summary file (default: Output/summary.txt)")
    parser.add_argument("--filtered", "-f", default="Output/filtered_headings.txt",
                        help="Filtered headings output (default: Output/filtered_headings.txt)")
    args = parser.parse_args()

    input_dir      = Path(args.input)
    output_file    = Path(args.output)
    filtered_file  = Path(args.filtered)

    if not input_dir.exists():
        print(f"ERROR: Input folder not found: {input_dir}")
        sys.exit(1)

    # Step 1: extract headings -> summary.txt
    process_input_folder(input_dir, output_file)

    # Step 2: filter clause numbers + generic titles -> filtered_headings.txt
    filter_headings(output_file, filtered_file)