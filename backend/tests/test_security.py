"""API keys never appear in responses or logs."""

import logging

import litellm

from tests.conftest import KEY_1, KEY_2, chat


def test_keys_never_in_responses(client, provider):
    provider.fail(KEY_1, litellm.RateLimitError(f"quota exceeded for ?key={KEY_1}", llm_provider="gemini", model="m"))
    provider.fail(KEY_2, litellm.ServiceUnavailableError(f"down for key {KEY_2}", llm_provider="gemini", model="m"))
    texts = [
        chat(client, "s", "hello").text,
        client.get("/health").text,
        client.get("/sessions/s/messages").text,
    ]
    for text in texts:
        assert KEY_1 not in text and KEY_2 not in text


def test_keys_are_redacted_from_logs(client, provider, caplog):
    caplog.set_level(logging.WARNING)
    provider.fail(KEY_1, litellm.RateLimitError(f"quota exceeded for ?key={KEY_1}", llm_provider="gemini", model="m"))
    chat(client, "s", "hello")
    logging.getLogger("some.library").error("leaked %s and %s", KEY_1, KEY_2)
    assert KEY_1 not in caplog.text and KEY_2 not in caplog.text
    assert "<key_1>" in caplog.text and "<key_2>" in caplog.text


def test_key_repr_hides_secret(make_settings):
    keys = make_settings().keys
    assert all(k.secret not in repr(k) for k in keys)
