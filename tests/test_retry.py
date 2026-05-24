from media_automata.retry import exponential_backoff_seconds, is_non_retryable_error, is_retryable_error
from media_automata.schemas import ErrorCode


def test_retry_classification() -> None:
    assert is_retryable_error(ErrorCode.NETWORK_TIMEOUT)
    assert is_retryable_error(ErrorCode.UNKNOWN_UI_STATE)
    assert is_non_retryable_error(ErrorCode.LOGIN_REQUIRED)
    assert is_non_retryable_error(ErrorCode.CAPTCHA_OR_VERIFICATION)


def test_exponential_backoff_is_capped() -> None:
    assert exponential_backoff_seconds(1, base_seconds=10, max_seconds=60) == 10
    assert exponential_backoff_seconds(3, base_seconds=10, max_seconds=60) == 40
    assert exponential_backoff_seconds(10, base_seconds=10, max_seconds=60) == 60
