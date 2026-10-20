import hashlib
import math
import re
import sqlite3
import struct

from repodoctor.models import SearchHit

RRF_K = 60
VECTOR_DIMS = 256


def pack_vector(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *[float(value) for value in values])


def unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    if count == 0:
        return []
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


def hybrid_search(connection: sqlite3.Connection, query: str, limit: int = 8) -> tuple[list[SearchHit], str]:
    lexical = _lexical_search(connection, query, limit=max(limit * 3, 12))
    tokens = _token_search(connection, query, limit=max(limit * 3, 12))
    note = "lexical+tokens" if tokens else "lexical"
    fused = reciprocal_rank_fusion(
        [[chunk_id for chunk_id, _score in lexical], [chunk_id for chunk_id, _score in tokens]]
    )
    chosen = fused[:limit]
    hits: list[SearchHit] = []
    for index, chunk_id in enumerate(chosen, start=1):
        row = _chunk_row(connection, chunk_id)
        if row is None:
            continue
        hits.append(
            SearchHit(
                chunk_id=chunk_id,
                path=str(row["path"]),
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                text=str(row["text"]),
                score=1.0 / index,
            )
        )
    return hits, note


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> list[int]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for index, item_id in enumerate(ranking, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + index)
    return sorted(scores, key=lambda item: scores[item], reverse=True)


def _lexical_search(connection: sqlite3.Connection, query: str, limit: int) -> list[tuple[int, float]]:
    match = _fts_query(query)
    if not match:
        return []
    try:
        rows = connection.execute(
            """
            SELECT rowid AS chunk_id, bm25(chunks_fts) AS rank
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(int(row["chunk_id"]), float(row["rank"])) for row in rows]


def _fts_query(text: str) -> str:
    import re

    terms = re.findall(r"[A-Za-z0-9_]+", text)
    if not terms:
        return ""
    return " OR ".join(f'"{term}"' for term in terms[:12])


def _token_search(connection: sqlite3.Connection, query: str, limit: int) -> list[tuple[int, float]]:
    count = connection.execute("SELECT COUNT(*) AS count FROM embeddings").fetchone()
    if count is None or int(count["count"]) == 0:
        return []
    query_vector = token_vector(query)
    scored: list[tuple[int, float]] = []
    rows = connection.execute("SELECT chunk_id, vector FROM embeddings").fetchall()
    for row in rows:
        vector = unpack_vector(row["vector"])
        score = _cosine(query_vector, vector)
        scored.append((int(row["chunk_id"]), score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [item for item in scored[:limit] if item[1] > 0]


def token_vector(text: str, dims: int = VECTOR_DIMS) -> list[float]:
    vector = [0.0] * dims
    for token in re.findall(r"[A-Za-z0-9_]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        bucket = int.from_bytes(digest[:2], "little") % dims
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _chunk_row(connection: sqlite3.Connection, chunk_id: int):
    return connection.execute(
        """
        SELECT c.id, f.path, c.start_line, c.end_line, c.text
        FROM chunks c
        JOIN files f ON f.id = c.file_id
        WHERE c.id = ?
        """,
        (chunk_id,),
    ).fetchone()

