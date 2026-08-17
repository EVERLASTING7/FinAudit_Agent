from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bootstrap_local_minio as subject  # noqa: E402
import bootstrap_local_minio_worker as worker_subject  # noqa: E402
from minio.error import S3Error  # noqa: E402
from minio.minioadmin import MinioAdminException  # noqa: E402


def valid_environment() -> dict[str, str]:
    environment = {
        "APP_ENV": "local",
        "MINIO_SECURE": "false",
        "MINIO_ROOT_USER": "unit-test-root",
        "MINIO_ROOT_PASSWORD": "unit-test-root-password",
        "MINIO_ACCESS_KEY": "unit-test-app",
        "MINIO_SECRET_KEY": "unit-test-app-password",
    }
    environment.update({name: value for name, value in subject.BUCKET_ENV})
    return environment


def missing_object_error() -> S3Error:
    return S3Error(None, "NoSuchKey", "missing", None, None, None)


class FakeObjectClient:
    def __init__(self, harness: BootstrapHarness, role: str) -> None:
        self.harness = harness
        self.role = role

    def bucket_exists(self, bucket: str) -> bool:
        self.harness.object_calls.append((self.role, "bucket_exists", bucket))
        return bucket in self.harness.buckets

    def make_bucket(self, bucket: str) -> None:
        self.harness.object_calls.append((self.role, "make_bucket", bucket))
        self.harness.buckets.add(bucket)

    def put_object(
        self,
        bucket: str,
        object_name: str,
        data: BytesIO,
        length: int,
    ) -> object:
        self.harness.object_calls.append(
            (self.role, "put_object", bucket, object_name, length)
        )
        if self.harness.app_put_error is not None:
            raise self.harness.app_put_error
        self.harness.objects.add((bucket, object_name))
        return object()

    def stat_object(self, bucket: str, object_name: str) -> object:
        self.harness.object_calls.append(
            (self.role, "stat_object", bucket, object_name)
        )
        if (bucket, object_name) not in self.harness.objects:
            raise missing_object_error()
        return object()

    def remove_object(self, bucket: str, object_name: str) -> None:
        self.harness.object_calls.append(
            (self.role, "remove_object", bucket, object_name)
        )
        if self.role == "app" and self.harness.app_remove_error is not None:
            raise self.harness.app_remove_error
        if self.role == "root" and self.harness.root_remove_error is not None:
            raise self.harness.root_remove_error
        self.harness.objects.discard((bucket, object_name))


class FakeAdminClient:
    def __init__(self, harness: BootstrapHarness) -> None:
        self.harness = harness

    def user_add(self, access_key: str, secret_key: str) -> str:
        self.harness.admin_calls.append(("user_add", access_key))
        self.harness.raise_admin_error("user_add")
        if self.harness.user_exists:
            raise RuntimeError("user already exists")
        self.harness.user_exists = True
        return ""

    def user_remove(self, access_key: str) -> str:
        self.harness.admin_calls.append(("user_remove", access_key))
        self.harness.raise_admin_error("user_remove")
        if not self.harness.user_exists:
            raise MinioAdminException("404", "synthetic missing user")
        self.harness.user_exists = False
        return ""

    def policy_add(self, policy_name: str, *, policy: dict[str, object]) -> str:
        self.harness.admin_calls.append(("policy_add", policy_name, policy))
        self.harness.raise_admin_error("policy_add")
        if self.harness.policy is not None:
            raise RuntimeError("policy already exists")
        self.harness.policy = policy
        return ""

    def policy_info(self, policy_name: str) -> str:
        self.harness.admin_calls.append(("policy_info", policy_name))
        self.harness.raise_admin_error("policy_info")
        if self.harness.policy is None:
            raise MinioAdminException("404", "synthetic missing policy")
        if self.harness.policy_raw_override is not None:
            return self.harness.policy_raw_override
        return json.dumps(self.harness.policy)

    def attach_policy(self, policies: list[str], *, user: str) -> str:
        self.harness.admin_calls.append(("attach_policy", policies, user))
        self.harness.raise_admin_error("attach_policy")
        if not self.harness.user_exists or self.harness.policy is None:
            raise RuntimeError("identity or policy missing")
        return ""

    def user_info(self, access_key: str) -> str:
        self.harness.admin_calls.append(("user_info", access_key))
        self.harness.raise_admin_error("user_info")
        if not self.harness.user_exists:
            raise MinioAdminException("404", "synthetic missing user")
        return json.dumps(self.harness.user_info)


class BootstrapHarness:
    def __init__(self, config: subject.BootstrapConfig) -> None:
        self.config = config
        self.buckets: set[str] = set()
        self.objects: set[tuple[str, str]] = set()
        self.object_calls: list[tuple[object, ...]] = []
        self.admin_calls: list[tuple[object, ...]] = []
        self.user_exists = False
        self.policy: dict[str, object] | None = None
        self.policy_raw_override: str | None = None
        self.admin_errors: dict[str, Exception] = {}
        self.user_info: dict[str, object] = {
            "status": "enabled",
            "policyName": subject.POLICY_NAME,
            "memberOf": [],
        }
        self.app_put_error: Exception | None = None
        self.app_remove_error: Exception | None = None
        self.root_remove_error: Exception | None = None
        self.root_client = FakeObjectClient(self, "root")
        self.app_client = FakeObjectClient(self, "app")
        self.admin_client = FakeAdminClient(self)

    def raise_admin_error(self, operation: str) -> None:
        error = self.admin_errors.get(operation)
        if error is not None:
            raise error

    def build_minio(
        self,
        endpoint: str,
        *,
        access_key: str,
        secret_key: str,
        secure: bool,
        http_client: object,
    ) -> FakeObjectClient:
        self.object_calls.append(("construct", endpoint, access_key, secure))
        if (
            access_key == self.config.root_user
            and secret_key == self.config.root_password
        ):
            return self.root_client
        if (
            access_key == self.config.app_access_key
            and secret_key == self.config.app_secret_key
        ):
            return self.app_client
        raise AssertionError("unexpected credentials")

    def build_admin(self, **kwargs: object) -> FakeAdminClient:
        self.admin_calls.append(("construct", kwargs["endpoint"], kwargs["secure"]))
        return self.admin_client

    def run(self) -> None:
        with (
            patch("minio.Minio", side_effect=self.build_minio),
            patch("minio.minioadmin.MinioAdmin", side_effect=self.build_admin),
            patch("urllib3.PoolManager", return_value=object()),
        ):
            subject.bootstrap(self.config)


class BootstrapConfigTests(unittest.TestCase):
    def test_approved_profile_loads_without_exposing_credentials(self) -> None:
        config = subject.load_config(valid_environment())

        self.assertEqual(
            config.buckets, tuple(value for _, value in subject.BUCKET_ENV)
        )
        self.assertNotIn(config.root_password, repr(config))
        self.assertNotIn(config.app_secret_key, repr(config))

    def test_bucket_drift_fails_closed(self) -> None:
        environment = valid_environment()
        environment["MINIO_BUCKET_TEMP"] = "shared"

        with self.assertRaisesRegex(subject.BootstrapError, "BUCKET_PROFILE_MISMATCH"):
            subject.load_config(environment)

    def test_root_identity_cannot_be_reused_by_application(self) -> None:
        environment = valid_environment()
        environment["MINIO_ACCESS_KEY"] = environment["MINIO_ROOT_USER"]

        with self.assertRaisesRegex(
            subject.BootstrapError,
            "ROOT_AND_APPLICATION_IDENTITIES_MUST_DIFFER",
        ):
            subject.load_config(environment)

    def test_failure_output_is_redacted(self) -> None:
        environment = valid_environment()
        secret = environment["MINIO_SECRET_KEY"]
        output = io.StringIO()

        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(subject, "bootstrap", side_effect=RuntimeError(secret)),
            patch.object(sys, "argv", [subject.__file__]),
            contextlib.redirect_stdout(output),
        ):
            result = subject.main()

        self.assertEqual(result, 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(
            output.getvalue().splitlines(),
            ["LOCAL_MINIO_BOOTSTRAP=FAIL", "LOCAL_MINIO_REASON=UNEXPECTED_FAILURE"],
        )

    def test_success_output_claims_only_quarantine_access(self) -> None:
        output = io.StringIO()

        with (
            patch.dict(os.environ, valid_environment(), clear=True),
            patch.object(subject, "bootstrap"),
            patch.object(sys, "argv", [subject.__file__]),
            contextlib.redirect_stdout(output),
        ):
            result = subject.main()

        self.assertEqual(result, 0)
        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "LOCAL_MINIO_BOOTSTRAP=PASS",
                "LOCAL_MINIO_BUCKETS=7",
                "LOCAL_MINIO_QUARANTINE_ACCESS=PASS",
            ],
        )


class BootstrapRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = subject.load_config(valid_environment())

    def test_policy_limits_quarantine_writes_and_product_reads(self) -> None:
        self.assertEqual(
            subject._application_policy(self.config.buckets),
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetBucketLocation"],
                        "Resource": [
                            "arn:aws:s3:::quarantine",
                            "arn:aws:s3:::originals",
                            "arn:aws:s3:::reports",
                            "arn:aws:s3:::exports",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "s3:AbortMultipartUpload",
                            "s3:DeleteObject",
                            "s3:PutObject",
                        ],
                        "Resource": ["arn:aws:s3:::quarantine/*"],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject"],
                        "Resource": [
                            "arn:aws:s3:::originals/organizations/*",
                            "arn:aws:s3:::reports/organizations/*",
                            "arn:aws:s3:::exports/organizations/*",
                        ],
                    },
                ],
            },
        )

    def test_worker_policy_limits_report_write_scope(self) -> None:
        self.assertEqual(
            worker_subject._worker_policy(self.config.buckets),
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetBucketLocation"],
                        "Resource": [
                            "arn:aws:s3:::quarantine",
                            "arn:aws:s3:::originals",
                            "arn:aws:s3:::reports",
                            "arn:aws:s3:::exports",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:DeleteObject", "s3:GetObject"],
                        "Resource": ["arn:aws:s3:::quarantine/*"],
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "s3:AbortMultipartUpload",
                            "s3:DeleteObject",
                            "s3:GetObject",
                            "s3:PutObject",
                        ],
                        "Resource": ["arn:aws:s3:::originals/*"],
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
                            "arn:aws:s3:::reports/organizations/*",
                            "arn:aws:s3:::exports/organizations/*",
                        ],
                    },
                ],
            },
        )

    def test_first_and_second_bootstrap_use_safe_persistent_identity_sequence(
        self,
    ) -> None:
        harness = BootstrapHarness(self.config)

        harness.run()
        first_run_calls = list(harness.admin_calls)
        harness.admin_calls.clear()
        harness.run()
        second_run_calls = list(harness.admin_calls)

        self.assertEqual(harness.buckets, set(self.config.buckets))
        self.assertEqual(
            [call for call in harness.object_calls if call[1] == "make_bucket"],
            [("root", "make_bucket", bucket) for bucket in self.config.buckets],
        )
        expected_policy = subject._application_policy(self.config.buckets)
        self.assertEqual(
            first_run_calls,
            [
                ("construct", subject.BOOTSTRAP_ENDPOINT, False),
                ("user_info", self.config.app_access_key),
                ("policy_info", subject.POLICY_NAME),
                ("policy_add", subject.POLICY_NAME, expected_policy),
                ("user_add", self.config.app_access_key),
                ("attach_policy", [subject.POLICY_NAME], self.config.app_access_key),
                ("user_info", self.config.app_access_key),
            ],
        )
        self.assertEqual(
            second_run_calls,
            [
                ("construct", subject.BOOTSTRAP_ENDPOINT, False),
                ("user_info", self.config.app_access_key),
                ("user_remove", self.config.app_access_key),
                ("policy_info", subject.POLICY_NAME),
                ("user_add", self.config.app_access_key),
                ("attach_policy", [subject.POLICY_NAME], self.config.app_access_key),
                ("user_info", self.config.app_access_key),
            ],
        )
        object_verification_calls = [
            call
            for call in harness.object_calls
            if len(call) > 1
            and call[1] in {"put_object", "stat_object", "remove_object"}
        ]
        self.assertEqual(
            object_verification_calls,
            [
                ("app", "put_object", "quarantine", subject.VERIFY_MARKER, 0),
                ("root", "stat_object", "quarantine", subject.VERIFY_MARKER),
                ("app", "remove_object", "quarantine", subject.VERIFY_MARKER),
                ("root", "stat_object", "quarantine", subject.VERIFY_MARKER),
            ]
            * 2,
        )
        self.assertEqual(harness.objects, set())

    def test_existing_policy_drift_or_malformed_json_fails_after_revoking_old_user(
        self,
    ) -> None:
        for policy, raw_override in (
            ({"Version": "2012-10-17", "Statement": []}, None),
            (subject._application_policy(self.config.buckets), "{not-json"),
        ):
            with self.subTest(raw_override=raw_override):
                harness = BootstrapHarness(self.config)
                harness.user_exists = True
                harness.policy = policy
                harness.policy_raw_override = raw_override

                with self.assertRaisesRegex(
                    subject.BootstrapError,
                    "APPLICATION_POLICY_DRIFT",
                ):
                    harness.run()

                self.assertFalse(harness.user_exists)
                self.assertNotIn(
                    ("user_add", self.config.app_access_key),
                    harness.admin_calls,
                )
                self.assertFalse(
                    any(
                        len(call) > 1 and call[1] == "put_object"
                        for call in harness.object_calls
                    )
                )

    def test_existing_policy_allows_only_action_and_resource_order_variation(
        self,
    ) -> None:
        expected = subject._application_policy(self.config.buckets)
        reordered = json.loads(json.dumps(expected))
        reordered["Statement"][1]["Action"].reverse()
        reordered["Statement"][1]["Resource"].reverse()
        harness = BootstrapHarness(self.config)
        harness.user_exists = True
        harness.policy = reordered

        harness.run()

        self.assertTrue(harness.user_exists)
        self.assertEqual(harness.policy, reordered)

    def test_policy_comparison_rejects_semantic_or_structural_drift(self) -> None:
        expected = subject._application_policy(self.config.buckets)
        variants: list[object] = []
        for mutation in ("extra_action", "duplicate_action", "condition"):
            variant = json.loads(json.dumps(expected))
            statement = variant["Statement"][1]
            if mutation == "extra_action":
                statement["Action"].append("s3:GetObject")
            elif mutation == "duplicate_action":
                statement["Action"].append(statement["Action"][0])
            else:
                statement["Condition"] = {"StringEquals": {"s3:x": "y"}}
            variants.append(variant)
        reversed_statements = json.loads(json.dumps(expected))
        reversed_statements["Statement"].reverse()
        variants.extend(
            (reversed_statements, {"Version": "2012-10-17", "Statement": "invalid"})
        )

        for stored in variants:
            with self.subTest(stored=stored):
                self.assertNotEqual(
                    subject._canonical_policy_for_comparison(stored),
                    subject._canonical_policy_for_comparison(expected),
                )

    def test_only_admin_404_is_treated_as_absent(self) -> None:
        for operation, expected_code in (
            ("user_info", "APPLICATION_IDENTITY_INSPECT_FAILED"),
            ("policy_info", "APPLICATION_POLICY_INSPECT_FAILED"),
        ):
            with self.subTest(operation=operation):
                harness = BootstrapHarness(self.config)
                harness.admin_errors[operation] = MinioAdminException(
                    "500", "provider-secret-sentinel"
                )

                with self.assertRaisesRegex(
                    subject.BootstrapError,
                    expected_code,
                ) as exc_info:
                    harness.run()

                rendered = f"{exc_info.exception!s}\n{exc_info.exception!r}"
                self.assertNotIn("provider-secret-sentinel", rendered)
                self.assertFalse(
                    any(
                        len(call) > 1 and call[1] == "put_object"
                        for call in harness.object_calls
                    )
                )

    def test_identity_rebootstrap_phase_failures_are_fixed_and_redacted(self) -> None:
        cases = (
            (
                "user_remove",
                "APPLICATION_IDENTITY_REMOVE_FAILED",
                True,
                subject._application_policy(self.config.buckets),
            ),
            ("policy_add", "APPLICATION_POLICY_CREATE_FAILED", False, None),
            (
                "user_add",
                "APPLICATION_IDENTITY_CREATE_FAILED",
                False,
                subject._application_policy(self.config.buckets),
            ),
            (
                "attach_policy",
                "APPLICATION_POLICY_ATTACH_FAILED",
                False,
                subject._application_policy(self.config.buckets),
            ),
        )
        for operation, expected_code, user_exists, policy in cases:
            with self.subTest(operation=operation):
                harness = BootstrapHarness(self.config)
                harness.user_exists = user_exists
                harness.policy = policy
                harness.admin_errors[operation] = RuntimeError(
                    "provider-secret-sentinel"
                )

                with self.assertRaisesRegex(
                    subject.BootstrapError,
                    expected_code,
                ) as exc_info:
                    harness.run()

                rendered = f"{exc_info.exception!s}\n{exc_info.exception!r}"
                self.assertNotIn("provider-secret-sentinel", rendered)
                self.assertFalse(
                    any(
                        len(call) > 1 and call[1] == "put_object"
                        for call in harness.object_calls
                    )
                )

    def test_identity_verification_rejects_extra_policy_or_group(self) -> None:
        for invalid_user_info in (
            {
                "status": "enabled",
                "policyName": f"{subject.POLICY_NAME},readwrite",
                "memberOf": [],
            },
            {
                "status": "enabled",
                "policyName": subject.POLICY_NAME,
                "memberOf": ["operators"],
            },
        ):
            with self.subTest(user_info=invalid_user_info):
                harness = BootstrapHarness(self.config)
                harness.user_info = invalid_user_info

                with self.assertRaisesRegex(
                    subject.BootstrapError,
                    "APPLICATION_IDENTITY_VERIFY_FAILED",
                ):
                    harness.run()

                self.assertNotIn(("quarantine", subject.VERIFY_MARKER), harness.objects)
                self.assertFalse(
                    any(
                        len(call) > 1 and call[1] == "put_object"
                        for call in harness.object_calls
                    )
                )

    def test_app_delete_failure_is_cleaned_up_by_root(self) -> None:
        harness = BootstrapHarness(self.config)
        harness.app_remove_error = RuntimeError("app delete failed")

        with self.assertRaisesRegex(
            subject.BootstrapError,
            "APPLICATION_QUARANTINE_ACCESS_VERIFY_FAILED",
        ):
            harness.run()

        self.assertEqual(harness.objects, set())
        self.assertIn(
            ("root", "remove_object", "quarantine", subject.VERIFY_MARKER),
            harness.object_calls,
        )

    def test_cleanup_failure_is_not_swallowed(self) -> None:
        harness = BootstrapHarness(self.config)
        harness.app_remove_error = RuntimeError("app delete failed")
        harness.root_remove_error = RuntimeError("root cleanup failed")

        with self.assertRaisesRegex(
            subject.BootstrapError,
            "APPLICATION_QUARANTINE_CLEANUP_FAILED",
        ):
            harness.run()

        self.assertEqual(harness.objects, {("quarantine", subject.VERIFY_MARKER)})


if __name__ == "__main__":
    unittest.main()
