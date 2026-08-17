from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO

BOOTSTRAP_ENDPOINT = "127.0.0.1:9000"
POLICY_NAME = "finaudit-local-storage-v3"
QUARANTINE_BUCKET = "quarantine"
ORIGINALS_BUCKET = "originals"
REPORTS_BUCKET = "reports"
EXPORTS_BUCKET = "exports"
VERIFY_MARKER = "bootstrap/quarantine-access-v1"
MISSING_OBJECT_CODES = frozenset({"NoSuchKey", "NoSuchObject"})
BUCKET_ENV = (
    ("MINIO_BUCKET_QUARANTINE", "quarantine"),
    ("MINIO_BUCKET_ORIGINALS", "originals"),
    ("MINIO_BUCKET_ASSETS", "assets"),
    ("MINIO_BUCKET_PREVIEWS", "previews"),
    ("MINIO_BUCKET_REPORTS", "reports"),
    ("MINIO_BUCKET_EXPORTS", "exports"),
    ("MINIO_BUCKET_TEMP", "temp"),
)


class BootstrapError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BootstrapConfig:
    root_user: str = field(repr=False)
    root_password: str = field(repr=False)
    app_access_key: str = field(repr=False)
    app_secret_key: str = field(repr=False)
    buckets: tuple[str, ...]


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value:
        raise BootstrapError(f"MISSING_{name}")
    return value


def _validate_access_key(value: str, code: str) -> None:
    if (
        len(value) < 3
        or len(value) > 64
        or value != value.strip()
        or any(character.isspace() or ord(character) < 32 for character in value)
        or "CHANGE_ME" in value.upper()
        or value.upper().startswith("REPLACE_")
    ):
        raise BootstrapError(code)


def _validate_secret(value: str, code: str) -> None:
    if (
        len(value) < 8
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
        or "CHANGE_ME" in value.upper()
        or value.upper().startswith("REPLACE_")
    ):
        raise BootstrapError(code)


def load_config(environment: Mapping[str, str]) -> BootstrapConfig:
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
    app_secret_key = _required(environment, "MINIO_SECRET_KEY")
    _validate_access_key(root_user, "ROOT_CREDENTIALS_INVALID")
    _validate_secret(root_password, "ROOT_CREDENTIALS_INVALID")
    _validate_access_key(app_access_key, "APPLICATION_CREDENTIALS_INVALID")
    _validate_secret(app_secret_key, "APPLICATION_CREDENTIALS_INVALID")
    if root_user == app_access_key:
        raise BootstrapError("ROOT_AND_APPLICATION_IDENTITIES_MUST_DIFFER")

    return BootstrapConfig(
        root_user=root_user,
        root_password=root_password,
        app_access_key=app_access_key,
        app_secret_key=app_secret_key,
        buckets=buckets,
    )


def _application_policy(buckets: tuple[str, ...]) -> dict[str, object]:
    if (
        len(buckets) < 6
        or buckets[0] != QUARANTINE_BUCKET
        or buckets[1] != ORIGINALS_BUCKET
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
                "Action": [
                    "s3:AbortMultipartUpload",
                    "s3:DeleteObject",
                    "s3:PutObject",
                ],
                "Resource": [f"arn:aws:s3:::{QUARANTINE_BUCKET}/*"],
            },
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [
                    f"arn:aws:s3:::{ORIGINALS_BUCKET}/organizations/*",
                    f"arn:aws:s3:::{REPORTS_BUCKET}/organizations/*",
                    f"arn:aws:s3:::{EXPORTS_BUCKET}/organizations/*",
                ],
            },
        ],
    }


def _canonical_policy_for_comparison(policy: object) -> object:
    if not isinstance(policy, dict):
        return policy
    statements = policy.get("Statement")
    if not isinstance(statements, list):
        return policy

    canonical_statements: list[object] = []
    for statement in statements:
        if not isinstance(statement, dict):
            canonical_statements.append(statement)
            continue
        canonical_statement = dict(statement)
        for policy_field in ("Action", "Resource"):
            values = canonical_statement.get(policy_field)
            if isinstance(values, list) and all(
                isinstance(value, str) for value in values
            ):
                canonical_statement[policy_field] = sorted(values)
        canonical_statements.append(canonical_statement)
    canonical_policy = dict(policy)
    canonical_policy["Statement"] = canonical_statements
    return canonical_policy


def _validate_application_user_info(raw_user_info: str) -> None:
    try:
        user_info = json.loads(raw_user_info)
    except (TypeError, json.JSONDecodeError) as error:
        raise BootstrapError("APPLICATION_IDENTITY_VERIFY_FAILED") from error

    if not isinstance(user_info, dict):
        raise BootstrapError("APPLICATION_IDENTITY_VERIFY_FAILED")
    member_of = user_info.get("memberOf", [])
    if member_of is None:
        member_of = []
    if (
        user_info.get("status") != "enabled"
        or user_info.get("policyName") != POLICY_NAME
        or member_of != []
    ):
        raise BootstrapError("APPLICATION_IDENTITY_VERIFY_FAILED")


def bootstrap(config: BootstrapConfig) -> None:
    try:
        from minio import Minio
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
                total=2, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504]
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
        for bucket in config.buckets:
            if not root_client.bucket_exists(bucket):
                root_client.make_bucket(bucket)
            if not root_client.bucket_exists(bucket):
                raise BootstrapError("BUCKET_VERIFY_FAILED")
    except BootstrapError:
        raise
    except Exception as error:
        raise BootstrapError("ROOT_BUCKET_BOOTSTRAP_FAILED") from error

    try:
        admin_client = MinioAdmin(
            endpoint=BOOTSTRAP_ENDPOINT,
            credentials=StaticProvider(config.root_user, config.root_password),
            secure=False,
            http_client=http_client(),
        )
    except Exception:
        raise BootstrapError("APPLICATION_ADMIN_CLIENT_CREATE_FAILED") from None

    application_user_exists = False
    try:
        admin_client.user_info(config.app_access_key)
        application_user_exists = True
    except MinioAdminException as error:
        if getattr(error, "_code", None) != "404":
            raise BootstrapError("APPLICATION_IDENTITY_INSPECT_FAILED") from None
    except Exception:
        raise BootstrapError("APPLICATION_IDENTITY_INSPECT_FAILED") from None

    if application_user_exists:
        try:
            admin_client.user_remove(config.app_access_key)
        except Exception:
            raise BootstrapError("APPLICATION_IDENTITY_REMOVE_FAILED") from None

    expected_policy = _application_policy(config.buckets)
    raw_policy: str | None = None
    try:
        raw_policy = admin_client.policy_info(POLICY_NAME)
    except MinioAdminException as error:
        if getattr(error, "_code", None) != "404":
            raise BootstrapError("APPLICATION_POLICY_INSPECT_FAILED") from None
    except Exception:
        raise BootstrapError("APPLICATION_POLICY_INSPECT_FAILED") from None

    if raw_policy is not None:
        try:
            stored_policy = json.loads(raw_policy)
        except (TypeError, json.JSONDecodeError):
            raise BootstrapError("APPLICATION_POLICY_DRIFT") from None
        if _canonical_policy_for_comparison(
            stored_policy
        ) != _canonical_policy_for_comparison(expected_policy):
            raise BootstrapError("APPLICATION_POLICY_DRIFT")
    else:
        try:
            admin_client.policy_add(POLICY_NAME, policy=expected_policy)
        except Exception:
            raise BootstrapError("APPLICATION_POLICY_CREATE_FAILED") from None

    try:
        admin_client.user_add(config.app_access_key, config.app_secret_key)
    except Exception:
        raise BootstrapError("APPLICATION_IDENTITY_CREATE_FAILED") from None
    try:
        admin_client.attach_policy([POLICY_NAME], user=config.app_access_key)
    except Exception:
        raise BootstrapError("APPLICATION_POLICY_ATTACH_FAILED") from None
    try:
        raw_user_info = admin_client.user_info(config.app_access_key)
    except Exception:
        raise BootstrapError("APPLICATION_IDENTITY_VERIFY_FAILED") from None
    _validate_application_user_info(raw_user_info)

    def root_confirms_marker_missing() -> None:
        try:
            root_client.stat_object(QUARANTINE_BUCKET, VERIFY_MARKER)
        except S3Error as error:
            if error.code in MISSING_OBJECT_CODES:
                return
            raise
        raise BootstrapError("APPLICATION_QUARANTINE_DELETE_VERIFY_FAILED")

    try:
        app_client = Minio(
            BOOTSTRAP_ENDPOINT,
            access_key=config.app_access_key,
            secret_key=config.app_secret_key,
            secure=False,
            http_client=http_client(),
        )
        app_client.put_object(QUARANTINE_BUCKET, VERIFY_MARKER, BytesIO(b""), 0)
        root_client.stat_object(QUARANTINE_BUCKET, VERIFY_MARKER)
        app_client.remove_object(QUARANTINE_BUCKET, VERIFY_MARKER)
        root_confirms_marker_missing()
    except Exception as error:
        try:
            root_client.remove_object(QUARANTINE_BUCKET, VERIFY_MARKER)
            root_confirms_marker_missing()
        except Exception as cleanup_error:
            raise BootstrapError(
                "APPLICATION_QUARANTINE_CLEANUP_FAILED"
            ) from cleanup_error
        if isinstance(error, BootstrapError):
            raise error
        raise BootstrapError("APPLICATION_QUARANTINE_ACCESS_VERIFY_FAILED") from error


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            raise BootstrapError("ARGUMENTS_NOT_SUPPORTED")
        config = load_config(os.environ)
        bootstrap(config)
    except BootstrapError as error:
        print("LOCAL_MINIO_BOOTSTRAP=FAIL")
        print(f"LOCAL_MINIO_REASON={error.code}")
        return 1
    except Exception:
        print("LOCAL_MINIO_BOOTSTRAP=FAIL")
        print("LOCAL_MINIO_REASON=UNEXPECTED_FAILURE")
        return 1

    print("LOCAL_MINIO_BOOTSTRAP=PASS")
    print(f"LOCAL_MINIO_BUCKETS={len(config.buckets)}")
    print("LOCAL_MINIO_QUARANTINE_ACCESS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
