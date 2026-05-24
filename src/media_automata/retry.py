from __future__ import annotations

from media_automata.schemas import ErrorCode

RETRYABLE_ERRORS = {
    ErrorCode.COMPOSER_NOT_FOUND,
    ErrorCode.MEDIA_UPLOAD_FAILED,
    ErrorCode.NETWORK_TIMEOUT,
    ErrorCode.UNKNOWN_UI_STATE,
    ErrorCode.INTERNAL_ERROR,
}

NON_RETRYABLE_ERRORS = {
    ErrorCode.LOGIN_REQUIRED,
    ErrorCode.CAPTCHA_OR_VERIFICATION,
    ErrorCode.CONTENT_REJECTED,
    ErrorCode.PUBLISH_BUTTON_DISABLED,
}


def is_retryable_error(error_code: ErrorCode | None) -> bool:
    if error_code is None:
        return False
    return error_code in RETRYABLE_ERRORS


def is_non_retryable_error(error_code: ErrorCode | None) -> bool:
    if error_code is None:
        return False
    return error_code in NON_RETRYABLE_ERRORS


def exponential_backoff_seconds(attempt_count: int, *, base_seconds: int = 30, max_seconds: int = 900) -> int:
    attempt = max(attempt_count, 1)
    return min(base_seconds * (2 ** (attempt - 1)), max_seconds)
