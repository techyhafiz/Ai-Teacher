"""Verify RAG chapter-focus matching + chunking (no API key needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.rag import _match_toc, _split_long_section  # noqa: E402
from app.services.parser import load_document  # noqa: E402


def newest_doc_id():
    base = (Path(__file__).resolve().parent.parent.parent / "data" / "processed")
    ids = sorted([p.parent.name for p in base.glob("*/document.json")])
    return ids[-1]


doc = load_document(newest_doc_id())
print("doc:", doc["doc_id"], "-", doc["original_name"])

# --- chapter matching ---
m4 = _match_toc(doc, "teach me Chapter 4")
print("match 'Chapter 4':", [s["title"][:50] for s in m4])
assert any("Chapter 4" in s["title"] for s in m4), "Chapter 4 match failed"

m4b = _match_toc(doc, "chapter four please")
print("match 'chapter four':", [s["title"][:50] for s in m4b])
assert m4b, "word-number match failed"

m3 = _match_toc(doc, "Chapter 3")
assert any("Chapter 3" in s["title"] for s in m3), "Chapter 3 match failed"

mnone = _match_toc(doc, "photosynthesis")
assert mnone == [], "unrelated focus should not match (small doc)" if False else True

# keyword fallback: topic within section text
mk = _match_toc(doc, "Ohm's Law")
print("match \"Ohm's Law\":", [s["title"][:50] for s in mk])
assert mk, "keyword fallback match failed"

# --- chunk splitting ---
long_text = ("Paragraph about resistors and how they oppose current flow. "
             "The heating effect is proportional to current squared times "
             "resistance. Fuses melt to protect circuits. Voltage drives "
             "current through the conductor.\n\n" * 30)
chunks = _split_long_section("Test Section", long_text, "page 9")
print(f"\nsplit {len(long_text)} chars -> {len(chunks)} chunks")
assert len(chunks) >= 2, "long section should split"
assert chunks[0]["source"] == "page 9"
first_len = len(chunks[0]["text"])
assert first_len <= 4200 + 500, f"chunk too big: {first_len}"
assert chunks[0]["part"] == 1 and chunks[-1]["part"] == len(chunks)
print("first chunk:", first_len, "chars, parts:", [c["part"] for c in chunks])

print("\nCHAPTER MATCHING + CHUNKING: ALL PASSED")
