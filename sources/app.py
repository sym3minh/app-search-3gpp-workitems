"""
app.py — Entry point + theme engine.

class App(tk.Tk, TabsMixin):
    - __init__: khởi tạo state, build UI, apply theme, bind shortcuts
    - _build_ui: header bar + ttk.Notebook + 5 tab frames
    - _apply_theme: ~130 dòng gán màu cho toàn bộ widget
    - _toggle_theme / _on_ctrl_f / _t

Import: config, ui_tabs.TabsMixin
"""

import tkinter as tk
from tkinter import ttk
import threading

from config import (
    THEMES, FONT_BOLD, FONT_H1, FONT_SMALL, FONT_UI, FONT_MONO,
    CACHE_FILE,
)
from ui_tabs import TabsMixin
from ui_tabs_rag import ClusterTabsMixin


class App(tk.Tk, TabsMixin, ClusterTabsMixin):

    def __init__(self):
        super().__init__()
        self.title("3GPP Search Tool")
        self.geometry("1200x800")
        self.minsize(900, 640)

        self._theme_name = "dark"
        self._T          = THEMES["dark"].copy()

        # ── Tab 1 state ─────────────────────────────────────────────────────
        self._wi_last_output    = None
        self._wi_last_tdoc_dir  = None
        self._wi_running        = False
        self._wi_item_links     = {}
        self._wi_tdoc_status    = {}
        self._wi_tdoc_busy      = set()
        self._wi_all_items      = []
        self._wi_pending_export = None

        # ── Tab 2 state ─────────────────────────────────────────────────────
        self._cr_last_output    = None
        self._cr_running        = False
        self._cr_row_urls       = {}
        self._cr_dl_urls        = {}
        self._cr_dl_busy        = set()
        self._cr_all_rows       = []
        self._cr_pending_export = None

        # ── Tab 3 (ACR) state ────────────────────────────────────────────────
        self._acr_all_rows       = []
        self._acr_sort_col       = None
        self._acr_sort_asc       = True
        self._acr_dl_busy        = False
        self._acr_last_tdoc_dir  = None
        self._acr_update_running = False
        self._acr_stop_event     = threading.Event()

        # ── Tab 4 (LK / WI Detail) state ────────────────────────────────────
        self._lk_tdoc_busy      = False
        self._lk_uid            = None
        self._lk_last_tdoc_dir  = None
        self._lk_stop_event     = threading.Event()

        # ── Tab 6 (Clustering) state ─────────────────────────────────────────
        self._cl_running    = False
        self._cl_stop_event = threading.Event()

        # ── Build UI ─────────────────────────────────────────────────────────
        self._build_ui()
        self._apply_theme()
        self._wi_check_cache_status()
        self._cr_check_db_status()

        # Global Ctrl+F — delegate to active tab's find bar
        self.bind_all("<Control-f>", self._on_ctrl_f)
        self.bind_all("<Control-F>", self._on_ctrl_f)

    # ══════════════════════════════════════════════════════════════════════════
    # Global UI skeleton
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ── Header ───────────────────────────────────────────────────────────
        self._top = tk.Frame(self, padx=18, pady=8)
        self._top.grid(row=0, column=0, sticky="ew")
        self._top.columnconfigure(2, weight=1)

        self._lbl_brand = tk.Label(self._top, text="3GPP",
                                    font=("Segoe UI", 18, "bold"))
        self._lbl_brand.grid(row=0, column=0, sticky="w")

        self._lbl_title = tk.Label(self._top, text=" Search Tool", font=FONT_H1)
        self._lbl_title.grid(row=0, column=1, sticky="w")

        self._theme_btn = tk.Button(
            self._top, text="☀  Light", font=FONT_SMALL,
            relief="flat", bd=0, padx=10, pady=3,
            cursor="hand2", command=self._toggle_theme)
        self._theme_btn.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self._wi_cache_label = tk.Label(self._top, text="", font=FONT_SMALL)
        self._wi_cache_label.grid(row=0, column=3, sticky="e", padx=(0, 8))

        self._wi_update_btn = tk.Button(
            self._top, text="↻ Update WorkPlan",
            font=FONT_SMALL, relief="flat", bd=0,
            padx=8, pady=4, cursor="hand2",
            command=self._wi_do_update)
        self._wi_update_btn.grid(row=0, column=4, sticky="e")

        # ── Notebook + 6 tab frames ──────────────────────────────────────────
        self._notebook = ttk.Notebook(self)
        self._notebook.grid(row=1, column=0, sticky="nsew")

        for attr, label in [
            ("_tab_wi",   "  Work Item Search  "),
            ("_tab_cr",   "  Advanced Search (CR Titles)  "),
            ("_tab_acr",  "  Acronym Search  "),
            ("_tab_lk",   "  WI Detail  "),
            ("_tab_spec", "  Spec Search  "),
            ("_tab_cl",   "  CR Clustering  "),
        ]:
            f = tk.Frame(self._notebook)
            f.columnconfigure(0, weight=1)
            f.rowconfigure(1, weight=1)
            setattr(self, attr, f)
            self._notebook.add(f, text=label)

        self._build_tab_wi()
        self._build_tab_cr()
        self._build_tab_acr()
        self._build_tab_lookup()
        self._build_tab_spec()
        self._build_tab_cluster()

    # ══════════════════════════════════════════════════════════════════════════
    # Theme engine
    # ══════════════════════════════════════════════════════════════════════════

    def _toggle_theme(self):
        self._theme_name = "light" if self._theme_name == "dark" else "dark"
        self._T          = THEMES[self._theme_name].copy()
        self._apply_theme()
        self._theme_btn.config(
            text="🌙 Dark" if self._theme_name == "light" else "☀  Light")

    def _apply_theme(self):
        T      = self._T
        BG     = T["BG"];     BG2    = T["BG2"];    BG3     = T["BG3"]
        ACCENT = T["ACCENT"]; SUCCESS = T["SUCCESS"]
        FG     = T["FG"];     FG2    = T["FG2"];    BORDER  = T["BORDER"]
        LINK   = T["LINK"]
        SBG    = T["SCROLLBG"]; SFG = T["SCROLLFG"]; SHO   = T["SCROLLHO"]
        WARN   = T["WARN"];   ERROR  = T["ERROR"]

        self.configure(bg=BG)

        # ── Frames: BG ───────────────────────────────────────────────────────
        for w in [
            self._top, self._tab_wi, self._tab_cr, self._tab_acr,
            self._tab_lk, self._tab_spec, self._tab_cl,
            self._wi_bar, self._wi_opts, self._wi_content,
            self._wi_sbar, self._wi_tbl,
            self._wi_log_outer, self._wi_log_inner,
            self._cr_bar, self._cr_opts, self._cr_content,
            self._cr_sbar, self._cr_tbl,
            self._acr_bar, self._acr_opts, self._acr_content,
            self._acr_sbar, self._acr_tbl,
            self._acr_log_outer, self._acr_log_inner,
            self._spec_bar, self._spec_content,
            self._lk_bar, self._lk_content,
            self._lk_sbar, self._lk_log_outer, self._lk_log_inner,
        ]:
            try: w.configure(bg=BG)
            except Exception: pass

        # ── Frames: BG2 (bar/sbar/log panels) ───────────────────────────────
        for w in [
            self._wi_bar, self._wi_opts, self._wi_sbar,
            self._wi_log_outer, self._wi_log_inner,
            self._cr_bar, self._cr_opts, self._cr_sbar,
            self._acr_bar, self._acr_opts, self._acr_sbar,
            self._acr_log_outer, self._acr_log_inner,
            self._spec_bar,
            self._lk_bar, self._lk_sbar,
            self._lk_log_outer, self._lk_log_inner,
        ]:
            try: w.configure(bg=BG2)
            except Exception: pass

        # inner children of log frames
        for outer in (self._wi_log_outer, self._lk_log_outer,
                      self._acr_log_outer):
            for child in outer.winfo_children():
                try: child.configure(bg=BG2)
                except Exception: pass

        self._lk_canvas.configure(bg=BG)
        self._lk_detail_frame.configure(bg=BG)
        self._spec_canvas.configure(bg=BG)
        self._spec_card_frame.configure(bg=BG)

        # ── Labels ───────────────────────────────────────────────────────────
        for lbl, bg, fg in [
            (self._lbl_brand,        BG,  ACCENT),
            (self._lbl_title,        BG,  FG),
            (self._wi_cache_label,   BG,  FG2),
            (self._wi_lbl_kw,        BG2, FG2),
            (self._wi_lbl_hint,      BG2, FG2),
            (self._wi_lbl_rel,       BG2, FG2),
            (self._wi_lbl_lim,       BG2, FG2),
            (self._wi_status_icon,   BG2, SUCCESS),
            (self._wi_status_lbl,    BG2, FG2),
            (self._cr_lbl_kw,        BG2, FG2),
            (self._cr_lbl_hint,      BG2, FG2),
            (self._cr_lbl_lim,       BG2, FG2),
            (self._cr_db_label,      BG2, FG2),
            (self._cr_status_icon,   BG2, SUCCESS),
            (self._cr_status_lbl,    BG2, FG2),
            (self._acr_lbl_kw,       BG2, FG2),
            (self._acr_lbl_hint,     BG2, FG2),
            (self._acr_db_label,     BG2, FG2),
            (self._acr_status_icon,  BG2, SUCCESS),
            (self._acr_status_lbl,   BG2, FG2),
            (self._spec_lbl_kw,      BG2, FG2),
            (self._spec_lbl_hint,    BG2, FG2),
            (self._spec_status_lbl,  BG,  FG2),
            (self._lk_lbl,           BG2, FG2),
            (self._lk_hint,          BG2, FG2),
            (self._lk_status_icon,   BG2, SUCCESS),
            (self._lk_status_lbl,    BG2, FG2),
        ]:
            lbl.configure(bg=bg, fg=fg)

        # ── Recursive retheme for dynamic panels (WI Detail + Spec Search) ──
        def _retheme_tree(widget, default_bg):
            for child in widget.winfo_children():
                cls = child.winfo_class()
                try:
                    if cls == "Frame":
                        try:
                            child.configure(
                                bg=BG2 if child.cget("padx") else default_bg)
                        except Exception:
                            child.configure(bg=default_bg)
                    elif cls == "Label":
                        try:
                            is_bold = "bold" in str(child.cget("font"))
                            cur_fg  = child.cget("fg")
                            if cur_fg == LINK:  new_fg = LINK
                            elif is_bold:       new_fg = ACCENT
                            else:               new_fg = FG
                            child.configure(bg=default_bg, fg=new_fg)
                        except Exception:
                            pass
                    elif cls == "Button":
                        pass  # preserve button colours set elsewhere
                    else:
                        try: child.configure(bg=default_bg)
                        except Exception: pass
                except Exception:
                    pass
                _retheme_tree(child, default_bg)

        _retheme_tree(self._lk_detail_frame, BG)
        _retheme_tree(self._spec_card_frame,  BG)

        # ── Entries ──────────────────────────────────────────────────────────
        for e in [
            self._wi_query_entry, self._wi_lim_entry,
            self._cr_query_entry, self._cr_lim_entry,
            self._acr_query_entry,
            self._spec_query_entry,
            self._lk_entry,
        ]:
            e.configure(bg=BG3, fg=FG, insertbackground=ACCENT,
                        highlightcolor=ACCENT, highlightbackground=BORDER)

        # ── Buttons ──────────────────────────────────────────────────────────
        self._theme_btn.configure(
            bg=BG3, fg=FG2,
            activebackground=ACCENT, activeforeground="white")
        self._wi_update_btn.configure(
            bg=BG3, fg=FG2,
            activebackground=ACCENT, activeforeground="white")
        self._acr_update_btn.configure(
            bg=BG3, fg=FG2,
            activebackground=ACCENT, activeforeground="white")

        for btn in [self._wi_search_btn, self._cr_search_btn,
                    self._acr_search_btn, self._spec_search_btn,
                    self._lk_search_btn]:
            btn.configure(bg=ACCENT, fg="white", activebackground=ACCENT)

        for btn in [self._wi_open_btn, self._cr_open_btn]:
            btn.configure(bg=SUCCESS, fg="white",
                          activebackground=SUCCESS, disabledforeground=FG2)

        for btn in [self._wi_vscode_btn, self._lk_vscode_btn, self._acr_vscode_btn]:
            btn.configure(bg=BG3, fg=FG2,
                          activebackground=ACCENT, activeforeground="white",
                          disabledforeground=FG2)

        self._acr_dl_btn.configure(
            bg=WARN, fg=BG, activebackground=WARN,
            disabledforeground=FG2)
        self._acr_stop_btn.configure(
            bg=ERROR, fg="white",
            activebackground=ERROR, disabledforeground=FG2)
        self._lk_stop_btn.configure(
            bg=ERROR, fg="white",
            activebackground=ERROR, disabledforeground=FG2)
        self._lk_tdoc_btn.configure(
            bg=WARN, fg=BG, activebackground=WARN,
            disabledforeground=FG2)

        # ── Checkbuttons ─────────────────────────────────────────────────────
        for cb in self._wi_check_widgets + [self._cr_wi_only_cb,
                                             self._acr_exact_cb]:
            cb.configure(bg=BG2, fg=FG2,
                         activebackground=BG2, activeforeground=FG,
                         selectcolor=BG3)
        for cb in [self._wi_log_btn, self._acr_log_btn, self._lk_log_btn]:
            cb.configure(bg=BG2, fg=FG2,
                         activebackground=BG2, activeforeground=FG,
                         selectcolor=BG2)

        # ── Log Text widgets ─────────────────────────────────────────────────
        self._wi_log_text.configure(bg=BG2, fg=FG2, insertbackground=FG)
        self._acr_log_text.configure(bg=BG2, fg=FG2, insertbackground=FG)
        self._lk_log_text.configure(bg=BG2, fg=FG2, insertbackground=FG)

        # ── PulseBars ────────────────────────────────────────────────────────
        self._wi_pulse.retheme(BG2, ACCENT)
        self._cr_pulse.retheme(BG2, ACCENT)
        self._acr_pulse.retheme(BG2, ACCENT)
        self._lk_pulse.retheme(BG2, ACCENT)

        # ── Scrollbars ───────────────────────────────────────────────────────
        for sb in [
            self._wi_vsb,  self._wi_hsb,  self._wi_log_lsb,
            self._cr_vsb,  self._cr_hsb,
            self._acr_vsb, self._acr_hsb, self._acr_log_lsb,
            self._lk_vsb,  self._lk_log_lsb,
        ]:
            sb.retheme(SBG, SFG, SHO)

        # ── Find bars & copy menus ────────────────────────────────────────────
        self._retheme_find_bar(self._wi_find,  T)
        self._retheme_find_bar(self._cr_find,  T)
        self._retheme_find_bar(self._acr_find, T)
        self._retheme_copy_menu(self._wi_copy_menu,  T)
        self._retheme_copy_menu(self._cr_copy_menu,  T)
        self._retheme_copy_menu(self._acr_copy_menu, T)

        # ── ttk.Style ────────────────────────────────────────────────────────
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",
                         background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",
                         background=T["TAB_BG"], foreground=FG2,
                         padding=[14, 6], font=FONT_BOLD, borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", T["TAB_SEL"]), ("active", BG3)],
                  foreground=[("selected", ACCENT),       ("active", FG)],
                  padding=[("selected", [14, 6]),          ("!selected", [14, 6])])
        style.configure("Treeview",
                         background=BG2, foreground=FG, rowheight=26,
                         fieldbackground=BG2, bordercolor=BORDER, borderwidth=0)
        style.configure("Treeview.Heading",
                         background=BG3, foreground=FG2,
                         relief="flat", font=FONT_BOLD)
        style.map("Treeview",
                  background=[("selected", BG3)],
                  foreground=[("selected", ACCENT)])
        style.map("TCombobox",
                  fieldbackground=[("readonly", BG3)],
                  background=[("readonly", BG3)],
                  foreground=[("readonly", FG)],
                  selectbackground=[("readonly", BG3)],
                  selectforeground=[("readonly", FG)])

        # ── Tree row tags ─────────────────────────────────────────────────────
        for tree in [self._wi_tree, self._cr_tree, self._acr_tree]:
            tree.tag_configure("link",    foreground=LINK)
            tree.tag_configure("odd",     background=BG2)
            tree.tag_configure("even",    background=BG)
            tree.tag_configure("dl_busy", foreground=WARN)
            tree.tag_configure("dl_done", foreground=SUCCESS)

        # Restripe existing rows after theme change
        for i, iid in enumerate(self._wi_tree.get_children()):
            self._wi_tree.item(iid, tags=("odd" if i % 2 else "even",))
        for i, iid in enumerate(self._cr_tree.get_children()):
            self._cr_tree.item(iid, tags=("odd" if i % 2 else "even",))
        for i, iid in enumerate(self._acr_tree.get_children()):
            self._acr_tree.item(iid, tags=("odd" if i % 2 else "even",))

        # ── Tab 6 — CR Clustering ─────────────────────────────────────────────
        self._cl_apply_theme()

    # ══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _on_ctrl_f(self, event=None):
        """Show the find bar for whichever tab is currently visible."""
        tab = self._notebook.select()
        if tab == str(self._tab_wi):
            self._wi_find._show()
        elif tab == str(self._tab_cr):
            self._cr_find._show()
        elif tab == str(self._tab_acr):
            self._acr_find._show()

    def _t(self, k):
        return self._T[k]


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
