from pathlib import Path

from media_automata.storage import LocalStorage


def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    storage_uri, digest = storage.save_text("hello", filename="result.txt", prefix="artifacts")

    assert storage_uri.startswith("local://artifacts/")
    assert len(digest) == 64
    assert storage.resolve(storage_uri).read_text() == "hello"


def test_local_storage_uses_mime_extension_when_filename_has_no_suffix(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    storage_uri, _ = storage.save_bytes(
        b"jpeg bytes",
        filename="whatsapp-media",
        prefix="assets",
        mime_type="image/jpeg",
    )

    assert storage_uri.endswith(".jpg")
