from __future__ import annotations

import contextlib
import io
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verify_local_minio_restart_persistence as subject  # noqa: E402
from minio.error import S3Error  # noqa: E402


def valid_environment() -> dict[str, str]:
    environment = {
        subject.GATE_ENV: subject.GATE_VALUE,
        "APP_ENV": "local",
        "MINIO_ENDPOINT": subject.LOCAL_ENDPOINT,
        "MINIO_SECURE": "false",
        "MINIO_ROOT_USER": "unit-test-root",
        "MINIO_ROOT_PASSWORD": "unit-test-root-password",
        "MINIO_ACCESS_KEY": "unit-test-app",
        "MINIO_SECRET_KEY": "unit-test-app-password",
    }
    environment.update({name: expected for name, expected in subject.BUCKET_ENV})
    return environment


def missing_object_error() -> S3Error:
    return S3Error(None, "NoSuchKey", "missing", None, None, None)


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False
        self.released = False

    def read(self, amount: int) -> bytes:
        return self.content[:amount]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeRootClient:
    def __init__(self) -> None:
        self.content: bytes | None = None
        self.content_type = "application/pdf"
        self.sha256 = subject.hashlib.sha256(subject.PAYLOAD).hexdigest()
        self.remove_calls = 0
        self.last_response: FakeResponse | None = None
        self.stat_calls = 0
        self.stat_failure_call: int | None = None

    def stat_object(self, bucket: str, key: str) -> object:
        self.stat_calls += 1
        if self.stat_calls == self.stat_failure_call:
            raise RuntimeError("provider stat sentinel")
        if self.content is None:
            raise missing_object_error()
        return SimpleNamespace(
            size=len(self.content),
            content_type=self.content_type,
            metadata={"x-amz-meta-sha256": self.sha256},
        )

    def get_object(self, bucket: str, key: str) -> FakeResponse:
        if self.content is None:
            raise missing_object_error()
        self.last_response = FakeResponse(self.content)
        return self.last_response

    def remove_object(self, bucket: str, key: str) -> None:
        self.remove_calls += 1
        self.content = None


class FakeAdapter:
    def __init__(self, root: FakeRootClient) -> None:
        self.root = root
        self.put_calls = 0
        self.delete_calls = 0
        self.put_error: Exception | None = None

    def put_quarantine(self, **kwargs: object) -> object:
        self.put_calls += 1
        data = kwargs["data"]
        length = kwargs["length"]
        assert hasattr(data, "read")
        assert isinstance(length, int)
        self.root.content = data.read(length)  # type: ignore[union-attr]
        if self.put_error is not None:
            raise self.put_error
        return subject.expected_locator()

    def delete_quarantine(self, locator: object) -> None:
        self.delete_calls += 1
        self.root.content = None


@dataclass
class Harness:
    root: FakeRootClient
    adapter: FakeAdapter

    @classmethod
    def create(cls) -> "Harness":
        root = FakeRootClient()
        return cls(root=root, adapter=FakeAdapter(root))

    def patches(self) -> tuple[object, object]:
        return (
            patch.object(subject, "_root_client", return_value=self.root),
            patch.object(subject, "MinioQuarantineAdapter", return_value=self.adapter),
        )


class RestartPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = subject.load_config(valid_environment())

    def test_config_repr_hides_all_credentials_and_rejects_unsafe_profile(self) -> None:
        rendered = repr(self.config)
        self.assertNotIn("unit-test-root", rendered)
        self.assertNotIn("unit-test-root-password", rendered)
        self.assertNotIn("unit-test-app", rendered)
        self.assertNotIn("unit-test-app-password", rendered)

        unsafe = valid_environment()
        unsafe["MINIO_ENDPOINT"] = "http://minio:9000"
        with self.assertRaisesRegex(
            subject.RestartPersistenceError, "LOCAL_PROFILE_INVALID"
        ):
            subject.load_config(unsafe)

    def test_prepare_verify_delete_and_cleanup_use_only_the_exact_owned_object(
        self,
    ) -> None:
        harness = Harness.create()
        root_patch, adapter_patch = harness.patches()
        with root_patch, adapter_patch:
            subject.prepare(self.config)
            self.assertEqual(harness.root.content, subject.PAYLOAD)
            subject.verify(self.config)
            self.assertIsNotNone(harness.root.last_response)
            assert harness.root.last_response is not None
            self.assertTrue(harness.root.last_response.closed)
            self.assertTrue(harness.root.last_response.released)
            subject.delete(self.config)
            self.assertIsNone(harness.root.content)
            subject.cleanup(self.config)

        self.assertEqual(harness.adapter.put_calls, 1)
        self.assertEqual(harness.adapter.delete_calls, 1)
        self.assertEqual(harness.root.remove_calls, 0)

    def test_prepare_refuses_a_preexisting_object_without_deleting_or_overwriting_it(
        self,
    ) -> None:
        harness = Harness.create()
        harness.root.content = b"preexisting"
        root_patch, adapter_patch = harness.patches()
        with root_patch, adapter_patch:
            with self.assertRaisesRegex(
                subject.RestartPersistenceError,
                "GATE_OBJECT_ALREADY_EXISTS",
            ):
                subject.prepare(self.config)

        self.assertEqual(harness.root.content, b"preexisting")
        self.assertEqual(harness.adapter.put_calls, 0)
        self.assertEqual(harness.root.remove_calls, 0)

    def test_prepare_failure_after_put_performs_exact_root_cleanup(self) -> None:
        harness = Harness.create()
        harness.root.content_type = "text/plain"
        root_patch, adapter_patch = harness.patches()
        with root_patch, adapter_patch:
            with self.assertRaisesRegex(
                subject.RestartPersistenceError,
                "ROOT_OBJECT_CONTENT_MISMATCH",
            ):
                subject.prepare(self.config)

        self.assertIsNone(harness.root.content)
        self.assertEqual(harness.root.remove_calls, 1)

    def test_prepare_exception_after_object_write_performs_exact_root_cleanup(
        self,
    ) -> None:
        harness = Harness.create()
        harness.adapter.put_error = TimeoutError("provider sentinel")
        root_patch, adapter_patch = harness.patches()
        with root_patch, adapter_patch:
            with self.assertRaisesRegex(
                subject.RestartPersistenceError,
                "APPLICATION_PREPARE_FAILED",
            ):
                subject.prepare(self.config)

        self.assertIsNone(harness.root.content)
        self.assertEqual(harness.root.remove_calls, 1)

    def test_prepare_cleanup_stat_failure_requires_owned_recovery(self) -> None:
        harness = Harness.create()
        harness.adapter.put_error = TimeoutError("provider sentinel")
        harness.root.stat_failure_call = 2
        root_patch, adapter_patch = harness.patches()
        with root_patch, adapter_patch:
            with self.assertRaisesRegex(
                subject.RestartPersistenceError,
                "PREPARE_CLEANUP_FAILED",
            ):
                subject.prepare(self.config)

        self.assertIsNotNone(harness.root.content)

    def test_cleanup_is_idempotent_for_the_gate_owned_exact_key(self) -> None:
        harness = Harness.create()
        harness.root.content = subject.PAYLOAD
        root_patch, adapter_patch = harness.patches()
        with root_patch, adapter_patch:
            subject.cleanup(self.config)
            subject.cleanup(self.config)

        self.assertEqual(harness.root.remove_calls, 1)

    def test_cleanup_refuses_to_delete_a_non_gate_object_at_the_fixed_key(self) -> None:
        harness = Harness.create()
        harness.root.content = b"preexisting"
        root_patch, adapter_patch = harness.patches()
        with root_patch, adapter_patch:
            with self.assertRaisesRegex(
                subject.RestartPersistenceError,
                "ROOT_OBJECT_CONTENT_MISMATCH",
            ):
                subject.cleanup(self.config)

        self.assertEqual(harness.root.content, b"preexisting")
        self.assertEqual(harness.root.remove_calls, 0)

    def test_main_outputs_only_fixed_codes(self) -> None:
        invalid = valid_environment()
        invalid[subject.GATE_ENV] = "wrong"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = subject.main(["gate", "prepare"], invalid)

        rendered = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("LOCAL_MINIO_RESTART_PERSISTENCE=FAIL", rendered)
        self.assertIn("LOCAL_MINIO_RESTART_REASON=GATE_CONFIRMATION_INVALID", rendered)
        for secret in (
            invalid["MINIO_ROOT_USER"],
            invalid["MINIO_ROOT_PASSWORD"],
            invalid["MINIO_ACCESS_KEY"],
            invalid["MINIO_SECRET_KEY"],
        ):
            self.assertNotIn(secret, rendered)

    def test_main_returns_owned_cleanup_required_exit_code(self) -> None:
        with (
            patch.object(
                subject,
                "prepare",
                side_effect=subject.RestartPersistenceError("PREPARE_CLEANUP_FAILED"),
            ),
            patch.dict(subject.PHASES, {"prepare": subject.prepare}),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = subject.main(["gate", "prepare"], valid_environment())

        self.assertEqual(exit_code, subject.CLEANUP_REQUIRED_EXIT_CODE)
        self.assertIn(
            "LOCAL_MINIO_RESTART_REASON=PREPARE_CLEANUP_FAILED", output.getvalue()
        )

    def test_main_rejects_invalid_arguments_without_a_traceback(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = subject.main(["gate"], valid_environment())

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "LOCAL_MINIO_RESTART_PERSISTENCE=FAIL",
                "LOCAL_MINIO_RESTART_REASON=ARGUMENTS_INVALID",
            ],
        )


if __name__ == "__main__":
    unittest.main()
