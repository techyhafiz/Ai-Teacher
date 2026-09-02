"""Verify document structure detection end-to-end (no API key needed)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.parser import process_document, load_document  # noqa: E402

PDF = (Path(__file__).resolve().parent.parent.parent / "data" / "uploads"
       / "test_textbook.pdf")


async def main():
    rec = await process_document(PDF, "test_textbook.pdf")
    print("sections:")
    for s in rec["sections"]:
        print(f"  [{s['id']}] {s['title'][:60]} ({s['source']}) "
              f"- {len(s['text'])} chars")
    print("toc entries:", len(rec["toc"]))
    print("stats:", rec["stats"])

    # structure assertions
    titles = [s["title"] for s in rec["sections"]]
    assert any("Chapter 3" in t for t in titles), "Chapter 3 heading missing"
    assert any("Chapter 4" in t for t in titles), "Chapter 4 heading missing"
    ch4 = next(s for s in rec["sections"] if "Chapter 4" in s["title"])
    assert "Ohm" in ch4["text"] or "Ohm's Law" in ch4["text"], "Ohm content missing"
    assert "V = I" in ch4["text"], "equation text missing"
    print("\nSTRUCTURE DETECTION: ALL ASSERTIONS PASSED")

    # reload from disk
    rec2 = load_document(rec["doc_id"])
    assert rec2["doc_id"] == rec["doc_id"]
    print("PERSISTENCE: document.json reload OK")


asyncio.run(main())
