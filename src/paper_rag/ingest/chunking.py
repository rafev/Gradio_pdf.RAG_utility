"""Section-aware chunking of paper pages.

Chunks never cross page boundaries (so citations can name a page), carry the most recent
section heading, and stop at the References/Bibliography section (reference lists pollute
semantic search; they are still sent to Claude for citation extraction).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(
    r"""^\s*(
        (?:\d{1,2}(?:\.\d{1,2}){0,2}\.?\s+[A-Z][A-Za-z0-9 ,:;&()'\-/]{2,80})   # 3.1 Method Overview
      | (?:[IVX]{1,5}\.\s+[A-Z][A-Za-z0-9 ,:;&()'\-/]{2,80})                  # IV. EXPERIMENTS
      | (?:Abstract|Introduction|Related\ Work|Background|Methods?|Methodology|Experiments?
          |Results|Discussion|Conclusions?|Limitations|Acknowledg(?:e)?ments?|Appendix(?:\ [A-Z])?)
    )\s*$""",
    re.VERBOSE | re.IGNORECASE,
)
_REFERENCES_RE = re.compile(r"^\s*(?:\d{1,2}\.?\s+)?(References|Bibliography|Works Cited)\s*$", re.IGNORECASE)
_SEPARATORS = ("\n\n", "\n", ". ", " ")
_MIN_SEGMENT = 200


@dataclass(frozen=True)
class Chunk:
    paper_id: str
    chunk_n: int
    text: str
    page: int
    section: str

    @property
    def id(self) -> str:
        return f"{self.paper_id}:{self.chunk_n}"


def clean_text(text: str) -> str:
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # de-hyphenate line wraps
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)  # unwrap single newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text: str, size: int, overlap: int, separators: tuple[str, ...] = _SEPARATORS) -> list[str]:
    """Recursive character splitter: prefer paragraph, then line, sentence, word boundaries."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    sep = next((s for s in separators if s in text), None)
    if sep is None:  # no separators left: hard split
        step = max(size - overlap, 1)
        return [text[i : i + size] for i in range(0, len(text), step)]

    remaining = separators[separators.index(sep) + 1 :]
    pieces: list[str] = []
    for part in text.split(sep):
        if len(part) > size:
            # No overlap inside the recursion: the merge loop below adds it once between chunks.
            pieces.extend(split_text(part, size, 0, remaining))
        elif part.strip():
            pieces.append(part)

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{sep}{piece}" if current else piece
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
        tail = _overlap_tail(current, overlap)
        current = f"{tail}{sep}{piece}" if tail and len(tail) + len(sep) + len(piece) <= size else piece
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0 or not text:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


def _segments(page_text: str, section: str) -> tuple[list[tuple[str, str]], str, bool]:
    """Split one page into (section, raw_text) segments. Returns (segments, last_section, hit_references)."""
    segments: list[tuple[str, str]] = []
    buf: list[str] = []
    for line in page_text.splitlines():
        stripped = line.strip()
        if _REFERENCES_RE.match(stripped):
            if buf:
                segments.append((section, "\n".join(buf)))
            return segments, "References", True
        if _HEADING_RE.match(stripped) and len(stripped.split()) <= 12:
            if buf:
                segments.append((section, "\n".join(buf)))
                buf = []
            section = re.sub(r"\s+", " ", stripped)
            continue
        buf.append(line)
    if buf:
        segments.append((section, "\n".join(buf)))
    return segments, section, False


def chunk_pages(paper_id: str, pages: list[str], size: int = 1000, overlap: int = 150) -> list[Chunk]:
    chunks: list[Chunk] = []
    section = "Front matter"
    for page_n, page_text in enumerate(pages, start=1):
        segments, section, hit_refs = _segments(page_text, section)

        # Fold tiny segments (e.g. a heading's first line before a figure) into the next one.
        merged: list[tuple[str, str]] = []
        carry = ""
        for seg_section, seg_text in segments:
            text = clean_text(f"{carry}\n\n{seg_text}" if carry else seg_text)
            if len(text) < _MIN_SEGMENT:
                carry = text
                continue
            carry = ""
            merged.append((seg_section, text))
        if carry:
            if merged:
                merged[-1] = (merged[-1][0], f"{merged[-1][1]}\n\n{carry}")
            else:
                merged.append((section, carry))

        for seg_section, text in merged:
            for piece in split_text(text, size, overlap):
                if len(piece) >= 40:
                    chunks.append(Chunk(paper_id, len(chunks), piece, page_n, seg_section))
        if hit_refs:
            break
    return chunks
