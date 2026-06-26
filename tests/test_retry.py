from media_automata.retry import exponential_backoff_seconds, is_retryable_error
from media_automata.schemas import ErrorCode


def test_retryable_errors_are_limited_to_transient_failures() -> None:
    assert is_retryable_error(ErrorCode.NETWORK_TIMEOUT)
    assert is_retryable_error(ErrorCode.MEDIA_UPLOAD_FAILED)
    assert is_retryable_error("UNKNOWN_UI_STATE")
    assert not is_retryable_error(ErrorCode.LOGIN_REQUIRED)
    assert not is_retryable_error(ErrorCode.CAPTCHA_OR_VERIFICATION)
    assert not is_retryable_error(ErrorCode.CONTENT_REJECTED)
    assert not is_retryable_error(None)


def test_exponential_backoff_is_bounded() -> None:
    assert exponential_backoff_seconds(1) == 30
    assert exponential_backoff_seconds(2) == 60
    assert exponential_backoff_seconds(3) == 120
    assert exponential_backoff_seconds(99) == 300
