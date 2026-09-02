"""RAG service: structure-aware chunking, Gemini embeddings, ChromaDB store,
hybrid retrieval (vector search + long-context direct injection).

Hybrid strategy (as discussed):
  - All documents are chunked (section-aware, ~1200 tokens/chunk with
    section metadata) and embedded into ChromaDB.
  - At planning/retrieval time:
      * small materials (fits in context) → retrieve top-k AND note that
        full text is available for direct injection
      * large materials → vector retrieval with citations
  - Every retrieved chunk carries {section_title, page/slide source} so
    lesson segments can cite their sources.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..config import CHROMA_DIR
from .gemini import embed_texts
from .parser import document_full_text, document_token_estimate, load_document

log = logging.getLogger("rag")

CHUNK_TARGET_CHARS = 4200          # ~1200 tokens
CHUNK_OVERLAP_CHARS = 400
LONG_CONTEXT_MAX_TOKENS = 55_000    # below this, inject full text directly

_chroma_client = None
_collections: dict[str, Any] = {}

# Multilingual-safe stop-words (minimal English list; retrieval is semantic anyway)
_STOP = set("a an the of and or to in on for with is are was were be been this that "
            "it as at by from".split())


# ---------------------------------------------------------------------------
# ChromaDB setup
# ---------------------------------------------------------------------------

def _get_collection(doc_id: str):
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    if doc_id not in _collections:
        _collections[doc_id] = _chroma_client.get_or_create_collection(
            name=f"doc_{doc_id}",
            metadata={"hnsw:space": "cosine"},
        )
    return _collections[doc_id]


def drop_collection(doc_id: str) -> None:
    if doc_id in _collections:
        _collections.pop(doc_id)
    try:
        import chromadb
        global _chroma_client
        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _chroma_client.delete_collection(f"doc_{doc_id}")
    except Exception:                                       # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _clean_section_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_long_section(title: str, text: str, source: str) -> list[dict]:
    """Split a section longer than the target into overlapping chunks,
    preferring paragraph/sentence boundaries."""
    chunks: list[dict] = []
    if len(text) <= CHUNK_TARGET_CHARS:
        return [{"title": title, "text": _clean_section_text(text),
                 "source": source, "part": None}]

    paras = re.split(r"\n{2,}", text)
    cur: list[str] = []
    cur_len = 0
    part = 1
    for p in paras:
        p = p.strip()
        if not p:
            continue
        if cur_len + len(p) > CHUNK_TARGET_CHARS and cur:
            chunks.append({"title": title, "text": "\n\n".join(cur),
                           "source": source, "part": part})
            part += 1
            # start next chunk with overlap tail
            tail = cur[-1][-CHUNK_OVERLAP_CHARS:]
            cur = [tail] if tail else []
            cur_len = len(tail)
        cur.append(p)
        cur_len += len(p) + 2
    if cur:
        chunks.append({"title": title, "text": "\n\n".join(cur),
                       "source": source, "part": part})
    return chunks


async def ingest_document(doc_id: str) -> dict[str, Any]:
    """Chunk + embed + store a processed document. Returns ingest stats."""
    doc = load_document(doc_id)
    if not doc:
        raise ValueError(f"Document {doc_id} not found (process it first)")

    drop_collection(doc_id)
    col = _get_collection(doc_id)

    # Build chunks from sections
    chunks: list[dict[str, Any]] = []
    for sec in doc["sections"]:
        text = sec["text"]
        # append OCR text discovered for pages in this section's range
        chunks.extend(_split_long_section(sec["title"], text,
                                          sec.get("source", "")))
    # OCR pages that had no native text at all may be missing from sections;
    # add them as standalone chunks
    seen_pages = set()
    for ch in chunks:
        m = re.match(r"page (\d+)", ch.get("source") or "")
        if m:
            seen_pages.add(int(m.group(1)))
    for o in doc.get("ocr", []):
        if o["page"] not in seen_pages and o.get("ocr_text"):
            chunks.append({"title": f"Page {o['page']} (scanned)",
                           "text": o["ocr_text"],
                           "source": f"page {o['page']} (OCR)", "part": None})

    if not chunks:
        raise ValueError("No extractable content in document")

    # Embed + store
    texts = [c["text"] for c in chunks]
    embeddings = await embed_texts(texts, task="retrieval_document")

    ids = [f"{doc_id}_c{i:05d}" for i in range(len(chunks))]
    metas = []
    for c in chunks:
        metas.append({
            "title": c["title"][:200],
            "source": (c.get("source") or "")[:100],
            "part": c.get("part") or 0,
            "doc_id": doc_id,
        })
    col.add(ids=ids, embeddings=embeddings, documents=texts, metadata=metas)

    log.info("RAG ingested doc=%s: %d chunks", doc_id, len(chunks))
    return {"doc_id": doc_id, "chunks": len(chunks)}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

async def retrieve(
    doc_id: str,
    query: str,
    *,
    k: int = 6,
    with_context_note: bool = True,
) -> dict[str, Any]:
    """Hybrid retrieval for a query against a document.

    Returns:
      {
        mode: 'long_context' | 'vector',
        chunks: [{text, title, source, distance}]  (vector mode)
        full_text_available: bool,
        est_tokens: int
      }
    """
    doc = load_document(doc_id)
    if not doc:
        raise ValueError(f"Unknown doc_id {doc_id}")

    est_total = document_token_estimate(doc_id)
    full_text = None
    if est_total <= LONG_CONTEXT_MAX_TOKENS:
        full_text = document_full_text(doc_id)

    col = _get_collection(doc_id)
    n = col.count()
    if n == 0:
        # not ingested (shouldn't happen via API, but be safe)
        await ingest_document(doc_id)

    q_emb = (await embed_texts([query], task="retrieval_query"))[0]
    k_eff = min(k, max(1, col.count()))
    res = col.query(query_embeddings=[q_emb], n_results=k_eff,
                    include=["documents", "metadatas", "distances"])

    chunks = []
    for text, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                                 res["distances"][0]):
        chunks.append({
            "text": text,
            "title": meta.get("title", ""),
            "source": meta.get("source", ""),
            "distance": float(dist),
        })

    return {
        "mode": "long_context" if full_text is not None else "vector",
        "chunks": chunks,
        "full_text": full_text,
        "est_tokens": est_total,
    }


async def retrieve_for_focus(
    doc_id: str,
    focus: str,
    learner_request: str,
) -> dict[str, Any]:
    """Retrieval for 'teach me Chapter 4' style requests.

    Combines a focus match (chapter/section title matching in TOC) with
    semantic retrieval so we reliably grab the right chapter.
    """
    doc = load_document(doc_id)
    if not doc:
        raise ValueError(f"Unknown doc_id {doc_id}")

    # 1) direct TOC title match on the focus words (e.g. 'chapter 4')
    matched_sections: list[dict] = _match_toc(doc, focus)
    matched_texts = [s for s in matched_sections]

    est_total = document_token_estimate(doc_id)
    full_text = None
    matched_tokens = sum(estimate(s["text"]) for s in matched_texts)

    # If matched content is small enough, long-context inject just that scope
    if matched_texts and matched_tokens <= LONG_CONTEXT_MAX_TOKENS:
        return {
            "mode": "long_context",
            "scope": "matched",
            "full_text": _sections_text(matched_texts),
            "chunks": [],
            "est_tokens": matched_tokens,
            "citations": [f"{s['title']} ({s.get('source', '')})".strip()
                          for s in matched_texts],
        }

    # 2) else vector retrieval with the focus as query
    result = await retrieve(doc_id, f"{focus}. {learner_request}")
    result["mode"] = "vector"
    result["scope"] = "document"
    return result


def _match_toc(doc: dict, focus: str) -> list[dict]:
    """Fuzzy-match TOC/section titles against the focus string."""
    focus_l = focus.lower().strip()
    # normalize 'chapter 4', 'ch 4', 'chapter four', 'unit 2', roman numerals
    num_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                 "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                 "twelve": 12}
    m = re.search(r"(?:chapter|ch\.?|unit|part|lesson)\s*([0-9]+|one|two|three|"
                  r"four|five|six|seven|eight|nine|ten|eleven|twelve)", focus_l)
    want_num = None
    if m:
        t = m.group(1)
        want_num = num_words.get(t, None) if t.isalpha() else int(t)
    keyword = re.sub(
        r"(?:chapter|ch\.?|unit|part|lesson)\s*[0-9]+|about|on|teach|me|explain",
        "", focus_l).strip(" :,-.")

    sections = doc["sections"]
    if want_num is not None:
        # match titles like 'Chapter 4', '4. Electricity', 'IV. ...'
        for s in sections:
            t = s["title"].lower()
            if re.match(rf"^\s*(chapter|ch\.?|unit|part|lesson)?\s*{want_num}"
                        r"\b", t) or re.search(rf"\b{want_num}\s*[.:)-]", t):
                return [s] + _following_sections(sections, s, include_self=False)
        # roman numerals
        romans = {1: "i", 2: "ii", 3: "iii", 4: "iv", 5: "v", 6: "vi", 7: "vii",
                  8: "viii", 9: "ix", 10: "x", 11: "xi", 12: "xii"}
        if want_num in romans:
            rn = romans[want_num]
            for s in sections:
                t = s["title"].lower()
                if t.startswith(rn + " ") or t.startswith(rn + ".") or \
                   t.startswith(rn + ")"):
                    return [s] + _following_sections(sections, s, include_self=False)

    if keyword and len(keyword) >= 3:
        hits = [s for s in sections if keyword in s["title"].lower()]
        if hits:
            return hits
        # keyword in text but title match failed -> treat as title search in text
        hits = [s for s in sections if keyword in s["text"][:400].lower()]
        if hits:
            return hits
    return []


def _following_sections(sections: list[dict], sec: dict, include_self: bool = False
                         ) -> list[dict]:
    """All sections after a matched heading until the next same-or-higher
    level heading (chapter scope)."""
    idx = next(i for i, s in enumerate(sections) if s is sec)
    out = [sec] if include_self else []
    lvl = sec.get("level", 1)
    for s in sections[idx + 1:]:
        if s.get("level", 1) <= lvl and s.get("title", "").lower().startswith(
                ("chapter", "unit", "part")):
            break
        if s.get("level", 1) <= lvl and len(s.get("title", "")) < 70 and \
           re.match(r"^\s*(chapter|unit|part)\b", s["title"].lower()):
            break
        out.append(s)
    return out


def _sections_text(sections: list[dict]) -> str:
    parts = []
    for s in sections:
        parts.append(f"## {s['title']}\n{s['text']}")
    return "\n\n".join(parts)


def estimate(text: str) -> int:
    return max(16, int(len(text) / 3.2) + 8)
