from __future__ import annotations

import json
import os
import re
import sys
import time
from importlib import resources
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.ai.adapters.openai_compatible import (  # noqa: E402
    OPENAI_EMBEDDINGS_ADAPTER_ID,
    OpenAiCompatibleProfile,
    OpenAiEmbeddingsAdapter,
)
from app.ai.contracts import TransportPolicy  # noqa: E402
from app.ai.embedding_runtime import (  # noqa: E402
    EmbeddingCallIdentity,
    EmbeddingRuntime,
)
from app.ai.gateway import AiGateway  # noqa: E402
from app.ai.live_policy import (  # noqa: E402
    LIVE_EMBEDDING_POLICY,
    LIVE_POLICY_HASH,
    LIVE_POLICY_ID,
    LIVE_POLICY_RAW_SHA256,
)
from app.ai.network_policy import OutboundNetworkPolicy  # noqa: E402
from app.ai.policy_loader import ValidatedPolicySnapshot  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.migration import create_migration_engine  # noqa: E402
from app.db.session import create_session_factory  # noqa: E402
from app.models.auth import Organization  # noqa: E402
from app.services.ai_call_audit import AiCallAuditService  # noqa: E402

_CONFIRMATION = "ALLOW_ONE_BOUNDED_BAILIAN_EMBEDDING_CALL"
_REUSE_CONFIRMATION = "REUSE_REPOSITORY_BAILIAN_KEY"
_DESTRUCTIVE_CONFIRMATION = "RESET_DISPOSABLE_FINAUDIT_TEST_DATABASE"
_DATABASE_MARKER = "finaudit:disposable-migration-test"
_SAFE_DATABASE_NAME = re.compile(r"^finaudit_[a-z0-9_]+_test$")
_REGISTRY_SHA256 = "628dbf127cf3e88095c479cd8a6a03e87ece7e7f0977856357269579188eca34"
_INPUT_TEXTS = ("合同金额与付款条件", "发票号码与销售方税号")
_ORGANIZATION_ID = UUID("7254aede-786f-4ace-a4e6-44667a6b8be1")


class LiveBailianSmokeError(RuntimeError):
    pass


def _api_key() -> SecretStr:
    value = os.environ.get("EMBEDDING_API_KEY", "").strip()
    if not value and os.environ.get("FINAUDIT_REUSE_REPOSITORY_BAILIAN_KEY") == (
        _REUSE_CONFIRMATION
    ):
        configured = Settings().embedding_api_key
        value = "" if configured is None else configured.get_secret_value().strip()
    if (
        not value
        or value.upper().startswith("REPLACE_")
        or value.lower().startswith("disabled-local-")
    ):
        raise LiveBailianSmokeError("EMBEDDING_API_KEY_REQUIRED")
    return SecretStr(value)


def _database_url() -> str:
    raw = os.environ.get("TEST_DATABASE_URL", "")
    if not raw or os.environ.get("FINAUDIT_ALLOW_DESTRUCTIVE_DB_TESTS") != (
        _DESTRUCTIVE_CONFIRMATION
    ):
        raise LiveBailianSmokeError("DISPOSABLE_TEST_DATABASE_REQUIRED")
    try:
        parsed = make_url(raw)
    except Exception:
        raise LiveBailianSmokeError("DISPOSABLE_TEST_DATABASE_REQUIRED") from None
    if (
        parsed.drivername != "postgresql+psycopg"
        or parsed.host not in {"127.0.0.1", "localhost"}
        or parsed.query
        or _SAFE_DATABASE_NAME.fullmatch((parsed.database or "").lower()) is None
    ):
        raise LiveBailianSmokeError("DISPOSABLE_TEST_DATABASE_REQUIRED")
    return raw


def _adapter(api_key: SecretStr) -> OpenAiEmbeddingsAdapter:
    registry_bytes = (
        resources.files("app.ai.artifacts.cr011_v1")
        .joinpath("ip-deny-cidrs-v1.json")
        .read_bytes()
    )
    network_policy = OutboundNetworkPolicy(
        endpoint_id=LIVE_EMBEDDING_POLICY.endpoint_id,
        network_scope="external_public",
        base_url=LIVE_EMBEDDING_POLICY.base_url,
        approved_hostnames=LIVE_EMBEDDING_POLICY.approved_hostnames,
        allowed_cidrs=LIVE_EMBEDDING_POLICY.allowed_cidrs,
        billing_mode="external_cny",
        address_policy_version="ip-deny-cidrs-v1",
        registry_sha256=_REGISTRY_SHA256,
    )
    return OpenAiEmbeddingsAdapter(
        OpenAiCompatibleProfile(
            profile_type="embedding",
            base_url=LIVE_EMBEDDING_POLICY.base_url,
            model_id=LIVE_EMBEDDING_POLICY.model_id,
            allowed_response_model_ids=LIVE_EMBEDDING_POLICY.allowed_response_model_ids,
            api_key=api_key,
            network_policy=network_policy,
            registry_bytes=registry_bytes,
            max_request_bytes=LIVE_EMBEDDING_POLICY.max_request_bytes,
            max_response_header_bytes=LIVE_EMBEDDING_POLICY.max_response_header_bytes,
            max_response_body_bytes=LIVE_EMBEDDING_POLICY.max_response_body_bytes,
            embedding_dimension=LIVE_EMBEDDING_POLICY.embedding_dimension,
        )
    )


def _run() -> dict[str, object]:
    if sys.argv != [sys.argv[0]]:
        raise LiveBailianSmokeError("ARGUMENTS_NOT_SUPPORTED")
    if os.environ.get("FINAUDIT_LIVE_BAILIAN_SMOKE") != _CONFIRMATION:
        raise LiveBailianSmokeError("LIVE_BAILIAN_SMOKE_CONFIRMATION_REQUIRED")
    api_key = _api_key()
    database_url = _database_url()
    engine = create_migration_engine(database_url)
    factory = create_session_factory(engine)
    adapter: OpenAiEmbeddingsAdapter | None = None
    try:
        with engine.connect() as connection:
            marker, revision = connection.execute(
                text(
                    "SELECT shobj_description(database_catalog.oid, 'pg_database'), "
                    "(SELECT version_num FROM alembic_version) "
                    "FROM pg_database AS database_catalog "
                    "WHERE database_catalog.datname=current_database()"
                )
            ).one()
        if marker != _DATABASE_MARKER or revision != "20260818_027":
            raise LiveBailianSmokeError("DISPOSABLE_TEST_DATABASE_REQUIRED")
        with factory.begin() as session:
            if session.scalar(
                select(Organization.id).where(Organization.id == _ORGANIZATION_ID)
            ):
                raise LiveBailianSmokeError("SMOKE_ORGANIZATION_CONFLICT")
            session.add(
                Organization(
                    id=_ORGANIZATION_ID,
                    name="Synthetic paid embedding smoke",
                    unified_social_credit_code="SYNTH-PAID-EMBEDDING-SMOKE",
                    tax_number="SYNTH-PAID-EMBEDDING-TAX",
                    status="active",
                )
            )

        adapter = _adapter(api_key)
        audit = AiCallAuditService(factory)
        runtime = EmbeddingRuntime(
            gateway=AiGateway(
                llm_adapters={},
                embedding_adapters={OPENAI_EMBEDDINGS_ADAPTER_ID: adapter},
            ),
            target=adapter.target,
            transport_policy=TransportPolicy(
                connect_timeout_seconds=5,
                read_timeout_seconds=LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
                total_timeout_seconds=LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
                max_attempts=1,
            ),
            policy_snapshot=ValidatedPolicySnapshot(
                policy_version=2,
                policy_hash=LIVE_POLICY_HASH,
                raw_sha256=LIVE_POLICY_RAW_SHA256,
                provider_calls_enabled=True,
                runtime_profile_id=LIVE_POLICY_ID,
            ),
            embedding_policy=LIVE_EMBEDDING_POLICY,
            audit_writer=audit,
        )
        operation_id = uuid4()
        trace_id = uuid4()
        result = runtime.embed_texts_audited(
            trace_id=str(trace_id),
            input_texts=_INPUT_TEXTS,
            identity=EmbeddingCallIdentity(
                organization_id=_ORGANIZATION_ID,
                business_operation_id=operation_id,
                job_id=None,
                request_id=trace_id,
                resource_type="knowledge_base",
                resource_id=None,
                trace_id=trace_id,
            ),
            deadline_monotonic=time.monotonic()
            + LIVE_EMBEDDING_POLICY.operation.deadline_seconds,
        )
        with factory.begin() as session:
            result.adoption.adopt_in_transaction(session)
        for _ in range(2):
            projected = audit.project_once()
            if projected.event_id is None:
                raise LiveBailianSmokeError("EMBEDDING_AUDIT_PROJECTION_FAILED")
        summary = audit.get_operation_summary(_ORGANIZATION_ID, operation_id)
        if (
            summary is None
            or summary.attempt_count != 1
            or summary.cost_currency != "CNY"
            or summary.actual_cost_microunits != result.actual_cost_microunits
            or summary.attempts[0].status != "succeeded"
        ):
            raise LiveBailianSmokeError("EMBEDDING_AUDIT_VERIFICATION_FAILED")
        return {
            "actual_cost_microunits": result.actual_cost_microunits,
            "audit_event_version": summary.attempts[0].event_version,
            "audit_status": summary.attempts[0].status,
            "cost_currency": result.cost_currency,
            "input_tokens": result.input_tokens,
            "model_id": adapter.target.model_id,
            "policy_hash": LIVE_POLICY_HASH,
            "policy_id": LIVE_POLICY_ID,
            "response_body_sha256": result.response_body_sha256,
            "status": "passed",
            "vector_count": len(result.vectors),
            "vector_dimension": len(result.vectors[0]),
        }
    finally:
        if adapter is not None:
            adapter.close()
        engine.dispose()


def main() -> int:
    try:
        summary = _run()
    except LiveBailianSmokeError as error:
        print(
            json.dumps({"code": str(error), "status": "failed"}, separators=(",", ":"))
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {"code": "LIVE_BAILIAN_SMOKE_UNEXPECTED", "status": "failed"},
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
