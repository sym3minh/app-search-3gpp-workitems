"""
ui_tabs.py — UI + event handlers cho 5 tabs.

Import: config, widgets, workplan, cr_search, acr_db, tdoc
class TabsMixin — được App kế thừa qua multiple inheritance.
Chứa toàn bộ code UI và event handling của 5 tabs.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading, sqlite3, datetime, re, webbrowser, time
from pathlib import Path

import config
from config import (
    THEMES, FONT_MONO, FONT_UI, FONT_BOLD, FONT_H1, FONT_SMALL,
    TDOC_FETCH_OK, PANDAS_OK,
    CACHE_FILE, DB_FILE, ACR_DB_FILE,
    PORTAL_BASE, HDRS,
    OUTPUT_DIR, EXCELS_DIR, DOWNLOAD_EXTRACTED_DIR, DATA_DIR,
)
from widgets import SmoothScrollbar, PulseBar
from workplan import (
    download_workplan, search_workitems,
    load_wi_by_id, load_workplan_wi_info, _load_wi_full,
    parallel_check_any, parallel_check_cr, parallel_check_spec,
    export_wi_xlsx, build_wi_filename, open_file, _release_sort_key,
)
from cr_search import (
    cr_db_status, cr_search, download_cr_file,
    export_cr_xlsx, build_cr_filename,
)
from acr_db import acr_update_db
from tdoc import (
    NoCRFound, NoAgreedTDocs,
    tdoc_fetch_agreed, tdoc_fetch_from_db, tdoc_fetch_smart, tdoc_process,
    _find_zip_in_cache, _extract_zip_to, _tdoc_download_one,
)


class TabsMixin:
    """
    Mixin chứa toàn bộ UI và event handlers của 5 tabs.
    Được App kế thừa qua multiple inheritance.

    Cấu trúc:
        Shared helpers
        Tab 1 — Work Item Search
        Tab 2 — CR Titles Search
        Tab 3 — Acronym Search
        Tab 4 — WI Detail / Lookup
        Tab 5 — Spec Search
    """

    # ══════════════════════════════════════════════════════════════════════════
    # Shared helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _make_find_bar(self, parent, tree, get_rows_fn, repopulate_fn):
        """
        Tạo inline Ctrl+F find bar.
        Đặt trong parent dùng grid (row=2, columnspan=2).
        Hidden by default, hiện khi Ctrl+F.
        """
        frame = tk.Frame(parent, padx=8, pady=4)
        frame.columnconfigure(1, weight=1)
        frame._visible = False
        frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        frame.grid_remove()

        lbl = tk.Label(frame, text="🔍 Find:", font=FONT_UI)
        lbl.grid(row=0, column=0, padx=(0, 6))

        var   = tk.StringVar()
        entry = tk.Entry(frame, textvariable=var, font=FONT_UI,
                         relief="flat", bd=0, highlightthickness=1)
        entry.grid(row=0, column=1, sticky="ew", ipady=4, padx=(0, 6))

        count_lbl = tk.Label(frame, text="", font=FONT_SMALL, width=12, anchor="w")
        count_lbl.grid(row=0, column=2, padx=(0, 4))

        close_btn = tk.Button(frame, text="✕", font=FONT_SMALL,
                              relief="flat", bd=0, padx=6, pady=2, cursor="hand2")
        close_btn.grid(row=0, column=3)

        def do_filter(*_):
            q    = var.get().lower()
            rows = get_rows_fn()
            for iid in tree.get_children():
                tree.delete(iid)
            matched = 0
            for i, row_data in enumerate(rows):
                vals = [str(v).lower() for v in row_data["_values"]]
                if not q or any(q in v for v in vals):
                    iid = tree.insert("", "end", values=row_data["_values"],
                                      tags=("odd" if matched % 2 else "even",))
                    repopulate_fn(iid, row_data)
                    matched += 1
            total = len(rows)
            count_lbl.config(text=f"{matched}/{total}" if q else "")

        def show():
            if not frame._visible:
                frame.grid()
                frame._visible = True
            entry.focus_set()
            entry.select_range(0, "end")

        def hide():
            var.set("")
            do_filter()
            frame.grid_remove()
            frame._visible = False
            tree.focus_set()

        var.trace_add("write", do_filter)
        entry.bind("<Escape>", lambda e: hide())
        close_btn.config(command=hide)

        frame._show       = show
        frame._hide       = hide
        frame._do_filter  = do_filter
        frame._var        = var
        frame._count_lbl  = count_lbl
        frame._lbl        = lbl
        frame._entry      = entry
        frame._close_btn  = close_btn
        return frame

    def _add_copy_menu(self, tree, col_names):
        """Right-click context menu + Ctrl+C để copy cell/row từ treeview."""
        menu = tk.Menu(self, tearoff=0)

        def copy_cell():
            iid = tree.focus()
            if not iid:
                return
            col  = getattr(tree, "_last_click_col", 1)
            vals = tree.item(iid, "values")
            if vals and 1 <= col <= len(vals):
                self.clipboard_clear()
                self.clipboard_append(str(vals[col - 1]))

        def copy_row():
            iid = tree.focus()
            if not iid:
                return
            vals = tree.item(iid, "values")
            if vals:
                self.clipboard_clear()
                self.clipboard_append("\t".join(str(v) for v in vals))

        menu.add_command(label="Copy cell", command=copy_cell)
        menu.add_command(label="Copy row",  command=copy_row)

        def on_right(event):
            iid = tree.identify_row(event.y)
            col = tree.identify_column(event.x)
            if iid:
                tree.focus(iid)
                tree.selection_set(iid)
                tree._last_click_col = int(col.replace("#", ""))
                menu.post(event.x_root, event.y_root)

        def on_left(event):
            col = tree.identify_column(event.x)
            tree._last_click_col = int(col.replace("#", ""))

        tree.bind("<Button-3>",      on_right)
        tree.bind("<ButtonPress-1>", on_left)
        tree.bind("<Control-c>",     lambda e: copy_row())
        tree.bind("<Control-C>",     lambda e: copy_row())
        return menu

    def _retheme_find_bar(self, fb, T):
        """Re-apply theme colours to a find bar frame."""
        if fb is None:
            return
        BG2 = T["BG2"]; FG = T["FG"]; FG2 = T["FG2"]
        ACCENT = T["ACCENT"]; BG3 = T["BG3"]
        fb.configure(bg=BG2)
        fb._lbl.configure(bg=BG2, fg=FG2)
        fb._entry.configure(bg=BG3, fg=FG, insertbackground=ACCENT,
                            highlightcolor=ACCENT, highlightbackground=T["BORDER"])
        fb._count_lbl.configure(bg=BG2, fg=FG2)
        fb._close_btn.configure(bg=BG2, fg=FG2, activebackground=T["ERROR"],
                                 activeforeground="white")

    def _open_in_vscode(self, folder_path):
        """Mở folder_path trong VSCode. Hiển thị warning nếu lệnh 'code' không có trong PATH."""
        import subprocess, shutil
        code_cmd = shutil.which("code")
        if code_cmd:
            subprocess.Popen([code_cmd, str(folder_path)])
        else:
            messagebox.showwarning(
                "VSCode không tìm thấy",
                "Không tìm thấy lệnh 'code' trong PATH.\n\n"
                "Hãy đảm bảo VSCode đã được cài đặt và\n"
                "thêm vào PATH (Shell Command: Install 'code' command in PATH)."
            )

    def _retheme_copy_menu(self, menu, T):
        menu.configure(bg=T["BG3"], fg=T["FG"],
                       activebackground=T["ACCENT"], activeforeground="white",
                       relief="flat", bd=1)

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1 — Work Item Search
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_wi(self):
        p = self._tab_wi

        self._wi_bar = tk.Frame(p, padx=18, pady=12)
        self._wi_bar.grid(row=0, column=0, sticky="ew")
        self._wi_bar.columnconfigure(1, weight=1)

        self._wi_lbl_kw = tk.Label(self._wi_bar, text="Keywords",
                                    font=FONT_BOLD, width=10, anchor="e")
        self._wi_lbl_kw.grid(row=0, column=0, padx=(0, 8))
        self._wi_query_var   = tk.StringVar()
        self._wi_query_entry = tk.Entry(self._wi_bar, textvariable=self._wi_query_var,
                                         font=("Consolas", 12), relief="flat", bd=0,
                                         highlightthickness=2)
        self._wi_query_entry.grid(row=0, column=1, sticky="ew", ipady=7, padx=(0, 10))
        self._wi_query_entry.bind("<Return>", lambda e: self._wi_do_search())
        self._wi_query_entry.focus_set()

        self._wi_lbl_hint = tk.Label(
            self._wi_bar,
            text="Phân tách nhiều từ bằng  |  ví dụ: NTN|satellite|(DC)",
            font=FONT_SMALL)
        self._wi_lbl_hint.grid(row=1, column=1, sticky="w", pady=(2, 0))
        self._wi_search_btn = tk.Button(self._wi_bar, text="Search ⏎", font=FONT_BOLD,
                                         relief="flat", bd=0, padx=20, pady=7,
                                         cursor="hand2", command=self._wi_do_search)
        self._wi_search_btn.grid(row=0, column=2)

        self._wi_opts = tk.Frame(self._wi_bar)
        self._wi_opts.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._wi_lbl_rel = tk.Label(self._wi_opts, text="Release:", font=FONT_UI)
        self._wi_lbl_rel.pack(side="left")
        self._wi_rel_var = tk.StringVar()
        self._wi_rel_cb  = ttk.Combobox(self._wi_opts, textvariable=self._wi_rel_var,
                                          width=5, state="readonly",
                                          values=["", "15", "16", "17", "18", "19", "20"])
        self._wi_rel_cb.pack(side="left", padx=(4, 16))
        self._wi_lbl_lim = tk.Label(self._wi_opts, text="Limit:", font=FONT_UI)
        self._wi_lbl_lim.pack(side="left")
        self._wi_limit_var = tk.StringVar(value="200")
        self._wi_lim_entry = tk.Entry(self._wi_opts, textvariable=self._wi_limit_var,
                                       width=6, font=FONT_UI, relief="flat", bd=0,
                                       highlightthickness=1)
        self._wi_lim_entry.pack(side="left", padx=(4, 16), ipady=3)

        self._wi_cs_var   = tk.BooleanVar()
        self._wi_cr_var   = tk.BooleanVar()
        self._wi_spec_var = tk.BooleanVar()
        self._wi_any_var  = tk.BooleanVar()
        self._wi_check_widgets = []
        for text, var in [("Case-sensitive", self._wi_cs_var), ("Check CR",   self._wi_cr_var),
                           ("Check Spec",    self._wi_spec_var), ("Check Any", self._wi_any_var)]:
            cb = tk.Checkbutton(self._wi_opts, text=text, variable=var,
                                font=FONT_UI, highlightthickness=0)
            cb.pack(side="left", padx=6)
            self._wi_check_widgets.append(cb)

        self._wi_content = tk.Frame(p)
        self._wi_content.grid(row=1, column=0, sticky="nsew")
        self._wi_content.columnconfigure(0, weight=1)
        self._wi_content.rowconfigure(1, weight=1)

        self._wi_sbar = tk.Frame(self._wi_content, padx=14)
        self._wi_sbar.grid(row=0, column=0, sticky="ew")
        self._wi_sbar.columnconfigure(1, weight=1)
        self._wi_status_icon = tk.Label(self._wi_sbar, text="●", font=FONT_SMALL)
        self._wi_status_icon.grid(row=0, column=0, padx=(0, 6), pady=6)
        self._wi_status_var = tk.StringVar(value="Sẵn sàng.")
        self._wi_status_lbl = tk.Label(self._wi_sbar, textvariable=self._wi_status_var,
                                        font=FONT_SMALL, anchor="w")
        self._wi_status_lbl.grid(row=0, column=1, sticky="w")
        self._wi_pulse = PulseBar(self._wi_sbar, width=160)
        self._wi_pulse.grid(row=0, column=2, padx=(10, 0), sticky="ew")
        self._wi_open_btn = tk.Button(self._wi_sbar, text="📂 Mở Excel",
                                       font=FONT_BOLD, relief="flat", bd=0,
                                       padx=14, pady=4, cursor="hand2",
                                       command=self._wi_open_excel, state="disabled")
        self._wi_open_btn.grid(row=0, column=3, padx=(10, 0))
        self._wi_vscode_btn = tk.Button(self._wi_sbar, text="⎇ Mở VSCode",
                                         font=FONT_BOLD, relief="flat", bd=0,
                                         padx=14, pady=4, cursor="hand2",
                                         state="disabled")
        self._wi_vscode_btn.grid(row=0, column=4, padx=(6, 0))

        self._wi_paned = ttk.PanedWindow(self._wi_content, orient=tk.VERTICAL)
        self._wi_paned.grid(row=1, column=0, sticky="nsew")

        self._wi_tbl = tk.Frame(self._wi_paned)
        self._wi_paned.add(self._wi_tbl, weight=1)
        self._wi_tbl.columnconfigure(0, weight=1)
        self._wi_tbl.rowconfigure(0, weight=1)

        cols = ("uid", "code", "title", "cr_link", "spec_link", "tdocs")
        self._wi_tree = ttk.Treeview(self._wi_tbl, columns=cols,
                                      show="headings", selectmode="browse")
        for cid, heading, width, anchor in [
            ("uid",       "Unique_ID",  90,  "center"),
            ("code",      "Acronym",    140, "w"),
            ("title",     "Name",       420, "w"),
            ("cr_link",   "CR Link",    90,  "center"),
            ("spec_link", "Spec Link",  90,  "center"),
            ("tdocs",     "TDocs",      80,  "center"),
        ]:
            self._wi_tree.heading(cid, text=heading)
            self._wi_tree.column(cid, width=width, minwidth=40, anchor=anchor,
                                  stretch=(cid == "title"))

        self._wi_vsb = SmoothScrollbar(self._wi_tbl, orient="vertical",   command=self._wi_tree.yview)
        self._wi_hsb = SmoothScrollbar(self._wi_tbl, orient="horizontal",  command=self._wi_tree.xview)
        self._wi_tree.configure(yscrollcommand=self._wi_vsb.set, xscrollcommand=self._wi_hsb.set)
        self._wi_tree.grid(row=0, column=0, sticky="nsew")
        self._wi_vsb.grid(row=0, column=1, sticky="ns",  padx=(2, 2))
        self._wi_hsb.grid(row=1, column=0, sticky="ew",  pady=(2, 2))
        self._wi_tree.bind("<ButtonRelease-1>", self._wi_on_cell_click)
        self._wi_tree.bind("<Motion>",          self._wi_on_motion)
        self._wi_copy_menu = self._add_copy_menu(
            self._wi_tree,
            ["Unique_ID", "Acronym", "Name", "CR Link", "Spec Link", "TDocs"])

        self._wi_find = self._make_find_bar(
            self._wi_tbl, self._wi_tree,
            lambda: self._wi_all_items,
            self._wi_repopulate_row)

        self._wi_log_toggle_var = tk.BooleanVar(value=False)
        self._wi_log_btn = tk.Checkbutton(self._wi_sbar, text="▾ Log",
                                           variable=self._wi_log_toggle_var,
                                           command=self._wi_toggle_log,
                                           font=FONT_SMALL, indicatoron=False,
                                           relief="flat", highlightthickness=0)
        self._wi_log_btn.grid(row=0, column=5, padx=(8, 0))

        self._wi_log_outer = tk.Frame(self._wi_paned)
        self._wi_log_inner = tk.Frame(self._wi_log_outer)
        self._wi_log_inner.pack(fill="both", expand=True)
        self._wi_log_text  = tk.Text(self._wi_log_inner, height=7, font=FONT_MONO,
                                      relief="flat", bd=0, wrap="word", state="disabled")
        wi_lsb = SmoothScrollbar(self._wi_log_inner, orient="vertical",
                                  command=self._wi_log_text.yview)
        self._wi_log_text.configure(yscrollcommand=wi_lsb.set)
        self._wi_log_text.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=4)
        wi_lsb.pack(side="right", fill="y")
        self._wi_log_lsb = wi_lsb

    def _wi_repopulate_row(self, iid, row_data):
        self._wi_item_links[iid]   = row_data["_links"]
        self._wi_tdoc_status[iid]  = row_data["_tdoc_status"]

    # ── Tab 1 logic ────────────────────────────────────────────────────────────

    def _wi_check_cache_status(self):
        T = self._T
        if CACHE_FILE.exists():
            age = (datetime.date.today() -
                   datetime.date.fromtimestamp(CACHE_FILE.stat().st_mtime)).days
            kb  = CACHE_FILE.stat().st_size // 1024
            self._wi_cache_label.config(
                text=f"Cache: {CACHE_FILE.name}  {kb} KB  ({age}d ago)",
                fg=T["WARN"] if age > 20 else T["FG2"])
        else:
            self._wi_cache_label.config(
                text="Chưa có cache — cần tải WorkPlan", fg=T["WARN"])

    def _wi_log(self, msg, color=None):
        def _do():
            self._wi_log_text.config(state="normal")
            tag = None
            if color:
                tag = f"col_{color.replace('#', '')}"
                self._wi_log_text.tag_configure(tag, foreground=color)
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self._wi_log_text.insert("end", f"[{ts}] {msg}\n", tag or "")
            self._wi_log_text.see("end")
            self._wi_log_text.config(state="disabled")
        self.after(0, _do)

    def _wi_set_status(self, msg, color=None, icon_color=None):
        def _do():
            self._wi_status_var.set(msg)
            if icon_color: self._wi_status_icon.config(fg=icon_color)
            if color:      self._wi_status_lbl.config(fg=color)
        self.after(0, _do)

    def _wi_toggle_log(self):
        if self._wi_log_toggle_var.get():
            self._wi_paned.add(self._wi_log_outer, weight=0)
            def _set_sash(attempt=0):
                try:
                    total = self._wi_paned.winfo_height()
                    if total > 60:
                        self._wi_paned.sashpos(0, max(60, total - 170))
                    elif attempt < 10:
                        self.after(20, lambda: _set_sash(attempt + 1))
                except Exception:
                    pass
            self.after(10, _set_sash)
        else:
            try: self._wi_paned.remove(self._wi_log_outer)
            except Exception: pass

    def _wi_start_busy(self, msg="Đang xử lý..."):
        self._wi_running = True
        self._wi_search_btn.config(state="disabled", text="...")
        self._wi_update_btn.config(state="disabled")
        self._wi_pulse.start()
        T = self._T
        self._wi_set_status(msg, T["WARN"], T["WARN"])

    def _wi_stop_busy(self):
        self._wi_running = False
        self._wi_search_btn.config(state="normal", text="Search ⏎")
        self._wi_update_btn.config(state="normal")
        self._wi_pulse.stop()

    def _wi_do_update(self):
        if self._wi_running: return
        self._wi_start_busy("Đang tải WorkPlan từ 3GPP...")
        def worker():
            try:
                download_workplan(force=True,
                    log_fn=lambda m: (self._wi_log(m), self._wi_set_status(m)))
                self.after(0, self._wi_check_cache_status)
                T = self._T
                self._wi_set_status("Cập nhật thành công!", T["SUCCESS"], T["SUCCESS"])
                self._wi_log("Done.", T["SUCCESS"])
            except Exception as e:
                T = self._T
                self._wi_log(f"LỖI: {e}", T["ERROR"])
                self._wi_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"])
            finally:
                self.after(0, self._wi_stop_busy)
        threading.Thread(target=worker, daemon=True).start()

    def _wi_do_search(self):
        if self._wi_running: return
        query = self._wi_query_var.get().strip()
        if not query:
            messagebox.showwarning("Thiếu từ khóa", "Nhập ít nhất 1 từ khóa.")
            return
        release = self._wi_rel_var.get().strip() or None
        try:    limit = int(self._wi_limit_var.get())
        except: limit = 200
        cs   = self._wi_cs_var.get()
        ccr  = self._wi_cr_var.get()
        csp  = self._wi_spec_var.get()
        cany = self._wi_any_var.get()
        for row in self._wi_tree.get_children(): self._wi_tree.delete(row)
        self._wi_item_links.clear()
        self._wi_tdoc_status.clear()
        self._wi_all_items = []
        self._wi_open_btn.config(state="disabled")
        self._wi_last_output   = None
        self._wi_pending_export = None
        self._wi_start_busy("Đang tìm kiếm...")

        def worker():
            T = self._T
            try:
                xlsx, age = download_workplan(log_fn=lambda m: self._wi_log(m))
                self._wi_log(f"Cache: {xlsx.name} ({age}d ago)")
                self._wi_set_status("Đang tìm trong file WorkPlan...")
                items, total = search_workitems(xlsx, query, release_filter=release,
                                                limit=limit, case_sensitive=cs)
                self._wi_log(f"Tìm thấy {total} items (hiển thị {len(items)})")
                if cany and items:
                    def p(d, t): self._wi_set_status(f"Kiểm tra [{d}/{t}]...", T["WARN"], T["WARN"])
                    items = parallel_check_any(items, p)
                elif ccr and items:
                    def p(d, t): self._wi_set_status(f"Kiểm tra CR [{d}/{t}]...", T["WARN"], T["WARN"])
                    items = parallel_check_cr(items, p)
                elif csp and items:
                    def p(d, t): self._wi_set_status(f"Kiểm tra Spec [{d}/{t}]...", T["WARN"], T["WARN"])
                    items = parallel_check_spec(items, p)
                self._wi_pending_export = (items, query, release or "", limit, ccr, csp, cany, cs) if items else None

                def update_ui():
                    T2 = self._T
                    self._wi_tree.tag_configure("link",  foreground=T2["LINK"])
                    self._wi_tree.tag_configure("odd",   background=T2["BG2"])
                    self._wi_tree.tag_configure("even",  background=T2["BG"])
                    store = []
                    for i, item in enumerate(items):
                        cr   = item.get("cr_link", "")
                        spec = item.get("spec_link", "")
                        vals = (item["uid"], item["code"], item["title"],
                                "→ CR" if cr else "—",
                                "→ Spec" if spec else "—",
                                "↓ TDocs")
                        iid = self._wi_tree.insert("", "end", values=vals,
                                                    tags=("odd" if i % 2 else "even",))
                        self._wi_item_links[iid]  = (cr, spec)
                        self._wi_tdoc_status[iid] = "ready"
                        store.append({"_values": vals, "_links": (cr, spec),
                                      "_tdoc_status": "ready"})
                    self._wi_all_items = store
                    msg = f"{total} work item tìm thấy cho \"{query}\""
                    if total > len(items):
                        msg += f"  (hiển thị {len(items)}/{total})"
                    self._wi_set_status(msg, T2["FG2"], T2["SUCCESS"])
                    if items: self._wi_open_btn.config(state="normal")
                self.after(0, update_ui)
            except Exception as e:
                T = self._T
                self._wi_log(f"LỖI: {e}", T["ERROR"])
                self._wi_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"])
            finally:
                self.after(0, self._wi_stop_busy)
        threading.Thread(target=worker, daemon=True).start()

    def _wi_open_excel(self):
        T = self._T
        if self._wi_last_output and self._wi_last_output.exists():
            open_file(self._wi_last_output); return
        if not self._wi_pending_export:
            messagebox.showinfo("Không có dữ liệu", "Chưa có kết quả tìm kiếm để xuất.")
            return
        items, query, release, limit, ccr, csp, cany, cs = self._wi_pending_export
        try:
            EXCELS_DIR.mkdir(exist_ok=True)
            fname    = build_wi_filename(query, release, limit, ccr, csp, cany, cs)
            out_path = EXCELS_DIR / fname
            export_wi_xlsx(items, out_path)
            self._wi_last_output = out_path
            self._wi_set_status(f"Đã xuất: {out_path.name}", T["SUCCESS"], T["SUCCESS"])
            open_file(out_path)
        except Exception as e:
            messagebox.showerror("Lỗi xuất Excel", str(e))

    def _wi_start_tdoc_download(self, iid, uid):
        if not TDOC_FETCH_OK:
            messagebox.showwarning("Thiếu thư viện",
                "Cần cài thêm:\n\npip install requests beautifulsoup4\n\nSau đó khởi động lại app.")
            return
        self._wi_tdoc_busy.add(iid)
        self._wi_tdoc_status[iid] = "busy"
        self._wi_tree.set(iid, "tdocs", "⏳ ...")
        if not self._wi_log_toggle_var.get():
            self._wi_log_toggle_var.set(True); self._wi_toggle_log()
        T = self._T

        def worker():
            def log(msg, color=None): self._wi_log(msg, color)
            try:
                downloaded, skipped, errors, extract_dir = tdoc_fetch_smart(uid, log_fn=log)
                n = len(downloaded)
                log(f"WI {uid}: {n} file(s) tải xong (skip {skipped}, lỗi {errors})", T["SUCCESS"])
                if downloaded:
                    out   = tdoc_process(uid, downloaded, log_fn=log, extract_dir=extract_dir)
                    label = f"✓ {n} file"
                    log(f"Xong → {out.parent}", T["SUCCESS"])
                    _out_dir = out.parent
                    self.after(0, lambda p=_out_dir: (
                        self._wi_vscode_btn.config(
                            state="normal",
                            command=lambda fp=p: self._open_in_vscode(fp)
                        ),
                    ))
                else:
                    label = "✓ 0 file"
                self.after(0, lambda: (
                    self._wi_tree.set(iid, "tdocs", label),
                    self._wi_tdoc_status.__setitem__(iid, "done"),
                ))
            except NoCRFound:
                log(f"WI {uid}: Không có Change Request nào", T["WARN"])
                self.after(0, lambda: (
                    self._wi_tree.set(iid, "tdocs", "✗ No CR"),
                    self._wi_tdoc_status.__setitem__(iid, "none"),
                ))
            except NoAgreedTDocs:
                log(f"WI {uid}: Không có TDoc nào", T["WARN"])
                self.after(0, lambda: (
                    self._wi_tree.set(iid, "tdocs", "✗ None"),
                    self._wi_tdoc_status.__setitem__(iid, "none"),
                ))
            except Exception as e:
                log(f"WI {uid} ERROR: {e}", T["ERROR"])
                self.after(0, lambda: (
                    self._wi_tree.set(iid, "tdocs", "✗ Err"),
                    self._wi_tdoc_status.__setitem__(iid, "error"),
                ))
            finally:
                self._wi_tdoc_busy.discard(iid)
        threading.Thread(target=worker, daemon=True).start()

    def _wi_on_cell_click(self, event):
        if self._wi_tree.identify_region(event.x, event.y) != "cell": return
        col_num = int(self._wi_tree.identify_column(event.x).replace("#", ""))
        iid     = self._wi_tree.identify_row(event.y)
        if not iid: return
        if col_num in (4, 5):
            links = self._wi_item_links.get(iid, ("", ""))
            url   = links[0] if col_num == 4 else links[1]
            if url: webbrowser.open(url)
        elif col_num == 6:
            if iid not in self._wi_tdoc_busy:
                uid = self._wi_tree.set(iid, "uid")
                self._wi_start_tdoc_download(iid, uid)

    def _wi_on_motion(self, event):
        if self._wi_tree.identify_region(event.x, event.y) != "cell":
            self._wi_tree.config(cursor=""); return
        col_num = int(self._wi_tree.identify_column(event.x).replace("#", ""))
        iid     = self._wi_tree.identify_row(event.y)
        if col_num in (4, 5) and iid:
            links = self._wi_item_links.get(iid, ("", ""))
            self._wi_tree.config(cursor="hand2" if (links[0] if col_num == 4 else links[1]) else "")
        elif col_num == 6 and iid:
            st = self._wi_tdoc_status.get(iid, "ready")
            self._wi_tree.config(cursor="hand2" if st != "busy" else "watch")
        else:
            self._wi_tree.config(cursor="")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2 — CR Titles Search
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_cr(self):
        p = self._tab_cr

        self._cr_bar = tk.Frame(p, padx=18, pady=12)
        self._cr_bar.grid(row=0, column=0, sticky="ew")
        self._cr_bar.columnconfigure(1, weight=1)

        self._cr_lbl_kw = tk.Label(self._cr_bar, text="Keywords",
                                    font=FONT_BOLD, width=10, anchor="e")
        self._cr_lbl_kw.grid(row=0, column=0, padx=(0, 8))
        self._cr_query_var   = tk.StringVar()
        self._cr_query_entry = tk.Entry(self._cr_bar, textvariable=self._cr_query_var,
                                         font=("Consolas", 12), relief="flat", bd=0,
                                         highlightthickness=2)
        self._cr_query_entry.grid(row=0, column=1, sticky="ew", ipady=7, padx=(0, 10))
        self._cr_query_entry.bind("<Return>", lambda e: self._cr_do_search())
        self._cr_lbl_hint = tk.Label(
            self._cr_bar,
            text='Tìm đơn: NTN   |   Cụm từ: "non-terrestrial"   |   OR: NTN OR satellite',
            font=FONT_SMALL)
        self._cr_lbl_hint.grid(row=1, column=1, sticky="w", pady=(2, 0))
        self._cr_search_btn = tk.Button(self._cr_bar, text="Search ⏎", font=FONT_BOLD,
                                         relief="flat", bd=0, padx=20, pady=7,
                                         cursor="hand2", command=self._cr_do_search)
        self._cr_search_btn.grid(row=0, column=2)

        self._cr_opts = tk.Frame(self._cr_bar)
        self._cr_opts.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self._cr_lbl_lim = tk.Label(self._cr_opts, text="Limit:", font=FONT_UI)
        self._cr_lbl_lim.pack(side="left")
        self._cr_limit_var = tk.StringVar(value="100")
        self._cr_lim_entry = tk.Entry(self._cr_opts, textvariable=self._cr_limit_var,
                                       width=6, font=FONT_UI, relief="flat", bd=0,
                                       highlightthickness=1)
        self._cr_lim_entry.pack(side="left", padx=(4, 20), ipady=3)
        self._cr_wi_only_var = tk.BooleanVar()
        self._cr_wi_only_cb  = tk.Checkbutton(self._cr_opts, text="Workitem Only",
                                               variable=self._cr_wi_only_var,
                                               font=FONT_UI, highlightthickness=0)
        self._cr_wi_only_cb.pack(side="left", padx=6)
        self._cr_db_label = tk.Label(self._cr_opts, text="", font=FONT_SMALL)
        self._cr_db_label.pack(side="right", padx=(20, 0))

        self._cr_content = tk.Frame(p)
        self._cr_content.grid(row=1, column=0, sticky="nsew")
        self._cr_content.columnconfigure(0, weight=1)
        self._cr_content.rowconfigure(1, weight=1)

        self._cr_sbar = tk.Frame(self._cr_content, padx=14)
        self._cr_sbar.grid(row=0, column=0, sticky="ew")
        self._cr_sbar.columnconfigure(1, weight=1)
        self._cr_status_icon = tk.Label(self._cr_sbar, text="●", font=FONT_SMALL)
        self._cr_status_icon.grid(row=0, column=0, padx=(0, 6), pady=6)
        self._cr_status_var = tk.StringVar(value="Sẵn sàng.")
        self._cr_status_lbl = tk.Label(self._cr_sbar, textvariable=self._cr_status_var,
                                        font=FONT_SMALL, anchor="w")
        self._cr_status_lbl.grid(row=0, column=1, sticky="w")
        self._cr_pulse = PulseBar(self._cr_sbar, width=160)
        self._cr_pulse.grid(row=0, column=2, padx=(10, 0), sticky="ew")
        self._cr_open_btn = tk.Button(self._cr_sbar, text="📂 Mở Excel",
                                       font=FONT_BOLD, relief="flat", bd=0,
                                       padx=14, pady=4, cursor="hand2",
                                       command=self._cr_open_excel, state="disabled")
        self._cr_open_btn.grid(row=0, column=3, padx=(10, 0))

        self._cr_tbl = tk.Frame(self._cr_content)
        self._cr_tbl.grid(row=1, column=0, sticky="nsew")
        self._cr_tbl.columnconfigure(0, weight=1)
        self._cr_tbl.rowconfigure(0, weight=1)

        cols = ("title", "workitem_id", "extra", "download", "portal_link")
        self._cr_tree = ttk.Treeview(self._cr_tbl, columns=cols,
                                      show="headings", selectmode="browse")
        for cid, heading, width, anchor in [
            ("title",       "Title",       280, "w"),
            ("workitem_id", "Workitem ID", 100, "center"),
            ("extra",       "Release",     280, "w"),
            ("download",    "↓ Download",   90, "center"),
            ("portal_link", "Portal",       90, "center"),
        ]:
            self._cr_tree.heading(cid, text=heading)
            self._cr_tree.column(cid, width=width, minwidth=40, anchor=anchor,
                                  stretch=(cid == "extra"))

        self._cr_vsb = SmoothScrollbar(self._cr_tbl, orient="vertical",   command=self._cr_tree.yview)
        self._cr_hsb = SmoothScrollbar(self._cr_tbl, orient="horizontal",  command=self._cr_tree.xview)
        self._cr_tree.configure(yscrollcommand=self._cr_vsb.set, xscrollcommand=self._cr_hsb.set)
        self._cr_tree.grid(row=0, column=0, sticky="nsew")
        self._cr_vsb.grid(row=0, column=1, sticky="ns", padx=(2, 2))
        self._cr_hsb.grid(row=1, column=0, sticky="ew", pady=(2, 2))
        self._cr_tree.bind("<ButtonRelease-1>", self._cr_on_cell_click)
        self._cr_tree.bind("<Motion>",          self._cr_on_motion)
        self._cr_copy_menu = self._add_copy_menu(
            self._cr_tree,
            ["Title", "Workitem ID", "Extra", "Download", "Portal"])

        self._cr_find = self._make_find_bar(
            self._cr_tbl, self._cr_tree,
            lambda: self._cr_all_rows,
            self._cr_repopulate_row)

    def _cr_repopulate_row(self, iid, row_data):
        self._cr_row_urls[iid] = row_data["_portal_url"]
        self._cr_dl_urls[iid]  = row_data["_dl_url"]

    # ── Tab 2 logic ────────────────────────────────────────────────────────────

    def _cr_check_db_status(self):
        T = self._T
        exists, kb, titles, wis, last = cr_db_status()
        if not exists:
            self._cr_db_label.config(
                text="⚠ cr_titles.db chưa có — chạy cr_indexer.py trước",
                fg=T["WARN"])
        else:
            last_str = last[:10] if last else "N/A"
            self._cr_db_label.config(
                text=f"DB: {kb:,} KB  |  {titles:,} titles  |  {wis:,} WIs  |  crawled: {last_str}",
                fg=T["FG2"])

    def _cr_set_status(self, msg, color=None, icon_color=None):
        def _do():
            self._cr_status_var.set(msg)
            if icon_color: self._cr_status_icon.config(fg=icon_color)
            if color:      self._cr_status_lbl.config(fg=color)
        self.after(0, _do)

    def _cr_do_search(self):
        if self._cr_running: return
        query = self._cr_query_var.get().strip()
        if not query:
            messagebox.showwarning("Thiếu từ khóa", "Nhập ít nhất 1 từ khóa.")
            return
        try:    limit = int(self._cr_limit_var.get())
        except: limit = 100
        wi_only = self._cr_wi_only_var.get()
        for row in self._cr_tree.get_children(): self._cr_tree.delete(row)
        self._cr_row_urls.clear(); self._cr_dl_urls.clear(); self._cr_dl_busy.clear()
        self._cr_all_rows = []; self._cr_open_btn.config(state="disabled")
        self._cr_last_output = None; self._cr_pending_export = None
        self._cr_running = True
        self._cr_search_btn.config(state="disabled", text="...")
        self._cr_pulse.start()
        T = self._T
        self._cr_set_status("Đang tìm kiếm...", T["WARN"], T["WARN"])

        def worker():
            T = self._T
            try:
                rows, total = cr_search(query, limit=limit, workitem_only=wi_only)
                if rows:
                    wi_ids = {str(r["workitem_id"]) for r in rows}
                    self._cr_set_status("Đang tra cứu workplan...", T["WARN"], T["WARN"])
                    wi_info = load_workplan_wi_info(wi_ids)
                    if wi_only:
                        for r in rows:
                            r["extra"] = wi_info.get(str(r["workitem_id"]), {}).get("name", "")
                    else:
                        for r in rows:
                            r["extra"] = wi_info.get(str(r["workitem_id"]), {}).get("release", "")
                        rows.sort(key=lambda r: _release_sort_key(r["extra"]), reverse=True)
                self._cr_pending_export = (rows, query, limit, wi_only) if rows else None

                def update_ui():
                    T2 = self._T
                    self._cr_tree.heading("extra", text="WI Name" if wi_only else "Release")
                    self._cr_tree.tag_configure("link",  foreground=T2["LINK"])
                    self._cr_tree.tag_configure("odd",   background=T2["BG2"])
                    self._cr_tree.tag_configure("even",  background=T2["BG"])
                    store = []
                    for i, row in enumerate(rows):
                        dl_url = row.get("download_url", "")
                        dl_lbl = "↓ DL" if dl_url else "—"
                        vals   = (row["title"], row["workitem_id"],
                                  row.get("extra", ""), dl_lbl, "→ Portal")
                        iid = self._cr_tree.insert("", "end", values=vals,
                                                    tags=("odd" if i % 2 else "even",))
                        self._cr_row_urls[iid] = row["portal_url"]
                        self._cr_dl_urls[iid]  = dl_url
                        store.append({"_values": vals, "_portal_url": row["portal_url"],
                                      "_dl_url": dl_url})
                    self._cr_all_rows = store
                    self._cr_set_status(f"{total} kết quả cho \"{query}\"", T2["FG2"], T2["SUCCESS"])
                    if rows: self._cr_open_btn.config(state="normal")
                self.after(0, update_ui)
            except Exception as e:
                T = self._T
                self._cr_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"])
                messagebox.showerror("Lỗi tìm kiếm", str(e))
            finally:
                self._cr_running = False
                self.after(0, lambda: (
                    self._cr_search_btn.config(state="normal", text="Search ⏎"),
                    self._cr_pulse.stop()))
        threading.Thread(target=worker, daemon=True).start()

    def _cr_start_download(self, iid, dl_url):
        if iid in self._cr_dl_busy: return
        if not TDOC_FETCH_OK:
            messagebox.showwarning("Thiếu thư viện", "pip install requests beautifulsoup4")
            return
        self._cr_dl_busy.add(iid)
        self._cr_tree.set(iid, "download", "⏳")
        T = self._T

        def worker():
            try:
                import requests as _req
                import urllib3; urllib3.disable_warnings()
                sess = _req.Session()
                sess.headers.update({"User-Agent": HDRS["User-Agent"]})
                out_dir = DOWNLOAD_EXTRACTED_DIR / "cr_singles"
                out_dir.mkdir(parents=True, exist_ok=True)
                tdoc_num = re.sub(r'[^A-Za-z0-9\-]', '_',
                                  dl_url.split('/')[-1].split('?')[0]) or "CR"
                from urllib.parse import urlparse, parse_qs
                qs         = parse_qs(urlparse(dl_url).query)
                uid_param  = (qs.get('contributionUid') or qs.get('tdocuid') or [None])[0]
                cache_stem = uid_param or tdoc_num
                cached_zip = _find_zip_in_cache(cache_stem)
                if cached_zip:
                    xdir = out_dir / cache_stem
                    if not xdir.exists():
                        _extract_zip_to(cached_zip, xdir)
                    fp = cached_zip
                else:
                    tdoc_info = {"tdoc_number": tdoc_num, "download_url": dl_url}
                    fp = _tdoc_download_one(sess, tdoc_info, out_dir)
                if fp:
                    def done():
                        self._cr_tree.set(iid, "download", "✓ DL")
                        self._cr_tree.item(iid, tags=(*self._cr_tree.item(iid, "tags"), "dl_done"))
                    self.after(0, done)
                    self.after(200, lambda: open_file(fp))
                else:
                    self.after(0, lambda: self._cr_tree.set(iid, "download", "✗ Err"))
            except Exception:
                self.after(0, lambda: self._cr_tree.set(iid, "download", "✗ Err"))
            finally:
                self._cr_dl_busy.discard(iid)
        threading.Thread(target=worker, daemon=True).start()

    def _cr_open_excel(self):
        T = self._T
        if self._cr_last_output and self._cr_last_output.exists():
            open_file(self._cr_last_output); return
        if not self._cr_pending_export:
            messagebox.showinfo("Không có dữ liệu", "Chưa có kết quả tìm kiếm để xuất.")
            return
        rows, query, limit, wi_only = self._cr_pending_export
        try:
            EXCELS_DIR.mkdir(exist_ok=True)
            fname    = build_cr_filename(query, limit, wi_only)
            out_path = EXCELS_DIR / fname
            export_cr_xlsx(rows, out_path, workitem_only=wi_only)
            self._cr_last_output = out_path
            self._cr_set_status(f"Đã xuất: {out_path.name}", T["SUCCESS"], T["SUCCESS"])
            open_file(out_path)
        except Exception as e:
            messagebox.showerror("Lỗi xuất Excel", str(e))

    def _cr_on_cell_click(self, event):
        if self._cr_tree.identify_region(event.x, event.y) != "cell": return
        col_num = int(self._cr_tree.identify_column(event.x).replace("#", ""))
        iid     = self._cr_tree.identify_row(event.y)
        if not iid: return
        if col_num == 4:
            dl = self._cr_dl_urls.get(iid, "")
            if dl: self._cr_start_download(iid, dl)
        elif col_num == 5:
            url = self._cr_row_urls.get(iid, "")
            if url: webbrowser.open(url)

    def _cr_on_motion(self, event):
        if self._cr_tree.identify_region(event.x, event.y) != "cell":
            self._cr_tree.config(cursor=""); return
        col_num = int(self._cr_tree.identify_column(event.x).replace("#", ""))
        iid     = self._cr_tree.identify_row(event.y)
        if col_num == 4 and iid:
            dl = self._cr_dl_urls.get(iid, "")
            self._cr_tree.config(cursor="hand2" if dl and iid not in self._cr_dl_busy else "")
        elif col_num == 5 and iid and self._cr_row_urls.get(iid):
            self._cr_tree.config(cursor="hand2")
        else:
            self._cr_tree.config(cursor="")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 3 — Acronym Search
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_acr(self):
        p = self._tab_acr
        p.rowconfigure(1, weight=1)

        self._acr_bar = tk.Frame(p, padx=18, pady=12)
        self._acr_bar.grid(row=0, column=0, sticky="ew")
        self._acr_bar.columnconfigure(1, weight=1)

        self._acr_lbl_kw = tk.Label(self._acr_bar, text="Acronym",
                                     font=FONT_BOLD, width=10, anchor="e")
        self._acr_lbl_kw.grid(row=0, column=0, padx=(0, 8))
        self._acr_query_var   = tk.StringVar()
        self._acr_query_entry = tk.Entry(self._acr_bar, textvariable=self._acr_query_var,
                                          font=("Consolas", 12), relief="flat", bd=0,
                                          highlightthickness=2)
        self._acr_query_entry.grid(row=0, column=1, sticky="ew", ipady=7, padx=(0, 10))
        self._acr_query_entry.bind("<Return>", lambda e: self._acr_do_search())

        self._acr_search_btn = tk.Button(self._acr_bar, text="Search ⏎", font=FONT_BOLD,
                                          relief="flat", bd=0, padx=20, pady=7,
                                          cursor="hand2", command=self._acr_do_search)
        self._acr_search_btn.grid(row=0, column=2)
        self._acr_update_btn = tk.Button(self._acr_bar, text="↻ Update DB", font=FONT_SMALL,
                                          relief="flat", bd=0, padx=10, pady=4,
                                          cursor="hand2", command=self._acr_do_update)
        self._acr_update_btn.grid(row=0, column=3, padx=(8, 0))

        self._acr_opts = tk.Frame(self._acr_bar)
        self._acr_opts.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self._acr_lbl_hint = tk.Label(
            self._acr_opts,
            text="Tìm trong cột Work items và Subject của 3gpp_cr_approved.db",
            font=FONT_SMALL)
        self._acr_lbl_hint.pack(side="left", padx=(0, 20))
        self._acr_exact_var = tk.BooleanVar(value=False)
        self._acr_exact_cb  = tk.Checkbutton(self._acr_opts, text="Exact match",
                                              variable=self._acr_exact_var,
                                              font=FONT_UI, highlightthickness=0)
        self._acr_exact_cb.pack(side="left", padx=6)
        self._acr_db_label = tk.Label(self._acr_opts, text="", font=FONT_SMALL)
        self._acr_db_label.pack(side="right", padx=(20, 0))

        self._acr_content = tk.Frame(p)
        self._acr_content.grid(row=1, column=0, sticky="nsew")
        self._acr_content.columnconfigure(0, weight=1)
        self._acr_content.rowconfigure(1, weight=1)

        self._acr_sbar = tk.Frame(self._acr_content, padx=14)
        self._acr_sbar.grid(row=0, column=0, sticky="ew")
        self._acr_sbar.columnconfigure(1, weight=1)
        self._acr_status_icon = tk.Label(self._acr_sbar, text="●", font=FONT_SMALL)
        self._acr_status_icon.grid(row=0, column=0, padx=(0, 6), pady=6)
        self._acr_status_var = tk.StringVar(value="Sẵn sàng.")
        self._acr_status_lbl = tk.Label(self._acr_sbar, textvariable=self._acr_status_var,
                                         font=FONT_SMALL, anchor="w")
        self._acr_status_lbl.grid(row=0, column=1, sticky="w")
        self._acr_pulse = PulseBar(self._acr_sbar, width=160)
        self._acr_pulse.grid(row=0, column=2, padx=(10, 0), sticky="ew")
        self._acr_dl_btn = tk.Button(self._acr_sbar, text="↓ Download",
                                      font=FONT_BOLD, relief="flat", bd=0,
                                      padx=14, pady=4, cursor="hand2",
                                      command=self._acr_download, state="disabled")
        self._acr_dl_btn.grid(row=0, column=3, padx=(10, 0))
        self._acr_stop_btn = tk.Button(self._acr_sbar, text="■ Stop",
                                        font=FONT_SMALL, relief="flat", bd=0,
                                        padx=8, pady=4, cursor="hand2",
                                        command=self._acr_do_stop, state="disabled")
        self._acr_stop_btn.grid(row=0, column=4, padx=(4, 0))
        self._acr_vscode_btn = tk.Button(self._acr_sbar, text="⎇ Mở VSCode",
                                          font=FONT_BOLD, relief="flat", bd=0,
                                          padx=14, pady=4, cursor="hand2",
                                          state="disabled")
        self._acr_vscode_btn.grid(row=0, column=5, padx=(6, 0))

        self._acr_paned = ttk.PanedWindow(self._acr_content, orient=tk.VERTICAL)
        self._acr_paned.grid(row=1, column=0, sticky="nsew")

        self._acr_tbl = tk.Frame(self._acr_paned)
        self._acr_paned.add(self._acr_tbl, weight=1)
        self._acr_tbl.columnconfigure(0, weight=1)
        self._acr_tbl.rowconfigure(0, weight=1)

        ACR_COLS = ("spec", "subject", "wg_status", "tsg_status", "wg_tdoc",
                    "category", "release", "date", "tsg_tdoc", "work_items", "dl")
        self._acr_tree = ttk.Treeview(self._acr_tbl, columns=ACR_COLS,
                                       show="headings", selectmode="browse")
        col_cfg = [
            ("spec",       "Spec Number",  90,  "center"),
            ("subject",    "Subject",      300, "w"),
            ("wg_status",  "WG Status",    90,  "center"),
            ("tsg_status", "TSG Status",   90,  "center"),
            ("wg_tdoc",    "WG TDoc",      110, "center"),
            ("category",   "Category",     70,  "center"),
            ("release",    "Release",      70,  "center"),
            ("date",       "Date",         80,  "center"),
            ("tsg_tdoc",   "TSG TDoc",     110, "center"),
            ("work_items", "Work Items",   220, "w"),
            ("dl",         "⬇",            36,  "center"),
        ]
        for cid, heading, width, anchor in col_cfg:
            self._acr_tree.heading(cid, text=heading,
                                   command=lambda c=cid: self._acr_sort_by(c))
            self._acr_tree.column(cid, width=width, minwidth=36, anchor=anchor,
                                  stretch=(cid in ("subject", "work_items")))
        self._acr_tree.heading("dl", text="⬇", command=lambda: None)
        self._acr_tree.column("dl",  width=36, minwidth=36, stretch=False)

        self._acr_vsb = SmoothScrollbar(self._acr_tbl, orient="vertical",   command=self._acr_tree.yview)
        self._acr_hsb = SmoothScrollbar(self._acr_tbl, orient="horizontal",  command=self._acr_tree.xview)
        self._acr_tree.configure(yscrollcommand=self._acr_vsb.set, xscrollcommand=self._acr_hsb.set)
        self._acr_tree.grid(row=0, column=0, sticky="nsew")
        self._acr_vsb.grid(row=0, column=1, sticky="ns", padx=(2, 2))
        self._acr_hsb.grid(row=1, column=0, sticky="ew", pady=(2, 2))
        self._acr_tree.bind("<Motion>",          self._acr_tree_motion)
        self._acr_tree.bind("<Leave>",           lambda e: self._acr_tree.config(cursor=""))
        self._acr_tree.bind("<ButtonRelease-1>",  self._acr_tree_click)
        self._acr_copy_menu = self._add_copy_menu(
            self._acr_tree,
            ["Spec Number", "Subject", "WG Status", "TSG Status", "WG TDoc",
             "Category", "Release", "Date", "TSG TDoc", "Work Items", "⬇"])

        self._acr_find = self._make_find_bar(
            self._acr_tbl, self._acr_tree,
            lambda: self._acr_all_rows,
            self._acr_repopulate_row)

        def _acr_find_trace(*_):
            pass  # no filtered-download button to show/hide
        self._acr_find._var.trace_add("write", _acr_find_trace)

        # Log panel
        self._acr_log_toggle_var = tk.BooleanVar(value=False)
        self._acr_log_btn = tk.Checkbutton(self._acr_sbar, text="▾ Log",
                                            variable=self._acr_log_toggle_var,
                                            command=self._acr_toggle_log,
                                            font=FONT_SMALL, indicatoron=False,
                                            relief="flat", highlightthickness=0)
        self._acr_log_btn.grid(row=0, column=6, padx=(8, 0))

        self._acr_log_outer = tk.Frame(self._acr_paned)
        self._acr_log_inner = tk.Frame(self._acr_log_outer)
        self._acr_log_inner.pack(fill="both", expand=True)
        self._acr_log_text  = tk.Text(self._acr_log_inner, height=7, font=FONT_MONO,
                                       relief="flat", bd=0, wrap="word", state="disabled")
        acr_lsb = SmoothScrollbar(self._acr_log_inner, orient="vertical",
                                   command=self._acr_log_text.yview)
        self._acr_log_text.configure(yscrollcommand=acr_lsb.set)
        self._acr_log_text.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=4)
        acr_lsb.pack(side="right", fill="y")
        self._acr_log_lsb = acr_lsb

        self._acr_check_db()

    def _acr_repopulate_row(self, iid, row_data):
        pass  # no extra dicts needed for acr tab

    # ── Tab 3 logic ────────────────────────────────────────────────────────────

    def _acr_check_db(self):
        T = self._T
        if ACR_DB_FILE.exists():
            try:
                conn = sqlite3.connect(str(ACR_DB_FILE))
                n    = conn.execute("SELECT COUNT(*) FROM cr_approved").fetchone()[0]
                conn.close()
                sz_kb = ACR_DB_FILE.stat().st_size // 1024
                age   = (datetime.date.today() -
                         datetime.date.fromtimestamp(ACR_DB_FILE.stat().st_mtime)).days
                self._acr_db_label.config(
                    text=f"DB: {n:,} rows  {sz_kb} KB  ({age}d ago)",
                    fg=T.get("WARN", "#F7A74F") if age > 60 else T.get("FG2", "#9BA3C9"))
            except Exception as e:
                self._acr_db_label.config(text=f"DB error: {e}", fg=T.get("ERROR", "#F75F5F"))
        else:
            self._acr_db_label.config(
                text="DB not found — nhấn ↻ Update DB để tải",
                fg=T.get("WARN", "#F7A74F"))

    def _acr_do_update(self):
        if self._acr_update_running: return
        if not TDOC_FETCH_OK:
            messagebox.showwarning("Thiếu thư viện", "Cần cài:\n  pip install requests beautifulsoup4")
            return
        if not PANDAS_OK:
            messagebox.showwarning("Thiếu thư viện", "Cần cài:\n  pip install pandas openpyxl")
            return
        if not self._acr_log_toggle_var.get():
            self._acr_log_toggle_var.set(True); self._acr_toggle_log()
        self._acr_update_running = True
        self._acr_update_btn.config(state="disabled", text="⏳ Updating...")
        self._acr_pulse.start()
        T = self._T

        def log(msg, color=None): self._acr_log(msg, color)

        def worker():
            try:
                log("═" * 55)
                log("Bắt đầu update 3gpp_cr_approved.db ...")
                n = acr_update_db(log_fn=log)
                def done():
                    self._acr_update_running = False
                    self._acr_update_btn.config(state="normal", text="↻ Update DB")
                    self._acr_pulse.stop()
                    self._acr_check_db()
                    self._acr_set_status(f"Update thành công — {n:,} rows", T["SUCCESS"], T["SUCCESS"])
                    log(f"✅ Hoàn tất! {n:,} approved rows", T["SUCCESS"])
                self.after(0, done)
            except Exception as e:
                def err():
                    self._acr_update_running = False
                    self._acr_update_btn.config(state="normal", text="↻ Update DB")
                    self._acr_pulse.stop()
                    self._acr_set_status(f"Lỗi update: {e}", T["ERROR"], T["ERROR"])
                    log(f"LỖI: {e}", T["ERROR"])
                self.after(0, err)
        threading.Thread(target=worker, daemon=True).start()

    def _acr_set_status(self, msg, color=None, icon_color=None):
        def _do():
            self._acr_status_var.set(msg)
            if icon_color: self._acr_status_icon.config(fg=icon_color)
            if color:      self._acr_status_lbl.config(fg=color)
        self.after(0, _do)

    def _acr_log(self, msg, color=None):
        def _do():
            self._acr_log_text.config(state="normal")
            tag = None
            if color:
                tag = f"col_{color.replace('#', '')}"
                self._acr_log_text.tag_configure(tag, foreground=color)
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self._acr_log_text.insert("end", f"[{ts}] {msg}\n", tag or "")
            self._acr_log_text.see("end")
            self._acr_log_text.config(state="disabled")
        self.after(0, _do)

    def _acr_toggle_log(self):
        if self._acr_log_toggle_var.get():
            self._acr_paned.add(self._acr_log_outer, weight=0)
            def _set_sash(attempt=0):
                try:
                    total = self._acr_paned.winfo_height()
                    if total > 60:
                        self._acr_paned.sashpos(0, max(60, total - 170))
                    elif attempt < 10:
                        self.after(20, lambda: _set_sash(attempt + 1))
                except Exception: pass
            self.after(10, _set_sash)
        else:
            try: self._acr_paned.remove(self._acr_log_outer)
            except Exception: pass

    def _acr_do_search(self, keyword=None):
        query = keyword if keyword is not None else self._acr_query_var.get().strip()
        if keyword is not None:
            self._acr_query_var.set(keyword)
        if not query:
            messagebox.showwarning("Thiếu từ khóa", "Nhập ít nhất 1 từ khóa.")
            return
        if not ACR_DB_FILE.exists():
            messagebox.showerror("Không tìm thấy DB", f"File {ACR_DB_FILE} chưa tồn tại.")
            return
        exact = self._acr_exact_var.get()
        T = self._T
        for iid in self._acr_tree.get_children(): self._acr_tree.delete(iid)
        self._acr_all_rows = []
        self._acr_dl_btn.config(state="disabled")
        self._acr_sort_col = None
        self._acr_set_status("Đang tìm kiếm...", T["WARN"], T["WARN"])
        self._acr_pulse.start()

        def worker():
            try:
                conn    = sqlite3.connect(str(ACR_DB_FILE))
                q_lower = query.lower()
                if exact:
                    all_rows = conn.execute(
                        'SELECT "Spec number","Subject","WG-level status","TSG-level status",'
                        '"WG Tdoc","Category","Release","Date","TSG Tdoc","Work items"'
                        ' FROM cr_approved'
                    ).fetchall()
                    results = []
                    for r in all_rows:
                        subject    = str(r[1] or "").lower()
                        work_items = str(r[9] or "")
                        tokens     = [t.strip().lower() for t in work_items.split(",")]
                        if q_lower in tokens or q_lower == subject.strip():
                            results.append(r)
                else:
                    results = conn.execute(
                        'SELECT "Spec number","Subject","WG-level status","TSG-level status",'
                        '"WG Tdoc","Category","Release","Date","TSG Tdoc","Work items"'
                        ' FROM cr_approved'
                        ' WHERE "Work items" LIKE ? COLLATE NOCASE'
                        '    OR "Subject"    LIKE ? COLLATE NOCASE',
                        (f"%{query}%", f"%{query}%")
                    ).fetchall()
                conn.close()

                def update_ui():
                    T2 = self._T
                    store = []
                    for i, r in enumerate(results):
                        vals = tuple(str(v or "") for v in r) + ("⬇",)
                        iid  = self._acr_tree.insert("", "end", values=vals,
                                                      tags=("odd" if i % 2 else "even",))
                        store.append({"_values": vals})
                    self._acr_all_rows = store
                    n = len(results)
                    self._acr_set_status(
                        f"{n:,} kết quả cho \"{query}\"" + (" (exact)" if exact else ""),
                        T2["FG2"], T2["SUCCESS"])
                    if n > 0: self._acr_dl_btn.config(state="normal")
                    self._acr_pulse.stop()
                self.after(0, update_ui)
            except Exception as e:
                self.after(0, lambda: (
                    self._acr_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"]),
                    self._acr_pulse.stop()))
        threading.Thread(target=worker, daemon=True).start()

    def _acr_sort_by(self, col):
        if self._acr_sort_col == col:
            self._acr_sort_asc = not self._acr_sort_asc
        else:
            self._acr_sort_col = col
            self._acr_sort_asc = True
        items = [(self._acr_tree.set(iid, col), iid)
                 for iid in self._acr_tree.get_children()]
        items.sort(key=lambda x: x[0].lower(), reverse=not self._acr_sort_asc)
        for idx, (_, iid) in enumerate(items):
            self._acr_tree.move(iid, "", idx)
            self._acr_tree.item(iid, tags=("odd" if idx % 2 else "even",))
        col_headings = {
            "spec": "Spec Number", "subject": "Subject", "wg_status": "WG Status",
            "tsg_status": "TSG Status", "wg_tdoc": "WG TDoc", "category": "Category",
            "release": "Release", "date": "Date", "tsg_tdoc": "TSG TDoc",
            "work_items": "Work Items",
        }
        for c, h in col_headings.items():
            arrow = (" ▲" if self._acr_sort_asc else " ▼") if c == col else ""
            self._acr_tree.heading(c, text=h + arrow,
                                   command=lambda cc=c: self._acr_sort_by(cc))
        self._acr_tree.heading("dl", text="⬇", command=lambda: None)

    def _acr_do_stop(self):
        self._acr_stop_event.set()
        self._acr_stop_btn.config(state="disabled", text="⏹ Stopping…")
        self._acr_log("⏹ Yêu cầu dừng — sẽ dừng sau file hiện tại...",
                      self._T.get("WARN", "#F7A74F"))

    def _acr_tree_motion(self, event):
        region   = self._acr_tree.identify_region(event.x, event.y)
        col      = self._acr_tree.identify_column(event.x)
        cols     = list(self._acr_tree["columns"])
        dl_col   = f"#{cols.index('dl') + 1}"
        spec_col = f"#{cols.index('spec') + 1}"
        if region == "cell" and col in (dl_col, spec_col):
            self._acr_tree.config(cursor="hand2")
        else:
            self._acr_tree.config(cursor="")

    def _acr_tree_click(self, event):
        region   = self._acr_tree.identify_region(event.x, event.y)
        col      = self._acr_tree.identify_column(event.x)
        cols     = list(self._acr_tree["columns"])
        dl_col   = f"#{cols.index('dl') + 1}"
        spec_col = f"#{cols.index('spec') + 1}"
        if region == "cell":
            iid = self._acr_tree.identify_row(event.y)
            if iid:
                vals = self._acr_tree.item(iid, "values")
                if col == dl_col:
                    self._acr_single_download(vals)
                elif col == spec_col:
                    spec_num = str(vals[0]).strip()
                    if spec_num:
                        self._spec_search_from_acr(spec_num)

    def _acr_single_download(self, vals):
        if not TDOC_FETCH_OK:
            messagebox.showwarning("Thiếu thư viện", "Cần cài:\n  pip install requests beautifulsoup4")
            return
        wg_tdoc   = str(vals[4]).strip() if len(vals) > 4 else ""
        _tdoc_pat = re.compile(r'[A-Za-z]\d*-\d+')

        def _valid(s):
            return bool(s) and s != "-" and bool(_tdoc_pat.search(s))

        if _valid(wg_tdoc):
            tdoc_id = wg_tdoc
        else:
            messagebox.showwarning("Không có WG TDoc hợp lệ",
                f"WG TDoc: '{wg_tdoc}'\n\nKhông tìm thấy WG TDoc ID hợp lệ.")
            return

        keyword = self._acr_query_var.get().strip()
        safe_kw = re.sub(r'[^\w\-]', '_', keyword).strip('_') or "acr_download"
        out_dir = DOWNLOAD_EXTRACTED_DIR / safe_kw / "Single_download"
        out_dir.mkdir(parents=True, exist_ok=True)
        url = f"https://portal.3gpp.org/ngppapp/DownloadTDoc.aspx?contributionUid={tdoc_id}"
        if not self._acr_log_toggle_var.get():
            self._acr_log_toggle_var.set(True); self._acr_toggle_log()
        T = self._T
        self._acr_pulse.start()
        self._acr_set_status(f"Đang tải {tdoc_id}…", T["WARN"], T["WARN"])
        self._acr_log(f"Single download → {tdoc_id}  →  {out_dir}")

        def worker():
            try:
                import requests as _req
                import urllib3 as _u3
                _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)
                cached_zip = _find_zip_in_cache(tdoc_id)
                if cached_zip:
                    xdir = out_dir / tdoc_id
                    if not xdir.exists(): _extract_zip_to(cached_zip, xdir)
                    fp = cached_zip
                    def done_cached():
                        self._acr_pulse.stop()
                        sz = fp.stat().st_size // 1024
                        self._acr_log(f"✅ {tdoc_id} → {fp.name}  ({sz} KB) [cache hit]", T["SUCCESS"])
                        self._acr_set_status(f"Cache hit: {fp.name}  ({sz} KB)", T["SUCCESS"], T["SUCCESS"])
                    self.after(0, done_cached); return
                sess = _req.Session()
                sess.headers.update({"User-Agent": HDRS["User-Agent"],
                                     "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
                try: sess.get("https://portal.3gpp.org/", timeout=10, verify=False)
                except Exception: pass
                tdoc_info = {"tdoc_number": tdoc_id, "download_url": url}
                fp = _tdoc_download_one(sess, tdoc_info, out_dir)
                def done():
                    self._acr_pulse.stop()
                    if fp:
                        sz = fp.stat().st_size // 1024
                        self._acr_log(f"✅ {tdoc_id} → {fp.name}  ({sz} KB)", T["SUCCESS"])
                        self._acr_set_status(f"Đã tải: {fp.name}  ({sz} KB)", T["SUCCESS"], T["SUCCESS"])
                    else:
                        self._acr_log(f"❌ Không tải được {tdoc_id}", T["ERROR"])
                        self._acr_set_status(f"Lỗi tải {tdoc_id}", T["ERROR"], T["ERROR"])
                self.after(0, done)
            except Exception as e:
                def err():
                    self._acr_pulse.stop()
                    self._acr_log(f"LỖI tải {tdoc_id}: {e}", T["ERROR"])
                    self._acr_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"])
                self.after(0, err)
        threading.Thread(target=worker, daemon=True).start()

    def _acr_download(self):
        """Download tất cả các TDoc đang hiển thị trong bảng (sau filter nếu có)."""
        if self._acr_dl_busy: return
        if not TDOC_FETCH_OK:
            messagebox.showwarning("Thiếu thư viện",
                "Cần cài thêm:\n\npip install requests beautifulsoup4"); return
        _tdoc_pat = re.compile(r'[A-Za-z]\d*-\d+')
        def _valid(s): return bool(s) and s != "-" and bool(_tdoc_pat.search(s))

        # Lấy tất cả rows đang hiển thị trong bảng
        target_rows = []
        for iid in self._acr_tree.get_children():
            vals = self._acr_tree.item(iid, "values")
            if len(vals) < 5: continue
            wg_tdoc = str(vals[4]).strip()
            if _valid(wg_tdoc):
                target_rows.append((wg_tdoc, vals))
        if not target_rows:
            messagebox.showinfo("Không có kết quả",
                "Không có row nào có WG TDoc hợp lệ trong kết quả đang hiển thị.")
            return
        if not self._acr_log_toggle_var.get():
            self._acr_log_toggle_var.set(True); self._acr_toggle_log()
        self._acr_dl_busy = True
        self._acr_stop_event.clear()
        self._acr_dl_btn.config(state="disabled", text="⏳ Downloading...")
        self._acr_stop_btn.config(state="normal")
        self._acr_pulse.start()
        keyword   = self._acr_query_var.get().strip()
        safe_kw   = re.sub(r'[^\w\-]', '_', keyword).strip('_') or "acr_download"
        find_txt  = self._acr_find._var.get().strip()
        safe_find = re.sub(r'[^\w\-]', '_', find_txt).strip('_') if find_txt else ""
        T = self._T
        def log(msg, color=None): self._acr_log(msg, color)

        def worker():
            try:
                import requests as _req
                import urllib3 as _u3
                _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)
                # Download dir: phân thư mục theo filter nếu có
                out_dir = (DOWNLOAD_EXTRACTED_DIR / safe_kw / safe_find
                           if safe_find else DOWNLOAD_EXTRACTED_DIR / safe_kw)
                out_dir.mkdir(parents=True, exist_ok=True)
                proc_out_dir = (DATA_DIR / "outputs" / "summary" / safe_kw / safe_find
                                if safe_find else DATA_DIR / "outputs" / "summary" / safe_kw)
                sess = _req.Session()
                sess.headers.update({"User-Agent": HDRS["User-Agent"],
                                     "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
                try: sess.get("https://portal.3gpp.org/", timeout=10, verify=False)
                except Exception: pass
                downloaded = []; skipped = 0; errors = 0; total = len(target_rows)
                label = f"[{find_txt!r}] " if find_txt else ""
                log(f"Download {label}{total} file(s) → {out_dir}")
                for i, (tdoc_id, vals) in enumerate(target_rows, 1):
                    if self._acr_stop_event.is_set():
                        log(f"⏹ Dừng theo yêu cầu sau {i-1}/{total} file(s).", T["WARN"]); break
                    url = f"https://portal.3gpp.org/ngppapp/DownloadTDoc.aspx?contributionUid={tdoc_id}"
                    tdoc_info = {"tdoc_number": tdoc_id, "download_url": url}
                    cached_zip = _find_zip_in_cache(tdoc_id)
                    if cached_zip:
                        log(f"[{i}/{total}] CACHE {tdoc_id} (zip cache hit)")
                        xdir = out_dir / tdoc_id
                        if not xdir.exists(): _extract_zip_to(cached_zip, xdir, log_fn=log)
                        skipped += 1; downloaded.append(cached_zip); continue
                    existing = next(
                        (out_dir / f"{tdoc_id}{ext}" for ext in ['.doc', '.docx', '.pdf']
                         if (out_dir / f"{tdoc_id}{ext}").exists()), None)
                    if existing and existing.stat().st_size > 500:
                        log(f"[{i}/{total}] SKIP {tdoc_id} (extracted exists)")
                        skipped += 1; downloaded.append(existing); continue
                    fp = _tdoc_download_one(sess, tdoc_info, out_dir)
                    if fp:
                        downloaded.append(fp)
                        log(f"[{i}/{total}] OK   {tdoc_id}  ({fp.stat().st_size//1024} KB)", T["SUCCESS"])
                    else:
                        errors += 1; log(f"[{i}/{total}] FAIL {tdoc_id}", T["ERROR"])
                    time.sleep(0.3)
                if downloaded and not self._acr_stop_event.is_set():
                    log("Đang xử lý / gộp file...", T["WARN"])
                    try:
                        out = tdoc_process(safe_kw, downloaded, log_fn=log,
                                           out_dir=proc_out_dir, extract_dir=out_dir)
                        log(f"Xong → {out}", T["SUCCESS"])
                        _out_dir = out.parent
                        self.after(0, lambda p=_out_dir: (
                            self._acr_vscode_btn.config(
                                state="normal",
                                command=lambda fp=p: self._open_in_vscode(fp)
                            ),
                        ))
                    except Exception as e:
                        log(f"tdoc_process lỗi: {e}", T["ERROR"])
                def finish():
                    self._acr_dl_busy = False
                    self._acr_dl_btn.config(state="normal", text="↓ Download")
                    self._acr_stop_btn.config(state="disabled", text="■ Stop")
                    self._acr_pulse.stop()
                    stopped = self._acr_stop_event.is_set()
                    msg = (f"{'Đã dừng' if stopped else 'Xong'}: {len(downloaded)} tải về, "
                           f"{errors} lỗi, {skipped} bỏ qua → {out_dir}")
                    self._acr_set_status(msg, T["WARN"] if stopped else T["SUCCESS"],
                                              T["WARN"] if stopped else T["SUCCESS"])
                self.after(0, finish)
            except Exception as e:
                log(f"ERROR: {e}", T["ERROR"])
                def err_finish():
                    self._acr_dl_busy = False
                    self._acr_dl_btn.config(state="normal", text="↓ Download")
                    self._acr_stop_btn.config(state="disabled", text="■ Stop")
                    self._acr_pulse.stop()
                    self._acr_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"])
                self.after(0, err_finish)
        threading.Thread(target=worker, daemon=True).start()

    # ── Cross-tab navigation ───────────────────────────────────────────────────

    def _acr_search_from_wi(self, acronym: str):
        """Switch to Acronym Search tab và search cho acronym đã cho."""
        self._notebook.select(self._tab_acr)
        self._acr_exact_var.set(True)
        self._acr_do_search(keyword=acronym)

    def _spec_search_from_acr(self, spec_num: str):
        """Switch to Spec Search tab và search cho spec number đã cho."""
        self._notebook.select(self._tab_spec)
        self._spec_query_var.set(spec_num)
        self._spec_do_search()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 4 — WI Detail / Lookup
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_lookup(self):
        p = self._tab_lk

        bar = tk.Frame(p, padx=18, pady=12)
        bar.grid(row=0, column=0, sticky="ew")
        bar.columnconfigure(1, weight=1)
        self._lk_bar = bar

        self._lk_lbl = tk.Label(bar, text="Workitem ID", font=FONT_BOLD,
                                  width=12, anchor="e")
        self._lk_lbl.grid(row=0, column=0, padx=(0, 8))
        self._lk_query_var = tk.StringVar()
        self._lk_entry = tk.Entry(bar, textvariable=self._lk_query_var,
                                   font=("Consolas", 14), relief="flat", bd=0,
                                   highlightthickness=2, width=20)
        self._lk_entry.grid(row=0, column=1, sticky="w", ipady=7, padx=(0, 10))
        self._lk_entry.bind("<Return>", lambda e: self._lk_do_lookup())
        self._lk_hint = tk.Label(bar, text="Nhập workitem ID ví dụ: 1040027", font=FONT_SMALL)
        self._lk_hint.grid(row=1, column=1, sticky="w", pady=(2, 0))
        self._lk_search_btn = tk.Button(bar, text="Lookup ⏎", font=FONT_BOLD,
                                         relief="flat", bd=0, padx=20, pady=7,
                                         cursor="hand2", command=self._lk_do_lookup)
        self._lk_search_btn.grid(row=0, column=2)

        self._lk_content = tk.Frame(p)
        self._lk_content.grid(row=1, column=0, sticky="nsew")
        self._lk_content.columnconfigure(0, weight=1)
        self._lk_content.rowconfigure(1, weight=1)

        self._lk_sbar = tk.Frame(self._lk_content, padx=14)
        self._lk_sbar.grid(row=0, column=0, sticky="ew")
        self._lk_sbar.columnconfigure(1, weight=1)
        self._lk_status_icon = tk.Label(self._lk_sbar, text="●", font=FONT_SMALL)
        self._lk_status_icon.grid(row=0, column=0, padx=(0, 6), pady=6)
        self._lk_status_var = tk.StringVar(value="Nhập workitem ID và nhấn Lookup.")
        self._lk_status_lbl = tk.Label(self._lk_sbar, textvariable=self._lk_status_var,
                                        font=FONT_SMALL, anchor="w")
        self._lk_status_lbl.grid(row=0, column=1, sticky="ew")
        self._lk_pulse = PulseBar(self._lk_sbar, width=120)
        self._lk_pulse.grid(row=0, column=2, padx=(8, 4), pady=6)
        self._lk_tdoc_btn = tk.Button(self._lk_sbar, text="↓ Download",
                                       font=FONT_BOLD, relief="flat", bd=0,
                                       padx=14, pady=4, cursor="hand2",
                                       command=self._lk_do_tdoc_download, state="disabled")
        self._lk_tdoc_btn.grid(row=0, column=3, padx=(0, 0), sticky="e")
        self._lk_stop_btn = tk.Button(self._lk_sbar, text="■ Stop",
                                       font=FONT_SMALL, relief="flat", bd=0,
                                       padx=8, pady=4, cursor="hand2",
                                       command=self._lk_do_stop, state="disabled")
        self._lk_stop_btn.grid(row=0, column=4, padx=(4, 0), sticky="e")
        self._lk_vscode_btn = tk.Button(self._lk_sbar, text="⎇ Mở VSCode",
                                         font=FONT_BOLD, relief="flat", bd=0,
                                         padx=14, pady=4, cursor="hand2",
                                         state="disabled")
        self._lk_vscode_btn.grid(row=0, column=5, padx=(6, 0), sticky="e")
        self._lk_log_toggle_var = tk.BooleanVar(value=False)
        self._lk_log_btn = tk.Checkbutton(self._lk_sbar, text="▾ Log",
                                           variable=self._lk_log_toggle_var,
                                           command=self._lk_toggle_log,
                                           font=FONT_SMALL, indicatoron=False,
                                           relief="flat", highlightthickness=0)
        self._lk_log_btn.grid(row=0, column=6, padx=(4, 0), sticky="e")

        self._lk_paned = ttk.PanedWindow(self._lk_content, orient=tk.VERTICAL)
        self._lk_paned.grid(row=1, column=0, sticky="nsew")

        detail_outer = tk.Frame(self._lk_paned)
        self._lk_paned.add(detail_outer, weight=1)
        detail_outer.columnconfigure(0, weight=1)
        detail_outer.rowconfigure(0, weight=1)

        self._lk_canvas = tk.Canvas(detail_outer, highlightthickness=0, bd=0)
        lk_vsb = SmoothScrollbar(detail_outer, orient="vertical",
                                  command=self._lk_canvas.yview)
        self._lk_canvas.configure(yscrollcommand=lk_vsb.set)
        self._lk_canvas.grid(row=0, column=0, sticky="nsew")
        lk_vsb.grid(row=0, column=1, sticky="ns", padx=(2, 0))
        self._lk_vsb = lk_vsb

        self._lk_detail_frame = tk.Frame(self._lk_canvas)
        self._lk_canvas_win   = self._lk_canvas.create_window(
            (0, 0), window=self._lk_detail_frame, anchor="nw")
        self._lk_detail_frame.bind("<Configure>", self._lk_on_frame_configure)
        self._lk_canvas.bind("<Configure>",       self._lk_on_canvas_configure)

        self._lk_log_outer = tk.Frame(self._lk_paned)
        self._lk_log_inner = tk.Frame(self._lk_log_outer)
        self._lk_log_inner.pack(fill="both", expand=True)
        self._lk_log_text  = tk.Text(self._lk_log_inner, height=7, font=FONT_MONO,
                                      relief="flat", bd=0, wrap="word", state="disabled")
        lk_lsb = SmoothScrollbar(self._lk_log_inner, orient="vertical",
                                  command=self._lk_log_text.yview)
        self._lk_log_text.configure(yscrollcommand=lk_lsb.set)
        self._lk_log_text.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=4)
        lk_lsb.pack(side="right", fill="y")
        self._lk_log_lsb = lk_lsb

    def _lk_on_frame_configure(self, _=None):
        self._lk_canvas.configure(scrollregion=self._lk_canvas.bbox("all"))

    def _lk_on_canvas_configure(self, event):
        self._lk_canvas.itemconfig(self._lk_canvas_win, width=event.width)

    # ── Tab 4 logic ────────────────────────────────────────────────────────────

    def _lk_set_status(self, msg, color=None, icon_color=None):
        def _do():
            self._lk_status_var.set(msg)
            if icon_color: self._lk_status_icon.config(fg=icon_color)
            if color:      self._lk_status_lbl.config(fg=color)
        self.after(0, _do)

    def _lk_log(self, msg, color=None):
        def _do():
            self._lk_log_text.config(state="normal")
            tag = None
            if color:
                tag = f"col_{color.replace('#', '')}"
                self._lk_log_text.tag_configure(tag, foreground=color)
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            self._lk_log_text.insert("end", f"[{ts}] {msg}\n", tag or "")
            self._lk_log_text.see("end")
            self._lk_log_text.config(state="disabled")
        self.after(0, _do)

    def _lk_toggle_log(self):
        if self._lk_log_toggle_var.get():
            self._lk_paned.add(self._lk_log_outer, weight=0)
            def _set_sash(attempt=0):
                try:
                    total = self._lk_paned.winfo_height()
                    if total > 60:
                        self._lk_paned.sashpos(0, max(60, total - 170))
                    elif attempt < 10:
                        self.after(20, lambda: _set_sash(attempt + 1))
                except Exception: pass
            self.after(10, _set_sash)
        else:
            try: self._lk_paned.remove(self._lk_log_outer)
            except Exception: pass

    def _lk_do_stop(self):
        self._lk_stop_event.set()
        self._lk_stop_btn.config(state="disabled", text="⏹ Stopping…")
        self._lk_log("⏹ Yêu cầu dừng — sẽ dừng sau file hiện tại...",
                     self._T.get("WARN", "#F7A74F"))

    def _lk_do_lookup(self):
        uid = self._lk_query_var.get().strip()
        if not uid:
            messagebox.showwarning("Thiếu ID", "Nhập workitem ID."); return
        for w in self._lk_detail_frame.winfo_children(): w.destroy()
        self._lk_uid = None
        self._lk_tdoc_btn.config(state="disabled")
        T = self._T
        self._lk_set_status("Đang tra cứu...", T["WARN"], T["WARN"])

        def worker():
            T = self._T
            try:
                info_dict = load_workplan_wi_info({uid})
                info      = info_dict.get(uid)
                db_count  = 0
                if DB_FILE.exists():
                    try:
                        conn = sqlite3.connect(str(DB_FILE))
                        db_count = conn.execute(
                            "SELECT COUNT(*) FROM cr_titles WHERE workitem_id=?", (uid,)
                        ).fetchone()[0]
                        conn.close()
                    except Exception:
                        pass

                def update_ui():
                    T2     = self._T
                    BG     = T2["BG"]; FG = T2["FG"]; FG2 = T2["FG2"]
                    ACCENT = T2["ACCENT"]
                    f      = self._lk_detail_frame
                    row_idx = [0]

                    def add_row(label, value, value_color=None):
                        tk.Label(f, text=label, font=FONT_BOLD, bg=BG, fg=ACCENT,
                                  anchor="e", width=22).grid(
                            row=row_idx[0], column=0, sticky="e", padx=(8, 10), pady=4)
                        val_frame = tk.Frame(f, bg=BG)
                        val_frame.grid(row=row_idx[0], column=1, sticky="ew", pady=4)
                        tk.Label(val_frame, text=str(value or "—"), font=FONT_UI,
                                  bg=BG, fg=value_color or FG,
                                  anchor="w", wraplength=600, justify="left").pack(anchor="w")
                        row_idx[0] += 1

                    f.columnconfigure(1, weight=1)
                    tk.Label(f, text=f"Workitem  {uid}", font=("Segoe UI", 13, "bold"),
                              bg=BG, fg=ACCENT).grid(
                        row=0, column=0, columnspan=2, sticky="w", padx=10, pady=(10, 16))
                    row_idx[0] = 1

                    if info:
                        add_row("Name",    info.get("name", ""))
                        add_row("Release", info.get("release", ""))
                        extra = _load_wi_full(uid)
                        if extra:
                            acronym_val = extra.get("code", "")
                            tk.Label(f, text="Acronym", font=FONT_BOLD, bg=BG, fg=ACCENT,
                                      anchor="e", width=22).grid(
                                row=row_idx[0], column=0, sticky="e", padx=(8, 10), pady=4)
                            acr_frame = tk.Frame(f, bg=BG)
                            acr_frame.grid(row=row_idx[0], column=1, sticky="ew", pady=4)
                            if acronym_val:
                                acr_lnk = tk.Label(acr_frame, text=acronym_val, font=FONT_UI,
                                                    bg=BG, fg=T2["LINK"], anchor="w", cursor="hand2")
                                acr_lnk.pack(anchor="w")
                                acr_lnk.bind("<Button-1>",
                                             lambda e, a=acronym_val: self._acr_search_from_wi(a))
                            else:
                                tk.Label(acr_frame, text="—", font=FONT_UI,
                                          bg=BG, fg=FG, anchor="w").pack(anchor="w")
                            row_idx[0] += 1
                            add_row("Completion", extra.get("completion", ""))
                            add_row("Status",     extra.get("status", ""))
                            add_row("Start",      extra.get("start", ""))
                            add_row("Finish",     extra.get("finish", ""))
                            add_row("Impacted TSs/TRs", extra.get("impacted", ""))
                    else:
                        tk.Label(f, text=f"Không tìm thấy workitem {uid} trong workplan.xlsx",
                                  font=FONT_UI, bg=BG, fg=T2["WARN"], anchor="w").grid(
                            row=row_idx[0], column=0, columnspan=2, sticky="w", padx=10)
                        row_idx[0] += 1

                    sep = tk.Frame(f, height=1, bg=T2["BORDER"])
                    sep.grid(row=row_idx[0], column=0, columnspan=2,
                             sticky="ew", pady=10, padx=10)
                    row_idx[0] += 1
                    add_row("CR Titles in DB",
                            f"{db_count:,}  (từ cr_titles.db)",
                            FG2 if db_count == 0 else FG)
                    portal_url = f"{PORTAL_BASE}/ChangeRequests.aspx?q=1&workitem={uid}"
                    lf = tk.Frame(f, bg=BG)
                    lf.grid(row=row_idx[0], column=0, columnspan=2, sticky="w", padx=10, pady=8)
                    tk.Button(lf, text="🔗 Mở Portal 3GPP", font=FONT_UI,
                               relief="flat", bd=0, padx=12, pady=4, cursor="hand2",
                               bg=T2["ACCENT"], fg="white",
                               activebackground=T2["ACCENT"],
                               command=lambda: webbrowser.open(portal_url)).pack(side="left")

                    self._lk_uid = uid
                    self._lk_tdoc_btn.config(state="normal")
                    self._lk_set_status(f"Workitem {uid} — tải xong", FG2, T2["SUCCESS"])
                    self._lk_on_frame_configure()

                self.after(0, update_ui)
            except Exception as e:
                T = self._T
                self._lk_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"])
        threading.Thread(target=worker, daemon=True).start()

    def _lk_do_tdoc_download(self):
        uid = self._lk_uid
        if not uid or self._lk_tdoc_busy: return
        if not TDOC_FETCH_OK:
            messagebox.showwarning("Thiếu thư viện", "pip install requests beautifulsoup4")
            return
        self._lk_tdoc_busy = True
        self._lk_stop_event.clear()
        self._lk_tdoc_btn.config(state="disabled", text="⏳ Downloading...")
        self._lk_stop_btn.config(state="normal")
        self._lk_pulse.start()
        if not self._lk_log_toggle_var.get():
            self._lk_log_toggle_var.set(True); self._lk_toggle_log()
        T = self._T

        def worker():
            def log(msg, color=None): self._lk_log(msg, color)
            try:
                downloaded, skipped, errors, extract_dir = tdoc_fetch_smart(
                    uid, log_fn=log, stop_event=self._lk_stop_event)
                n = len(downloaded)
                log(f"WI {uid}: {n} file(s) (skip {skipped}, lỗi {errors})", T["SUCCESS"])
                if downloaded and not self._lk_stop_event.is_set():
                    out = tdoc_process(uid, downloaded, log_fn=log, extract_dir=extract_dir)
                    log(f"Xong → {out}", T["SUCCESS"])
                    _out_dir = out.parent
                    self.after(0, lambda p=_out_dir: (
                        self._lk_vscode_btn.config(
                            state="normal",
                            command=lambda fp=p: self._open_in_vscode(fp)
                        ),
                    ))
                self._lk_set_status(f"Done — {n} file(s)", T["SUCCESS"], T["SUCCESS"])
            except NoCRFound:
                log(f"WI {uid}: Không có Change Request nào", T["WARN"])
                self._lk_set_status("Không có CR", T["WARN"], T["WARN"])
            except NoAgreedTDocs:
                log(f"WI {uid}: Không có TDoc nào", T["WARN"])
                self._lk_set_status("Không có TDoc", T["WARN"], T["WARN"])
            except Exception as e:
                log(f"ERROR: {e}", T["ERROR"])
                self._lk_set_status(f"Lỗi: {e}", T["ERROR"], T["ERROR"])
            finally:
                self._lk_tdoc_busy = False
                self.after(0, lambda: (
                    self._lk_tdoc_btn.config(state="normal", text="↓ Download"),
                    self._lk_stop_btn.config(state="disabled", text="■ Stop"),
                    self._lk_pulse.stop()))
        threading.Thread(target=worker, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 5 — Spec Search
    # ══════════════════════════════════════════════════════════════════════════

    def _build_tab_spec(self):
        p = self._tab_spec
        p.rowconfigure(1, weight=1)

        self._spec_bar = tk.Frame(p, padx=18, pady=12)
        self._spec_bar.grid(row=0, column=0, sticky="ew")
        self._spec_bar.columnconfigure(1, weight=1)

        self._spec_lbl_kw = tk.Label(self._spec_bar, text="Spec Number",
                                      font=FONT_BOLD, width=12, anchor="e")
        self._spec_lbl_kw.grid(row=0, column=0, padx=(0, 8))
        self._spec_query_var   = tk.StringVar()
        self._spec_query_entry = tk.Entry(self._spec_bar, textvariable=self._spec_query_var,
                                           font=("Consolas", 12), relief="flat", bd=0,
                                           highlightthickness=2)
        self._spec_query_entry.grid(row=0, column=1, sticky="ew", ipady=7, padx=(0, 10))
        self._spec_query_entry.bind("<Return>", lambda e: self._spec_do_search())
        self._spec_search_btn = tk.Button(self._spec_bar, text="Search ⏎", font=FONT_BOLD,
                                           relief="flat", bd=0, padx=20, pady=7,
                                           cursor="hand2", command=self._spec_do_search)
        self._spec_search_btn.grid(row=0, column=2)
        self._spec_lbl_hint = tk.Label(
            self._spec_bar,
            text="Nhập số spec ví dụ: 29.513  →  tra cứu trên whatthespec.net",
            font=FONT_SMALL)
        self._spec_lbl_hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self._spec_content = tk.Frame(p)
        self._spec_content.grid(row=1, column=0, sticky="nsew")
        self._spec_content.columnconfigure(0, weight=1)
        self._spec_content.rowconfigure(0, weight=1)

        spec_outer = tk.Frame(self._spec_content)
        spec_outer.grid(row=0, column=0, sticky="nsew", padx=24, pady=16)
        spec_outer.columnconfigure(0, weight=1)
        spec_outer.rowconfigure(0, weight=1)

        self._spec_canvas = tk.Canvas(spec_outer, highlightthickness=0, bd=0,
                                       bg=self._T["BG"])
        spec_vsb = tk.Scrollbar(spec_outer, orient="vertical", command=self._spec_canvas.yview)
        self._spec_canvas.configure(yscrollcommand=spec_vsb.set)
        self._spec_canvas.grid(row=0, column=0, sticky="nsew")
        spec_vsb.grid(row=0, column=1, sticky="ns")

        self._spec_card_frame = tk.Frame(self._spec_canvas, bg=self._T["BG"])
        self._spec_canvas_win = self._spec_canvas.create_window(
            (0, 0), window=self._spec_card_frame, anchor="nw")
        self._spec_card_frame.bind(
            "<Configure>",
            lambda e: self._spec_canvas.configure(
                scrollregion=self._spec_canvas.bbox("all")))
        self._spec_canvas.bind(
            "<Configure>",
            lambda e: self._spec_canvas.itemconfig(self._spec_canvas_win, width=e.width))

        self._spec_status_lbl = tk.Label(self._spec_content, text="",
                                          font=FONT_SMALL, anchor="w")
        self._spec_status_lbl.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 8))

    # ── Tab 5 logic ────────────────────────────────────────────────────────────

    def _spec_do_search(self):
        q = self._spec_query_var.get().strip()
        if not q:
            messagebox.showwarning("Thiếu số spec", "Nhập số spec ví dụ: 29.513"); return
        if not TDOC_FETCH_OK:
            messagebox.showwarning("Thiếu thư viện", "Cần cài:\n  pip install requests beautifulsoup4")
            return
        T = self._T
        self._spec_status_lbl.config(text=f"Đang tìm {q} …", fg=T.get("WARN", "#F7A74F"))
        self._spec_search_btn.config(state="disabled", text="⏳ …")
        for w in self._spec_card_frame.winfo_children(): w.destroy()

        def _parse_exact_match(html_text, spec_num):
            """
            Iterate tất cả <tr>, trả về row khớp chính xác spec_num.
            Tốt hơn cách cũ (lấy first_tr) vì tránh nhầm khi có nhiều kết quả.
            """
            from bs4 import BeautifulSoup
            soup  = BeautifulSoup(html_text, "html.parser")
            table = soup.find("table", id="3gppresults")
            if not table:
                return None
            tbody = table.find("tbody")
            rows  = tbody.find_all("tr") if tbody else [
                r for r in table.find_all("tr") if not r.find("th")
            ]
            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                spec_a    = tds[0].find("a")
                cell_text = spec_a.get_text(strip=True) if spec_a else tds[0].get_text(strip=True)
                if cell_text != spec_num:
                    continue
                return {
                    "spec_num":   cell_text,
                    "spec_link":  spec_a["href"] if spec_a and spec_a.get("href") else "",
                    "title":      tds[1].get_text(strip=True),
                    "wg":         tds[3].get_text(strip=True) if len(tds) > 3 else "",
                    "from_cache": False,
                }
            return None

        def _query_ts_info_db(spec_num):
            """Fallback: tra cứu title + WG trong ts_info.db tại .cache folder."""
            import sqlite3 as _sql
            ts_db = config.CACHE_DIR / "ts_info.db"
            if not ts_db.exists():
                return None
            try:
                conn = _sql.connect(str(ts_db))
                row  = conn.execute(
                    "SELECT spec_number, title, wg FROM ts_info WHERE spec_number = ?",
                    (spec_num,)
                ).fetchone()
                conn.close()
                if row and (row[1] or row[2]):          # có ít nhất title hoặc wg
                    return {
                        "spec_num":   row[0],
                        "spec_link":  "",
                        "title":      row[1] or "",
                        "wg":         row[2] or "",
                        "from_cache": True,
                    }
            except Exception:
                pass
            return None

        def worker():
            result     = None
            net_error  = None
            source_url = f"https://whatthespec.net/3gpp/spec.php?q={q}"

            # ── 1. Thử fetch từ network ──────────────────────────────────────
            try:
                import requests as _req
                import urllib3 as _u3
                _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)
                resp = _req.get(source_url, timeout=20,
                                headers={"User-Agent": HDRS["User-Agent"]},
                                verify=False)
                resp.raise_for_status()
                result = _parse_exact_match(resp.text, q)
                if result:
                    result["source_url"] = source_url
            except Exception as exc:
                net_error = str(exc)

            # ── 2. Fallback sang ts_info.db nếu network thất bại ────────────
            if result is None and net_error:
                result = _query_ts_info_db(q)
                if result:
                    result["source_url"] = source_url   # vẫn giữ URL để mở web

            def update_ui():
                T2     = self._T
                BG     = T2["BG"];    BG2    = T2["BG2"]; BG3 = T2["BG3"]
                FG     = T2["FG"];    FG2    = T2["FG2"]
                ACCENT = T2["ACCENT"]; LINK  = T2["LINK"]
                WARN   = T2.get("WARN",    "#F7A74F")
                ERROR  = T2.get("ERROR",   "#F75F5F")
                SUCCESS= T2.get("SUCCESS", "#2DD4A5")

                self._spec_canvas.configure(bg=BG)
                self._spec_card_frame.configure(bg=BG)
                self._spec_search_btn.config(state="normal", text="Search ⏎")

                if result is None:
                    # Không tìm thấy cả network lẫn cache
                    if net_error:
                        status_text = f"Lỗi mạng: {net_error[:80]} — không có trong cache"
                        status_fg   = ERROR
                    else:
                        status_text = f"Không tìm thấy spec \"{q}\" trên whatthespec.net"
                        status_fg   = WARN
                    self._spec_status_lbl.config(text=status_text, fg=status_fg)
                    tk.Label(self._spec_card_frame,
                             text=f"Không có kết quả cho \"{q}\".",
                             font=FONT_UI, bg=BG, fg=FG2).pack(anchor="w", pady=8)
                    return

                # ── Hiển thị kết quả ────────────────────────────────────────
                from_cache = result.get("from_cache", False)
                if from_cache:
                    status_text = f"Tìm thấy trong cache: {result['spec_num']}  (offline)"
                    status_fg   = WARN
                else:
                    status_text = f"Tìm thấy: {result['spec_num']}"
                    status_fg   = SUCCESS
                self._spec_status_lbl.config(text=status_text, fg=status_fg)

                card = tk.Frame(self._spec_card_frame, bg=BG2,
                                relief="flat", bd=0, padx=24, pady=20)
                card.pack(fill="x", padx=4, pady=4)
                card.columnconfigure(1, weight=1)

                def add_row(label, value_widget_fn, row):
                    tk.Label(card, text=label, font=FONT_BOLD, bg=BG2, fg=ACCENT,
                             anchor="e", width=14).grid(
                        row=row, column=0, sticky="e", padx=(0, 14), pady=6)
                    value_widget_fn(card, row)

                def spec_val(parent, row):
                    f = tk.Frame(parent, bg=BG2)
                    f.grid(row=row, column=1, sticky="ew", pady=6)
                    fg_spec = LINK if result["spec_link"] else FG
                    cur_spec = "hand2" if result["spec_link"] else ""
                    lnk = tk.Label(f, text=result["spec_num"],
                                   font=("Segoe UI", 13, "bold"),
                                   bg=BG2, fg=fg_spec, cursor=cur_spec, anchor="w")
                    lnk.pack(side="left")
                    if result["spec_link"]:
                        lnk.bind("<Button-1>",
                                 lambda e, u=result["spec_link"]: webbrowser.open(u))
                    if from_cache:
                        tk.Label(f, text="  📦 từ cache",
                                 font=FONT_SMALL, bg=BG2, fg=WARN).pack(side="left")
                add_row("Spec", spec_val, 0)

                def title_val(parent, row):
                    text = result["title"] if result["title"] else "(không có)"
                    tk.Label(parent, text=text,
                             font=("Segoe UI", 11), bg=BG2,
                             fg=FG if result["title"] else FG2,
                             anchor="w", wraplength=700, justify="left").grid(
                        row=row, column=1, sticky="ew", pady=6)
                add_row("Title", title_val, 1)

                if result["wg"]:
                    def wg_val(parent, row):
                        tk.Label(parent, text=result["wg"],
                                 font=FONT_UI, bg=BG2, fg=FG, anchor="w").grid(
                            row=row, column=1, sticky="w", pady=6)
                    add_row("WG", wg_val, 2)

                # Buttons — chỉ hiện nếu có link (network result)
                if result["spec_link"] or not from_cache:
                    btn_f = tk.Frame(card, bg=BG2)
                    btn_f.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
                    if result["spec_link"]:
                        tk.Button(btn_f, text="🔗 Mở trang 3GPP Spec",
                                  font=FONT_UI, relief="flat", bd=0, padx=14, pady=5,
                                  cursor="hand2", bg=ACCENT, fg="white",
                                  activebackground=ACCENT,
                                  command=lambda u=result["spec_link"]: webbrowser.open(u)
                                  ).pack(side="left", padx=(0, 10))
                    tk.Button(btn_f, text="🌐 Mở whatthespec.net",
                              font=FONT_UI, relief="flat", bd=0, padx=14, pady=5,
                              cursor="hand2", bg=BG3, fg=FG,
                              activebackground=ACCENT, activeforeground="white",
                              command=lambda u=result["source_url"]: webbrowser.open(u)
                              ).pack(side="left")

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()
