from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO

from bootstrap_local_minio import (
    BOOTSTRAP_ENDPOINT,
    BUCKET_ENV,
    MISSING_OBJECT_CODES,
    BootstrapError,
    _canonical_policy_for_comparison,
    _required,
    _validate_access_key,
    _validate_secret,
)

POLICY_NAME = "finaudit-local-worker-storage-v2"
QUARANTINE_BUCKET = "quarantine"
ORIGINALS_BUCKET = "originals"
REPORTS_BUCKET = "reports"
EXPORTS_BUCKET = "exports"
VERIFY_SOURCE = "bootstrap/worker-access-source-v1"
VERIFY_TARGET = "bootstrap/worker-access-target-v1"


@dataclass(frozen=True)
class WorkerBootstrapConfig:
    root_user: str = field(repr=False)
    root_password: str = field(repr=False)
    app_access_key: str = field(repr=False)
    worker_access_key: str = field(repr=False)
    worker_secret_key: str = field(repr=False)
    buckets: tuple[str, ...]


def load_config(environment: Mapping[str, str]) -> WorkerBootstrapConfig:
    if _required(environment, "APP_ENV") != "local":
        raise BootstrapError("APP_ENV_MUST_BE_LOCAL")
    if _required(environment, "MINIO_SECURE").lower() != "false":
        raise BootstrapError("MINIO_SECURE_MUST_BE_FALSE")
    buckets = tuple(_required(environment, name) for name, _ in BUCKET_ENV)
    if buckets != tuple(expected for _, expected in BUCKET_ENV):
        raise BootstrapError("BUCKET_PROFILE_MISMATCH")

    root_user = _required(environment, "MINIO_ROOT_USER")
    root_password = _required(environment, "MINIO_ROOT_PASSWORD")
    app_access_key = _required(environment, "MINIO_ACCESS_KEY")
    worker_access_key = _required(environment, "MINIO_WORKER_ACCESS_KEY")
    worker_secret_key = _required(environment, "MINIO_WORKER_SECRET_KEY")
    _validate_access_key(root_user, "ROOT_CREDENTIALS_INVALID")
    _validate_secret(root_password, "ROOT_CREDENTIALS_INVALID")
    _validate_access_key(app_access_key, "APPLICATION_CREDENTIALS_INVALID")
    _validate_access_key(worker_access_key, "WORKER_CREDENTIALS_INVALID")
    _validate_secret(worker_secret_key, "WORKER_CREDENTIALS_INVALID")
    if len({root_user, app_access_key, worker_access_key}) != 3:
        raise BootstrapError("STORAGE_IDENTITIES_MUST_DIFFER")
    return WorkerBootstrapConfig(
        root_user=root_user,
        root_password=root_password,
        app_access_key=app_access_key,
        worker_access_key=worker_access_key,
        worker_secret_key=worker_secret_key,
        buckets=buckets,
    )


def _worker_policy(buckets: tuple[str, ...]) -> dict[str, object]:
    if (
        len(buckets) < 6
        or buckets[:2] != (QUARANTINE_BUCKET, ORIGINALS_BUCKET)
        or buckets[4:6] != (REPORTS_BUCKET, EXPORTS_BUCKET)
    ):
        raise BootstrapError("BUCKET_PROFILE_MISMATCH")
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetBucketLocation"],
                "Resource": [
                    f"arn:aws:s3:::{QUARANTINE_BUCKET}",
                    f"arn:aws:s3:::{ORIGINALS_BUCKET}",
                    f"arn:aws:s3:::{REPORTS_BUCKET}",
                    f"arn:aws:s3:::{EXPORTS_BUCKET}",
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:DeleteObject", "s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{QUARANTINE_BUCKET}/*"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:AbortMultipartUpload",
                    "s3:DeleteObject",
                    "s3:GetObject",
                    "s3:PutObject",
                ],
                "Resource": [f"arn:aws:s3:::{ORIGINALS_BUCKET}/*"],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:AbortMultipartUpload",
                    "s3:DeleteObject",
                    "s3:GetObject",
                    "s3:PutObject",
                ],
                "Resource": [
                    f"arn:aws:s3:::{REPORTS_BUCKET}/organizations/*",
                    f"arn:aws:s3:::{EXPORTS_BUCKET}/organizations/*",
                ],
            },
        ],
    }


def _validate_worker_user_info(raw_user_info: str) -> None:
    try:
        user_info = json.loads(raw_user_info)
    except (TypeError, json.JSONDecodeError) as error:
        raise BootstrapError("WORKER_IDENTITY_VERIFY_FAILED") from error
    if not isinstance(user_info, dict):
        raise BootstrapError("WORKER_IDENTITY_VERIFY_FAILED")
    member_of = user_info.get("memberOf", [])
    if member_of is None:
        member_of = []
    if (
        user_info.get("status") != "enabled"
        or user_info.get("policyName") != POLICY_NAME
        or member_of != []
    ):
        raise BootstrapError("WORKER_IDENTITY_VERIFY_FAILED")


def bootstrap(config: WorkerBootstrapConfig) -> None:
    try:
        from minio import Minio
        from minio.commonconfig import CopySource
        from minio.credentials.providers import StaticProvider
        from minio.error import MinioAdminException, S3Error
        from minio.minioadmin import MinioAdmin
        from urllib3 import PoolManager, Retry, Timeout
    except ImportError as error:
        raise BootstrapError("MINIO_SDK_MISSING") from error

    def http_client() -> PoolManager:
        return PoolManager(
            timeout=Timeout(connect=3, read=10),
            retries=Retry(
                total=2,
                backoff_factor=0.2,
                status_forcelist=[500, 502, 503, 504],
            ),
        )

    try:
        root_client = Minio(
            BOOTSTRAP_ENDPOINT,
            access_key=config.root_user,
            secret_key=config.root_password,
            secure=False,
            http_client=http_client(),
        )
        admin_client = MinioAdmin(
            endpoint=BOOTSTRAP_ENDPOINT,
            credentials=StaticProvider(config.root_user, config.root_password),
            secure=False,
            http_client=http_client(),
        )
    except Exception:
        raise BootstrapError("WORKER_ADMIN_CLIENT_CREATE_FAILED") from None

    worker_exists = False
    try:
        admin_client.user_info(config.worker_access_key)
        worker_exists = True
    except MinioAdminException as error:
        if getattr(error, "_code", None) != "404":
            raise BootstrapError("WORKER_IDENTITY_INSPECT_FAILED") from None
    except Exception:
        raise BootstrapError("WORKER_IDENTITY_INSPECT_FAILED") from None
    if worker_exists:
        try:
            admin_client.user_remove(config.worker_access_key)
        except Exception:
            raise BootstrapError("WORKER_IDENTITY_REMOVE_FAILED") from None

    expected_policy = _worker_policy(config.buckets)
    raw_policy: str | None = None
    try:
        raw_policy = admin_client.policy_info(POLICY_NAME)
    except MinioAdminException as error:
        if getattr(error, "_code", None) != "404":
            raise BootstrapError("WORKER_POLICY_INSPECT_FAILED") from None
    except Exception:
        raise BootstrapError("WORKER_POLICY_INSPECT_FAILED") from None
    if raw_policy is not None:
        try:
            stored_policy = json.loads(raw_policy)
        except (TypeError, json.JSONDecodeError):
            raise BootstrapError("WORKER_POLICY_DRIFT") from None
        if _canonical_policy_for_comparison(stored_policy) != _canonical_policy_for_comparison(
            expected_policy
        ):
            raise BootstrapError("WORKER_POLICY_DRIFT")
    else:
        try:
            admin_client.policy_add(POLICY_NAME, policy=expected_policy)
        except Exception:
            raise BootstrapError("WORKER_POLICY_CREATE_FAILED") from None

    try:
        admin_client.user_add(config.worker_access_key, config.worker_secret_key)
        admin_client.attach_policy([POLICY_NAME], user=config.worker_access_key)
        raw_user_info = admin_client.user_info(config.worker_access_key)
    except Exception:
        raise BootstrapError("WORKER_IDENTITY_CREATE_OR_ATTACH_FAILED") from None
    _validate_worker_user_info(raw_user_info)

    worker_client = Minio(
        BOOTSTRAP_ENDPOINT,
        access_key=config.worker_access_key,
        secret_key=config.worker_secret_key,
        secure=False,
        http_client=http_client(),
    )

    def root_confirms_missing(bucket: str, key: str) -> None:
        try:
            root_client.stat_object(bucket, key)
        except S3Error as error:
            if error.code in MISSING_OBJECT_CODES:
                return
            raise
        raise BootstrapError("WORKER_CLEANUP_VERIFY_FAILED")

    response = None
    try:
        payload = b"finaudit-worker-storage-access-v1"
        root_client.put_object(
            QUARANTINE_BUCKET,
            VERIFY_SOURCE,
            BytesIO(payload),
            len(payload),
        )
        response = worker_client.get_object(QUARANTINE_BUCKET, VERIFY_SOURCE)
        if response.read(len(payload) + 1) != payload:
            raise BootstrapError("WORKER_QUARANTINE_READ_VERIFY_FAILED")
        response.close()
        response.release_conn()
        response = None
        worker_client.copy_object(
            ORIGINALS_BUCKET,
            VERIFY_TARGET,
            CopySource(QUARANTINE_BUCKET, VERIFY_SOURCE),
        )
        response = worker_client.get_object(ORIGINALS_BUCKET, VERIFY_TARGET)
        if response.read(len(payload) + 1) != payload:
            raise BootstrapError("WORKER_ORIGINALS_WRITE_VERIFY_FAILED")
        response.close()
        response.release_conn()
        response = None
        worker_client.remove_object(QUARANTINE_BUCKET, VERIFY_SOURCE)
        worker_client.remove_object(ORIGINALS_BUCKET, VERIFY_TARGET)
        root_confirms_missing(QUARANTINE_BUCKET, VERIFY_SOURCE)
        root_confirms_missing(ORIGINALS_BUCKET, VERIFY_TARGET)
    except BootstrapError:
        raise
    except Exception:
        raise BootstrapError("WORKER_STORAGE_ACCESS_VERIFY_FAILED") from None
    finally:
        if response is not None:
            try:
                response.close()
                response.release_conn()
            except Exception:
                pass
        cleanup_failed = False
        for bucket, key in (
            (QUARANTINE_BUCKET, VERIFY_SOURCE),
            (ORIGINALS_BUCKET, VERIFY_TARGET),
        ):
            try:
                root_client.remove_object(bucket, key)
                root_confirms_missing(bucket, key)
            except Exception:
                cleanup_failed = True
        if cleanup_failed:
            raise BootstrapError("WORKER_CLEANUP_FAILED")


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            raise BootstrapError("ARGUMENTS_NOT_SUPPORTED")
        config = load_config(os.environ)
        bootstrap(config)
    except BootstrapError as error:
        print("LOCAL_MINIO_WORKER_BOOTSTRAP=FAIL")
        print(f"LOCAL_MINIO_WORKER_REASON={error.code}")
        return 1
    except Exception:
        print("LOCAL_MINIO_WORKER_BOOTSTRAP=FAIL")
        print("LOCAL_MINIO_WORKER_REASON=UNEXPECTED_FAILURE")
        return 1
    print("LOCAL_MINIO_WORKER_BOOTSTRAP=PASS")
    print("LOCAL_MINIO_WORKER_ACCESS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
