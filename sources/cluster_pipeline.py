"""
cluster_pipeline.py
===================
Stage 7 → 9: PCA → HDBSCAN → UMAP.

Đọc vào:    embeddings_cache.npy         (1000 × 768)
            embeddings_metadata.json
Ghi ra:     pca_model.pkl                (fitted PCA, dùng lại cho doc mới)
            cluster_labels.npy           (1000,) int — label HDBSCAN
            umap_coords.npy              (1000 × 2) float — toạ độ 2D
            umap_model.pkl               (fitted UMAP, dùng lại khi project doc mới)
            cluster_summary.json         (thống kê số cluster, noise count…)

Tất cả file output cùng thư mục với embeddings_cache.npy.

File này KHÔNG phụ thuộc vào model embedding → chạy lại rất nhanh khi tune
hyperparameters (PCA n_components, HDBSCAN min_cluster_size, UMAP n_neighbors…).
"""

from __future__ import annotations

import json
import logging
import pickle
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fixed hyperparameters (không scale theo N)
# ---------------------------------------------------------------------------

DEFAULT_UMAP_MIN_DIST  = 0.1
DEFAULT_UMAP_METRIC    = "cosine"
DEFAULT_UMAP_SEED      = 42

# Sentinel: khi run_all.py không truyền giá trị tường minh,
# cluster_pipeline.run() sẽ tự tính từ N thông qua auto_params().
_AUTO = None


# ---------------------------------------------------------------------------
# Auto-scaling hyperparameters theo corpus size
# ---------------------------------------------------------------------------

def auto_params(n_docs: int) -> dict:
    """
    Tính hyperparameters tối ưu cho UMAP dựa trên số lượng documents.

    Lưu ý:
    - pca_components KHÔNG nằm trong dict trả về — xác định bởi find_pca_components().
    - hdbscan_min_size và hdbscan_min_samp KHÔNG nằm trong dict trả về —
      được chọn tự động bởi select_hdbscan_min_size() với thuật toán riêng.
      Xem select_hdbscan_min_size() để biết chi tiết logic lựa chọn.

    Chỉ trả về:
        umap_n_neighbors = clamp(int(sqrt(N)), 5, 50)

    Bảng tham khảo umap_n_neighbors:
        N=30   → neighbors=5
        N=72   → neighbors=8
        N=193  → neighbors=13
        N=300  → neighbors=17
        N=600  → neighbors=24
        N=1000 → neighbors=31
        N=2000 → neighbors=44
    """
    import math

    if n_docs < 5:
        logger.warning(
            "auto_params: n_docs=%d rat nho — clustering se khong co y nghia thong ke.",
            n_docs,
        )

    neighbors = int(max(5, min(50, math.sqrt(n_docs))))

    return {
        "umap_n_neighbors": neighbors,
    }


def _hdbscan_stats(labels: np.ndarray) -> tuple[int, float]:
    """Trả về (n_clusters, noise_ratio) từ mảng labels HDBSCAN."""
    n_total    = len(labels)
    n_clusters = int(labels.max()) + 1 if labels.max() >= 0 else 0
    n_noise    = int((labels == -1).sum())
    noise_ratio = n_noise / n_total if n_total > 0 else 0.0
    return n_clusters, noise_ratio


def select_hdbscan_min_size(
    reduced:  np.ndarray,
    n_docs:   int,
    min_samp: int = 2,
) -> tuple[int, np.ndarray]:
    """
    Chọn hdbscan_min_cluster_size tối ưu bằng cách thử min_size = 3 rồi 4,
    sau đó áp dụng bộ tiêu chí ưu tiên để giữ lại kết quả tốt hơn.

    Tham số cố định:
        min_samp    = 2  (không scale theo N)
        max_cluster = 15% × n_docs  (ngưỡng "quá nhiều cụm")

    Bộ tiêu chí (theo thứ tự ưu tiên):

        1. Nếu min_size=3 cho cl_3 < max_cluster VÀ noise_3 ≤ 25%
           → dùng ngay min_size=3, bỏ qua min_size=4.

        2. Thử min_size=4. Nếu cl_4 < max_cluster VÀ cl_4 ≥ 3 VÀ noise_4 ≤ 25%
           → dùng min_size=4.

        3. Nếu cả hai đều có cl ≥ 3:
           - Nếu noise_3 / noise_4 > 0.95 → dùng 4 (4 ít noise hơn đáng kể)
           - Ngược lại → dùng 3 (3 không tệ hơn nhiều, giữ granularity cao hơn)

        4. Nếu chỉ một phía có cl ≥ 3 → dùng phía đó.

        5. Fallback (cả hai đều cl < 3):
           - noise_3 / noise_4 > 0.95 → dùng 4
           - Ngược lại → dùng 3

    Lưu ý tránh ZeroDivisionError:
        Nếu noise_4 == 0 (không có noise point nào với min_size=4), tỷ số được
        coi là 0.0 (tức là 3 không tệ hơn 4 về noise) → dùng 3 ở bước 3/5.

    Trả về:
        (chosen_min_size, labels)  — labels là np.ndarray shape (N,) int32
    """
    max_cluster = max(1, int(n_docs * 0.15))   # 15% corpus

    logger.info(
        "HDBSCAN auto-select: n_docs=%d  max_cluster=%d  min_samp=%d",
        n_docs, max_cluster, min_samp,
    )

    # --- Thử min_size = 3 ---
    labels_3 = run_hdbscan(reduced, min_cluster_size=3, min_samples=min_samp)
    cl_3, noise_3 = _hdbscan_stats(labels_3)
    logger.info(
        "  min_size=3 → clusters=%d  noise_ratio=%.3f (%.1f%%)",
        cl_3, noise_3, noise_3 * 100,
    )

    # Tiêu chí 1: min_size=3 đã đủ tốt
    if cl_3 < max_cluster and noise_3 <= 0.25:
        logger.info("  → Chọn min_size=3 (tiêu chí 1: cl<max_cluster và noise≤25%%)")
        return 3, labels_3

    # --- Thử min_size = 4 ---
    labels_4 = run_hdbscan(reduced, min_cluster_size=4, min_samples=min_samp)
    cl_4, noise_4 = _hdbscan_stats(labels_4)
    logger.info(
        "  min_size=4 → clusters=%d  noise_ratio=%.3f (%.1f%%)",
        cl_4, noise_4, noise_4 * 100,
    )

    # Tiêu chí 2: min_size=4 đáp ứng điều kiện chất lượng
    if cl_4 < max_cluster and cl_4 >= 3 and noise_4 <= 0.25:
        logger.info("  → Chọn min_size=4 (tiêu chí 2: cl<max_cluster, cl≥3, noise≤25%%)")
        return 4, labels_4

    # Tỷ số noise để so sánh (tránh ZeroDivisionError)
    noise_ratio_cmp = (noise_3 / noise_4) if noise_4 > 0 else 0.0

    # Tiêu chí 3: cả hai có cl ≥ 3 → so sánh noise ratio
    if cl_3 >= 3 and cl_4 >= 3:
        if noise_ratio_cmp > 0.95:
            logger.info(
                "  → Chọn min_size=4 (tiêu chí 3: cả hai cl≥3, noise_3/noise_4=%.3f > 0.95)",
                noise_ratio_cmp,
            )
            return 4, labels_4
        else:
            logger.info(
                "  → Chọn min_size=3 (tiêu chí 3: cả hai cl≥3, noise_3/noise_4=%.3f ≤ 0.95)",
                noise_ratio_cmp,
            )
            return 3, labels_3

    # Tiêu chí 4: chỉ một phía có cl ≥ 3
    if cl_3 >= 3:
        logger.info("  → Chọn min_size=3 (tiêu chí 4: chỉ min_size=3 có cl≥3)")
        return 3, labels_3
    if cl_4 >= 3:
        logger.info("  → Chọn min_size=4 (tiêu chí 4: chỉ min_size=4 có cl≥3)")
        return 4, labels_4

    # Tiêu chí 5: fallback — cả hai đều cl < 3
    if noise_ratio_cmp > 0.95:
        logger.info(
            "  → Chọn min_size=4 (tiêu chí 5 fallback: noise_3/noise_4=%.3f > 0.95)",
            noise_ratio_cmp,
        )
        return 4, labels_4
    else:
        logger.info(
            "  → Chọn min_size=3 (tiêu chí 5 fallback: noise_3/noise_4=%.3f ≤ 0.95)",
            noise_ratio_cmp,
        )
        return 3, labels_3


def find_pca_components(
    matrix: np.ndarray,
    target_variance: float = 0.85,
    min_components: int = 10,
    max_components: int = 150,
) -> int:
    """
    Tim so PCA components toi thieu de dat target_variance tren matrix thuc te.

    Tai sao khong dung cong thuc sqrt(N)?
    Explained variance phu thuoc vao DO DA DANG NOI DUNG cua corpus, khong
    phai so luong document. 193 CRs tu 12 work items khac nhau can nhieu
    components hon 193 CRs cung mot work item.

    Voi BGE-base embeddings (768-dim), thuc nghiem cho thay:
        corpus dong nhat   ~ 20-35 components du 85%
        corpus da dang vua ~ 40-70 components
        corpus rat da dang ~ 80-120 components

    Cach hoat dong:
        1. Chay PCA day du (full_k components) — nhanh, chi vai giay.
        2. Tinh cumulative explained variance ratio.
        3. Tra ve index dau tien vuot target_variance, clamp vao [min, max].

    Parameters
    ----------
    matrix          : (N, 768) doc-level embeddings
    target_variance : nguong explained variance (default 0.85 = 85%)
    min_components  : san toi thieu (default 10)
    max_components  : tran toi da (default 150)

    Returns
    -------
    n_components : int
    """
    from sklearn.decomposition import PCA

    full_k = min(matrix.shape[0], matrix.shape[1], max_components + 20)
    full_k = max(full_k, min_components + 1)

    logger.info(
        "PCA probe: fitting %d components to find %.0f%% variance threshold ...",
        full_k, target_variance * 100,
    )
    t0 = time.time()
    probe = PCA(n_components=full_k, random_state=42)
    probe.fit(matrix)

    cumvar = probe.explained_variance_ratio_.cumsum()
    idxs = [i for i, v in enumerate(cumvar) if v >= target_variance]

    if idxs:
        n_components = idxs[0] + 1
    else:
        n_components = full_k
        logger.warning(
            "Khong dat %.0f%% variance du dung %d components (dat duoc %.1f%%). "
            "Corpus rat da dang — can nhac giam target_variance xuong 0.80.",
            target_variance * 100, full_k, float(cumvar[-1]) * 100,
        )

    n_components = int(max(min_components, min(max_components, n_components)))
    actual_var   = float(cumvar[n_components - 1]) * 100

    logger.info(
        "PCA probe done (%.1fs) — chon %d components -> %.1f%% variance",
        time.time() - t0, n_components, actual_var,
    )
    return n_components


# ---------------------------------------------------------------------------
# Stage 7 — PCA
# ---------------------------------------------------------------------------

def run_pca(
    matrix: np.ndarray,
    n_components: int = 50,
) -> tuple[np.ndarray, object, float]:
    """
    Giảm chiều: (N, 768) → (N, n_components).

    Trả về:
        reduced             : np.ndarray shape (N, n_components)
        pca                 : fitted sklearn PCA object (để dùng lại)
        explained_variance  : float — % variance giữ lại (0–100)

    Cảnh báo nếu explained variance < 80%: n_components có thể quá nhỏ so với
    độ đa dạng của corpus — cân nhắc tăng --pca hoặc dùng n_components=0.90.
    """
    from sklearn.decomposition import PCA

    n_components = min(n_components, matrix.shape[0], matrix.shape[1])
    logger.info(
        "PCA: %s → n_components=%d …",
        matrix.shape, n_components,
    )
    t0  = time.time()
    pca = PCA(n_components=n_components, random_state=42)
    reduced = pca.fit_transform(matrix)

    explained = float(pca.explained_variance_ratio_.sum() * 100)
    logger.info(
        "PCA done  (%.1fs) — explained variance: %.1f%%",
        time.time() - t0, explained,
    )
    if explained < 80.0:
        logger.warning(
            "PCA explained variance thấp (%.1f%% < 80%%) với %d components. "
            "Corpus có thể đa dạng hơn dự kiến — thử tăng --pca hoặc dùng "
            "n_components=0.90 để giữ đủ 90%% variance.",
            explained, n_components,
        )
    return reduced.astype(np.float32), pca, explained


# ---------------------------------------------------------------------------
# Stage 8 — HDBSCAN
# ---------------------------------------------------------------------------

def run_hdbscan(
    reduced: np.ndarray,
    min_cluster_size: int = 5,
    min_samples:      int = 3,
) -> np.ndarray:
    """
    Cluster trên PCA space dùng cosine distance precomputed.

    Thay vì truyền reduced trực tiếp với metric='euclidean', ta tính trước
    ma trận cosine distance rồi truyền vào HDBSCAN với metric='precomputed'.

    Lý do dùng cosine thay vì euclidean:
    - Doc-level vectors đã normalize L2 (Stage 6A) → cosine distance = 1 - cosine_similarity,
      phân biệt góc giữa các vector tốt hơn độ dài Euclidean sau PCA.
    - Sau PCA các trục có scale khác nhau (variance lớn ở PC1, nhỏ dần) → euclidean
      bị dominated bởi vài PC đầu; cosine không bị ảnh hưởng bởi scale này.
    - Tách bước tính khoảng cách khỏi clustering: dist_matrix có thể cache/debug
      độc lập với HDBSCAN hyperparameters.

    Nhược điểm cần lưu ý:
    - Memory: dist_matrix shape (N, N) float64 → với N=2000: ~32MB (chấp nhận được).
    - metric='precomputed' không hỗ trợ core_dist_n_jobs → bỏ tham số đó.
    - Không thể dùng HDBSCAN.approximate_predict() sau này (không có tree).

    Trả về:
        labels : np.ndarray shape (N,) — int, -1 = noise
    """
    try:
        import hdbscan as hdbscan_lib
    except ImportError:
        raise ImportError("hdbscan chưa được cài. Chạy: pip install hdbscan")

    from sklearn.metrics.pairwise import cosine_distances

    n = reduced.shape[0]
    logger.info(
        "HDBSCAN: min_cluster_size=%d  min_samples=%d  metric=cosine(precomputed) …",
        min_cluster_size, min_samples,
    )
    t0 = time.time()

    # Tính cosine distance matrix: shape (N, N), dtype float64
    # cosine_distances trả về giá trị trong [0, 2]; với vectors normalize L2 thì [0, 1]
    # cosine_distances yêu cầu float64; reduced có thể là float32 sau PCA → cast trước
    dist_matrix = cosine_distances(reduced.astype(np.float64))

    # Clamp giá trị âm nhỏ do floating-point (cosine_distances đôi khi trả -1e-16)
    # Không dùng out= để tránh vô tình thay đổi dtype
    dist_matrix = np.clip(dist_matrix, 0.0, None).astype(np.float64)

    logger.info(
        "Cosine distance matrix computed  (%.1fs) — shape %s, "
        "mem ~%.1f MB, dist range [%.4f, %.4f]",
        time.time() - t0,
        dist_matrix.shape,
        dist_matrix.nbytes / 1e6,
        float(dist_matrix.min()),
        float(np.ma.masked_equal(dist_matrix, 0).max()),  # max non-zero
    )

    t1 = time.time()
    clusterer = hdbscan_lib.HDBSCAN(
        min_cluster_size = min_cluster_size,
        min_samples      = min_samples,
        metric           = "precomputed",
        # core_dist_n_jobs không hỗ trợ với metric='precomputed'
    )
    labels = clusterer.fit_predict(dist_matrix)

    n_clusters = int(labels.max()) + 1 if labels.max() >= 0 else 0
    n_noise    = int((labels == -1).sum())
    logger.info(
        "HDBSCAN done  (%.1fs) — %d clusters, %d noise points",
        time.time() - t1, n_clusters, n_noise,
    )
    return labels.astype(np.int32)


# ---------------------------------------------------------------------------
# Stage 9 — UMAP
# ---------------------------------------------------------------------------

def run_umap(
    reduced: np.ndarray,
    n_neighbors: int   = 15,
    min_dist:    float = DEFAULT_UMAP_MIN_DIST,
    metric:      str   = DEFAULT_UMAP_METRIC,
    random_state: int  = DEFAULT_UMAP_SEED,
) -> tuple[np.ndarray, object]:
    """
    Chiếu từ PCA-space xuống 2D để visualization.

    Trả về:
        coords : np.ndarray shape (N, 2)
        reducer: fitted UMAP object (để project doc mới)
    """
    try:
        import umap
    except ImportError:
        raise ImportError("umap-learn chưa được cài. Chạy: pip install umap-learn")

    logger.info(
        "UMAP: n_neighbors=%d  min_dist=%.2f  metric=%s …",
        n_neighbors, min_dist, metric,
    )
    t0 = time.time()
    reducer = umap.UMAP(
        n_components  = 2,
        n_neighbors   = n_neighbors,
        min_dist      = min_dist,
        metric        = metric,
        random_state  = random_state,
        low_memory    = False,    # 20GB RAM đủ dùng
    )
    coords = reducer.fit_transform(reduced)

    logger.info("UMAP done  (%.1fs)", time.time() - t0)
    return coords.astype(np.float32), reducer


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------

def _save_pkl(obj, path: Path) -> None:
    with open(path, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    logger.info("Saved: %s", path)


def _save_cluster_summary(
    labels:   np.ndarray,
    metadata: list[dict],
    path:     Path,
    params_used: dict | None = None,
    explained_variance_pct: float | None = None,
) -> None:
    """
    Ghi cluster_summary.json: thống kê từng cluster và danh sách filename.
    Bao gồm params_used và explained_variance_pct để dễ debug / reproduce kết quả.
    """
    unique_labels = sorted(set(labels.tolist()))
    clusters_info = []

    for lbl in unique_labels:
        idxs    = [i for i, l in enumerate(labels.tolist()) if l == lbl]
        members = [metadata[i]["filename"] for i in idxs]
        # Lấy work_item phổ biến nhất trong cluster
        wi_counts: dict[str, int] = {}
        for i in idxs:
            wi = metadata[i].get("work_item") or "unknown"
            wi_counts[wi] = wi_counts.get(wi, 0) + 1
        top_wi = max(wi_counts, key=wi_counts.get) if wi_counts else "unknown"

        clusters_info.append({
            "cluster_id":      lbl,
            "is_noise":        lbl == -1,
            "size":            len(idxs),
            "top_work_item":   top_wi,
            "member_files":    members,
        })

    n_total   = len(labels)
    n_noise   = int((labels == -1).sum())
    n_clusters = sum(1 for c in clusters_info if not c["is_noise"])
    noise_ratio = round(n_noise / n_total, 4) if n_total > 0 else 0.0

    summary = {
        "n_documents":           n_total,
        "n_clusters":            n_clusters,
        "n_noise":               n_noise,
        "noise_ratio":           noise_ratio,          # ← mới: tỉ lệ noise / total
        "explained_variance_pct": round(explained_variance_pct, 2) if explained_variance_pct is not None else None,
        "params_used":           params_used or {},
        "clusters":              clusters_info,
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved cluster summary: %s", path)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    data_dir: str | Path = ".",
    # PCA — None = auto-scale từ N
    pca_components:    int | None   = _AUTO,
    # HDBSCAN — None = auto-select qua select_hdbscan_min_size()
    # Truyền giá trị tường minh để bỏ qua auto-select và dùng fixed min_size.
    hdbscan_min_size:  int | None   = _AUTO,
    hdbscan_min_samp:  int | None   = _AUTO,
    # UMAP — None = auto-scale từ N; min_dist và metric luôn cố định
    umap_n_neighbors:  int | None   = _AUTO,
    umap_min_dist:     float        = DEFAULT_UMAP_MIN_DIST,
    umap_metric:       str          = DEFAULT_UMAP_METRIC,
    umap_seed:         int          = DEFAULT_UMAP_SEED,
) -> dict:
    """
    Chạy Stage 7 → 9, đọc / ghi tại data_dir.

    HDBSCAN min_cluster_size:
    - Mặc định (None): gọi select_hdbscan_min_size() — tự thử min_size=3 và 4,
      chọn kết quả tốt hơn theo bộ tiêu chí (max_cluster, noise ratio).
    - Truyền giá trị tường minh (vd: --hdb-min-size 5): bỏ qua auto-select,
      dùng fixed min_size đó.

    HDBSCAN min_samples:
    - Mặc định (None): dùng 2 (cố định, không scale theo N).
    - Truyền giá trị tường minh để override.

    Trả về dict kết quả để visualize.py dùng lại nếu gọi inline.
    """
    data_dir = Path(data_dir)

    # --- Load cache ---
    npy_path  = data_dir / "embeddings_cache.npy"
    meta_path = data_dir / "embeddings_metadata.json"

    if not npy_path.exists():
        raise FileNotFoundError(
            f"{npy_path} không tồn tại. Chạy embed_pipeline.py trước."
        )

    logger.info("Loading embeddings cache: %s …", npy_path)
    matrix   = np.load(str(npy_path))                            # (N, 768)
    metadata = json.loads(meta_path.read_text(encoding="utf-8")) # list[dict]

    assert matrix.shape[0] == len(metadata), (
        f"Mismatch: {matrix.shape[0]} vectors vs {len(metadata)} metadata entries"
    )

    n_docs = matrix.shape[0]
    logger.info("Loaded %d doc-level vectors, dim=%d", n_docs, matrix.shape[1])

    # --- Resolve PCA ---
    if pca_components is _AUTO:
        pca_components = find_pca_components(matrix)

    # --- Resolve UMAP n_neighbors ---
    if umap_n_neighbors is _AUTO:
        ap = auto_params(n_docs)
        umap_n_neighbors = ap["umap_n_neighbors"]
        logger.info("Auto umap_n_neighbors=%d (N=%d)", umap_n_neighbors, n_docs)

    # --- Resolve HDBSCAN min_samples ---
    # Cố định = 2 khi AUTO; override nếu được truyền tường minh
    if hdbscan_min_samp is _AUTO:
        hdbscan_min_samp = 2

    # --- Stage 7: PCA (cần chạy trước HDBSCAN để có reduced matrix) ---
    reduced, pca, explained_variance = run_pca(matrix, n_components=pca_components)
    _save_pkl(pca, data_dir / "pca_model.pkl")
    np.save(str(data_dir / "pca_reduced.npy"), reduced)

    # --- Stage 8: HDBSCAN ---
    # Nếu min_size được truyền tường minh → dùng trực tiếp (không auto-select)
    # Nếu min_size là AUTO → gọi select_hdbscan_min_size() để chọn tự động
    if hdbscan_min_size is not _AUTO:
        logger.info(
            "Manual HDBSCAN params: min_size=%d  min_samp=%d",
            hdbscan_min_size, hdbscan_min_samp,
        )
        labels = run_hdbscan(
            reduced,
            min_cluster_size = hdbscan_min_size,
            min_samples      = hdbscan_min_samp,
        )
    else:
        hdbscan_min_size, labels = select_hdbscan_min_size(
            reduced,
            n_docs   = n_docs,
            min_samp = hdbscan_min_samp,
        )

    np.save(str(data_dir / "cluster_labels.npy"), labels)

    # Sanity check: cảnh báo nếu kết quả clustering có vẻ degenerate
    n_clusters_found = int(labels.max()) + 1 if labels.max() >= 0 else 0
    n_noise_found    = int((labels == -1).sum())
    noise_pct        = n_noise_found / n_docs * 100

    if n_clusters_found <= 2 and n_docs > 50:
        logger.warning(
            "HDBSCAN chi tim thay %d cluster(s) tren %d docs. "
            "Neu explained_variance thap (<80%%), van de chinh la PCA — thu tang --pca. "
            "Neu variance da >85%%, thu giam --hdb-min-size (hien=%d) xuong %d.",
            n_clusters_found, n_docs,
            hdbscan_min_size, max(3, hdbscan_min_size // 2),
        )
    if noise_pct > 30.0:
        logger.warning(
            "Noise ratio cao: %d/%d docs (%.0f%%). "
            "Nguyen nhan pho bien nhat: PCA giu qua it variance (xem explained_variance_pct "
            "trong cluster_summary.json). Thu tang --pca hoac giam target_variance. "
            "Neu PCA da du (>85%%), thu giam --hdb-min-size (hien=%d).",
            n_noise_found, n_docs, noise_pct,
            hdbscan_min_size,
        )

    _save_cluster_summary(
        labels, metadata, data_dir / "cluster_summary.json",
        params_used={
            "n_docs":           n_docs,
            "pca_components":   pca_components,
            "hdbscan_min_size": hdbscan_min_size,
            "hdbscan_min_samp": hdbscan_min_samp,
            "hdbscan_metric":   "cosine(precomputed)",
            "umap_n_neighbors": umap_n_neighbors,
            "umap_min_dist":    umap_min_dist,
            "umap_metric":      umap_metric,
        },
        explained_variance_pct=explained_variance,
    )

    # --- Stage 9: UMAP ---
    coords, reducer = run_umap(
        reduced,
        n_neighbors  = umap_n_neighbors,
        min_dist     = umap_min_dist,
        metric       = umap_metric,
        random_state = umap_seed,
    )
    np.save(str(data_dir / "umap_coords.npy"), coords)
    _save_pkl(reducer, data_dir / "umap_model.pkl")

    logger.info("cluster_pipeline complete — all outputs in %s", data_dir)

    return {
        "matrix":   matrix,
        "reduced":  reduced,
        "labels":   labels,
        "coords":   coords,
        "metadata": metadata,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    logging.basicConfig(
        level  = logging.INFO,
        format = "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt= "%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Stage 7-9: PCA → HDBSCAN → UMAP")
    parser.add_argument("--dir",            default=".",   help="Thư mục chứa embeddings_cache.npy")
    parser.add_argument("--pca",            type=int,   default=None,  help="PCA n_components (default: auto)")
    parser.add_argument("--hdb-min-size",   type=int,   default=None,  help="HDBSCAN min_cluster_size (default: auto)")
    parser.add_argument("--hdb-min-samp",   type=int,   default=None,  help="HDBSCAN min_samples (default: auto)")
    parser.add_argument("--umap-neighbors", type=int,   default=None,  help="UMAP n_neighbors (default: auto)")
    parser.add_argument("--umap-dist",      type=float, default=DEFAULT_UMAP_MIN_DIST)
    parser.add_argument("--umap-metric",    default=DEFAULT_UMAP_METRIC)
    args = parser.parse_args()

    run(
        data_dir          = args.dir,
        pca_components    = args.pca,
        hdbscan_min_size  = args.hdb_min_size,
        hdbscan_min_samp  = args.hdb_min_samp,
        umap_n_neighbors  = args.umap_neighbors,
        umap_min_dist     = args.umap_dist,
        umap_metric       = args.umap_metric,
    )
