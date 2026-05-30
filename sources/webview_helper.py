"""
webview_helper.py
=================
Mở visualization.html trong pywebview window (subprocess riêng).

Tại sao subprocess thay vì thread?
- pywebview.start() PHẢI chạy trên main thread của process.
- Tkinter đã chiếm main thread → không thể chạy webview.start() trong thread con.
- Giải pháp: spawn process Python mới, process đó gọi webview.start() bình thường.

Truyền script qua stdin (python -):
- Không ghi file tạm ra disk → source directory luôn sạch.
- Không có race condition khi nhiều instance gọi đồng thời.
- html_path được truyền qua biến môi trường WEBVIEW_HTML_PATH thay vì sys.argv
  (vì stdin đã bị dùng cho script, không còn dùng được để pipe data khác).

Fallback:
    Nếu pywebview không cài hoặc spawn thất bại → messagebox + webbrowser.open().
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tkinter.messagebox as _mb
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Script chạy trong subprocess — đọc từ stdin, nhận html_path qua env var
# ---------------------------------------------------------------------------

_WEBVIEW_SCRIPT = """\
import sys, os, platform, subprocess
from pathlib import Path

def main():
    html_path = Path(os.environ["WEBVIEW_HTML_PATH"])
    if not html_path.exists():
        print(f"[webview] File not found: {html_path}", file=sys.stderr)
        sys.exit(1)

    try:
        import webview
    except ImportError:
        print("[webview] pywebview not installed", file=sys.stderr)
        sys.exit(2)

    class FileAPI:
        def open_file(self, path: str) -> None:
            if not path:
                return
            fp = Path(path)
            if not fp.exists():
                return
            system = platform.system()
            try:
                if system == "Windows":
                    os.startfile(str(fp))
                elif system == "Darwin":
                    subprocess.run(["open", str(fp)], check=True)
                else:
                    subprocess.run(["xdg-open", str(fp)], check=True)
            except Exception as e:
                print(f"[webview] Cannot open file: {e}", file=sys.stderr)

    webview.create_window(
        title     = "CR Visualization",
        url       = html_path.as_uri(),
        js_api    = FileAPI(),
        width     = 1440,
        height    = 900,
        min_size  = (800, 600),
        resizable = True,
    )
    webview.start(debug=False)

main()
"""

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def open_in_pywebview(html_path: Path) -> None:
    """
    Spawn một process Python mới để mở html_path trong pywebview.

    Script được truyền qua stdin (``python -``) — không ghi file tạm ra disk.
    html_path được truyền qua biến môi trường WEBVIEW_HTML_PATH.

    Parameters
    ----------
    html_path : Path tới file visualization.html (phải tồn tại)
    """
    if not html_path.exists():
        logger.error("Visualization file không tồn tại: %s", html_path)
        _mb.showerror(
            "File không tồn tại",
            f"Không tìm thấy:\n{html_path}\n\nHãy chạy pipeline trước.",
        )
        return

    # Truyền html_path qua env var vì stdin đã dùng cho script
    child_env = {**os.environ, "WEBVIEW_HTML_PATH": str(html_path)}

    try:
        proc = subprocess.Popen(
            [sys.executable, "-"],          # "-" = đọc script từ stdin
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=child_env,
        )

        # Gửi script vào stdin rồi đóng để child bắt đầu chạy
        proc.stdin.write(_WEBVIEW_SCRIPT.encode())
        proc.stdin.close()

        # Kiểm tra nhanh xem process có crash ngay không
        try:
            proc.wait(timeout=1.5)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = None   # Process vẫn đang chạy bình thường → OK

        if rc == 2:
            # pywebview không cài
            logger.warning("pywebview chưa được cài. Fallback về webbrowser.")
            _mb.showwarning(
                "pywebview không tìm thấy",
                "Không tìm thấy thư viện pywebview.\n"
                "Chạy lệnh sau rồi khởi động lại app:\n\n"
                "    pip install pywebview\n\n"
                "Tạm thời mở bằng trình duyệt hệ thống.",
            )
            webbrowser.open(html_path.as_uri())
        elif rc is not None and rc != 0:
            # Crash vì lý do khác
            stderr = proc.stderr.read().decode(errors="replace")
            logger.error("pywebview process lỗi (rc=%d): %s", rc, stderr)
            _mb.showerror(
                "Lỗi mở Visualization",
                f"pywebview khởi động thất bại (exit {rc}).\n\n"
                f"{stderr[:300]}\n\nMở bằng trình duyệt thay thế.",
            )
            webbrowser.open(html_path.as_uri())
        else:
            logger.info("pywebview window opened (pid=%d)", proc.pid)

    except Exception:
        logger.exception("Không thể spawn webview process. Fallback về webbrowser.")
        webbrowser.open(html_path.as_uri())
