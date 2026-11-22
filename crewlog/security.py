import hmac, hashlib

def _sign(secret: str, issued: int) -> str:
    return hmac.new(secret.encode(), f"form:{issued}".encode(), hashlib.sha256).hexdigest()

def make_token(secret: str, now: float) -> str:
    issued = int(now)
    return f"{issued}.{_sign(secret, issued)}"

def check_token(secret: str, token: str, now: float, min_age: float, max_age: float) -> str:
    issued_text, _, signature = token.partition(".")
    if not (issued_text.isascii() and issued_text.isdigit() and len(issued_text) <= 12 and signature):
        return "malformed"
    issued = int(issued_text)

    expected = _sign(secret, int(issued))
    if not hmac.compare_digest(signature.encode(), expected.encode()):
        return "bad_signature"

    age = now - issued
    if age < min_age:
        return "too_fast"
    elif age > max_age:
        return "expired"

    return "ok"