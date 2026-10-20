from uuid import uuid4

from app.brain.chunking import MAX_WORDS, SourceBlock, chunk_blocks


def block(text: str, ordinal: int = 1) -> SourceBlock:
    return SourceBlock(
        id=uuid4(),
        ordinal=ordinal,
        block_type="line",
        text=text,
        locator={"kind": "markdown_line", "line": ordinal, "heading_path": ["Demo"]},
    )


def test_chunking_is_deterministic_and_preserves_exact_references() -> None:
    source = [block("permit pending", 1), block("material delivery delayed", 2)]

    first = chunk_blocks(source)
    second = chunk_blocks(source)

    assert [item.content_hash for item in first] == [item.content_hash for item in second]
    assert first[0].text == "permit pending\nmaterial delivery delayed"
    assert [ref.block_id for ref in first[0].source_references] == [item.id for item in source]
    assert first[0].source_references[0].locator["line"] == 1


def test_oversized_block_splits_with_character_offsets() -> None:
    source = block(" ".join(f"word-{index}" for index in range(MAX_WORDS + 25)))

    chunks = chunk_blocks([source])

    assert len(chunks) == 2
    assert all(len(chunk.text.split()) <= MAX_WORDS for chunk in chunks)
    assert chunks[0].source_references[0].start_character == 0
    assert chunks[0].source_references[0].end_character is not None
    assert chunks[1].source_references[0].start_character is not None


def test_empty_blocks_do_not_create_search_chunks() -> None:
    assert chunk_blocks([block("   ")]) == []
