from io import BytesIO

import pytest
from PIL import Image

from media_automata.media import IMAGE_MAX_BYTES, inspect_media, validate_media_size


def test_inspect_media_extracts_image_dimensions() -> None:
    buffer = BytesIO()
    Image.new("RGB", (3, 2), color="white").save(buffer, format="PNG")

    metadata = inspect_media(buffer.getvalue(), "image/png")

    assert metadata.width == 3
    assert metadata.height == 2
    assert metadata.duration_seconds is None


def test_validate_media_size_rejects_oversized_image() -> None:
    with pytest.raises(ValueError, match="exceeds limit"):
        validate_media_size(b"x" * (IMAGE_MAX_BYTES + 1), "image/png")
