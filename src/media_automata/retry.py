from __future__ import annotations

from media_automata.schemas import ErrorCode

RETRYABLE_ERRORS = frozenset(
    {
        ErrorCode.COMPOSER_NOT_FOUND,
        ErrorCode.MEDIA_UPLOAD_FAILED,
        ErrorCode.NETWORK_TIMEOUT,
        ErrorCode.UNKNOWN_UI_STATE,
        ErrorCode.INTERNAL_ERROR,
    }
)


def is_retryable_error(error_code: ErrorCode | str | None) -> bool:
    if error_code is None:
        return False
    try:
        normalized = ErrorCode(error_code)
    except ValueError:
        return False
    return normalized in RETRYABLE_ERRORS


def exponential_backoff_seconds(attempt_count: int, *, base_seconds: int = 30, cap_seconds: int = 300) -> int:
    normalized_attempt = max(attempt_count, 1)
    return min(base_seconds * (2 ** (normalized_attempt - 1)), cap_seconds)
