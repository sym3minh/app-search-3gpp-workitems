"""
ui_tabs_rag.py — Tab 6: CR Clustering pipeline control.

class ClusterTabsMixin — được App kế thừa qua multiple inheritance.

Tab layout:
  ┌──────────────────────────────────────────────────────────────┐
  │ Bar row 0: Docs Folder [entry………………………………………………] [Browse]    │
  │ Bar row 1: Output Dir  [entry………………………………………………] [Browse]    │
  │ Bar row 2: [Skip Embed][Force][Skip Chroma][Cluster Only]    │
  │            PCA:[__] HDB:[__]  [▶ Run Pipeline][■ Stop] ▓▓   │
  ├──────────────────────────────────────────────────────────────┤
  │ Status: ● Sẵn sàng.                     [▾ Log] [↻ Refresh] │
  ├──────────────────────────┬───────────────────────────────────┤
  │ Info Panel (scrollable)  │ Log panel (Text)                  │
  │  [🌐 Open Visualization] │                                   │
  │  📦 Cache Status         │                                   │
  │  🔬 Cluster Summary      │                                   │
  │  ⚙ Params Used           │                                   │
  │  📋 Clusters table       │                                   │
  └──────────────────────────┴───────────────────────────────────┘

Requires App state (initialised in App.__init__):
    self._cl_running    = False
    self._cl_stop_event = threading.Event()

Imports: config, widgets
"""

from __future__ import annotations

import datetime
import json
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import config
from config import FONT_MONO, FONT_UI, FONT_BOLD, FONT_SMALL, OUTPUT_DIR, DATA_DIR, CLUSTERING_OUT_DIR
from widgets import SmoothScrollbar, PulseBar
from webview_helper import open_in_pywebview


class ClusterTabsMixin:

    # ══════════════════════════════════════════════════════════════════════════
    # Build UI
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_cluster(self):
        p = self._tab_cl
        p.columnconfigure(0, weight=1)
        p.rowconfigure(2, weight=1)   # row 2 = content area expands

        # ── Row 0 of parent: Top bar ──────────────────────────────────────────
        self._cl_bar = tk.Frame(p, padx=18, pady=6)
        self._cl_bar.grid(row=0, column=0, sticky="ew")
        self._cl_bar.columnconfigure(1, weight=1)

        # Docs Folder
        self._cl_lbl_docs = tk.Label(
            self._cl_bar, text="Docs Folder", font=FONT_BOLD,
            width=12, anchor="e")
        self._cl_lbl_docs.grid(row=0, column=0, padx=(0, 8), pady=(0, 5))

        self._cl_docs_var = tk.StringVar(value=str(DATA_DIR / "cr_docs"))
        self._cl_docs_entry = tk.Entry(
            self._cl_bar, textvariable=self._cl_docs_var,
            font=FONT_UI, relief="flat", bd=0, highlightthickness=1)
        self._cl_docs_entry.grid(row=0, column=1, sticky="ew",
                                  ipady=5, padx=(0, 8), pady=(0, 5))

        self._cl_docs_browse = tk.Button(
            self._cl_bar, text="Browse…", font=FONT_SMALL,
            relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
            command=self._cl_browse_docs)
        self._cl_docs_browse.grid(row=0, column=2, pady=(0, 5))

        # Output Dir
        self._cl_lbl_out = tk.Label(
            self._cl_bar, text="Output Dir", font=FONT_BOLD,
            width=12, anchor="e")
        self._cl_lbl_out.grid(row=1, column=0, padx=(0, 8), pady=(0, 5))

        self._cl_out_var = tk.StringVar(value=str(CLUSTERING_OUT_DIR))
        self._cl_out_entry = tk.Entry(
            self._cl_bar, textvariable=self._cl_out_var,
            font=FONT_UI, relief="flat", bd=0, highlightthickness=1)
        self._cl_out_entry.grid(row=1, column=1, sticky="ew",
                                 ipady=5, padx=(0, 8), pady=(0, 5))

        self._cl_out_browse = tk.Button(
            self._cl_bar, text="Browse…", font=FONT_SMALL,
            relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
            command=self._cl_browse_out)
        self._cl_out_browse.grid(row=1, column=2, pady=(0, 5))

        # Options row
        self._cl_opts = tk.Frame(self._cl_bar)
        self._cl_opts.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 0))

        self._cl_skip_embed_var   = tk.BooleanVar(value=False)
        self._cl_force_embed_var  = tk.BooleanVar(value=False)
        self._cl_skip_chroma_var  = tk.BooleanVar(value=True)
        self._cl_only_cluster_var = tk.BooleanVar(value=False)

        for var, text in [
            (self._cl_skip_embed_var,   "Skip Embed"),
            (self._cl_force_embed_var,  "Force Re-embed"),
            (self._cl_skip_chroma_var,  "Skip Chroma"),
            (self._cl_only_cluster_var, "Cluster Only"),
        ]:
            cb = tk.Checkbutton(self._cl_opts, text=text, variable=var,
                                font=FONT_SMALL, highlightthickness=0)
            cb.pack(side="left", padx=(0, 8))

        self._cl_lbl_pca = tk.Label(self._cl_opts, text="PCA:", font=FONT_SMALL)
        self._cl_lbl_pca.pack(side="left", padx=(8, 4))
        self._cl_pca_var = tk.StringVar(value="")
        self._cl_pca_entry = tk.Entry(
            self._cl_opts, textvariable=self._cl_pca_var,
            font=FONT_MONO, width=5, relief="flat", bd=0, highlightthickness=1)
        self._cl_pca_entry.pack(side="left", padx=(0, 12), ipady=3)

        self._cl_lbl_hdb = tk.Label(self._cl_opts, text="HDB min:", font=FONT_SMALL)
        self._cl_lbl_hdb.pack(side="left", padx=(0, 4))
        self._cl_hdb_var = tk.StringVar(value="")
        self._cl_hdb_entry = tk.Entry(
            self._cl_opts, textvariable=self._cl_hdb_var,
            font=FONT_MONO, width=5, relief="flat", bd=0, highlightthickness=1)
        self._cl_hdb_entry.pack(side="left", padx=(0, 18), ipady=3)

        # Run / Stop / PulseBar  (right-aligned)
        self._cl_pulse = PulseBar(self._cl_opts, width=100)
        self._cl_pulse.pack(side="right", padx=(6, 0))

        self._cl_stop_btn = tk.Button(
            self._cl_opts, text="■ Stop", font=FONT_SMALL,
            relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
            command=self._cl_do_stop, state="disabled")
        self._cl_stop_btn.pack(side="right", padx=(4, 0))

        self._cl_run_btn = tk.Button(
            self._cl_opts, text="▶ Run Pipeline", font=FONT_BOLD,
            relief="flat", bd=0, padx=16, pady=4, cursor="hand2",
            command=self._cl_do_run)
        self._cl_run_btn.pack(side="right", padx=(8, 4))

        # ── Row 1 of parent: Status bar ───────────────────────────────────────
        self._cl_sbar = tk.Frame(p, padx=14)
        self._cl_sbar.grid(row=1, column=0, sticky="ew", pady=(0, 2))
        self._cl_sbar.columnconfigure(1, weight=1)

        self._cl_status_icon = tk.Label(self._cl_sbar, text="●", font=FONT_SMALL)
        self._cl_status_icon.grid(row=0, column=0, padx=(0, 6), pady=(2, 4))

        self._cl_status_var = tk.StringVar(value="Sẵn sàng.")
        self._cl_status_lbl = tk.Label(
            self._cl_sbar, textvariable=self._cl_status_var,
            font=FONT_SMALL, anchor="w")
        self._cl_status_lbl.grid(row=0, column=1, sticky="w")

        self._cl_log_toggle_var = tk.BooleanVar(value=True)
        self._cl_log_btn = tk.Checkbutton(
            self._cl_sbar, text="▾ Log",
            variable=self._cl_log_toggle_var,
            command=self._cl_toggle_log,
            font=FONT_SMALL, indicatoron=False,
            relief="flat", highlightthickness=0)
        self._cl_log_btn.grid(row=0, column=2, padx=(8, 0))

        self._cl_refresh_btn = tk.Button(
            self._cl_sbar, text="↻ Refresh", font=FONT_SMALL,
            relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
            command=self._cl_refresh_status)
        self._cl_refresh_btn.grid(row=0, column=3, padx=(6, 0))

        # ── Row 2 of parent: Content (PanedWindow) ────────────────────────────
        self._cl_content = tk.Frame(p)
        self._cl_content.grid(row=2, column=0, sticky="nsew")
        self._cl_content.columnconfigure(0, weight=1)
        self._cl_content.rowconfigure(0, weight=1)

        self._cl_paned = ttk.PanedWindow(self._cl_content, orient=tk.HORIZONTAL)
        self._cl_paned.grid(row=0, column=0, sticky="nsew")

        # Left pane — scrollable info panel
        self._cl_info_outer = tk.Frame(self._cl_paned)
        self._cl_info_outer.columnconfigure(0, weight=1)
        self._cl_info_outer.rowconfigure(0, weight=1)
        self._cl_paned.add(self._cl_info_outer, weight=0)

        self._cl_info_canvas = tk.Canvas(
            self._cl_info_outer, highlightthickness=0, bd=0, width=360)
        self._cl_info_vsb = SmoothScrollbar(
            self._cl_info_outer, orient="vertical",
            command=self._cl_info_canvas.yview)
        self._cl_info_canvas.configure(yscrollcommand=self._cl_info_vsb.set)
        self._cl_info_canvas.grid(row=0, column=0, sticky="nsew")
        self._cl_info_vsb.grid(row=0, column=1, sticky="ns", padx=(2, 2))

        self._cl_info_frame = tk.Frame(self._cl_info_canvas)
        self._cl_info_win = self._cl_info_canvas.create_window(
            (0, 0), window=self._cl_info_frame, anchor="nw")

        self._cl_info_frame.bind(
            "<Configure>",
            lambda e: self._cl_info_canvas.configure(
                scrollregion=self._cl_info_canvas.bbox("all")))
        self._cl_info_canvas.bind(
            "<Configure>",
            lambda e: self._cl_info_canvas.itemconfig(
                self._cl_info_win, width=e.width))

        # Mouse-wheel: activate when cursor enters the left pane
        self._cl_info_canvas.bind(
            "<Enter>",
            lambda e: self._cl_info_canvas.bind_all(
                "<MouseWheel>", self._cl_on_info_scroll))
        self._cl_info_canvas.bind(
            "<Leave>",
            lambda e: self._cl_info_canvas.unbind_all("<MouseWheel>"))

        # Right pane — log text
        self._cl_log_outer = tk.Frame(self._cl_paned)
        self._cl_log_inner = tk.Frame(self._cl_log_outer)
        self._cl_log_inner.pack(fill="both", expand=True)
        self._cl_paned.add(self._cl_log_outer, weight=1)

        self._cl_log_text = tk.Text(
            self._cl_log_inner, font=FONT_MONO,
            relief="flat", bd=0, wrap="word", state="disabled")
        self._cl_log_vsb = SmoothScrollbar(
            self._cl_log_inner, orient="vertical",
            command=self._cl_log_text.yview)
        self._cl_log_text.configure(yscrollcommand=self._cl_log_vsb.set)
        self._cl_log_text.pack(side="left", fill="both", expand=True,
                                padx=(10, 0), pady=4)
        self._cl_log_vsb.pack(side="right", fill="y")

        # Traces
        self._cl_docs_var.trace_add(
            "write", lambda *_: self.after(0, self._cl_sync_out_from_docs))
        self._cl_out_var.trace_add(
            "write", lambda *_: self.after(400, self._cl_refresh_status))

        # Initial render
        self._cl_refresh_status()

    # ══════════════════════════════════════════════════════════════════════════
    # Browse & path helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _cl_browse_docs(self):
        d = filedialog.askdirectory(
            title="Chọn thư mục chứa CR .docx / .doc files")
        if d:
            self._cl_docs_var.set(d)
            self._cl_sync_out_from_docs()

    def _cl_browse_out(self):
        d = filedialog.askdirectory(
            title="Chọn thư mục lưu output (embeddings, clusters...)")
        if d:
            self._cl_out_var.set(d)

    def _cl_sync_out_from_docs(self):
        """
        Tự động set Output Dir = CLUSTERING_OUT_DIR / <2 phần cuối của docs path>.

        Ví dụ:
            docs  = C:/any/path/data_channel/202
            out   = <app_root>/data/outputs/clustering/data_channel/202

        CLUSTERING_OUT_DIR đã là absolute path tính từ vị trí app, không hardcode.
        """
        docs_str = self._cl_docs_var.get().strip()
        if not docs_str:
            return
        try:
            parts = Path(docs_str).parts
            tail  = Path(*parts[-2:]) if len(parts) >= 2 else Path(parts[-1])
            self._cl_out_var.set(str(config.CLUSTERING_OUT_DIR / tail))
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # Scroll helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _cl_on_info_scroll(self, event):
        self._cl_info_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _cl_bind_wheel_to_children(self, widget):
        """Bind MouseWheel lên toàn bộ cây con để scroll hoạt động mọi nơi."""
        widget.bind("<MouseWheel>", self._cl_on_info_scroll)
        for child in widget.winfo_children():
            self._cl_bind_wheel_to_children(child)

    # ══════════════════════════════════════════════════════════════════════════
    # Log helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _cl_log(self, msg: str, color_key: str = None):
        """Thread-safe append vào log panel. color_key: None|warn|error|success."""
        T = self._T
        _map = {
            "warn":    T.get("WARN",    "#F7A74F"),
            "error":   T.get("ERROR",   "#F75F5F"),
            "success": T.get("SUCCESS", "#2DD4A5"),
        }
        color = _map.get(color_key) if color_key else T.get("FG2", "#9BA3C9")
        tag   = color_key or "default"

        def _do():
            self._cl_log_text.configure(state="normal")
            self._cl_log_text.tag_configure(tag, foreground=color)
            self._cl_log_text.insert("end", msg + "\n", tag)
            self._cl_log_text.configure(state="disabled")
            self._cl_log_text.see("end")

        self.after(0, _do)

    def _cl_toggle_log(self):
        if self._cl_log_toggle_var.get():
            try:
                self._cl_paned.add(self._cl_log_outer, weight=1)
            except Exception:
                pass
        else:
            try:
                self._cl_paned.forget(self._cl_log_outer)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════════════════
    # Status bar
    # ══════════════════════════════════════════════════════════════════════════

    def _cl_set_status(self, msg: str, color: str = None, icon_color: str = None):
        def _do():
            self._cl_status_var.set(msg)
            if color:      self._cl_status_lbl.config(fg=color)
            if icon_color: self._cl_status_icon.config(fg=icon_color)
        self.after(0, _do)

    # ══════════════════════════════════════════════════════════════════════════
    # Info panel
    # ══════════════════════════════════════════════════════════════════════════

    def _cl_refresh_status(self):
        """Rebuild info panel trái từ output dir hiện tại."""
        out_dir = Path(self._cl_out_var.get())

        for w in self._cl_info_frame.winfo_children():
            w.destroy()

        T       = self._T
        BG      = T["BG"];  BG2 = T["BG2"]; BG3 = T["BG3"]
        FG      = T["FG"];  FG2 = T["FG2"]
        ACCENT  = T["ACCENT"]
        SUCCESS = T["SUCCESS"]
        WARN    = T["WARN"]
        ERROR   = T["ERROR"]
        f       = self._cl_info_frame

        def section(text):
            tk.Label(f, text=text, font=FONT_BOLD,
                     bg=BG, fg=ACCENT, anchor="w").pack(
                fill="x", padx=14, pady=(10, 2))

        def row(label, value, fg=None):
            r = tk.Frame(f, bg=BG)
            r.pack(fill="x", padx=14, pady=1)
            tk.Label(r, text=label + ":", font=FONT_SMALL,
                     bg=BG, fg=FG2, width=18, anchor="e").pack(side="left")
            tk.Label(r, text=str(value), font=FONT_SMALL,
                     bg=BG, fg=fg or FG, anchor="w").pack(side="left", padx=(8, 0))

        def divider():
            tk.Frame(f, height=1, bg=T["BORDER"]).pack(
                fill="x", padx=14, pady=(6, 0))

        # ── Open Visualization (top) ──────────────────────────────────────────
        viz_path   = out_dir / "visualization.html"
        viz_exists = viz_path.exists()

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(fill="x", padx=14, pady=(12, 4))
        tk.Button(
            btn_row,
            text="🌐 Open Visualization",
            font=FONT_BOLD, relief="flat", bd=0,
            padx=16, pady=6,
            cursor="hand2" if viz_exists else "",
            state="normal" if viz_exists else "disabled",
            bg=ACCENT if viz_exists else BG3,
            fg="white" if viz_exists else FG2,
            activebackground=ACCENT, activeforeground="white",
            command=lambda p=viz_path: open_in_pywebview(p),
        ).pack(side="left")
        if not viz_exists:
            tk.Label(btn_row, text="  (chạy pipeline trước)",
                     font=FONT_SMALL, bg=BG, fg=FG2).pack(side="left")

        divider()

        # ── Cache Status ──────────────────────────────────────────────────────
        section("📦 Cache Status")

        emb_path  = out_dir / "embeddings_cache.npy"
        meta_path = out_dir / "embeddings_metadata.json"

        if emb_path.exists() and meta_path.exists():
            try:
                meta  = json.loads(meta_path.read_text(encoding="utf-8"))
                mtime = datetime.datetime.fromtimestamp(emb_path.stat().st_mtime)
                row("Docs embedded", f"{len(meta):,}", SUCCESS)
                row("Last run",      mtime.strftime("%Y-%m-%d  %H:%M"), FG2)
                alpha_path = out_dir / "alpha_snapshot.json"
                if alpha_path.exists():
                    try:
                        alpha     = json.loads(alpha_path.read_text(encoding="utf-8"))
                        alpha_str = "  ".join(f"{k}={v}" for k, v in alpha.items())
                        row("Alpha", alpha_str[:45] or "N/A", FG2)
                    except Exception:
                        pass
            except Exception as e:
                row("embeddings_cache", f"Error: {e}", ERROR)
        else:
            row("embeddings_cache", "Not found — chưa chạy pipeline", WARN)

        divider()

        # ── Cluster Summary ───────────────────────────────────────────────────
        section("🔬 Cluster Summary")

        summary_path = out_dir / "cluster_summary.json"
        if summary_path.exists():
            try:
                s       = json.loads(summary_path.read_text(encoding="utf-8"))
                n_noise = s.get("n_noise", 0)
                n_total = s.get("n_documents", 1) or 1

                row("Total docs", f"{s.get('n_documents', 'N/A'):,}")
                row("Clusters",   str(s.get("n_clusters", "N/A")), SUCCESS)
                row("Noise",
                    f"{n_noise:,}  ({n_noise/n_total:.1%})",
                    WARN if n_noise / n_total > 0.25 else FG)

                ev = s.get("explained_variance_pct")
                if ev is not None:
                    row("PCA variance", f"{ev:.1f}%",
                        WARN if ev < 80 else SUCCESS)

                params = s.get("params_used", {})
                if params:
                    divider()
                    section("⚙ Params Used")
                    row("PCA components",  str(params.get("pca_components",  "auto")))
                    row("HDB min_size",    str(params.get("hdbscan_min_size", "auto")))
                    row("HDB min_samples", str(params.get("hdbscan_min_samp", "auto")))
                    row("UMAP neighbors",  str(params.get("umap_n_neighbors", "auto")))
                    row("UMAP min_dist",   str(params.get("umap_min_dist",    "N/A")))

                clusters = s.get("clusters", [])
                if clusters:
                    divider()
                    section("📋 Clusters")
                    self._cl_build_cluster_table(clusters)

            except Exception as e:
                row("cluster_summary", f"Error reading: {e}", ERROR)
        else:
            row("cluster_summary", "Not found — chưa chạy pipeline", WARN)

        self._cl_info_canvas.configure(bg=BG)
        self._cl_info_frame.configure(bg=BG)

        # Bind wheel to all children so scrolling works when hovering over text
        self._cl_bind_wheel_to_children(self._cl_info_frame)

    def _cl_build_cluster_table(self, clusters: list):
        T  = self._T
        BG = T["BG"]

        frm = tk.Frame(self._cl_info_frame, bg=BG)
        frm.pack(fill="x", padx=14, pady=(4, 0))
        frm.columnconfigure(0, weight=1)

        cols  = ("cluster_id", "size", "top_wi")
        n_vis = min(14, len(clusters))
        tree  = ttk.Treeview(frm, columns=cols,
                             show="headings", height=n_vis, selectmode="none")

        tree.heading("cluster_id", text="Cluster")
        tree.heading("size",       text="Size")
        tree.heading("top_wi",     text="Top Work Item")
        tree.column("cluster_id", width=62,  anchor="center", stretch=False)
        tree.column("size",       width=52,  anchor="center", stretch=False)
        tree.column("top_wi",     width=180, anchor="w",      stretch=True)

        for c in sorted(clusters, key=lambda x: (x["is_noise"], -x["size"])):
            label = "Noise" if c["is_noise"] else str(c["cluster_id"])
            tag   = "noise" if c["is_noise"] else (
                "odd" if int(c["cluster_id"]) % 2 else "even")
            tree.insert("", "end",
                        values=(label, c["size"], c.get("top_work_item", "")),
                        tags=(tag,))

        tree.tag_configure("noise", foreground=T.get("WARN",  "#F7A74F"))
        tree.tag_configure("odd",   background=T["BG2"])
        tree.tag_configure("even",  background=T["BG"])
        tree.grid(row=0, column=0, sticky="ew")

    # ══════════════════════════════════════════════════════════════════════════
    # Pipeline run / stop
    # ══════════════════════════════════════════════════════════════════════════

    def _cl_do_run(self):
        if self._cl_running:
            return

        docs_dir = self._cl_docs_var.get().strip()
        out_dir  = self._cl_out_var.get().strip()

        if not docs_dir:
            messagebox.showwarning("Thiếu thông tin", "Chọn Docs Folder trước.")
            return
        if not out_dir:
            messagebox.showwarning("Thiếu thông tin", "Chọn Output Dir trước.")
            return

        skip_embed   = self._cl_skip_embed_var.get()
        force_embed  = self._cl_force_embed_var.get()
        skip_chroma  = self._cl_skip_chroma_var.get()
        only_cluster = self._cl_only_cluster_var.get()

        if skip_embed and force_embed:
            messagebox.showwarning(
                "Xung đột lựa chọn",
                "'Skip Embed' và 'Force Re-embed' không thể bật cùng lúc.")
            return

        def _int_or_none(svar):
            v = svar.get().strip()
            try:
                return int(v) if v else None
            except ValueError:
                return None

        pca     = _int_or_none(self._cl_pca_var)
        hdb_min = _int_or_none(self._cl_hdb_var)

        # UI: start state
        self._cl_running = True
        self._cl_stop_event.clear()
        self._cl_run_btn.config(state="disabled", text="⏳ Running…")
        self._cl_stop_btn.config(state="normal")
        self._cl_pulse.start()
        T = self._T
        self._cl_set_status("Pipeline đang chạy…", T["WARN"], T["WARN"])

        # Auto-show log
        if not self._cl_log_toggle_var.get():
            self._cl_log_toggle_var.set(True)
            self._cl_toggle_log()

        self._cl_log("═" * 60)
        self._cl_log("▶ Run Pipeline")
        self._cl_log(f"   docs  = {docs_dir}")
        self._cl_log(f"   out   = {out_dir}")
        if pca:     self._cl_log(f"   PCA   = {pca}")
        if hdb_min: self._cl_log(f"   HDB   = {hdb_min}")
        flags = [k for k, v in [
            ("skip_embed",   skip_embed),
            ("force_embed",  force_embed),
            ("skip_chroma",  skip_chroma),
            ("only_cluster", only_cluster),
        ] if v]
        if flags:
            self._cl_log(f"   flags = {', '.join(flags)}")
        self._cl_log("─" * 60)

        def worker():
            from run_all import run_pipeline
            T2 = self._T
            try:
                run_pipeline(
                    docs_dir     = docs_dir,
                    out_dir      = out_dir,
                    force_embed  = force_embed,
                    skip_embed   = skip_embed,
                    only_cluster = only_cluster,
                    skip_chroma  = skip_chroma,
                    pca          = pca,
                    hdb_min_size = hdb_min,
                    progress_cb  = self._cl_log,
                    stop_event   = self._cl_stop_event,
                )
                self._cl_log("─" * 60)
                self._cl_log("✓ Pipeline hoàn thành.", "success")
                self._cl_set_status("Pipeline hoàn thành.", T2["SUCCESS"], T2["SUCCESS"])
                self.after(0, self._cl_refresh_status)

            except InterruptedError:
                self._cl_log("─" * 60)
                self._cl_log("■ Pipeline bị dừng.", "warn")
                self._cl_set_status("Đã dừng.", T2["WARN"], T2["WARN"])

            except Exception as e:
                self._cl_log("─" * 60)
                self._cl_log(f"✗ Lỗi: {e}", "error")
                self._cl_set_status(f"Lỗi: {e}", T2["ERROR"], T2["ERROR"])

            finally:
                self._cl_running = False
                self.after(0, lambda: (
                    self._cl_run_btn.config(state="normal", text="▶ Run Pipeline"),
                    self._cl_stop_btn.config(state="disabled"),
                    self._cl_pulse.stop(),
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _cl_do_stop(self):
        self._cl_stop_event.set()
        self._cl_stop_btn.config(state="disabled", text="■ Stopping…")

    # ══════════════════════════════════════════════════════════════════════════
    # Theme
    # ══════════════════════════════════════════════════════════════════════════

    def _cl_apply_theme(self):
        """Gọi từ App._apply_theme() sau khi self._T đã cập nhật."""
        T  = self._T
        BG = T["BG"];  BG2 = T["BG2"]; BG3 = T["BG3"]
        FG = T["FG"];  FG2 = T["FG2"]
        ACCENT  = T["ACCENT"]
        ERROR   = T["ERROR"]
        BORDER  = T["BORDER"]
        SBG = T["SCROLLBG"]; SFG = T["SCROLLFG"]; SHO = T["SCROLLHO"]

        # Frames
        for w, bg in [
            (self._tab_cl,        BG),
            (self._cl_content,    BG),
            (self._cl_info_outer, BG),
            (self._cl_bar,        BG2),
            (self._cl_opts,       BG2),
            (self._cl_sbar,       BG2),
            (self._cl_log_outer,  BG2),
            (self._cl_log_inner,  BG2),
        ]:
            try:
                w.configure(bg=bg)
            except Exception:
                pass

        # Labels in bar (BG2 background)
        for lbl in [self._cl_lbl_docs, self._cl_lbl_out,
                    self._cl_lbl_pca,  self._cl_lbl_hdb]:
            lbl.configure(bg=BG2, fg=FG2)

        # Status bar labels (BG2 background)
        self._cl_status_icon.configure(bg=BG2, fg=FG2)
        self._cl_status_lbl.configure( bg=BG2, fg=FG2)

        # Entries
        for e in [self._cl_docs_entry, self._cl_out_entry,
                  self._cl_pca_entry,  self._cl_hdb_entry]:
            e.configure(bg=BG3, fg=FG,
                        insertbackground=ACCENT,
                        highlightcolor=ACCENT,
                        highlightbackground=BORDER)

        # Browse / Refresh buttons
        for btn in [self._cl_docs_browse, self._cl_out_browse,
                    self._cl_refresh_btn]:
            btn.configure(bg=BG3, fg=FG2,
                          activebackground=ACCENT, activeforeground="white")

        # Run / Stop
        self._cl_run_btn.configure(
            bg=ACCENT, fg="white", activebackground=ACCENT)
        self._cl_stop_btn.configure(
            bg=ERROR, fg="white", activebackground=ERROR,
            disabledforeground=FG2)

        # Checkbuttons (options row)
        for cb in self._cl_opts.winfo_children():
            if isinstance(cb, tk.Checkbutton):
                cb.configure(bg=BG2, fg=FG2,
                             activebackground=BG2, activeforeground=FG,
                             selectcolor=BG3)

        # Log toggle checkbutton
        self._cl_log_btn.configure(
            bg=BG2, fg=FG2,
            activebackground=BG2, activeforeground=FG,
            selectcolor=BG2)

        # Log text
        self._cl_log_text.configure(bg=BG2, fg=FG2, insertbackground=FG)

        # PulseBar & Scrollbars
        self._cl_pulse.retheme(BG2, ACCENT)
        self._cl_info_vsb.retheme(SBG, SFG, SHO)
        self._cl_log_vsb.retheme(SBG, SFG, SHO)

        # Rebuild info panel with new colours
        self._cl_refresh_status()