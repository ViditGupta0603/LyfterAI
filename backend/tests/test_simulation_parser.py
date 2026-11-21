from app.simulation import parse_simulation_header

KEYS = ["key_1", "key_2"]


def test_single_and_multiple_pairs():
    assert parse_simulation_header("key_1=429", KEYS) == {"key_1": 429}
    assert parse_simulation_header("key_1=429,key_2=500", KEYS) == {"key_1": 429, "key_2": 500}


def test_wildcard_expands_to_every_key():
    assert parse_simulation_header("*=503", KEYS) == {"key_1": 503, "key_2": 503}


def test_whitespace_and_case_are_tolerated():
    assert parse_simulation_header(" KEY_1 = 502 ", KEYS) == {"key_1": 502}


def test_invalid_parts_are_dropped():
    assert parse_simulation_header("abc,key_9=429,key_1=418,key_2=x,=500", KEYS) == {}


def test_later_pairs_override_earlier():
    assert parse_simulation_header("key_1=429,key_1=500", KEYS) == {"key_1": 500}
    assert parse_simulation_header("*=429,key_2=502", KEYS) == {"key_1": 429, "key_2": 502}


def test_empty_header():
    assert parse_simulation_header(None, KEYS) == {}
    assert parse_simulation_header("", KEYS) == {}
