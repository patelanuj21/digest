import hashlib
import base64
import secrets


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(32)  # 43 chars, within RFC 7636 bounds


def generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


