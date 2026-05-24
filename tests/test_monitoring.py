from media_automata.monitoring import openwa_session_ready, openwa_session_state


def test_openwa_session_state_reads_nested_session_payload() -> None:
    payload = {"data": {"session": {"status": "READY"}}}

    assert openwa_session_state(payload) == "READY"
    assert openwa_session_ready(payload) is True


def test_openwa_session_ready_rejects_non_ready_state() -> None:
    payload = {"session": {"state": "STARTING"}}

    assert openwa_session_state(payload) == "STARTING"
    assert openwa_session_ready(payload) is False
