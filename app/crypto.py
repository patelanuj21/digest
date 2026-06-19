from cryptography.fernet import Fernet, InvalidToken


def encrypt(value: str, key: bytes) -> bytes:
    return Fernet(key).encrypt(value.encode())


def decrypt(value: bytes, key: bytes) -> str:
    try:
        return Fernet(key).decrypt(value).decode()
    except InvalidToken:
        raise ValueError("Failed to decrypt value — key may have changed")
