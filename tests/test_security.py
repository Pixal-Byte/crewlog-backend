import pytest
from crewlog.security import make_token, check_token, hash_ip

SECRET = "x" * 40
T0 = 1_732_271_400
MIN, MAX = 3, 3600

def check(token, now):
    return check_token(SECRET, token, now, MIN, MAX)

@pytest.mark.parametrize("now", [T0 + MIN, T0 + MAX])
def test_token_is_ok_inside_the_window(now):
    token = make_token(SECRET, T0)
    assert check(token, now) == "ok"

@pytest.mark.parametrize("now", [T0 - 10, T0, T0 + MIN - 1, T0 + MIN - 2])
def test_token_is_rejected_if_too_fast(now):
    token = make_token(SECRET, T0)
    assert check(token, now) == "too_fast"

def test_make_token_ignores_the_fractional_second():
    assert make_token(SECRET, T0 + 0.9) == make_token(SECRET, T0)

@pytest.mark.parametrize("now", [T0 + MAX + 1, T0 + MAX + 1000])
def test_token_is_rejected_if_expired(now):
    token = make_token(SECRET, T0)
    assert check(token, now) == "expired"

def test_tampered_timestamp_is_rejected():
    token = make_token(SECRET, T0)
    _, _, signature = token.partition(".")
    tampered = f"{T0 - 100}.{signature}"
    assert check(tampered, T0 + 1) == "bad_signature"

def test_signature_is_checked_before_age():
    token = make_token(SECRET, T0)
    _, _, signature = token.partition(".")
    tampered = f"{T0 + 59}.{signature}"
    assert check(tampered, T0 + 60) == "bad_signature"

def test_wrong_secret():
    token = make_token("other_secret", T0)
    assert check(token, T0 + MIN) == "bad_signature"

@pytest.mark.parametrize("garbage", [
    "",
    "abc",
    "1.2.3",
    "x.y",
    "é.é",
    "123",
    "1.",
    "." + "a" * 64,
    "9" * 5000 + ".x"
])
def test_garbage(garbage):
    assert check(garbage, T0) in ("malformed", "bad_signature")


def test_same_ip_has_the_same_hash():
    hash_a = hash_ip(SECRET, "1.1.1.1")
    hash_b = hash_ip(SECRET, "1.1.1.1")
    assert hash_a == hash_b

def test_different_ips_have_different_hashes():
    hash_a = hash_ip(SECRET, "1.1.1.1")
    hash_b = hash_ip(SECRET, "8.8.8.8")
    assert hash_a != hash_b

def test_different_secrets_have_different_hashes():
    hash_a = hash_ip(SECRET,   "1.1.1.1")
    hash_b = hash_ip("y" * 40, "1.1.1.1")
    assert hash_a != hash_b

def test_output_is_a_sha256_hex_digest():
    digest = hash_ip(SECRET, "1.1.1.1")
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")