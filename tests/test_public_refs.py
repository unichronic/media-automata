from media_automata.public_refs import (
    extract_public_ref,
    format_public_ref,
    normalize_prefixed_ref,
)


def test_format_public_ref_uses_short_suffix() -> None:
    assert format_public_ref("job_a788aa854337400f83e780cdb88ab5c5") == "#a788aa85"
    assert format_public_ref("todo_abc123def456") == "#abc123de"


def test_normalize_prefixed_ref_accepts_hash_or_bare_hex() -> None:
    assert normalize_prefixed_ref("#a788aa85", "job") == "job_a788aa85"
    assert normalize_prefixed_ref("a788aa85", "job") == "job_a788aa85"
    assert normalize_prefixed_ref("job_a788aa85", "job") == "job_a788aa85"


def test_extract_public_ref_from_commands() -> None:
    assert extract_public_ref("/status #a788aa85", prefix="job") == "a788aa85"
    assert extract_public_ref("/retry a788aa85 linkedin", prefix="job") == "a788aa85"
    assert extract_public_ref("/todo done #abc123de linkedin", prefix="todo") == "abc123de"
