"""Fernet encryption for the stored SQL Server password and LLM API key.

The key is generated once into `<data_dir>/secret.key`.
"""

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


def init_cipher(data_dir: Path) -> None:
    global _fernet
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / "secret.key"
    if not key_path.exists():
        key_path.write_bytes(Fernet.generate_key())
    _fernet = Fernet(key_path.read_bytes().strip())


def _cipher() -> Fernet:
    if _fernet is None:
        raise RuntimeError("Şifreleme anahtarı yüklenmedi.")
    return _fernet


def encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str | None) -> str | None:
    """Plain text, or None when nothing is stored or the key no longer matches."""
    if not token:
        return None
    try:
        return _cipher().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
