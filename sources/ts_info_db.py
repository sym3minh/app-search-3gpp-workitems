"""
ts_info_db.py
=============
Lookup TS specification title từ SQLite database (.cache/ts_info.db).

Database schema (read-only, không sửa):
    CREATE TABLE ts_info (
        spec_number  TEXT PRIMARY KEY,
        title        TEXT,
        wg           TEXT
    );

Cách dùng
---------
    from ts_info_db import TsInfoDb

    db = TsInfoDb()                          # dùng path mặc định
    db = TsInfoDb("/path/to/ts_info.db")     # path tường minh

    title = db.get_title("38.863")           # → "Study on NR NTN ..." | None
    title = db.get_title("99.999")           # → None  (không có trong DB)
    title = db.get_title(None)               # → None  (ts_number không extract được)

Đặc điểm thiết kế
-----------------
- Singleton-style: mỗi instance cache toàn bộ bảng vào dict khi khởi tạo
  → không có query SQL nào trong vòng lặp xử lý documents
- Graceful degradation: nếu file DB không tồn tại hoặc schema sai
  → log warning, trả về None cho mọi lookup (pipeline tiếp tục bình thường)
- Thread-safe: sau khi __init__ xong, chỉ đọc dict (immutable)
- Không giữ connection mở sau __init__
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path mặc định: .cache/ts_info.db relative to thư mục chứa file này
_DEFAULT_DB_PATH = Path(__file__).parent / ".cache" / "ts_info.db"


class TsInfoDb:
    """
    In-memory cache cho bảng ts_info.

    Toàn bộ table được load 1 lần vào dict khi __init__:
        { "38.863": "Study on NR NTN High Power UE (HPUE)", ... }

    Sau đó get_title() chỉ là dict lookup — O(1), zero I/O.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """
        Parameters
        ----------
        db_path : path tới file .db. Nếu None → dùng .cache/ts_info.db
                  cạnh file này.
        """
        resolved = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._cache: dict[str, str] = {}
        self._loaded = False
        self._load(resolved)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_title(self, spec_number: Optional[str]) -> Optional[str]:
        """
        Trả về title của spec_number, hoặc None nếu:
        - spec_number là None / rỗng
        - DB không load được
        - spec_number không có trong DB
        - title trong DB là NULL hoặc rỗng
        """
        if not spec_number:
            return None
        key = spec_number.strip()
        title = self._cache.get(key)
        # Coi empty string như None (title rỗng trong DB → bỏ qua)
        return title if title else None

    @property
    def loaded(self) -> bool:
        """True nếu DB load thành công và có ít nhất 1 record."""
        return self._loaded

    def __len__(self) -> int:
        return len(self._cache)

    def __repr__(self) -> str:
        status = f"{len(self._cache)} specs" if self._loaded else "not loaded"
        return f"TsInfoDb({status})"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self, db_path: Path) -> None:
        """
        Load toàn bộ (spec_number, title) vào self._cache.

        Lỗi được xử lý hoàn toàn nội bộ:
        - FileNotFoundError → warning, cache rỗng
        - sqlite3 errors     → warning, cache rỗng
        - Bất kỳ lỗi nào     → warning, cache rỗng
        Pipeline không bị ảnh hưởng trong mọi trường hợp.
        """
        if not db_path.exists():
            logger.warning(
                "TsInfoDb: DB file not found at %s — ts_title sẽ bị bỏ qua cho mọi CR.",
                db_path,
            )
            return

        try:
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT spec_number, title FROM ts_info"
                ).fetchall()
            finally:
                conn.close()

            loaded_count = 0
            skipped_empty = 0
            for row in rows:
                spec = (row["spec_number"] or "").strip()
                title = (row["title"] or "").strip()
                if spec and title:
                    self._cache[spec] = title
                    loaded_count += 1
                elif spec:
                    skipped_empty += 1

            self._loaded = loaded_count > 0
            logger.info(
                "TsInfoDb loaded from %s — %d specs with title%s",
                db_path,
                loaded_count,
                f", {skipped_empty} skipped (empty title)" if skipped_empty else "",
            )

        except sqlite3.OperationalError as e:
            logger.warning(
                "TsInfoDb: Failed to query ts_info table in %s — %s. "
                "Kiểm tra schema: cần có cột spec_number và title.",
                db_path, e,
            )
        except Exception as e:
            logger.warning(
                "TsInfoDb: Unexpected error loading %s — %s",
                db_path, e,
            )
