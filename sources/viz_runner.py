"""
viz_runner.py
=============
Script con được spawn bởi _cl_open_viz() trong ui_tabs_rag.py.

Chạy pywebview trên main thread của process riêng → tránh xung đột
với tkinter mainloop đang chiếm main thread của process cha.

Cách dùng (do app gọi tự động, không cần chạy tay):
    python viz_runner.py <path_to_visualization.html>
"""

import os
import subprocess
import sys


class _FileAPI:
    """
    JS API được expose qua window.pywebview.api trong webview.
    Khi user click một dot trên biểu đồ, JS gọi:
        window.pywebview.api.open_file(filePath)
    Python mở file bằng ứng dụng mặc định của OS.
    """

    def open_file(self, path: str) -> None:
        if not path:
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path], check=False)
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception as exc:
            # Không crash webview khi mở file thất bại
            print(f"[viz_runner] Cannot open file {path!r}: {exc}", file=sys.stderr)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python viz_runner.py <visualization.html>", file=sys.stderr)
        sys.exit(1)

    html_path = sys.argv[1]
    try:
        html_content = open(html_path, encoding="utf-8").read()
    except OSError as e:
        print(f"[viz_runner] Cannot read {html_path!r}: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        import webview
    except ImportError:
        print("[viz_runner] pywebview not installed. Run: pip install pywebview",
              file=sys.stderr)
        sys.exit(1)

    window = webview.create_window(   # noqa: F841
        title     = "CR Clustering — Visualization",
        html      = html_content,
        js_api    = _FileAPI(),
        width     = 1400,
        height    = 900,
        resizable = True,
    )
    webview.start()   # blocks on main thread — đây là mục đích của script này


if __name__ == "__main__":
    main()
