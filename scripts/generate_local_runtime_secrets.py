from __future__ import annotations

import json
import os
import secrets
import stat
import sys
from pathlib import Path
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_AUTH_KID = "finaudit-local-key-v1"
_SECRET_NAMES = (
    "secret_key",
    "database_url",
    "redis_url",
    "celery_broker_url",
    "celery_result_backend",
    "postgres_password",
    "redis_password",
    "redis_config",
    "minio_root_user",
    "minio_root_password",
    "minio_access_key",
    "minio_secret_key",
    "minio_worker_access_key",
    "minio_worker_secret_key",
    "llm_api_key",
    "embedding_api_key",
    "metrics_internal_token",
    "auth_jwt_private_key",
    "auth_jwt_public_keyring",
    "bootstrap_admin_password",
)


class SecretGenerationError(RuntimeError):
    pass


def _write_exclusive(directory: Path, name: str, value: bytes) -> None:
    descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            descriptor = -1
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _token(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def generate(output_directory: Path) -> None:
    if not output_directory.is_absolute() or output_directory.is_symlink():
        raise SecretGenerationError("RUNTIME_DIRECTORY_INVALID")
    info = output_directory.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise SecretGenerationError("RUNTIME_DIRECTORY_INVALID")
    if any((output_directory / name).exists() for name in _SECRET_NAMES):
        raise SecretGenerationError("RUNTIME_SECRET_ALREADY_EXISTS")

    postgres_password = _token()
    redis_password = _token()
    minio_root_user = "finauditroot" + secrets.token_hex(6)
    minio_access_key = "finauditapp" + secrets.token_hex(6)
    minio_worker_access_key = "finauditworker" + secrets.token_hex(6)

    auth_private_key = Ed25519PrivateKey.generate()
    auth_private_pem = auth_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    auth_public_pem = (
        auth_private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )

    encoded_postgres_password = quote(postgres_password, safe="")
    encoded_redis_password = quote(redis_password, safe="")
    values: dict[str, bytes] = {
        "secret_key": _token(48).encode("utf-8"),
        "database_url": (
            "postgresql+psycopg://finaudit:"
            f"{encoded_postgres_password}@postgresql:5432/finaudit"
        ).encode(),
        "redis_url": f"redis://:{encoded_redis_password}@redis:6379/0".encode(),
        "celery_broker_url": f"redis://:{encoded_redis_password}@redis:6379/0".encode(),
        "celery_result_backend": f"redis://:{encoded_redis_password}@redis:6379/1".encode(),
        "postgres_password": postgres_password.encode("utf-8"),
        "redis_password": redis_password.encode("utf-8"),
        "redis_config": (
            "bind 0.0.0.0\n"
            "protected-mode yes\n"
            "port 6379\n"
            "appendonly yes\n"
            "appendfsync everysec\n"
            f"requirepass {redis_password}\n"
        ).encode(),
        "minio_root_user": minio_root_user.encode("utf-8"),
        "minio_root_password": _token().encode("utf-8"),
        "minio_access_key": minio_access_key.encode("utf-8"),
        "minio_secret_key": _token().encode("utf-8"),
        "minio_worker_access_key": minio_worker_access_key.encode("utf-8"),
        "minio_worker_secret_key": _token().encode("utf-8"),
        "llm_api_key": ("disabled-local-" + _token()).encode("utf-8"),
        "embedding_api_key": ("disabled-local-" + _token()).encode("utf-8"),
        "metrics_internal_token": _token().encode("utf-8"),
        "auth_jwt_private_key": auth_private_pem,
        "auth_jwt_public_keyring": json.dumps(
            {_AUTH_KID: auth_public_pem},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        "bootstrap_admin_password": _token(36).encode("utf-8"),
    }
    if set(values) != set(_SECRET_NAMES):
        raise SecretGenerationError("RUNTIME_SECRET_SET_INVALID")
    for name in _SECRET_NAMES:
        _write_exclusive(output_directory, name, values[name])


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            raise SecretGenerationError("ARGUMENTS_NOT_SUPPORTED")
        raw_directory = os.environ.get("FINAUDIT_RUNTIME_SECRET_DIR")
        if not raw_directory:
            raise SecretGenerationError("RUNTIME_DIRECTORY_REQUIRED")
        generate(Path(raw_directory))
    except (OSError, SecretGenerationError):
        print("LOCAL_RUNTIME_SECRETS=FAIL")
        return 1
    except Exception:
        print("LOCAL_RUNTIME_SECRETS=FAIL")
        return 1
    print("LOCAL_RUNTIME_SECRETS=PASS")
    print(f"LOCAL_RUNTIME_SECRET_FILES={len(_SECRET_NAMES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
