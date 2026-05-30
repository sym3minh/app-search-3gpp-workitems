"""
widgets.py — Custom tkinter widgets tái sử dụng.

Import: config
Không phụ thuộc bất kỳ business logic nào.
"""

import tkinter as tk
from config import FONT_UI, FONT_SMALL


# ══════════════════════════════════════════════════════════════════════════════
# SmoothScrollbar
# ══════════════════════════════════════════════════════════════════════════════

class SmoothScrollbar(tk.Canvas):
    """
    Thay thế ttk.Scrollbar — thumb bo tròn, hover highlight, drag mượt.
    API tương thích: .set(first, last), nhận command=tree.yview.
    .retheme(bg, fg, hover_fg) — áp dụng màu mới khi toggle theme.
    """
    THICKNESS = 10
    RADIUS    = 5
    MIN_THUMB = 28

    def __init__(self, master, orient="vertical", command=None,
                 bg="#1A1D27", fg="#3A3F5C", hover_fg="#4F8EF7", **kw):
        if orient == "vertical":
            kw.setdefault("width", self.THICKNESS + 4)
        else:
            kw.setdefault("height", self.THICKNESS + 4)
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kw)
        self._orient   = orient
        self._command  = command
        self._bg       = bg
        self._fg       = fg
        self._hfg      = hover_fg
        self._pos      = (0.0, 1.0)
        self._dragging = False
        self._drag_start = None
        self._hovering   = False

        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<B1-Motion>",       self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>",           lambda e: self._set_hover(True))
        self.bind("<Leave>",           lambda e: self._set_hover(False))
        self.bind("<Configure>",       lambda e: self._draw())

    def set(self, first, last):
        self._pos = (float(first), float(last))
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()  or (self.THICKNESS + 4)
        h = self.winfo_height() or 200

        if self._orient == "vertical":
            track_len = h
            thumb_len = max(self.MIN_THUMB,
                            int(track_len * (self._pos[1] - self._pos[0])))
            thumb_pos = int(track_len * self._pos[0])
            thumb_pos = min(thumb_pos, track_len - thumb_len)
            x0 = 2; x1 = w - 2
            y0 = thumb_pos; y1 = thumb_pos + thumb_len
        else:
            track_len = w
            thumb_len = max(self.MIN_THUMB,
                            int(track_len * (self._pos[1] - self._pos[0])))
            thumb_pos = int(track_len * self._pos[0])
            thumb_pos = min(thumb_pos, track_len - thumb_len)
            y0 = 2; y1 = h - 2
            x0 = thumb_pos; x1 = thumb_pos + thumb_len

        color = self._hfg if self._hovering or self._dragging else self._fg
        r     = self.RADIUS
        self.create_arc(x0,    y0,    x0+2*r, y0+2*r, start=90,  extent=90,  fill=color, outline="")
        self.create_arc(x1-2*r, y0,   x1,     y0+2*r, start=0,   extent=90,  fill=color, outline="")
        self.create_arc(x0,    y1-2*r, x0+2*r, y1,    start=180, extent=90,  fill=color, outline="")
        self.create_arc(x1-2*r, y1-2*r, x1,   y1,    start=270, extent=90,  fill=color, outline="")
        self.create_rectangle(x0+r, y0, x1-r, y1, fill=color, outline="")
        self.create_rectangle(x0, y0+r, x1, y1-r, fill=color, outline="")

    def _set_hover(self, state):
        self._hovering = state
        self._draw()

    def _on_press(self, event):
        self._dragging   = True
        ts               = self.winfo_height() if self._orient == "vertical" else self.winfo_width()
        coord            = event.y if self._orient == "vertical" else event.x
        self._drag_start = (coord, self._pos[0])
        self._draw()

    def _on_drag(self, event):
        if not self._dragging or self._drag_start is None:
            return
        ts    = self.winfo_height() if self._orient == "vertical" else self.winfo_width()
        coord = event.y if self._orient == "vertical" else event.x
        delta = (coord - self._drag_start[0]) / ts
        nf    = max(0.0, min(1.0 - (self._pos[1] - self._pos[0]),
                             self._drag_start[1] + delta))
        if self._command:
            self._command("moveto", str(nf))

    def _on_release(self, event):
        self._dragging = False
        self._draw()

    def retheme(self, bg, fg, hover_fg):
        self._bg = bg; self._fg = fg; self._hfg = hover_fg
        self.config(bg=bg)
        self._draw()


# ══════════════════════════════════════════════════════════════════════════════
# PulseBar
# ══════════════════════════════════════════════════════════════════════════════

class PulseBar(tk.Canvas):
    """
    Thanh loading animation chạy ngang (smooth easing).
    .start() / .stop() — bắt đầu/dừng animation.
    .retheme(bg, accent) — đổi màu.
    """
    HEIGHT = 3

    def __init__(self, master, accent="#4F8EF7", bg="#1A1D27", **kw):
        kw.setdefault("height", self.HEIGHT)
        super().__init__(master, bg=bg, highlightthickness=0, bd=0, **kw)
        self._accent   = accent
        self._running  = False
        self._phase    = 0.0
        self._after_id = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._animate()

    def stop(self):
        self._running = False
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None
        self.delete("all")

    def _animate(self):
        if not self._running:
            return
        self._phase    = (self._phase + 0.035) % 1.0
        self._draw()
        self._after_id = self.after(28, self._animate)

    def _draw(self):
        self.delete("all")
        w    = self.winfo_width() or 160
        span = int(w * 0.32)
        cx   = int(self._phase * (w + span)) - span // 2
        x0, x1 = max(0, cx), min(w, cx + span)
        if x1 > x0:
            self.create_rectangle(x0, 0, x1, self.HEIGHT,
                                  fill=self._accent, outline="")

    def retheme(self, bg, accent):
        self._accent = accent
        self.config(bg=bg)


# ══════════════════════════════════════════════════════════════════════════════
# FindBar
# ══════════════════════════════════════════════════════════════════════════════

class FindBar(tk.Frame):
    """
    Ctrl+F inline find bar cho Treeview.
    Sử dụng: attach(tree) để liên kết với treeview.
    ._show() / .hide() — hiện/ẩn bar và focus entry.
    Tự động filter khi gõ, hiển thị count, nút ▲▼ để navigate.
    """

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._tree      = None
        self._all_items = []   # list of (iid, values_tuple)
        self._visible   = []   # currently matched iids
        self._cursor    = 0

        self._var = tk.StringVar()
        self._var.trace_add("write", self._on_change)

        tk.Button(self, text="✕", font=FONT_SMALL, relief="flat", bd=0,
                  padx=6, pady=2, cursor="hand2",
                  command=self.hide).pack(side="left")
        tk.Label(self, text="Find:", font=FONT_SMALL).pack(side="left", padx=(4, 4))

        self._entry = tk.Entry(self, textvariable=self._var,
                               font=FONT_UI, relief="flat", bd=0,
                               highlightthickness=1, width=26)
        self._entry.pack(side="left", ipady=3)
        self._entry.bind("<Escape>", lambda e: self.hide())
        self._entry.bind("<Return>", lambda e: self._select_next())

        self._count_lbl = tk.Label(self, text="", font=FONT_SMALL)
        self._count_lbl.pack(side="left", padx=(8, 4))

        self._nav_prev = tk.Button(self, text="▲", font=FONT_SMALL, relief="flat",
                                   bd=0, padx=5, pady=2, cursor="hand2",
                                   command=self._select_prev)
        self._nav_prev.pack(side="left")
        self._nav_next = tk.Button(self, text="▼", font=FONT_SMALL, relief="flat",
                                   bd=0, padx=5, pady=2, cursor="hand2",
                                   command=self._select_next)
        self._nav_next.pack(side="left")

        self.pack_forget()   # hidden by default

    def attach(self, tree):
        """Link to a Treeview và bind Ctrl+F trên root window."""
        self._tree = tree
        root = self.winfo_toplevel()
        root.bind_all("<Control-f>", lambda e: self.show(), add="+")
        root.bind_all("<Control-F>", lambda e: self.show(), add="+")

    def show(self):
        self.pack(fill="x", pady=(2, 0))
        self._entry.focus_set()
        self._entry.select_range(0, "end")

    def hide(self):
        self._var.set("")
        self.pack_forget()
        if self._tree:
            self._tree.focus_set()

    def _snapshot(self):
        """Snapshot current tree items (iid + values)."""
        if not self._tree:
            return
        self._all_items = []
        for iid in self._tree.get_children():
            vals = self._tree.item(iid, "values")
            self._all_items.append((iid, vals))

    def notify_data_changed(self):
        """Call after populating the tree so FindBar knows the new rows."""
        self._snapshot()

    def _on_change(self, *_):
        if not self._tree:
            return
        q = self._var.get().strip().lower()
        if not q:
            self._count_lbl.config(text="")
            return
        if not self._all_items:
            self._snapshot()
        matches       = [iid for iid, vals in self._all_items
                         if any(q in str(v).lower() for v in vals)]
        self._visible = matches
        self._cursor  = 0
        self._count_lbl.config(text=f"{len(matches)} found")
        if matches:
            self._jump_to(0)

    def _jump_to(self, idx):
        if not self._visible:
            return
        iid = self._visible[idx % len(self._visible)]
        self._tree.see(iid)
        self._tree.selection_set(iid)

    def _select_next(self):
        if not self._visible:
            return
        self._cursor = (self._cursor + 1) % len(self._visible)
        self._jump_to(self._cursor)

    def _select_prev(self):
        if not self._visible:
            return
        self._cursor = (self._cursor - 1) % len(self._visible)
        self._jump_to(self._cursor)

    def retheme(self, bg, bg2, bg3, fg, fg2, accent, border):
        self.config(bg=bg2)
        for w in self.winfo_children():
            try:
                w.config(bg=bg2, fg=fg2, activebackground=bg3)
            except Exception:
                pass
        self._entry.config(bg=bg3, fg=fg, insertbackground=accent,
                           highlightcolor=accent, highlightbackground=border)
        self._count_lbl.config(bg=bg2, fg=fg2)
