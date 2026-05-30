"""
embed_pipeline.py
=================
Stage 2 → 6A + 6B: Text preparation, chunking, embedding, cache & RAG store.

Nhận vào:   root folder chứa các subfolder có .docx / .doc
Ghi ra:     embeddings_cache.npy
            embeddings_metadata.json
            chroma_store/   (ChromaDB persistent)

Gọi cr_extractor với output_txt=False để không sinh file .txt phụ.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — có thể override khi import
# ---------------------------------------------------------------------------

# Resolve thư mục gốc của project (parent của 3gpp_app/) từ vị trí file này.
# Đảm bảo paths luôn đúng bất kể working directory hiện tại là gì
# (quan trọng khi import từ GUI thay vì chạy CLI trực tiếp).
_APP_DIR  = Path(__file__).resolve().parent   # .../3gpp_app/
_ROOT_DIR = _APP_DIR.parent                   # .../ (chứa .cache, models, output)

ALPHA_HIGH   = 1.3   # weight multiplier cho Group HIGH
ALPHA_MEDIUM = 1.1   # weight multiplier cho Group MEDIUM
ALPHA_NORMAL = 1.0   # weight multiplier cho Group NORMAL
MAX_TOKENS   = 512   # hard limit của BGE model
EMBED_BATCH  = 32    # số chunks embed mỗi lần gọi model

# Absolute path tới model dir — tránh lỗi "Repo id must be in the form..."
# khi from_pretrained() nhận relative path trong môi trường GUI.
EMBED_MODEL: str = str(_ROOT_DIR / "models" / "bge-base-en-v1.5")

# Path tới SQLite DB chứa TS spec titles.
# Resolve từ ROOT_DIR (app_3gpp/.cache) thay vì APP_DIR (3gpp_app/.cache).
# Override bằng cách set biến này trước khi gọi run():
#     import embed_pipeline; embed_pipeline.TS_INFO_DB_PATH = "/custom/path/ts_info.db"
TS_INFO_DB_PATH: str | Path | None = _ROOT_DIR / ".cache" / "ts_info.db"

HIGH_FIELDS   = ["ts_title"]

MEDIUM_FIELDS = ["title", "summary_of_change"]

NORMAL_FIELDS = [
    "reason_for_change",
    "consequences_if_not_approved",
    "other_comments",
]

# ---------------------------------------------------------------------------
# Fields lưu vào embeddings_metadata.json (dùng cho tooltip visualization)
# KHÔNG phụ thuộc vào HIGH/MEDIUM/NORMAL grouping.
# Đây là toàn bộ 7 fields từ cr_extractor + ts_title từ DB.
# Thay đổi HIGH/MEDIUM/NORMAL_FIELDS không ảnh hưởng đến tooltip.
# ---------------------------------------------------------------------------
METADATA_FIELDS = [
    "ts_number",
    "work_item",
    "title",
    "ts_title",
    "reason_for_change",
    "summary_of_change",
    "consequences_if_not_approved",
    "other_comments",
    "file_path",   # absolute path — dùng để mở file Word khi click dot trên visualization
]

# ---------------------------------------------------------------------------
# Chunk cache filenames — Tier 1 (bất biến, không phụ thuộc alpha)
# ---------------------------------------------------------------------------

CHUNK_VECTORS_FILE  = "chunk_vectors_cache.npz"   # (total_chunks, 768) float32
CHUNK_META_FILE     = "chunk_meta_cache.json"      # per-chunk: doc_idx, group, token_count, ...
DOC_META_CACHE_FILE = "doc_meta_cache.json"        # per-doc: filename + metadata fields
ALPHA_SNAPSHOT_FILE = "alpha_snapshot.json"        # alpha tại thời điểm tạo embeddings_cache.npy


def get_current_alpha_snapshot() -> dict:
    """Trả về dict alpha hiện tại từ module constants."""
    return {"HIGH": ALPHA_HIGH, "MEDIUM": ALPHA_MEDIUM, "NORMAL": ALPHA_NORMAL}


def save_alpha_snapshot(output_dir: Path) -> None:
    snap = get_current_alpha_snapshot()
    (output_dir / ALPHA_SNAPSHOT_FILE).write_text(
        json.dumps(snap, indent=2), encoding="utf-8"
    )
    logger.info("Alpha snapshot saved: %s", snap)


def load_alpha_snapshot(output_dir: Path) -> dict | None:
    path = output_dir / ALPHA_SNAPSHOT_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def alpha_changed(output_dir: Path) -> bool:
    """True nếu alpha trong embed_pipeline.py khác với snapshot đã lưu."""
    saved = load_alpha_snapshot(output_dir)
    if saved is None:
        return True
    return saved != get_current_alpha_snapshot()


def chunk_cache_exists(output_dir: Path) -> bool:
    """True nếu Tier 1 cache đầy đủ (vectors + chunk meta + doc meta)."""
    return all(
        (output_dir / f).exists()
        for f in (CHUNK_VECTORS_FILE, CHUNK_META_FILE, DOC_META_CACHE_FILE)
    )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    text:        str
    alpha:       float
    token_count: int
    group:       str          # "HIGH" | "NORMAL"
    fields:      list[str]    # tên các fields có trong chunk này


@dataclass
class DocResult:
    filename:   str
    meta:       dict          # 7 fields từ cr_extractor
    chunks:     list[Chunk]
    vectors:    list[np.ndarray]   # parallel với chunks, shape (768,) mỗi item
    doc_vector: Optional[np.ndarray] = None   # weighted average, shape (768,)


# ---------------------------------------------------------------------------
# Stage 2 — Text Preparation & Field Grouping
# ---------------------------------------------------------------------------

def _field_text(meta: dict, key: str) -> str:
    """Trả về text của field, empty string nếu None."""
    return (meta.get(key) or "").strip()


def _build_group_text(meta: dict, keys: list[str]) -> tuple[str, list[str]]:
    """
    Nối các fields thành một đoạn text, bỏ qua fields rỗng.
    Trả về (text, danh sách fields thực sự có nội dung).
    """
    parts: list[str] = []
    present: list[str] = []
    for k in keys:
        val = _field_text(meta, k)
        if val:
            parts.append(val)
            present.append(k)
    return " ".join(parts), present


# ---------------------------------------------------------------------------
# Stage 3 — Token Measurement & Routing
# ---------------------------------------------------------------------------

def _count_tokens(text: str, tokenizer) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))


def _tokenize_fields(
    meta: dict,
    tokenizer,
) -> tuple[list[tuple[str, list[str], float, int]], int]:
    """
    Đo token count của từng field (không nhóm) để dùng cho bin-packing.

    Trả về:
        field_items: list of (text, [field_name], alpha, token_count)
        total_tokens: tổng tất cả fields
    """
    field_items: list[tuple[str, list[str], float, int]] = []

    for k in HIGH_FIELDS:
        val = _field_text(meta, k)
        if val:
            tc = _count_tokens(val, tokenizer)
            field_items.append((val, [k], ALPHA_HIGH, tc))

    for k in MEDIUM_FIELDS:
        val = _field_text(meta, k)
        if val:
            tc = _count_tokens(val, tokenizer)
            field_items.append((val, [k], ALPHA_MEDIUM, tc))

    for k in NORMAL_FIELDS:
        val = _field_text(meta, k)
        if val:
            tc = _count_tokens(val, tokenizer)
            field_items.append((val, [k], ALPHA_NORMAL, tc))

    total = sum(item[3] for item in field_items)
    return field_items, total


# ---------------------------------------------------------------------------
# Stage 4 — Dynamic Chunking
# ---------------------------------------------------------------------------

def _split_text_by_sentence(text: str, tokenizer, max_tokens: int) -> list[str]:
    """
    Cắt text dài thành các đoạn ≤ max_tokens tại ranh giới câu.
    Fallback: cắt tại khoảng trắng nếu không tìm được dấu câu.
    """
    # Tách câu tại . ! ? theo sau bởi khoảng trắng hoặc cuối chuỗi
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    sub_chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = _count_tokens(sent, tokenizer)

        if sent_tokens > max_tokens:
            # Câu đơn lẻ vẫn vượt limit → cắt theo từ
            if current_parts:
                sub_chunks.append(" ".join(current_parts))
                current_parts, current_tokens = [], 0
            words = sent.split()
            word_buf: list[str] = []
            word_tok = 0
            for w in words:
                wt = _count_tokens(w, tokenizer)
                if word_tok + wt > max_tokens and word_buf:
                    sub_chunks.append(" ".join(word_buf))
                    word_buf, word_tok = [w], wt
                else:
                    word_buf.append(w)
                    word_tok += wt
            if word_buf:
                sub_chunks.append(" ".join(word_buf))
        elif current_tokens + sent_tokens > max_tokens:
            if current_parts:
                sub_chunks.append(" ".join(current_parts))
            current_parts, current_tokens = [sent], sent_tokens
        else:
            current_parts.append(sent)
            current_tokens += sent_tokens

    if current_parts:
        sub_chunks.append(" ".join(current_parts))

    return [s for s in sub_chunks if s.strip()]


def _bin_pack_fields(
    field_items: list[tuple[str, list[str], float, int]],
    tokenizer,
    max_tokens: int = MAX_TOKENS,
) -> list[Chunk]:
    """
    Bin-pack các fields thành chunks ≤ max_tokens.

    Ưu tiên 1: cắt tại ranh giới field (bin-packing).
    Ưu tiên 2: nếu field đơn lẻ > max_tokens thì cắt giữa field theo câu.
    """
    # Bước đầu: mở rộng field nào > max_tokens thành sub-items
    expanded: list[tuple[str, list[str], float, int]] = []
    for text, field_names, alpha, token_count in field_items:
        if token_count > max_tokens:
            sub_texts = _split_text_by_sentence(text, tokenizer, max_tokens)
            for st in sub_texts:
                stc = _count_tokens(st, tokenizer)
                expanded.append((st, field_names, alpha, stc))
        else:
            expanded.append((text, field_names, alpha, token_count))

    # Bin-packing: cùng alpha thì pack chung, khác alpha thì không gộp
    # (không gộp HIGH và NORMAL vào chung 1 chunk để giữ alpha thuần)
    chunks: list[Chunk] = []
    buf_texts:  list[str]       = []
    buf_fields: list[str]       = []
    buf_alpha:  Optional[float] = None
    buf_tokens: int             = 0

    def flush():
        nonlocal buf_texts, buf_fields, buf_alpha, buf_tokens
        if buf_texts:
            if buf_alpha == ALPHA_HIGH:
                group = "HIGH"
            elif buf_alpha == ALPHA_MEDIUM:
                group = "MEDIUM"
            else:
                group = "NORMAL"
            chunks.append(Chunk(
                text        = " ".join(buf_texts),
                alpha       = buf_alpha,
                token_count = buf_tokens,
                group       = group,
                fields      = list(buf_fields),
            ))
        buf_texts, buf_fields, buf_alpha, buf_tokens = [], [], None, 0

    for text, field_names, alpha, token_count in expanded:
        # Thay đổi alpha group → flush chunk hiện tại
        if buf_alpha is not None and alpha != buf_alpha:
            flush()

        # Không đủ chỗ → flush rồi mở chunk mới
        if buf_tokens + token_count > max_tokens and buf_texts:
            flush()

        buf_texts.append(text)
        buf_fields.extend(field_names)
        buf_alpha = alpha
        buf_tokens += token_count

    flush()
    return chunks


def prepare_chunks(meta: dict, tokenizer) -> list[Chunk]:
    """
    Stage 2 + 3 + 4: từ dict metadata → list[Chunk] với token_count và alpha.
    """
    field_items, total_tokens = _tokenize_fields(meta, tokenizer)

    if not field_items:
        # Document rỗng / không extract được gì
        return []

    if total_tokens <= MAX_TOKENS:
        # Path A: 1 chunk duy nhất chứa tất cả (gộp HIGH + NORMAL chung)
        # Tuy nhiên giữ 2 chunks riêng để phân biệt alpha cho weighted average
        return _bin_pack_fields(field_items, tokenizer)
    else:
        # Path B: dynamic chunking
        return _bin_pack_fields(field_items, tokenizer)


def compute_weights(chunks: list[Chunk]) -> list[float]:
    """
    Tính final_weight cho mỗi chunk: raw_weight = alpha * token_count,
    sau đó normalize để tổng = 1.
    """
    if not chunks:
        return []
    # Đếm số chunks trong mỗi alpha group để normalize
    from collections import Counter
    group_counts = Counter(c.alpha for c in chunks)

    raws = [c.alpha / group_counts[c.alpha] for c in chunks]
    total = sum(raws)
    return [r / total for r in raws]


# ---------------------------------------------------------------------------
# Stage 5 — Embedding
# ---------------------------------------------------------------------------

def embed_chunks_batched(
    all_chunks: list[tuple[int, list[Chunk]]],
    model,
) -> dict[int, list[np.ndarray]]:
    """
    Embed tất cả chunks của tất cả documents theo batch.

    Parameters
    ----------
    all_chunks : list of (doc_idx, chunks_of_that_doc)
    model      : SentenceTransformer model

    Returns
    -------
    dict mapping doc_idx → list of np.ndarray (768,)
    """
    # Flatten tất cả texts kèm (doc_idx, chunk_idx)
    flat_texts:  list[str]            = []
    flat_keys:   list[tuple[int,int]] = []

    for doc_idx, chunks in all_chunks:
        for ci, chunk in enumerate(chunks):
            flat_texts.append(chunk.text)
            flat_keys.append((doc_idx, ci))

    if not flat_texts:
        return {}

    logger.info("Embedding %d chunks in batches of %d …", len(flat_texts), EMBED_BATCH)

    all_vectors: list[np.ndarray] = []
    for start in range(0, len(flat_texts), EMBED_BATCH):
        batch = flat_texts[start : start + EMBED_BATCH]
        vecs  = model.encode(
            batch,
            batch_size      = len(batch),
            show_progress_bar = False,
            normalize_embeddings = False,   # normalize ở Stage 6A
            convert_to_numpy = True,
        )
        all_vectors.extend(vecs)

    # Group lại theo doc_idx
    result: dict[int, list[np.ndarray]] = {}
    for (doc_idx, ci), vec in zip(flat_keys, all_vectors):
        result.setdefault(doc_idx, [])
        # đảm bảo list đủ dài
        while len(result[doc_idx]) <= ci:
            result[doc_idx].append(None)
        result[doc_idx][ci] = vec

    return result


# ---------------------------------------------------------------------------
# Stage 6A — Clustering cache
# ---------------------------------------------------------------------------

def compute_doc_vector(
    vectors:  list[np.ndarray],
    weights:  list[float],
) -> np.ndarray:
    """
    Tính weighted average rồi normalize L2.
    shape output: (768,)
    """
    doc_vec = np.zeros(vectors[0].shape, dtype=np.float64)
    for v, w in zip(vectors, weights):
        doc_vec += w * v.astype(np.float64)
    norm = np.linalg.norm(doc_vec)
    if norm > 0:
        doc_vec /= norm
    return doc_vec.astype(np.float32)


def save_clustering_cache(
    doc_results: list[DocResult],
    output_dir: Path,
) -> None:
    """
    Ghi embeddings_cache.npy và embeddings_metadata.json.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix   = np.stack([dr.doc_vector for dr in doc_results], axis=0)
    npy_path = output_dir / "embeddings_cache.npy"
    np.save(str(npy_path), matrix)

    metadata = []
    for dr in doc_results:
        entry = {
            "filename": dr.filename,
            **{k: (dr.meta.get(k) or "") for k in METADATA_FIELDS},
        }
        metadata.append(entry)

    meta_path = output_dir / "embeddings_metadata.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "Clustering cache saved: %s  (shape %s)  +  %s",
        npy_path, matrix.shape, meta_path,
    )


# ---------------------------------------------------------------------------
# Tier 1 cache — chunk vectors thô (bất biến, không phụ thuộc alpha)
# ---------------------------------------------------------------------------

def save_chunk_cache(doc_results: list[DocResult], output_dir: Path) -> None:
    """
    Lưu Tier 1 cache: toàn bộ chunk vectors thô + metadata.

    Mục đích: cho phép tính lại doc-level vectors (Tier 2) khi alpha thay đổi
    mà không cần gọi lại model embedding.

    Ghi ra:
        chunk_vectors_cache.npz  — shape (total_chunks, 768)
        chunk_meta_cache.json    — per-chunk: doc_idx, group, token_count, fields, text
        doc_meta_cache.json      — per-doc: filename + metadata (để rebuild embeddings_metadata.json)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    all_vectors: list[np.ndarray] = []
    chunk_metas: list[dict]       = []
    doc_metas:   list[dict]       = []

    for doc_idx, dr in enumerate(doc_results):
        for ci, (chunk, vec) in enumerate(zip(dr.chunks, dr.vectors)):
            all_vectors.append(vec)
            chunk_metas.append({
                "doc_idx":     doc_idx,
                "group":       chunk.group,
                "token_count": chunk.token_count,
                "fields":      chunk.fields,
                "text":        chunk.text,
            })
        doc_metas.append({
            "filename": dr.filename,
            **{k: (dr.meta.get(k) or "") for k in METADATA_FIELDS},
        })

    vectors_matrix = np.stack(all_vectors, axis=0)   # (total_chunks, 768)
    np.savez_compressed(
        str(output_dir / CHUNK_VECTORS_FILE),
        vectors=vectors_matrix,
    )
    (output_dir / CHUNK_META_FILE).write_text(
        json.dumps(chunk_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / DOC_META_CACHE_FILE).write_text(
        json.dumps(doc_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        "Chunk cache saved: %d chunks / %d docs  →  %s",
        len(all_vectors), len(doc_results), output_dir / CHUNK_VECTORS_FILE,
    )


def _alpha_from_group(group: str) -> float:
    """Map group string → alpha constant hiện tại trong module."""
    if group == "HIGH":
        return ALPHA_HIGH
    if group == "MEDIUM":
        return ALPHA_MEDIUM
    return ALPHA_NORMAL


def reweight_from_chunk_cache(output_dir: Path) -> None:
    """
    Tính lại embeddings_cache.npy từ Tier 1 cache với alpha hiện tại.

    Không gọi model embedding — chỉ tính weighted average từ chunk vectors.
    Cập nhật:
        embeddings_cache.npy       — doc-level vectors với alpha mới
        embeddings_metadata.json   — không thay đổi nội dung, ghi lại cho nhất quán
        alpha_snapshot.json        — lưu alpha mới vào snapshot

    Raises FileNotFoundError nếu Tier 1 cache chưa tồn tại.
    """
    output_dir = Path(output_dir)

    if not chunk_cache_exists(output_dir):
        raise FileNotFoundError(
            f"Chunk cache không tồn tại tại {output_dir}. "
            "Cần chạy embed đầy đủ ít nhất một lần trước."
        )

    current = get_current_alpha_snapshot()
    logger.info("Reweighting with alpha: %s", current)
    t0 = time.time()

    # Load Tier 1
    vectors     = np.load(str(output_dir / CHUNK_VECTORS_FILE))["vectors"]  # (total_chunks, 768)
    chunk_metas = json.loads((output_dir / CHUNK_META_FILE).read_text(encoding="utf-8"))
    doc_metas   = json.loads((output_dir / DOC_META_CACHE_FILE).read_text(encoding="utf-8"))

    n_docs = len(doc_metas)

    # Group chunk indices theo doc_idx
    doc_chunk_indices: dict[int, list[int]] = {i: [] for i in range(n_docs)}
    for ci, cm in enumerate(chunk_metas):
        doc_chunk_indices[cm["doc_idx"]].append(ci)

    # Tính lại doc-level vectors
    from collections import Counter

    doc_vectors: list[np.ndarray] = []
    for doc_idx in range(n_docs):
        indices = doc_chunk_indices[doc_idx]
        if not indices:
            doc_vectors.append(np.zeros(vectors.shape[1], dtype=np.float32))
            continue

        alphas = [_alpha_from_group(chunk_metas[ci]["group"]) for ci in indices]
        alpha_counts = Counter(alphas)
        raws   = [a / alpha_counts[a] for a in alphas]
        total  = sum(raws)
        weights = [r / total for r in raws]

        doc_vec = np.zeros(vectors.shape[1], dtype=np.float64)
        for ci, w in zip(indices, weights):
            doc_vec += w * vectors[ci].astype(np.float64)
        norm = np.linalg.norm(doc_vec)
        if norm > 0:
            doc_vec /= norm
        doc_vectors.append(doc_vec.astype(np.float32))

    # Lưu Tier 2
    matrix = np.stack(doc_vectors, axis=0)
    np.save(str(output_dir / "embeddings_cache.npy"), matrix)

    # Ghi lại embeddings_metadata.json từ doc_meta_cache (nội dung không đổi)
    (output_dir / "embeddings_metadata.json").write_text(
        json.dumps(doc_metas, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    save_alpha_snapshot(output_dir)

    logger.info(
        "Reweight done (%.2fs) — %d docs, shape %s",
        time.time() - t0, n_docs, matrix.shape,
    )


# ---------------------------------------------------------------------------
# Stage 6B — ChromaDB RAG store
# ---------------------------------------------------------------------------

def save_rag_store(
    doc_results: list[DocResult],
    chroma_path: Path,
) -> None:
    """
    Lưu từng chunk riêng lẻ vào ChromaDB persistent collection.
    Dùng upsert để chạy lại an toàn (không duplicate).
    """
    try:
        import chromadb
    except ImportError:
        raise ImportError("chromadb chưa được cài. Chạy: pip install chromadb")

    chroma_path.mkdir(parents=True, exist_ok=True)
    client     = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(
        name     = "3gpp_cr",
        metadata = {"hnsw:space": "cosine"},
    )

    ids_batch:   list[str]   = []
    embs_batch:  list[list]  = []
    docs_batch:  list[str]   = []
    metas_batch: list[dict]  = []

    UPSERT_BATCH = 500

    def flush_batch():
        if ids_batch:
            collection.upsert(
                ids        = ids_batch[:],
                embeddings = embs_batch[:],
                documents  = docs_batch[:],
                metadatas  = metas_batch[:],
            )
            ids_batch.clear(); embs_batch.clear()
            docs_batch.clear(); metas_batch.clear()

    for dr in doc_results:
        weights     = compute_weights(dr.chunks)
        chunk_total = len(dr.chunks)

        for ci, (chunk, vec) in enumerate(zip(dr.chunks, dr.vectors)):
            chunk_id = f"{Path(dr.filename).stem}_chunk_{ci}"

            ids_batch.append(chunk_id)
            embs_batch.append(vec.tolist())
            docs_batch.append(chunk.text)
            metas_batch.append({
                "filename":    dr.filename,
                "ts_number":   dr.meta.get("ts_number") or "",
                "title":       dr.meta.get("title")     or "",
                "ts_title":    dr.meta.get("ts_title")  or "",
                "work_item":   dr.meta.get("work_item") or "",
                "group":       chunk.group,
                "fields":      "|".join(chunk.fields),
                "chunk_index": ci,
                "chunk_total": chunk_total,
                "token_count": chunk.token_count,
                "weight":      round(weights[ci], 6),
            })

            if len(ids_batch) >= UPSERT_BATCH:
                flush_batch()

    flush_batch()
    logger.info(
        "RAG store saved to %s — collection '3gpp_cr'  (%d docs total)",
        chroma_path,
        collection.count(),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run(
    root_dir:    str | Path,
    output_dir:  str | Path = "output",
    skip_chroma: bool = False,
) -> list[DocResult]:
    """
    Chạy toàn bộ Stage 2 → 6A + 6B.

    Parameters
    ----------
    root_dir    : thư mục gốc chứa các subfolder có .docx / .doc
    output_dir  : nơi lưu embeddings_cache.npy, embeddings_metadata.json, chroma_store/
    skip_chroma : nếu True, bỏ qua Stage 6B (chỉ tạo clustering cache)
    """
    from cr_extractor import extract_cr_metadata          # import tại đây để tránh circular
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer
    from ts_info_db import TsInfoDb

    root_dir   = Path(root_dir)
    output_dir = Path(output_dir)

    # --- Khởi tạo TS spec title lookup ---
    ts_db = TsInfoDb(TS_INFO_DB_PATH)
    if ts_db.loaded:
        logger.info("TsInfoDb ready — %d specs available for ts_title enrichment", len(ts_db))
    else:
        logger.warning(
            "TsInfoDb not loaded (DB missing or empty) — "
            "ts_title sẽ là empty string cho tất cả documents. "
            "Pipeline tiếp tục bình thường."
        )

    # --- Tìm tất cả file Word ---
    doc_files = sorted(
        p for p in root_dir.rglob("*")
        if p.suffix.lower() in {".docx", ".doc"}
    )
    logger.info("Found %d Word files under %s", len(doc_files), root_dir)

    if not doc_files:
        logger.warning("Không tìm thấy file nào.")
        return []

    # --- Load tokenizer & model ---
    logger.info("Loading tokenizer from local: %s …", EMBED_MODEL)
    tokenizer = AutoTokenizer.from_pretrained(EMBED_MODEL, local_files_only=True)

    logger.info("Loading embedding model from local: %s …", EMBED_MODEL)
    model = SentenceTransformer(EMBED_MODEL, local_files_only=True)

    # --- Stage 1 + 2 + 3 + 4: extract & chunk ---
    doc_results:   list[DocResult]              = []
    all_chunks_in: list[tuple[int, list[Chunk]]] = []

    t0 = time.time()
    skip_count = 0

    for i, fpath in enumerate(doc_files):
        try:
            # output_txt=False → không ghi file .txt
            meta   = extract_cr_metadata(fpath, output_txt=False)

            # --- Enrich meta với ts_title từ DB ---
            # ts_title = title của TS/TR mà CR này nhắm tới (e.g. "38.863")
            # Nếu ts_number không có hoặc không tìm được trong DB → empty string
            # (empty string được _field_text() xử lý bằng cách bỏ qua, không gây lỗi)
            ts_title = ts_db.get_title(meta.get("ts_number")) or ""
            meta["ts_title"] = ts_title
            if ts_title:
                logger.debug(
                    "%s: ts_number=%s → ts_title=%r",
                    fpath.name, meta.get("ts_number"), ts_title[:60],
                )

            # Lưu absolute path vào meta → được ghi vào embeddings_metadata.json
            # và dùng bởi visualize.py để mở file khi click dot.
            meta["file_path"] = str(fpath.resolve())

            chunks = prepare_chunks(meta, tokenizer)

            if not chunks:
                logger.warning("No chunks for %s — skipping", fpath.name)
                skip_count += 1
                continue

            dr = DocResult(
                filename = fpath.name,
                meta     = meta,
                chunks   = chunks,
                vectors  = [],
            )
            doc_results.append(dr)
            all_chunks_in.append((len(doc_results) - 1, chunks))

        except Exception as exc:
            logger.warning("Skipped %s — %s", fpath.name, exc)
            logger.debug("Traceback:", exc_info=True) 
            skip_count += 1

    logger.info(
        "Extraction + chunking: %d docs OK, %d skipped  (%.1fs)",
        len(doc_results), skip_count, time.time() - t0,
    )

    # --- Stage 5: Embedding ---
    t1 = time.time()
    vec_map = embed_chunks_batched(all_chunks_in, model)

    for doc_idx, dr in enumerate(doc_results):
        dr.vectors = vec_map.get(doc_idx, [])

    logger.info("Embedding done  (%.1fs)", time.time() - t1)

    # --- Stage 6A: clustering cache ---
    for dr in doc_results:
        weights      = compute_weights(dr.chunks)
        dr.doc_vector = compute_doc_vector(dr.vectors, weights)

    save_clustering_cache(doc_results, output_dir)

    # --- Tier 1 cache + alpha snapshot (để reweight sau mà không embed lại) ---
    save_chunk_cache(doc_results, output_dir)
    save_alpha_snapshot(output_dir)

    # --- Stage 6B: ChromaDB ---
    if not skip_chroma:
        save_rag_store(doc_results, output_dir / "chroma_store")

    logger.info(
        "embed_pipeline done — %d documents processed  (total %.1fs)",
        len(doc_results), time.time() - t0,
    )
    return doc_results


# ---------------------------------------------------------------------------
# CLI (dùng trực tiếp, không qua run_all.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level  = logging.INFO,
        format = "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt= "%H:%M:%S",
    )

    root    = sys.argv[1] if len(sys.argv) > 1 else "."
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "output"
    run(root_dir=root, output_dir=out_dir)
