from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Mapping
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from minio import Minio  # noqa: E402
from minio.error import S3Error  # noqa: E402

from app.adapters.minio_quarantine import (  # noqa: E402
    MinioQuarantineAdapter,
    QuarantineObject,
    _build_http_client,
)
from app.core.config import Settings  # noqa: E402
from app.services.file_service import prepare_quarantine_intake  # noqa: E402

GATE_ENV = "FINAUDIT_LOCAL_MINIO_RESTART_PERSISTENCE"
GATE_VALUE = "VERIFY_SYNTHETIC_RESTART_PERSISTENCE_V1"
CLEANUP_REQUIRED_EXIT_CODE = 2
LOCAL_ENDPOINT = "http://127.0.0.1:9000"
LOCAL_AUTHORITY = "127.0.0.1:9000"
QUARANTINE_BUCKET = "quarantine"
MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "NoSuchObject"})
ORGANIZATION_ID = UUID("93000000-0000-4000-8000-000000000001")
FILE_ID = UUID("94000000-0000-4000-8000-000000000001")
PAYLOAD = b"%PDF-1.7\nsynthetic local MinIO restart persistence v1"
BUCKET_ENV = (
    ("MINIO_BUCKET_QUARANTINE", "quarantine"),
    ("MINIO_BUCKET_ORIGINALS", "originals"),
    ("MINIO_BUCKET_ASSETS", "assets"),
    ("MINIO_BUCKET_PREVIEWS", "previews"),
    ("MINIO_BUCKET_REPORTS", "reports"),
    ("MINIO_BUCKET_EXPORTS", "exports"),
    ("MINIO_BUCKET_TEMP", "temp"),
)


class RestartPersistenceError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RestartPersistenceConfig:
    settings: Settings = field(repr=False)
    root_user: str = field(repr=False)
    root_password: str = field(repr=False)


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value:
        raise RestartPersistenceError(f"MISSING_{name}")
    return value


def load_config(environment: Mapping[str, str]) -> RestartPersistenceConfig:
    if _required(environment, GATE_ENV) != GATE_VALUE:
        raise RestartPersistenceError("GATE_CONFIRMATION_INVALID")
    if (
        _required(environment, "APP_ENV") != "local"
        or _required(environment, "MINIO_ENDPOINT") != LOCAL_ENDPOINT
        or _required(environment, "MINIO_SECURE").lower() != "false"
        or any(
            _required(environment, name) != expected for name, expected in BUCKET_ENV
        )
    ):
        raise RestartPersistenceError("LOCAL_PROFILE_INVALID")

    root_user = _required(environment, "MINIO_ROOT_USER")
    root_password = _required(environment, "MINIO_ROOT_PASSWORD")
    app_access_key = _required(environment, "MINIO_ACCESS_KEY")
    app_secret_key = _required(environment, "MINIO_SECRET_KEY")
    if root_user == app_access_key:
        raise RestartPersistenceError("ROOT_AND_APPLICATION_IDENTITIES_MUST_DIFFER")

    bucket_values = {name.lower(): expected for name, expected in BUCKET_ENV}
    try:
        settings = Settings.model_validate(
            {
                "app_env": "local",
                "secret_key": "synthetic-local-restart-persistence-signing-key",
                "database_url": (
                    "postgresql+psycopg://synthetic:synthetic@127.0.0.1/finaudit_unused"
                ),
                "redis_url": "redis://:synthetic@127.0.0.1:6379/0",
                "celery_broker_url": "redis://:synthetic@127.0.0.1:6379/0",
                "celery_result_backend": "redis://:synthetic@127.0.0.1:6379/1",
                "minio_endpoint": LOCAL_ENDPOINT,
                "minio_access_key": app_access_key,
                "minio_secret_key": app_secret_key,
                "minio_secure": False,
                **bucket_values,
                "qdrant_collection": "finaudit_local_minio_restart_gate_e1024_v1",
                "ai_policy_file": "D:\\synthetic\\ai-policy-v1.json",
                "llm_api_key": "synthetic-local-restart-persistence-llm",
                "llm_extraction_model": "synthetic-extraction-model",
                "llm_generation_model": "synthetic-generation-model",
                "embedding_base_url": "http://127.0.0.1:8000/v1",
                "embedding_api_key": "synthetic-local-restart-persistence-embedding",
                "embedding_model": "synthetic-embedding-model",
                "metrics_internal_token": "synthetic-local-restart-persistence-metrics",
            }
        )
    except Exception as error:
        raise RestartPersistenceError("SETTINGS_INVALID") from error
    return RestartPersistenceConfig(settings, root_user, root_password)


def expected_locator() -> QuarantineObject:
    return QuarantineObject(
        QUARANTINE_BUCKET,
        f"organizations/{ORGANIZATION_ID.hex}/files/{FILE_ID.hex}/source",
    )


def _root_client(config: RestartPersistenceConfig) -> Minio:
    try:
        return Minio(
            LOCAL_AUTHORITY,
            access_key=config.root_user,
            secret_key=config.root_password,
            secure=False,
            http_client=_build_http_client(),
        )
    except Exception as error:
        raise RestartPersistenceError("ROOT_CLIENT_CREATE_FAILED") from error


def _object_is_missing(client: Minio, locator: QuarantineObject) -> bool:
    try:
        client.stat_object(locator.bucket_name, locator.object_key)
    except S3Error as error:
        if error.code in MISSING_OBJECT_CODES:
            return True
        raise RestartPersistenceError("ROOT_OBJECT_STAT_FAILED") from error
    except Exception as error:
        raise RestartPersistenceError("ROOT_OBJECT_STAT_FAILED") from error
    return False


def _verify_exact_object(client: Minio, locator: QuarantineObject) -> None:
    expected_sha256 = hashlib.sha256(PAYLOAD).hexdigest()
    try:
        result = client.stat_object(locator.bucket_name, locator.object_key)
        response = client.get_object(locator.bucket_name, locator.object_key)
        try:
            stored_payload = response.read(len(PAYLOAD) + 1)
        finally:
            response.close()
            response.release_conn()
    except Exception as error:
        raise RestartPersistenceError("ROOT_OBJECT_VERIFY_FAILED") from error

    metadata = result.metadata or {}
    if (
        result.size != len(PAYLOAD)
        or result.content_type != "application/pdf"
        or metadata.get("x-amz-meta-sha256") != expected_sha256
        or stored_payload != PAYLOAD
    ):
        raise RestartPersistenceError("ROOT_OBJECT_CONTENT_MISMATCH")


def _confirm_missing(client: Minio, locator: QuarantineObject) -> None:
    if not _object_is_missing(client, locator):
        raise RestartPersistenceError("ROOT_OBJECT_DELETE_VERIFY_FAILED")


def _root_cleanup(client: Minio, locator: QuarantineObject) -> None:
    try:
        client.remove_object(locator.bucket_name, locator.object_key)
    except Exception as error:
        raise RestartPersistenceError("ROOT_EXACT_CLEANUP_FAILED") from error
    try:
        _confirm_missing(client, locator)
    except RestartPersistenceError as error:
        raise RestartPersistenceError("ROOT_EXACT_CLEANUP_FAILED") from error


def _cleanup_attempted_put(client: Minio, locator: QuarantineObject) -> None:
    try:
        if _object_is_missing(client, locator):
            return
        _root_cleanup(client, locator)
    except RestartPersistenceError as error:
        raise RestartPersistenceError("PREPARE_CLEANUP_FAILED") from error


def prepare(config: RestartPersistenceConfig) -> None:
    root = _root_client(config)
    locator = expected_locator()
    if not _object_is_missing(root, locator):
        raise RestartPersistenceError("GATE_OBJECT_ALREADY_EXISTS")

    adapter = MinioQuarantineAdapter(config.settings)
    stream = BytesIO(PAYLOAD)
    put_attempted = False
    try:
        facts = prepare_quarantine_intake(
            stream,
            file_name="synthetic.pdf",
            declared_mime="application/pdf",
            max_size_bytes=len(PAYLOAD),
        )
        put_attempted = True
        actual_locator = adapter.put_quarantine(
            organization_id=ORGANIZATION_ID,
            file_id=FILE_ID,
            sha256=facts.sha256,
            data=stream,
            length=facts.size_bytes,
            content_type=facts.detected_mime,
        )
        if actual_locator != locator:
            raise RestartPersistenceError("APPLICATION_LOCATOR_MISMATCH")
        _verify_exact_object(root, locator)
    except Exception as error:
        if put_attempted:
            _cleanup_attempted_put(root, locator)
        if isinstance(error, RestartPersistenceError):
            raise error
        raise RestartPersistenceError("APPLICATION_PREPARE_FAILED") from error


def verify(config: RestartPersistenceConfig) -> None:
    _verify_exact_object(_root_client(config), expected_locator())


def delete(config: RestartPersistenceConfig) -> None:
    root = _root_client(config)
    locator = expected_locator()
    _verify_exact_object(root, locator)
    try:
        MinioQuarantineAdapter(config.settings).delete_quarantine(locator)
    except Exception as error:
        raise RestartPersistenceError("APPLICATION_DELETE_FAILED") from error
    _confirm_missing(root, locator)


def cleanup(config: RestartPersistenceConfig) -> None:
    root = _root_client(config)
    locator = expected_locator()
    if _object_is_missing(root, locator):
        return
    _verify_exact_object(root, locator)
    _root_cleanup(root, locator)


PHASES = {
    "prepare": prepare,
    "verify": verify,
    "delete": delete,
    "cleanup": cleanup,
}


def main(argv: list[str], environment: Mapping[str, str]) -> int:
    phase: str | None = None
    try:
        if len(argv) != 2 or argv[1] not in PHASES:
            raise RestartPersistenceError("ARGUMENTS_INVALID")
        phase = argv[1]
        PHASES[phase](load_config(environment))
    except RestartPersistenceError as error:
        print("LOCAL_MINIO_RESTART_PERSISTENCE=FAIL")
        print(f"LOCAL_MINIO_RESTART_REASON={error.code}")
        if phase == "prepare" and error.code == "PREPARE_CLEANUP_FAILED":
            return CLEANUP_REQUIRED_EXIT_CODE
        return 1
    except Exception:
        print("LOCAL_MINIO_RESTART_PERSISTENCE=FAIL")
        print("LOCAL_MINIO_RESTART_REASON=UNEXPECTED_FAILURE")
        return 1

    print(f"LOCAL_MINIO_RESTART_{phase.upper()}=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv, os.environ))
