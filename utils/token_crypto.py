import hashlib
import hmac

from cryptography.fernet import Fernet

import config


def _get_fernet() -> Fernet:
    key = getattr(config, "BOT_TOKEN_ENCRYPTION_KEY", None)
    if not key:
        raise RuntimeError(
            "BOT_TOKEN_ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_token(token: str) -> str:
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(token_encrypted: str) -> str:
    return _get_fernet().decrypt(token_encrypted.encode()).decode()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mask_token(token: str) -> str:
    bot_id, _, secret = token.partition(":")
    return f"{bot_id}:{secret[:2]}…{secret[-3:]}" if secret else "***"


def webhook_secret(storefront_id: int) -> str:
    key = getattr(config, "BOT_TOKEN_ENCRYPTION_KEY", "") or ""
    digest = hmac.new(key.encode(), f"storefront:{storefront_id}".encode(), hashlib.sha256)
    return digest.hexdigest()
