"""
visualize.py
============
Stage 10: Vẽ interactive scatter plot 2D từ UMAP coords + cluster labels.

Đọc vào:    umap_coords.npy
            cluster_labels.npy
            embeddings_metadata.json
Ghi ra:     visualization.html    (self-contained, mở bằng browser)

Không phụ thuộc vào model hay embedding — chạy lại trong vài giây khi chỉnh
màu sắc, tooltip, hay layout.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plotly JS — download một lần vào assets/, inline vào HTML khi render
# ---------------------------------------------------------------------------

_PLOTLY_JS_URL  = "https://cdn.plot.ly/plotly-basic-2.35.2.min.js"
_PLOTLY_JS_NAME = "plotly-basic.min.js"

# APP_DIR = thư mục chứa visualize.py (sources/)
_APP_DIR = Path(__file__).parent


def _ensure_plotly_js() -> Path:
    """
    Đảm bảo plotly-basic.min.js tồn tại trong <APP_DIR>/assets/.

    - Lần đầu: download từ CDN, lưu vào assets/.
    - Lần sau: dùng file đã cache, không cần mạng.

    Trả về Path tới file JS.
    Raise RuntimeError nếu chưa có file mà không có mạng.
    """
    dest = _APP_DIR / "assets" / _PLOTLY_JS_NAME
    if dest.exists():
        logger.debug("plotly-basic.min.js found at %s (cached)", dest)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading plotly-basic.min.js → %s …", dest)
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        req = urllib.request.Request(_PLOTLY_JS_URL)
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            dest.write_bytes(resp.read())
        logger.info("plotly-basic.min.js downloaded (%.0f KB)", dest.stat().st_size / 1024)
    except Exception as exc:
        raise RuntimeError(
            f"Không thể download plotly-basic.min.js và chưa có bản cache.\n"
            f"Hãy chạy lại khi có mạng một lần để cache file về {dest}.\n"
            f"Chi tiết lỗi: {exc}"
        ) from exc
    return dest

# ---------------------------------------------------------------------------
# TF-IDF cluster labeling
# ---------------------------------------------------------------------------

# Stopwords: tiếng Anh thông dụng + 3GPP boilerplate hay xuất hiện ở mọi cluster
_STOPWORDS = {
    # common English
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "shall", "can",
    "not", "no", "nor", "so", "yet", "both", "either", "neither", "that",
    "this", "these", "those", "it", "its", "for", "with", "as", "at", "by",
    "from", "on", "into", "through", "during", "before", "after", "above",
    "below", "up", "down", "out", "off", "over", "under", "again", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "any", "both", "few", "more", "most", "other", "some", "such", "than",
    "too", "very", "just", "but", "if", "while", "although", "because",
    "since", "unless", "until", "whether", "which", "who", "whom", "whose",
    "what", "about", "also", "only", "same", "new", "see", "per",
    # 3GPP boilerplate xuất hiện ở mọi cluster → không phân biệt được
    "change", "request", "release", "version", "specification", "technical",
    "report", "3gpp", "wg", "tsg", "ran", "cr", "ts", "tr", "rel",
    "following", "based", "related", "current", "updated", "added",
    "section", "table", "figure", "annex", "note", "void", "text",
    "applicable", "supported", "defined", "described", "given", "used",
    "use", "using", "include", "included", "introduces", "introduce",
}

_TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_\-\.]{1,}")   # token >= 2 ký tự


def _tokenize(text: str) -> list[str]:
    """Lowercase + tách token, bỏ stopwords và token thuần số."""
    tokens = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok not in _STOPWORDS and not tok.isdigit():
            tokens.append(tok)
    return tokens


def compute_cluster_keywords(
    labels:   np.ndarray,
    metadata: list[dict],
    top_n:    int = 6,
) -> dict[int, list[str]]:
    """
    Tính TF-IDF để lấy top_n keywords đặc trưng cho mỗi cluster.

    Chiến lược:
    - Corpus = mỗi cluster là một "document" (gộp text của tất cả CR trong cluster).
    - Fields: title (×2) + ts_title (×1) + summary_of_change + consequences_if_not_approved.
    - Dynamic IDF threshold: token xuất hiện > ~60% cluster bị loại tự động.
    - Noise (label = -1) bị bỏ qua — noise không có label ngữ nghĩa ổn định.
    - TF  = tần suất token trong cluster.
    - IDF = log((N+1) / (df+1)) + 1 — penalize token xuất hiện ở nhiều cluster.

    Trả về: {cluster_id: ["kw1", "kw2", ...]}
    """
    unique_labels = sorted(lbl for lbl in set(labels.tolist()) if lbl >= 0)
    if not unique_labels:
        return {}

    # --- Xây dựng bag-of-words cho từng cluster ---
    cluster_bow: dict[int, dict[str, int]] = {}

    for lbl in unique_labels:
        bow: dict[str, int] = {}
        for i, meta_lbl in enumerate(labels.tolist()):
            if meta_lbl != lbl:
                continue
            m = metadata[i]
            # Title boost ×2: súc tích, đặc trưng nhất cho CR
            for tok in _tokenize(m.get("title", "") or "") * 2:
                bow[tok] = bow.get(tok, 0) + 1
            # TS title boost ×1: bổ sung ngữ cảnh spec
            for tok in _tokenize(m.get("ts_title", "") or ""):
                bow[tok] = bow.get(tok, 0) + 1
            # Body fields: chỉ giữ 2 field có signal cao nhất
            for field in ("summary_of_change", "consequences_if_not_approved"):
                for tok in _tokenize(m.get(field, "") or ""):
                    bow[tok] = bow.get(tok, 0) + 1
        cluster_bow[lbl] = bow

    n_clusters = len(unique_labels)

    # --- IDF: đếm số cluster mà mỗi token xuất hiện ---
    df: dict[str, int] = {}
    for bow in cluster_bow.values():
        for tok in bow:
            df[tok] = df.get(tok, 0) + 1

    import math

    # Token có IDF < ngưỡng này xuất hiện quá nhiều cluster → vô nghĩa như stopword
    # log((N+1)/(df+1)) + 1 = 1.3
    # log((N+1)/(df+1)) = 0.3
    # (N+1)/(df+1) = e^0.3 ≈ 1.35
    # df ≈ N/1.35 ≈ 74% N
    # Vậy 1.3 thực ra lọc token xuất hiện ở ~74% cluster
    _IDF_THRESHOLD = 1.3

    # --- TF-IDF score và lấy top_n ---
    result: dict[int, list[str]] = {}
    for lbl, bow in cluster_bow.items():
        total_tokens = sum(bow.values()) or 1
        scored: list[tuple[float, str]] = []
        for tok, count in bow.items():
            tf  = count / total_tokens
            idf = math.log((n_clusters + 1) / (df.get(tok, 0) + 1)) + 1
            if idf < _IDF_THRESHOLD:   # dynamic stopword: quá phổ biến → bỏ
                continue
            scored.append((tf * idf, tok))

        scored.sort(reverse=True)
        result[lbl] = [tok for _, tok in scored[:top_n]]

    logger.info(
        "TF-IDF keywords computed for %d clusters (top %d each)",
        len(result), top_n,
    )
    return result

# ---------------------------------------------------------------------------
# Color palette cho clusters
# Noise (label = -1) luôn màu xám nhạt.
# ---------------------------------------------------------------------------

_NOISE_COLOR = "#575858"

# Tên hiển thị cho noise points — thay đổi tại đây nếu muốn dùng tên khác
NOISE_LABEL = "Other"

# Plotly qualitative palette — đủ 24 màu phân biệt rõ
_CLUSTER_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
    "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
    "#393b79", "#637939", "#8c6d31", "#843c39",
]


def _cluster_color(label: int) -> str:
    if label < 0:
        return _NOISE_COLOR
    return _CLUSTER_PALETTE[label % len(_CLUSTER_PALETTE)]


# ---------------------------------------------------------------------------
# pywebview click-to-open handler
# ---------------------------------------------------------------------------

# JS được inject vào HTML để bắt sự kiện click trên Plotly dot.
# Khi chạy trong pywebview, window.pywebview.api.open_file(path) sẽ gọi
# FileAPI.open_file() bên Python → mở file Word bằng OS.
# Khi chạy trong browser thông thường, đoạn JS này vô hại (window.pywebview
# không tồn tại → if-check thất bại, không làm gì).
_PYWEBVIEW_CLICK_JS = """\
<script>
(function () {
    "use strict";
    function attachClickHandler() {
        var divs = document.querySelectorAll(".plotly-graph-div");
        if (!divs.length) {
            setTimeout(attachClickHandler, 300);
            return;
        }
        divs.forEach(function (div) {
            if (div._pwv_attached) return;   // tránh attach 2 lần
            div._pwv_attached = true;
            div.on("plotly_click", function (data) {
                if (!data || !data.points || !data.points.length) return;
                var filePath = data.points[0].customdata[0];
                if (filePath && window.pywebview && window.pywebview.api) {
                    window.pywebview.api.open_file(filePath);
                }
            });
        });
    }
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", attachClickHandler);
    } else {
        attachClickHandler();
    }
})();
</script>
"""


def _inject_pywebview_click_handler(html: str) -> str:
    """
    Inject JS click handler vào HTML trước </body>.

    An toàn để gọi kể cả khi mở bằng browser thông thường — handler chỉ
    kích hoạt khi window.pywebview.api tồn tại (tức là đang chạy trong webview).
    """
    return html.replace("</body>", _PYWEBVIEW_CLICK_JS + "\n</body>", 1)


# ---------------------------------------------------------------------------
# Build hover text
# ---------------------------------------------------------------------------

def _make_hover(entry: dict, label: int, keywords: list[str]) -> str:
    cluster_str = NOISE_LABEL if label < 0 else str(label)
    kw_str      = ", ".join(keywords) if keywords else "—"

    def _trunc(s: str, n: int = 80) -> str:
        s = (s or "").strip()
        return s[:n] + "…" if len(s) > n else s

    lines = [
        f"<b>cluster:</b> {cluster_str}",
        f"<b>keywords:</b> {kw_str}",
        f"<b>file:</b> {entry.get('filename', '')}",
        f"<b>ts:</b> {entry.get('ts_number', '')}",
        f"<b>work_item:</b> {_trunc(entry.get('work_item', ''), 60)}",
        f"<b>title:</b> {_trunc(entry.get('title', ''), 80)}",
    ]
    return "<br>".join(lines)


# ---------------------------------------------------------------------------
# Core plot builder
# ---------------------------------------------------------------------------

def build_figure(
    coords:   np.ndarray,   # (N, 2)
    labels:   np.ndarray,   # (N,)
    metadata: list[dict],
    cluster_keywords: dict[int, list[str]] | None = None,
):
    """
    Trả về plotly Figure object.
    Mỗi cluster là một trace riêng → legend rõ ràng.

    cluster_keywords: dict từ compute_cluster_keywords(), nếu None thì bỏ qua.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        raise ImportError("plotly chưa được cài. Chạy: pip install plotly")

    kw = cluster_keywords or {}
    unique_labels = sorted(set(labels.tolist()))
    traces = []

    for lbl in unique_labels:
        mask   = labels == lbl
        x_vals = coords[mask, 0].tolist()
        y_vals = coords[mask, 1].tolist()

        keywords = kw.get(lbl, [])
        hover = [
            _make_hover(metadata[i], lbl, keywords)
            for i in range(len(labels)) if labels[i] == lbl
        ]
        # customdata: [file_path, search_text]
        # - file_path  : để JS pywebview mở file khi click dot
        # - search_text: lowercase concat của title + ts_number + filename
        #                → dùng cho keyword search bar ở client-side
        customdata = [
            [
                metadata[i].get("file_path", ""),
                "|".join([
                    (metadata[i].get("title",     "") or "").lower(),
                    (metadata[i].get("ts_number", "") or "").lower(),
                    (metadata[i].get("filename",  "") or "").lower(),
                ]),
            ]
            for i in range(len(labels)) if labels[i] == lbl
        ]

        # Legend: NOISE_LABEL hoặc "C3: kw1 · kw2 · kw3 · kw4 · kw5"
        if lbl < 0:
            name = NOISE_LABEL
        elif keywords:
            name = f"C{lbl}: {' · '.join(keywords[:6])}"
        else:
            name = f"C{lbl}"

        color   = _cluster_color(lbl)
        if lbl < 0:
            marker_dict = dict(
            symbol  = "asterisk",
            size    = 6,
            color   = "black",
            opacity = 0.7,
            line    = dict(width=1.0, color="black"),
          )
        else:
            marker_dict = dict(
            symbol  = "circle",
            size    = 8,
            color   = color,
            opacity = 0.85,
            line    = dict(width=0),
          )

        # Noise: go.Scatter (cần symbol "asterisk", Scattergl hỗ trợ hạn chế)
        # Cluster: go.Scattergl (WebGL — render nhanh hơn, không cần build SVG DOM)
        TraceClass = go.Scatter if lbl < 0 else go.Scattergl

        traces.append(TraceClass(
            x    = x_vals,
            y    = y_vals,
            mode = "markers",
            name = name,
            marker = marker_dict,
            text          = hover,
            hovertemplate = "%{text}<extra></extra>",
            hoverlabel    = dict(
                bgcolor   = "white",
                font_size = 12,
                namelength = -1,
            ),
            customdata = customdata,
        ))

    n_clusters = sum(1 for l in unique_labels if l >= 0)
    n_noise    = int((labels == -1).sum())
    n_total    = len(labels)

    fig = go.Figure(data=traces)

    # --- Centroid annotations: đặt text label tại trung tâm mỗi cluster ---
    annotations = []
    for lbl in unique_labels:
        if lbl < 0:
            continue   # noise không cần annotation
        mask = labels == lbl
        cx   = float(coords[mask, 0].mean())
        cy   = float(coords[mask, 1].mean())
        kws  = kw.get(lbl, [])
        annotations.append(dict(
            x          = cx,
            y          = cy,
            text       = f"<b>C{lbl}</b>",
            showarrow  = False,
            font       = dict(size=10, color="#333333"),
            align      = "center",
        ))

    fig.update_layout(
        title = dict(
            text     = (
                f"3GPP CR Clustering — {n_total} documents | "
                f"{n_clusters} clusters | {n_noise} noise"
            ),
            font     = dict(size=16),
            x        = 0.5,
            xanchor  = "center",
        ),
        xaxis  = dict(title="UMAP-1", showgrid=True, gridcolor="#eeeeee", zeroline=False),
        yaxis  = dict(title="UMAP-2", showgrid=True, gridcolor="#eeeeee", zeroline=False),
        legend = dict(
            title       = "Cluster",
            itemsizing  = "constant",
            bgcolor     = "rgba(255,255,255,0.85)",
            bordercolor = "#cccccc",
            borderwidth = 1,
            # Pin legend sát mép phải, ngoài plot area
            x           = 1.02,
            xanchor     = "left",
            y           = 1.0,
            yanchor     = "top",
        ),
        margin = dict(l=60, r=260, t=130, b=60),
        annotations   = annotations,
        plot_bgcolor  = "white",
        paper_bgcolor = "white",
        hovermode     = "closest",
        width  = 1400,
        height = 800,
    )
    return fig


# ---------------------------------------------------------------------------
# Keyword search bar — inject vào HTML (client-side JS only)
# ---------------------------------------------------------------------------

_SEARCH_BAR_HTML = """\
<style>
#cr-search-bar {
    position: fixed;
    top: 90px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 9999;
    display: flex;
    align-items: center;
    gap: 6px;
    background: rgba(255,255,255,0.96);
    border: 1px solid #c8c8c8;
    border-radius: 24px;
    padding: 5px 12px 5px 14px;
    box-shadow: 0 2px 10px rgba(0,0,0,0.13);
    font-family: sans-serif;
    font-size: 13px;
}
#cr-search-input {
    border: none;
    outline: none;
    background: transparent;
    font-size: 13px;
    width: 240px;
    color: #222;
}
#cr-search-input::placeholder { color: #aaa; }
#cr-search-clear {
    cursor: pointer;
    color: #999;
    font-size: 15px;
    line-height: 1;
    padding: 0 2px;
    display: none;
    background: none;
    border: none;
}
#cr-search-clear:hover { color: #555; }
#cr-search-count {
    color: #666;
    white-space: nowrap;
    min-width: 80px;
    text-align: right;
}
</style>

<div id="cr-search-bar">
    <svg width="14" height="14" viewBox="0 0 20 20" fill="none"
         stroke="#aaa" stroke-width="2.2" stroke-linecap="round">
        <circle cx="8.5" cy="8.5" r="5.5"/>
        <line x1="13" y1="13" x2="18" y2="18"/>
    </svg>
    <input id="cr-search-input" type="text"
           placeholder="Search title, TS number, filename…" autocomplete="off"/>
    <button id="cr-search-clear" title="Clear">&#x2715;</button>
    <span id="cr-search-count"></span>
</div>

<script>
(function () {
    "use strict";

    // Debounce: tránh restyle liên tục khi user gõ nhanh
    function debounce(fn, ms) {
        var timer;
        return function () {
            clearTimeout(timer);
            timer = setTimeout(fn, ms);
        };
    }

    function attachSearchHandler() {
        var plotDiv = document.querySelector(".plotly-graph-div");
        if (!plotDiv || !plotDiv.data) {
            setTimeout(attachSearchHandler, 300);
            return;
        }

        var input  = document.getElementById("cr-search-input");
        var clear  = document.getElementById("cr-search-clear");
        var counter= document.getElementById("cr-search-count");

        var totalPoints = plotDiv.data.reduce(function (sum, t) {
            return sum + (t.x ? t.x.length : 0);
        }, 0);

        function applySearch(keyword) {
            var kw = keyword.trim().toLowerCase();

            // Reset: selectedpoints null -> Plotly restore toan bo diem ve goc
            // Legend khong bi anh huong boi selectedpoints API
            if (!kw) {
                clear.style.display = "none";
                counter.textContent = "";
                plotDiv.data.forEach(function (_, ti) {
                    Plotly.restyle(plotDiv, { selectedpoints: [null] }, [ti]);
                });
                return;
            }

            clear.style.display = "inline";
            var matchedTotal = 0;

            plotDiv.data.forEach(function (trace, ti) {
                var n = trace.x ? trace.x.length : 0;
                if (n === 0) return;

                // customdata[i] = [file_path, search_text]
                var matchedIndices = [];
                for (var i = 0; i < n; i++) {
                    var cd = trace.customdata && trace.customdata[i];
                    var searchText = (cd && cd[1]) ? cd[1] : "";
                    if (searchText.indexOf(kw) !== -1) {
                        matchedIndices.push(i);
                        matchedTotal++;
                    }
                }

                // selectedpoints API:
                // - Legend items KHONG bi anh huong
                // - selected   -> opacity 1.0, giu mau goc
                // - unselected -> opacity 0.08, giu mau goc (chi mo, khong doi mau)
                Plotly.restyle(plotDiv, {
                    selectedpoints:              [matchedIndices],
                    "selected.marker.opacity":   1.0,
                    "unselected.marker.opacity": 0.15,
                }, [ti]);
            });

            counter.textContent = matchedTotal + " / " + totalPoints + " matched";
        }

        var debouncedSearch = debounce(function () {
            applySearch(input.value);
        }, 120);

        input.addEventListener("input", debouncedSearch);

        clear.addEventListener("click", function () {
            input.value = "";
            applySearch("");
            input.focus();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", attachSearchHandler);
    } else {
        attachSearchHandler();
    }
})();
</script>
"""


def _inject_search_bar(html: str) -> str:
    """Inject search bar UI + JS vào HTML trước </body>."""
    return html.replace("</body>", _SEARCH_BAR_HTML + "\n</body>", 1)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(data_dir: str | Path = ".", server_port: int | None = None) -> Path:
    """
    Đọc outputs của cluster_pipeline, vẽ và lưu visualization.html.

    Parameters
    ----------
    data_dir    : thư mục chứa umap_coords.npy / cluster_labels.npy /
                  embeddings_metadata.json
    server_port : giữ lại để tương thích ngược với run_all.py CLI, không dùng.
                  Click-to-open được xử lý bởi pywebview (inject vô điều kiện).

    Trả về Path tới file HTML.
    """
    data_dir = Path(data_dir)

    coords_path = data_dir / "umap_coords.npy"
    labels_path = data_dir / "cluster_labels.npy"
    meta_path   = data_dir / "embeddings_metadata.json"

    for p in (coords_path, labels_path, meta_path):
        if not p.exists():
            raise FileNotFoundError(
                f"{p} không tồn tại. Chạy cluster_pipeline.py trước."
            )

    logger.info("Loading visualization inputs from %s …", data_dir)
    coords   = np.load(str(coords_path))
    labels   = np.load(str(labels_path))
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    assert coords.shape[0] == len(labels) == len(metadata), (
        "Mismatch giữa coords / labels / metadata — hãy chạy lại cluster_pipeline."
    )

    fig      = build_figure(coords, labels, metadata,
                            cluster_keywords=compute_cluster_keywords(labels, metadata))
    out_path = data_dir / "visualization.html"

    # Đảm bảo plotly-basic.min.js đã có trong assets/ (download lần đầu nếu chưa có)
    js_path    = _ensure_plotly_js()
    js_content = js_path.read_text(encoding="utf-8")

    # include_plotlyjs=False → Plotly không nhúng JS mặc định (full 3.5MB từ CDN)
    # Ta tự inject bản basic (~1.2MB) đã cache local → offline + nhỏ hơn
    fig.write_html(
        str(out_path),
        include_plotlyjs = False,
        full_html        = True,
        config           = {
            "scrollZoom":     True,
            "displayModeBar": True,
            "toImageButtonOptions": {
                "format":   "svg",
                "filename": "cr_clustering",
            },
        },
    )

    html = out_path.read_text(encoding="utf-8")

    # Inject plotly-basic JS inline (self-contained, hoạt động offline)
    html = html.replace(
        "<head>",
        f"<head>\n<script>{js_content}</script>",
        1,
    )
    html = _inject_pywebview_click_handler(html)
    html = _inject_search_bar(html)
    out_path.write_text(html, encoding="utf-8")

    n_clusters = int(labels.max()) + 1 if labels.max() >= 0 else 0
    n_noise    = int((labels == -1).sum())
    logger.info(
        "Visualization saved: %s  (%d docs, %d clusters, %d noise)",
        out_path, len(labels), n_clusters, n_noise,
    )
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level  = logging.INFO,
        format = "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt= "%H:%M:%S",
    )
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    out = run(data_dir=data_dir)
    print(f"Open in browser: {out.resolve()}")
