# 3GPP Search Tool — Project Documentation

> **Purpose of this document:** Comprehensive codebase reference for GitHub documentation and AI session context reuse.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Folder Structure](#3-folder-structure)
4. [Architecture Explanation](#4-architecture-explanation)
5. [Key Modules Breakdown](#5-key-modules-breakdown)
6. [Execution Flow](#6-execution-flow)
7. [Important Design Decisions](#7-important-design-decisions)
8. [How to Run the Project](#8-how-to-run-the-project)

---

## 1. Project Overview

### Purpose

**3GPP Search Tool** is a Windows desktop application for engineers and researchers working with [3GPP](https://www.3gpp.org/) standardization documents. It provides a unified interface to search, browse, download, and semantically analyze 3GPP Change Requests (CRs), Work Items (WIs), and Technical Specifications (TSs).

### Problem It Solves

3GPP publishes thousands of technical documents across hundreds of Work Items and Releases. Finding relevant Change Requests, understanding their scope, and clustering similar CRs by topic is a time-consuming manual process. This tool automates:

- Searching the official 3GPP Work Plan (Excel file) for Work Items by keyword
- Full-text search across CR titles using an offline SQLite FTS5 database
- Looking up approved Change Requests with metadata (spec number, meeting, status)
- Downloading TDoc Word files directly from the 3GPP portal
- Extracting structured metadata (title, reason for change, summary, etc.) from CR `.docx`/`.doc` files
- Running a full ML pipeline (embedding → clustering → visualization) on a corpus of CR documents

### Key Features

- **6-tab GUI** with dark/light theme toggle
- **Work Item Search** — keyword search on `workplan.xlsx`, with optional parallel CR/Spec existence checks
- **Advanced CR Title Search** — SQLite FTS5 full-text search with OR, phrase, and wildcard syntax
- **Approved CR Search** — filter and browse CRs with TSG-level "Approved" status
- **WI Detail / TDoc Lookup** — fetch and process all agreed TDocs for a given Work Item
- **Spec Search** — browse Technical Specifications linked to Work Items
- **CR Clustering (Tab 6)** — full ML pipeline: BGE embeddings → PCA → HDBSCAN → UMAP → interactive HTML visualization
- **Semantic RAG Search** — ChromaDB-backed retrieval for natural language CR queries
- **Smart caching** — local cache for workplan, Excel files, downloaded ZIPs, embeddings

---

## 2. Tech Stack

### Core Language

| Component | Technology |
|---|---|
| Language | Python 3.9–3.13 |
| GUI Framework | Tkinter + ttk (standard library) |
| Entry Point | `pythonw.exe` (no console window on Windows) |

### Data & Search

| Component | Technology |
|---|---|
| Workplan parsing | `openpyxl` (reads `.xlsx` lazily with `read_only=True`) |
| CR title database | `sqlite3` (FTS5 virtual table) |
| Approved CR database | `sqlite3` + `pandas` (loaded from 3GPP ZIP → Excel → filtered) |
| HTTP requests | `requests`, `urllib` (dual strategy with SSL bypass for 3GPP) |
| HTML parsing | `beautifulsoup4` |

### Document Processing

| Component | Technology |
|---|---|
| `.docx` reading | `python-docx` |
| `.doc` (OLE2 binary) reading | `olefile` |
| Heading extraction | Direct XML parsing via `lxml`/`ElementTree` (inside `python-docx`) |
| CR metadata extraction | Custom regex parser (field label → value patterns) |

### ML / AI Pipeline

| Component | Technology |
|---|---|
| Sentence Embeddings | `sentence-transformers` — model: `BAAI/bge-base-en-v1.5` (local) |
| Tokenizer | `transformers` `AutoTokenizer` |
| Dimensionality Reduction | `scikit-learn` PCA |
| Clustering | `hdbscan` |
| 2D Projection | `umap-learn` |
| Vector Store (RAG) | `chromadb` (persistent local store) |
| Numerical arrays | `numpy` |
| Visualization | `plotly` (self-contained HTML output) |

### Infrastructure

| Component | Technology |
|---|---|
| Visualization display | `pywebview` (subprocess-based, fallback: `webbrowser`) |
| Setup automation | PowerShell (`_setup.ps1`) + Batch (`Create_Shortcut_Desktop.bat`) |
| App icon | `Pillow` (`make_icon.py`) |

---

## 3. Folder Structure

```
project_root/                          ← Working directory (cache & output created here)
│
├── Create_Shortcut_Desktop.bat           ← Windows shortcut creator (calls _setup.ps1)
├── _setup.ps1                         ← PowerShell: check deps + create Desktop shortcut
├── icon.ico                           ← Application icon
│
├── sources/                          ← Application source code (APP_DIR)
│   ├── app.py                         ← Entry point: App(tk.Tk) + theme engine
│   ├── config.py                      ← All global constants, paths, themes, fonts
│   ├── ui_tabs.py                     ← TabsMixin: UI + handlers for Tabs 1–5
│   ├── ui_tabs_rag.py                 ← ClusterTabsMixin: UI + handlers for Tab 6
│   ├── widgets.py                     ← Custom widgets: SmoothScrollbar, PulseBar, FindBar
│   ├── workplan.py                    ← WorkPlan .xlsx: download, search, export
│   ├── cr_search.py                   ← CR titles SQLite FTS5 search + file download
│   ├── acr_db.py                      ← Approved CR database builder (ZIP → Excel → SQLite)
│   ├── tdoc.py                        ← TDoc download pipeline + CR text extraction
│   ├── cr_extractor.py                ← CR metadata extractor (.docx / .doc)
│   ├── heading_extractor.py           ← Heading extractor from .docx (track-change-aware)
│   ├── ts_info_db.py                  ← TS spec title lookup (in-memory SQLite cache)
│   ├── embed_pipeline.py              ← ML Stage 2–6: extract → chunk → embed → store
│   ├── cluster_pipeline.py            ← ML Stage 7–9: PCA → HDBSCAN → UMAP
│   ├── rag_query.py                   ← RAG semantic search via ChromaDB
│   ├── run_all.py                     ← ML pipeline orchestrator (CLI + GUI callable API)
│   ├── visualize.py                   ← ML Stage 10: UMAP coords → Plotly HTML
│   ├── webview_helper.py              ← Opens visualization.html in pywebview subprocess
│   └── make_icon.py                   ← Generates icon.ico using Pillow
│
├── .cache/                            ← Auto-created: local cache files
│   ├── workplan.xlsx                  ← Cached 3GPP Work Plan (max 30 days)
│   ├── cr_titles.db                   ← SQLite FTS5 database (built by external indexer)
│   ├── ts_info.db                     ← SQLite: TS spec number → title mapping
│   └── 3gpp_cr_approved/
│       ├── <name>.xlsx                ← Cached approved CR Excel (from 3GPP ZIP)
│       └── 3gpp_cr_approved.db        ← SQLite: filtered approved CRs
│
├── data/
│   ├── downloads/
│   │   ├── Zip/<LETTER>/              ← ZIP cache: organized by first letter of filename
│   │   └── Extracted/                 ← Extracted TDoc folders
│   ├── outputs/
│   │   ├── summary/                   ← TDoc consolidated Markdown outputs
│   │   └── clustering/                ← ML pipeline outputs (embeddings, models, HTML)
│   └── cr_docs/                       ← Default input folder for CR .docx/.doc files
│
├── excels/                            ← Excel export directory
│
└── models/
    └── bge-base-en-v1.5/             ← Local BGE embedding model (must be downloaded)
```

---

## 4. Architecture Explanation

### Overall Architecture

The project is split into three logical layers:

```
┌──────────────────────────────────────────────────────────────┐
│                        GUI Layer                             │
│   app.py  ←→  ui_tabs.py  ←→  ui_tabs_rag.py               │
│   widgets.py  (custom Tkinter components)                    │
├──────────────────────────────────────────────────────────────┤
│                   Business Logic Layer                       │
│   workplan.py   cr_search.py   acr_db.py                    │
│   tdoc.py       cr_extractor.py   heading_extractor.py       │
│   ts_info_db.py                                             │
├──────────────────────────────────────────────────────────────┤
│                    ML / AI Pipeline Layer                    │
│   embed_pipeline.py   cluster_pipeline.py   rag_query.py    │
│   run_all.py          visualize.py                          │
└──────────────────────────────────────────────────────────────┘
              ↑ all layers share config.py constants
```

### Component Interaction

```
app.py
  ├── inherits TabsMixin (ui_tabs.py)        → Tabs 1–5 UI & handlers
  ├── inherits ClusterTabsMixin (ui_tabs_rag.py) → Tab 6 UI & handlers
  │
  ├── TabsMixin calls:
  │     workplan.py        → download / search workplan.xlsx
  │     cr_search.py       → FTS5 search on cr_titles.db
  │     acr_db.py          → build approved CR SQLite DB
  │     tdoc.py            → download TDocs from 3GPP portal
  │
  └── ClusterTabsMixin calls:
        run_all.run_pipeline()  → orchestrates full ML pipeline
          ├── embed_pipeline.run()
          │     ├── cr_extractor.extract_cr_metadata()
          │     ├── ts_info_db.TsInfoDb.get_title()
          │     └── saves: embeddings_cache.npy, chroma_store/
          ├── cluster_pipeline.run()
          │     └── saves: cluster_labels.npy, umap_coords.npy
          └── visualize.run()
                └── saves: visualization.html
```

### Data Flow

**Search Flow (Tabs 1–5):**
```
User input (query + filters)
  → Business logic module (workplan / cr_search / acr_db / tdoc)
  → HTTP request to 3GPP portal OR SQLite query on local DB
  → Results dict list
  → ttk.Treeview display + optional Excel export
```

**ML Pipeline Flow (Tab 6):**
```
.docx / .doc files (cr_docs/ folder)
  ↓ cr_extractor.py          → 7-field metadata dict per file
  ↓ ts_info_db.py            → enrich with ts_title (O(1) dict lookup)
  ↓ embed_pipeline.py        → tokenize → chunk (bin-packing, ≤512 tokens)
                             → BGE embed (batch=32) → weighted doc vectors
                             → embeddings_cache.npy + chroma_store/
  ↓ cluster_pipeline.py      → PCA (auto n_components for 85% variance)
                             → HDBSCAN (auto min_size: tries 3→4, picks best)
                             → UMAP (n_neighbors = √N, clamped 5–50)
                             → cluster_labels.npy + umap_coords.npy
  ↓ visualize.py             → Plotly 2D scatter (self-contained HTML)
  ↓ webview_helper.py        → pywebview subprocess window
```

---

## 5. Key Modules Breakdown

### `config.py` — Global Configuration
- **Purpose:** Single source of truth for all constants. The only file imported by all other modules.
- **Key contents:**
  - `THEMES` dict — dark/light color palettes (16 keys each)
  - `FONT_*` tuples — UI font definitions
  - Path constants: `CACHE_DIR`, `DB_FILE`, `ACR_DB_FILE`, `DOWNLOAD_ZIP_DIR`, etc.
  - URL constants: `WORKPLAN_INDEX`, `PORTAL_BASE`, `CR_DB_BASE_URL`
  - Optional dependency flags: `TDOC_FETCH_OK`, `PANDAS_OK`, `RAG_OK` — checked with `importlib.util.find_spec()` at startup without loading heavy packages

---

### `app.py` — Entry Point & Theme Engine
- **Purpose:** Top-level `App` class, UI skeleton, and theme system.
- **Main class:** `App(tk.Tk, TabsMixin, ClusterTabsMixin)` — multiple inheritance
- **Key methods:**
  - `__init__` — initializes all tab state variables, builds UI, applies theme, binds Ctrl+F
  - `_build_ui` — creates header bar + `ttk.Notebook` with 6 tab frames
  - `_apply_theme` — ~270 lines, manually re-styles every widget after theme switch
  - `_toggle_theme` — swaps between dark/light and calls `_apply_theme`
  - `_on_ctrl_f` — delegates find bar activation to the currently visible tab
- **State:** All tab state variables (`_wi_*`, `_cr_*`, `_acr_*`, `_lk_*`, `_cl_*`) are flat instance attributes on `App`

---

### `widgets.py` — Custom Tkinter Widgets
- **Purpose:** Reusable UI components, no business logic dependencies.
- **`SmoothScrollbar(tk.Canvas)`** — replaces `ttk.Scrollbar` with rounded thumb, hover highlight, smooth drag. API-compatible: `.set(first, last)`, `.retheme(bg, fg, hover_fg)`
- **`PulseBar(tk.Canvas)`** — 3px-height animated loading bar with easing. `.start()` / `.stop()` / `.retheme()`
- **`FindBar(tk.Frame)`** — inline Ctrl+F bar for Treeview: real-time filter, match count, ▲▼ navigation, `.notify_data_changed()` for snapshot refresh

---

### `workplan.py` — Work Plan Management
- **Purpose:** All logic for 3GPP `workplan.xlsx` — download, search, lookup, export.
- **Key functions:**
  - `download_workplan(force)` — scrapes 3GPP FTP index, downloads `.xlsx`, caches with 30-day TTL
  - `search_workitems(xlsx_path, query, ...)` — lazy `openpyxl` read, keyword split by `|`, release filter, returns `(list[dict], total_count)`
  - `load_wi_by_id(uid)` — single Work Item lookup by Unique_ID
  - `load_workplan_wi_info(wi_ids: set)` — batch lookup for CR Search enrichment
  - `parallel_check_any/cr/spec(items)` — `ThreadPoolExecutor(max_workers=10)` to check portal links concurrently
  - `export_wi_xlsx(items, path)` — styled Excel export with freeze panes

---

### `cr_search.py` — CR Title Search
- **Purpose:** FTS5 full-text search on `cr_titles.db` + single-file download.
- **Key functions:**
  - `cr_db_status()` — returns `(exists, kb, total_titles, total_workitems, last_crawled)`
  - `cr_search(query, limit, workitem_only)` — builds FTS5 query with prefix matching (`"word"*`), falls back to `LIKE` if FTS5 unavailable; handles schema variants (`wg_tdoc`, `tsg_tdoc`, `download_url`)
  - `download_cr_file(dl_url, extract_dir)` — follows HTML redirect pages, detects file type by magic bytes, routes ZIPs to shared cache at `data/downloads/Zip/<LETTER>/`
  - `export_cr_xlsx(rows, path)` — Excel export with styled headers

---

### `acr_db.py` — Approved CR Database
- **Purpose:** Full pipeline to build `3gpp_cr_approved.db` from the official 3GPP CR database ZIP.
- **Key functions:**
  - `acr_update_db(log_fn)` — public API: scrape ZIP URL → download → extract Excel → filter `TSG-level status == "approved"` → save to SQLite via `pandas.to_sql()`
  - `_acr_find_zip_url(log_fn)` — 3-strategy scraping: BeautifulSoup → regex → raw text pattern
  - `_acr_get_excel(zip_url)` — smart cache: compares ZIP stem with existing Excel filename; skips download if match
- **Smart caching logic:** `(was_downloaded=False AND DB exists)` → skip entirely; `(was_downloaded=False AND DB missing)` → rebuild from cached Excel; `(was_downloaded=True)` → full rebuild

---

### `tdoc.py` — TDoc Download & Processing (1678 lines)
- **Purpose:** Most complex module. Full pipeline from portal scraping to Markdown output.
- **Custom exceptions:** `NoCRFound`, `NoAgreedTDocs`
- **Key functions:**
  - `_detect_ext(content, ct, cd)` — 3-priority file type detection: Content-Disposition → magic bytes → Content-Type
  - `_zip_cache_path(fname)` — canonical ZIP cache layout: `Zip/<FIRST_CHAR>/<fname>.zip`
  - `tdoc_fetch_agreed(uid, session, ...)` — queries portal for TDocs with "agreed" status
  - `tdoc_fetch_from_db(uid, ...)` — fetches TDoc list from local `cr_titles.db`
  - `tdoc_fetch_smart(uid, ...)` — tries portal first, falls back to DB
  - `tdoc_process(uid, extract_dir, out_dir, ...)` — batch-processes all downloaded `.docx`/`.doc` files: extracts CR metadata, TS title lookup, headings; writes tiered Markdown (full/medium/compact based on document count N ≤15 / ≤30 / >30)

---

### `cr_extractor.py` — CR Metadata Extractor
- **Purpose:** Structured field extraction from 3GPP CR Word documents.
- **Extracted fields:** `ts_number`, `work_item`, `title`, `reason_for_change`, `summary_of_change`, `consequences_if_not_approved`, `other_comments`
- **Two reading strategies:**
  - `.docx` via `python-docx` — table-cell parser, stops at "Start of Change", max 8,000 chars
  - `.doc` (OLE2) via `olefile` — decodes `WordDocument` stream as `cp1252`, extracts printable runs, handles split labels (CR-Form v10 quirk)
- **Key functions:** `extract_cr_metadata(filepath, output_txt)`, `batch_extract(folder, ...)`

---

### `heading_extractor.py` — Heading Extractor
- **Purpose:** Extracts headings from the "change content" section of 3GPP CR `.docx` files.
- **Track-change-aware:** respects `<w:del>` (skip) and `<w:ins>` (keep) XML nodes.
- **3 extraction strategies (in priority order):**
  1. **Marker-based** — headings between `"Start/End of change"` markers
  2. **Post-CR-form** — headings after the CR form table (when no markers exist)
  3. **All headings** — full document fallback (when no CR form exists)
- **Style detection:** maps custom numeric style IDs (e.g., `"3"` → Heading 1) and `<w:outlineLvl>` directly

---

### `ts_info_db.py` — TS Spec Title Lookup
- **Purpose:** In-memory cache for TS specification title lookups.
- **Design:** `TsInfoDb` class loads the entire `ts_info` SQLite table into a `dict[str, str]` on init. All subsequent `get_title(spec_number)` calls are O(1) dict lookups — zero I/O during pipeline processing.
- **Graceful degradation:** if DB file is missing or schema wrong, logs a warning and returns `None` for all lookups; pipeline continues unaffected.

---

### `embed_pipeline.py` — Embedding Pipeline (Stage 2–6)
- **Purpose:** Converts CR documents to weighted embeddings stored in `.npy` cache and ChromaDB.
- **Field weighting system:**
  - `HIGH` (α=1.3): `ts_title`
  - `MEDIUM` (α=1.1): `title`, `summary_of_change`
  - `NORMAL` (α=1.0): `reason_for_change`, `consequences_if_not_approved`, `other_comments`
- **Two-tier cache system:**
  - **Tier 1** (`chunk_vectors_cache.npz`, `chunk_meta_cache.json`, `doc_meta_cache.json`) — raw chunk vectors; allows reweighting without re-embedding
  - **Tier 2** (`embeddings_cache.npy`) — final weighted doc vectors; invalidated only when alpha changes
- **Key functions:** `run(root_dir, output_dir, skip_chroma)`, `prepare_chunks(meta, tokenizer)`, `embed_chunks_batched(...)`, `save_rag_store(doc_results, chroma_path)`, `reweight_from_chunk_cache(output_dir)`

---

### `cluster_pipeline.py` — Clustering Pipeline (Stage 7–9)
- **Purpose:** Dimensionality reduction and clustering on doc-level embedding vectors.
- **Pipeline stages:**
  - **Stage 7 (PCA):** `find_pca_components()` auto-selects minimum components for 85% explained variance
  - **Stage 8 (HDBSCAN):** `select_hdbscan_min_size()` tries `min_size=3` then `4`, chooses by a 5-criterion decision tree (max cluster ratio, noise ratio)
  - **Stage 9 (UMAP):** `n_neighbors = clamp(√N, 5, 50)`, fixed `min_dist=0.1`, cosine metric
- **All hyperparameters** support `None` (auto-scale from N) or explicit override via CLI/GUI

---

### `rag_query.py` — RAG Semantic Search
- **Purpose:** Natural language search over embedded CR documents via ChromaDB.
- **`RagSearcher` class:** lazy-loads model and ChromaDB collection once, queries in milliseconds.
- **Key design:** de-duplicates by filename (keeps highest-scoring chunk per file); supports `where` filters by `work_item`, `group`, `ts_number`
- **BGE query prefix:** prepends `"Represent this sentence for searching relevant passages: "` to query (required by `bge-base-en-v1.5`)

---

### `run_all.py` — Pipeline Orchestrator
- **Purpose:** Single entry point for the full ML pipeline; also exposes `run_pipeline()` as a GUI-callable API.
- **Smart embed logic (`_run_embed`):**
  1. `--force-embed` → always re-embed
  2. `--skip-embed` + cache exists → skip entirely (including reweight)
  3. Chunk cache exists + alpha unchanged → skip
  4. Chunk cache exists + alpha changed → `reweight_from_chunk_cache()` (seconds, no model call)
  5. No chunk cache → full embed
- **GUI mode:** when `progress_cb` is provided, detaches all root logger handlers and replaces with `_CBHandler` that forwards log messages to the GUI log panel; also patches `sys.stdout/stderr` to `/dev/null` to silence `tqdm` progress bars

---

### `visualize.py` — Interactive Visualization (Stage 10)
- **Purpose:** Generates a self-contained HTML file with a Plotly 2D scatter plot of clustered CRs.
- **Key behavior:**
  - Downloads `plotly-basic.min.js` once to `assets/` folder; inlines it on each render (no CDN dependency)
  - Each dot represents one CR document, colored by cluster label
  - Tooltips show: filename, TS number, TS title, work item, title snippet
  - Clicking a dot calls `pywebview`'s JS API `window.pywebview.api.open_file(path)` to open the source Word file

---

### `webview_helper.py` — Visualization Window Launcher
- **Purpose:** Opens `visualization.html` in a native window via `pywebview`.
- **Why subprocess:** `pywebview.start()` must run on the main thread of its process. Since Tkinter already owns the main thread, `webview_helper` spawns a fresh Python subprocess, passes the script via stdin (`python -`), and passes the HTML path via environment variable `WEBVIEW_HTML_PATH`.
- **Fallback:** if `pywebview` is not installed (exit code 2) or crashes, falls back to `webbrowser.open()`

---

## 6. Execution Flow

### App Startup

```
python app.py (or pythonw.exe app.py)
  │
  ├── config.py loaded — check optional deps with find_spec() (no heavy imports)
  │
  ├── App.__init__()
  │     ├── Initialize all tab state variables (~15 flat instance attributes)
  │     ├── _build_ui()
  │     │     ├── Build header bar (brand label, theme toggle, update button)
  │     │     ├── Create ttk.Notebook with 6 tab frames
  │     │     ├── Call _build_tab_wi()      ← Tab 1 layout
  │     │     ├── Call _build_tab_cr()      ← Tab 2 layout
  │     │     ├── Call _build_tab_acr()     ← Tab 3 layout
  │     │     ├── Call _build_tab_lookup()  ← Tab 4 layout
  │     │     ├── Call _build_tab_spec()    ← Tab 5 layout
  │     │     └── Call _build_tab_cluster() ← Tab 6 layout
  │     ├── _apply_theme()  ← style all widgets with dark theme defaults
  │     ├── _wi_check_cache_status()  ← check workplan.xlsx age, update header label
  │     ├── _cr_check_db_status()     ← check cr_titles.db, update status label
  │     └── bind_all("<Control-f>")   ← global Ctrl+F delegator
  │
  └── app.mainloop()  ← Tkinter event loop
```

### Search Flow (Tab 1 example)

```
User types query → presses Enter or "Search ⏎" button
  → _wi_do_search() [main thread]
    → start PulseBar animation
    → launch background thread:
        download_workplan() if cache stale
        search_workitems(query, release, limit, ...)
        if check_cr/spec: parallel_check_any/cr/spec() with ThreadPoolExecutor
        → after(0, _wi_show_results)  ← schedule UI update on main thread
    → _wi_show_results() [main thread]
        → populate ttk.Treeview rows
        → stop PulseBar
        → update status label with count
```

### ML Pipeline Flow (Tab 6)

```
User sets Docs Folder + Output Dir → clicks "▶ Run Pipeline"
  → _cl_run() [main thread]
    → set _cl_running = True, disable controls
    → launch background thread:
        run_all.run_pipeline(
          docs_dir, out_dir,
          progress_cb=_cl_log,   ← GUI log callback
          stop_event=_cl_stop_event
        )
          ├── embed_pipeline.run()   ← extract → chunk → embed → cache
          ├── cluster_pipeline.run() ← PCA → HDBSCAN → UMAP
          └── visualize.run()        ← generate visualization.html
      → after(0, _cl_on_done)  ← update UI on main thread
    → _cl_on_done()
        → re-enable controls, refresh Info Panel
        → prompt to open visualization
```

---

## 7. Important Design Decisions

### Lazy Package Checking at Startup
`config.py` uses `importlib.util.find_spec()` to check for optional packages without actually importing them. Heavy packages (`sentence_transformers`, `chromadb`, `pandas`) are only imported inside the functions that need them. This keeps app startup fast and allows the app to run in a reduced-feature mode when ML dependencies are not installed.

### Multiple Inheritance for Mixins
`App` inherits from `tk.Tk`, `TabsMixin`, and `ClusterTabsMixin`. This keeps tab-specific UI code isolated in separate files (`ui_tabs.py`, `ui_tabs_rag.py`) while sharing the same App state and event loop. The tradeoff is that all state is flat on the `App` object and `_apply_theme()` must enumerate every widget manually.

### Threading Model
All network I/O and file processing runs in daemon background threads. UI updates are always scheduled back to the main thread via `self.after(0, callback)`. This prevents GUI freezing while keeping Tkinter's single-thread requirement.

### Two-Tier Embedding Cache
The embedding pipeline separates chunk-level vectors (Tier 1) from document-level weighted vectors (Tier 2). When only the alpha weighting constants change, the system can recompute document vectors from cached chunk vectors in seconds — without calling the BGE model. Alpha values are snapshotted to `alpha_snapshot.json` to detect changes across runs.

### ZIP File Shared Cache
Downloaded TDoc ZIP files are stored in a shared `data/downloads/Zip/<LETTER>/` cache organized by first character. Any subsequent download of the same ZIP file finds it immediately without an HTTP request. Extraction outputs go to `Extracted/` per-TDoc subfolders.

### pywebview via Subprocess
Since `pywebview.start()` must own the main thread and Tkinter already owns it, `webview_helper.py` spawns a fresh Python process and passes the inline script via `stdin`. The HTML path is communicated through an environment variable (not `argv`) because `stdin` is already used for the script. A 1.5-second timeout distinguishes "process still running normally" from "immediate crash."

### HDBSCAN Auto-Selection
Rather than exposing `min_cluster_size` as a raw parameter, `select_hdbscan_min_size()` runs HDBSCAN with `min_size=3` and `min_size=4` and applies a 5-criterion decision tree based on cluster count and noise ratio. This gives reasonable clustering quality across different corpus sizes without manual tuning.

### Tiered Markdown Output for TDoc Processing
When `tdoc_process()` writes the consolidated Markdown for a Work Item, it chooses one of three detail levels based on document count:
- **Full** (N ≤ 15): all 7 fields + headings
- **Medium** (15 < N ≤ 30): all 7 fields, no headings
- **Compact** (N > 30): only TS number, work item, title, summary of change

This keeps the output token-efficient for downstream LLM consumption.

---

## 8. How to Run the Project

### Prerequisites

- **Python 3.9–3.13** (tested on Windows with `pythonw.exe`)
- **Windows** (primary platform; UI and path assumptions are Windows-centric)
- Optional: BGE embedding model downloaded locally to `models/bge-base-en-v1.5/`

### Quick Setup (Windows)

```bat
REM Double-click or run from terminal:
Create_Shortcut_Desktop.bat
```

This calls `_setup.ps1` which:
1. Locates `pythonw.exe`
2. Checks and installs all dependencies via `pip`
3. Creates a Desktop shortcut pointing to `app.py`

### Manual Setup

```bash
# Install core GUI dependencies
pip install openpyxl requests beautifulsoup4 python-docx olefile

# Install ML/AI dependencies (optional, needed for Tab 6)
pip install numpy scikit-learn sentence-transformers transformers umap-learn hdbscan chromadb

# Install visualization display (optional)
pip install pywebview

# Install pandas (needed for Approved CR database)
pip install pandas
```

### Run the Application

```bash
# With console (shows errors/warnings)
python 3gpp_app/app.py

# Without console window (Windows, clean launch)
pythonw 3gpp_app/app.py
```

### Run the ML Pipeline (CLI)

```bash
# Full pipeline: embed → cluster → visualize
python 3gpp_app/run_all.py --root ./data/cr_docs --out ./data/outputs/clustering

# Skip re-embedding if cache exists, re-cluster only
python 3gpp_app/run_all.py --skip-embed --pca 30 --hdb-min-size 5

# Only regenerate visualization
python 3gpp_app/run_all.py --only-viz --out ./data/outputs/clustering
```

### Run RAG Search (CLI)

```bash
python 3gpp_app/rag_query.py "IMS data channel enhancements" --top 10
python 3gpp_app/rag_query.py "NTN handover LEO" --group HIGH --work-item NR_NTN
```

### Required External Data (not included in repo)

| File | Source | Location |
|---|---|---|
| `workplan.xlsx` | Auto-downloaded from 3GPP FTP | `.cache/workplan.xlsx` |
| `cr_titles.db` | Built by external `cr_indexer.py` tool | `.cache/cr_titles.db` |
| `ts_info.db` | External TS metadata tool | `.cache/ts_info.db` |
| `bge-base-en-v1.5/` | Download from Hugging Face | `models/bge-base-en-v1.5/` |

### Notes

- The `3gpp_cr_approved.db` is built automatically when clicking "↻ Update" in Tab 3
- The `workplan.xlsx` is downloaded automatically on first search in Tab 1
- The ML pipeline (Tab 6) requires `.docx`/`.doc` CR files placed in the configured Docs Folder
- All HTTP requests bypass SSL verification (`verify=False`) because 3GPP servers use self-signed certificates
