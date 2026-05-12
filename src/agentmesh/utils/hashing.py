from hashlib import sha256
from pathlib import Path


def hash_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())
