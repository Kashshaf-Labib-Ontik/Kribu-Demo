"""Deterministic, structure-aware chunking over Iteration 6 normalized blocks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.brain.contracts import ChunkDraft, SourceReference

CHUNKER_VERSION = "structure-v1"
TARGET_WORDS = 400
MAX_WORDS = 600
OVERLAP_WORDS = 60
_WORD = re.compile(r"\S+")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class SourceBlock:
    id: UUID
    ordinal: int
    block_type: str
    text: str
    locator: dict[str, Any]


@dataclass(frozen=True)
class _Piece:
    text: str
    reference: SourceReference


def chunk_blocks(blocks: list[SourceBlock]) -> list[ChunkDraft]:
    """Pack ordered blocks while retaining every exact locator and split offset."""
    pieces = [piece for block in blocks for piece in _split_block(block)]
    if not pieces:
        return []

    chunks: list[ChunkDraft] = []
    current: list[_Piece] = []
    current_words = 0
    for piece in pieces:
        piece_words = _word_count(piece.text)
        if current and current_words + piece_words > MAX_WORDS:
            chunks.append(_draft(len(chunks) + 1, current))
            current = _overlap(current)
            current_words = sum(_word_count(item.text) for item in current)
        current.append(piece)
        current_words += piece_words
        if current_words >= TARGET_WORDS:
            chunks.append(_draft(len(chunks) + 1, current))
            current = _overlap(current)
            current_words = sum(_word_count(item.text) for item in current)

    if current:
        candidate = _draft(len(chunks) + 1, current)
        if not chunks or candidate.content_hash != chunks[-1].content_hash:
            chunks.append(candidate)
    return chunks


def _split_block(block: SourceBlock) -> list[_Piece]:
    text = block.text.strip()
    if not text:
        return []
    if _word_count(text) <= MAX_WORDS:
        return [_piece(block, text, 0, len(text))]

    pieces: list[_Piece] = []
    cursor = 0
    buffer = ""
    buffer_start = 0
    for sentence in _SENTENCE_BOUNDARY.split(text):
        sentence_start = text.find(sentence, cursor)
        sentence_end = sentence_start + len(sentence)
        cursor = sentence_end
        if _word_count(sentence) > MAX_WORDS:
            if buffer:
                pieces.append(_piece(block, buffer, buffer_start, sentence_start))
                buffer = ""
            pieces.extend(_split_by_words(block, sentence, sentence_start))
            continue
        combined = f"{buffer} {sentence}".strip()
        if buffer and _word_count(combined) > MAX_WORDS:
            pieces.append(_piece(block, buffer, buffer_start, sentence_start))
            buffer = sentence
            buffer_start = sentence_start
        else:
            if not buffer:
                buffer_start = sentence_start
            buffer = combined
    if buffer:
        pieces.append(_piece(block, buffer, buffer_start, len(text)))
    return pieces


def _split_by_words(block: SourceBlock, text: str, offset: int) -> list[_Piece]:
    matches = list(_WORD.finditer(text))
    pieces: list[_Piece] = []
    for start in range(0, len(matches), MAX_WORDS):
        group = matches[start : start + MAX_WORDS]
        first, last = group[0], group[-1]
        pieces.append(
            _piece(
                block,
                text[first.start() : last.end()],
                offset + first.start(),
                offset + last.end(),
            )
        )
    return pieces


def _piece(block: SourceBlock, text: str, start: int, end: int) -> _Piece:
    return _Piece(
        text=text.strip(),
        reference=SourceReference(
            block_id=block.id,
            locator=block.locator,
            start_character=start if start > 0 or end < len(block.text.strip()) else None,
            end_character=end if start > 0 or end < len(block.text.strip()) else None,
        ),
    )


def _overlap(pieces: list[_Piece]) -> list[_Piece]:
    selected: list[_Piece] = []
    words = 0
    for piece in reversed(pieces):
        count = _word_count(piece.text)
        remaining = OVERLAP_WORDS - words
        if count > remaining:
            if remaining > 0:
                matches = list(_WORD.finditer(piece.text))[-remaining:]
                first, last = matches[0], matches[-1]
                base = piece.reference.start_character or 0
                selected.append(
                    _Piece(
                        text=piece.text[first.start() : last.end()],
                        reference=SourceReference(
                            block_id=piece.reference.block_id,
                            locator=piece.reference.locator,
                            start_character=base + first.start(),
                            end_character=base + last.end(),
                        ),
                    )
                )
            break
        selected.append(piece)
        words += count
        if words >= OVERLAP_WORDS:
            break
    return list(reversed(selected))


def _draft(ordinal: int, pieces: list[_Piece]) -> ChunkDraft:
    text = "\n".join(piece.text for piece in pieces).strip()
    references: list[SourceReference] = []
    seen: set[tuple[UUID, int | None, int | None]] = set()
    for piece in pieces:
        key = (
            piece.reference.block_id,
            piece.reference.start_character,
            piece.reference.end_character,
        )
        if key not in seen:
            seen.add(key)
            references.append(piece.reference)
    return ChunkDraft(
        ordinal=ordinal,
        text=text,
        source_references=references,
        content_hash=hashlib.sha256(text.encode("utf-8")).digest(),
    )


def _word_count(text: str) -> int:
    return len(_WORD.findall(text))
