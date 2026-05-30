"""
run_all.py
==========
Entry point duy nhất để chạy toàn bộ pipeline.

Cách dùng
---------
# Chạy đầy đủ (embed → cluster → visualize)
    python run_all.py

# Chỉ định root folder và output dir
    python run_all.py --root ./my_docs --out ./output

# Bỏ qua embedding nếu embeddings_cache.npy đã tồn tại
    python run_all.py --skip-embed

# Chỉ re-cluster (không embed lại, không visualize)
    python run_all.py --only-cluster

# Chỉ re-visualize
    python run_all.py --only-viz

# Không tạo ChromaDB RAG store (chỉ làm clustering)
    python run_all.py --skip-chroma

# Tune hyperparameters clustering mà không embed lại
    python run_all.py --skip-embed --pca 30 --hdb-min-size 8 --umap-dist 0.05

Cấu trúc file input (root folder)
----------------------------------
project/
├── run_all.py
├── embed_pipeline.py
├── cluster_pipeline.py
├── visualize.py
├── cr_extractor.py
├── S5-250426/
│     └── *.docx
└── C1-522446/
      └── *.doc

Output (cùng --out dir, mặc định = cùng thư mục với run_all.py)
----------------------------------------------------------
embeddings_cache.npy
embeddings_metadata.json
pca_model.pkl
pca_reduced.npy
cluster_labels.npy
cluster_summary.json
umap_coords.npy
umap_model.pkl
visualization.html
chroma_store/
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup — phải cấu hình trước khi import các module pipeline
# ---------------------------------------------------------------------------

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt= "%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("run_all")


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="3GPP CR Clustering Pipeline — full run_all entry point",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- Paths ---
    p.add_argument(
        "--root", default=".",
        help="Root folder chứa các subfolder .docx/.doc",
    )
    p.add_argument(
        "--out", default="output",
        help="Output folder cho tất cả các file cache và kết quả (default: ./output)",
    )

    # --- Stage control ---
    g = p.add_mutually_exclusive_group()
    g.add_argument(
    "--force-embed", action="store_true",
    help="Embed lại từ đầu dù cache đã tồn tại",
    )
    g.add_argument(
        "--skip-embed", action="store_true",
        help="Bỏ qua embed_pipeline nếu embeddings_cache.npy đã có",
    )
    g.add_argument(
        "--only-cluster", action="store_true",
        help="Chỉ chạy cluster_pipeline (Stage 7-9), bỏ embed và viz",
    )
    g.add_argument(
        "--only-viz", action="store_true",
        help="Chỉ chạy visualize (Stage 10)",
    )

    p.add_argument(
        "--skip-chroma", action="store_true",
        help="Không tạo ChromaDB RAG store (Stage 6B)",
    )

    # --- Embed hyperparameters ---
    embed_g = p.add_argument_group("Embedding hyperparameters")
    embed_g.add_argument("--batch-size",   type=int,   default=32,
                         help="Batch size cho embedding model (default: 32). "
                              "Alpha weights được đọc trực tiếp từ embed_pipeline.py.")

    # --- Cluster hyperparameters ---
    cluster_g = p.add_argument_group("Cluster hyperparameters")
    cluster_g.add_argument("--pca",            type=int,   default=None,
                            help="PCA n_components (default: auto từ N docs)")
    cluster_g.add_argument("--hdb-min-size",   type=int,   default=None,
                            help="HDBSCAN min_cluster_size (default: auto từ N docs)")
    cluster_g.add_argument("--hdb-min-samp",   type=int,   default=None,
                            help="HDBSCAN min_samples (default: auto từ N docs)")
    cluster_g.add_argument("--umap-neighbors", type=int,   default=None,
                            help="UMAP n_neighbors (default: auto từ N docs)")
    cluster_g.add_argument("--umap-dist",      type=float, default=0.1,
                            help="UMAP min_dist (Stage 9)")
    cluster_g.add_argument("--umap-metric",    default="cosine",
                            help="UMAP metric (Stage 9)")

    return p


# ---------------------------------------------------------------------------
# Stage runners
# ---------------------------------------------------------------------------

def _run_embed(args) -> bool:
    """
    Quyết định embed / reweight / skip dựa trên trạng thái cache và alpha snapshot.

    Trả về True nếu có thay đổi (embed hoặc reweight), False nếu skip.

    Logic:
        --force-embed              → embed lại từ đầu, bất kể cache
        --skip-embed + cache có    → dùng cache nguyên xi, bỏ qua kể cả reweight
        --skip-embed + cache chưa  → warning rồi embed đầy đủ
        chunk cache có, alpha đổi  → reweight (~giây, không gọi model)
        chunk cache có, alpha same → skip
        chunk cache chưa có        → embed đầy đủ
    """
    import importlib
    import embed_pipeline as ep
    importlib.reload(ep)   # force re-read từ disk — tránh sys.modules cache giữ giá trị cũ

    out_dir   = Path(args.out)
    cache_npy = out_dir / "embeddings_cache.npy"

    # --force-embed: luôn embed lại từ đầu
    if args.force_embed:
        logger.info("--force-embed: embed lại từ đầu.")
        return _do_full_embed(args, ep)

    # --skip-embed: dùng cache nguyên xi, bỏ qua kể cả reweight
    if args.skip_embed:
        if cache_npy.exists():
            logger.info("--skip-embed: bỏ qua embed và reweight, dùng cache nguyên xi.")
            return False
        logger.warning("--skip-embed nhưng cache chưa có → chạy embed đầy đủ.")
        return _do_full_embed(args, ep)

    # Không có chunk cache → embed đầy đủ
    if not ep.chunk_cache_exists(out_dir):
        logger.info("Chunk cache chưa có → embed đầy đủ.")
        return _do_full_embed(args, ep)

    # Chunk cache có → kiểm tra alpha
    if ep.alpha_changed(out_dir):
        saved = ep.load_alpha_snapshot(out_dir)
        current = ep.get_current_alpha_snapshot()
        logger.info(
            "Alpha thay đổi (saved=%s → current=%s) → reweight từ chunk cache.",
            saved, current,
        )
        ep.reweight_from_chunk_cache(out_dir)
        return True

    logger.info(
        "Cache đã có và alpha không đổi → bỏ qua embed. "
        "Dùng --force-embed để embed lại từ đầu."
    )
    return False


def _do_full_embed(args, ep) -> bool:
    ep.EMBED_BATCH = args.batch_size
    logger.info("=" * 60)
    logger.info("STAGE 2-6: embed_pipeline  (root=%s, out=%s)", args.root, args.out)
    logger.info("=" * 60)
    ep.run(root_dir=args.root, output_dir=args.out, skip_chroma=args.skip_chroma)
    return True


def _run_cluster(args) -> None:
    import cluster_pipeline as cp

    logger.info("=" * 60)
    logger.info("STAGE 7-9: cluster_pipeline  (dir=%s)", args.out)
    logger.info("=" * 60)
    cp.run(
        data_dir         = args.out,
        pca_components   = args.pca,
        hdbscan_min_size = args.hdb_min_size,
        hdbscan_min_samp = args.hdb_min_samp,
        umap_n_neighbors = args.umap_neighbors,
        umap_min_dist    = args.umap_dist,
        umap_metric      = args.umap_metric,
    )


def _run_viz(args) -> None:
    import visualize

    logger.info("=" * 60)
    logger.info("STAGE 10: visualize  (dir=%s)", args.out)
    logger.info("=" * 60)
    out_html = visualize.run(data_dir=args.out)
    logger.info("Visualization → open in browser:  %s", out_html.resolve())


# ---------------------------------------------------------------------------
# Guard: kiểm tra file cache trước khi chạy downstream stages
# ---------------------------------------------------------------------------

def _check_cache(out_dir: str | Path, *filenames: str) -> None:
    """Raise FileNotFoundError nếu bất kỳ file nào trong filenames chưa tồn tại."""
    missing = [f for f in filenames if not (Path(out_dir) / f).exists()]
    if missing:
        raise FileNotFoundError(
            f"Các file sau chưa có trong {out_dir!r}: {missing}\n"
            "Hãy chạy pipeline đầy đủ trước."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    t_start = time.time()

    # Tạo output dir nếu chưa có
    Path(args.out).mkdir(parents=True, exist_ok=True)

    try:
        if args.only_viz:
            _check_cache(args.out, "umap_coords.npy", "cluster_labels.npy", "embeddings_metadata.json")
            _run_viz(args)

        elif args.only_cluster:
            _check_cache(args.out, "embeddings_cache.npy", "embeddings_metadata.json")
            _run_cluster(args)

        else:
            # Full run hoặc --skip-embed
            _run_embed(args)
            _run_cluster(args)
            _run_viz(args)

    except FileNotFoundError as e:
        logger.error("Thiếu file input: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        sys.exit(130)
    except Exception as e:
        logger.exception("Pipeline failed: %s", e)
        sys.exit(1)

    elapsed = time.time() - t_start
    logger.info("=" * 60)
    logger.info("Pipeline hoàn thành  (tổng %.1fs = %.1f phút)", elapsed, elapsed / 60)
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Public callable API — dùng cho GUI (ui_tabs_rag.py)
# ---------------------------------------------------------------------------

def run_pipeline(
    docs_dir = ".",
    out_dir  = "output",
    *,
    force_embed:    bool        = False,
    skip_embed:     bool        = False,
    only_cluster:   bool        = False,
    only_viz:       bool        = False,
    skip_chroma:    bool        = False,
    batch_size:     int         = 32,
    pca            = None,
    hdb_min_size   = None,
    hdb_min_samp   = None,
    umap_neighbors = None,
    umap_dist:      float       = 0.1,
    umap_metric:    str         = "cosine",
    progress_cb     = None,
    stop_event      = None,
) -> None:
    """
    Callable API cho GUI — tương đương chạy main() nhưng không parse CLI.

    Parameters
    ----------
    docs_dir     : thư mục chứa .docx / .doc files (tương đương --root)
    out_dir      : thư mục output (tương đương --out)
    force_embed  : embed lại từ đầu dù cache đã có
    skip_embed   : bỏ qua embed nếu cache đã có
    only_cluster : chỉ chạy Stage 7-9
    only_viz     : chỉ chạy Stage 10
    skip_chroma  : không tạo ChromaDB
    pca          : PCA n_components (None = auto)
    hdb_min_size : HDBSCAN min_cluster_size (None = auto)
    hdb_min_samp : HDBSCAN min_samples (None = auto)
    umap_neighbors: UMAP n_neighbors (None = auto)
    progress_cb  : callable(msg: str, color_key: str | None) → nhận log từ pipeline.
                   color_key: None | "warn" | "error"
    stop_event   : threading.Event — set() để dừng giữa các stage
    """
    import types, os

    args = types.SimpleNamespace(
        root           = str(docs_dir),
        out            = str(out_dir),
        force_embed    = force_embed,
        skip_embed     = skip_embed,
        only_viz       = only_viz,
        only_cluster   = only_cluster,
        skip_chroma    = skip_chroma,
        batch_size     = batch_size,
        pca            = pca,
        hdb_min_size   = hdb_min_size,
        hdb_min_samp   = hdb_min_samp,
        umap_neighbors = umap_neighbors,
        umap_dist      = umap_dist,
        umap_metric    = umap_metric,
    )

    Path(args.out).mkdir(parents=True, exist_ok=True)

    # --- GUI stdio patch ---------------------------------------------------
    # tqdm (dùng bởi sentence_transformers) gọi sys.stderr.isatty() để
    # check TTY. Trên Windows GUI (pythonw.exe / app không có console),
    # sys.stdout và sys.stderr là None → AttributeError: 'NoneType'...
    # Fix: redirect về os.devnull để tqdm chạy silently, không crash.
    # Chỉ patch khi chạy từ GUI (progress_cb không None).
    # -----------------------------------------------------------------------
    _saved_stdout = sys.stdout
    _saved_stderr = sys.stderr
    if progress_cb is not None:
        _devnull = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = _devnull
        if sys.stderr is None:
            sys.stderr = _devnull
    else:
        _devnull = None

    # --- Logging: GUI mode ---------------------------------------------------
    # Khi chạy từ GUI (progress_cb không None):
    #   1. Tạm thời detach toàn bộ handler gốc (stdout/file) của root logger
    #      → tránh UnicodeEncodeError khi stdout của Windows dùng cp1252
    #      mà pipeline log ra ký tự UTF-8 / tiếng Việt.
    #   2. Thay bằng _CBHandler duy nhất → forward về GUI log panel.
    #   3. Restore handlers gốc trong finally.
    # CLI mode (progress_cb=None): không thay đổi gì.
    # -------------------------------------------------------------------------
    _root_logger    = logging.getLogger()
    _saved_handlers = []
    _gui_handler    = None

    if progress_cb is not None:
        # Detach existing handlers (e.g. stdout StreamHandler)
        _saved_handlers = _root_logger.handlers[:]
        for h in _saved_handlers:
            _root_logger.removeHandler(h)

        class _CBHandler(logging.Handler):
            def emit(_self, record):
                try:
                    msg   = _self.format(record)
                    color = None
                    if record.levelno >= logging.ERROR:
                        color = "error"
                    elif record.levelno >= logging.WARNING:
                        color = "warn"
                    progress_cb(msg, color)
                except Exception:
                    pass

        _gui_handler = _CBHandler()
        _gui_handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)-20s  %(message)s",
            datefmt="%H:%M:%S",
        ))
        _root_logger.addHandler(_gui_handler)

    def _check_stop():
        if stop_event is not None and stop_event.is_set():
            raise InterruptedError("Pipeline stopped by user.")

    try:
        if args.only_viz:
            _check_cache(args.out,
                         "umap_coords.npy", "cluster_labels.npy",
                         "embeddings_metadata.json")
            _run_viz(args)

        elif args.only_cluster:
            _check_cache(args.out, "embeddings_cache.npy", "embeddings_metadata.json")
            _check_stop()
            _run_cluster(args)

        else:
            _run_embed(args)
            _check_stop()
            _run_cluster(args)
            _check_stop()
            _run_viz(args)

    finally:
        if progress_cb is not None:
            # Remove GUI handler, restore original handlers
            if _gui_handler is not None:
                _root_logger.removeHandler(_gui_handler)
            for h in _saved_handlers:
                _root_logger.addHandler(h)
            # Restore sys.stdout/stderr
            sys.stdout = _saved_stdout
            sys.stderr = _saved_stderr
            if _devnull is not None:
                try:
                    _devnull.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
