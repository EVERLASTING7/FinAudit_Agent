from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import ANY, Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.knowledge import (
    get_knowledge_index_management_service,
    get_rag_query_service,
)
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.retrieval import (
    EvaluationDatasetData,
    EvaluationRunData,
    EvaluationTier,
    IndexStatus,
    IndexVersionData,
    QaCitationData,
    QaFeedbackData,
    QaQueryData,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.knowledge_index_management import (
    DatasetMutationResult,
    EvaluationRunMutationResult,
    IndexMutationResult,
    KnowledgeIndexManagementService,
)
from app.services.rag_query import (
    QaFeedbackMutationResult,
    QaQueryMutationResult,
    RagQueryService,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("9d000000-0000-4000-8000-000000000001")
USER_ID = UUID("9d000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("9d000000-0000-4000-8000-000000000003")
KNOWLEDGE_BASE_ID = UUID("9d000000-0000-4000-8000-000000000004")
INDEX_ID = UUID("9d000000-0000-4000-8000-000000000005")
DATASET_ID = UUID("9d000000-0000-4000-8000-000000000006")
RUN_ID = UUID("9d000000-0000-4000-8000-000000000007")
JOB_ID = UUID("9d000000-0000-4000-8000-000000000008")
QUERY_ID = UUID("9d000000-0000-4000-8000-000000000009")
FEEDBACK_ID = UUID("9d000000-0000-4000-8000-00000000000a")
POLICY_ID = UUID("9d000000-0000-4000-8000-00000000000b")
MARKDOWN_ID = UUID("9d000000-0000-4000-8000-00000000000c")
CHUNK_ID = UUID("9d000000-0000-4000-8000-00000000000d")
BLOCK_ID = UUID("9d000000-0000-4000-8000-00000000000e")
NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _auth_service() -> Mock:
    service = Mock(spec=AuthService)
    permissions = (
        "knowledge.approve",
        "knowledge.publish",
        "knowledge.submit",
        "knowledge.use",
    )
    roles = ("audit_reviewer", "system_admin")
    actor = AuthenticatedActor(USER_ID, ORGANIZATION_ID, SESSION_ID, roles, permissions)
    current = CurrentUserData(
        id=USER_ID,
        display_name="知识管理员",
        roles=roles,
        permissions=permissions,
    )
    service.authenticate.return_value = actor, current
    return service


def _index() -> IndexVersionData:
    return IndexVersionData(
        id=INDEX_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        version_no=1,
        status=IndexStatus.READY,
        collection_name="finaudit-test",
        embedding_adapter_id="deterministic_hash_v1",
        embedding_model_id="embedding-test",
        vector_dimension=16,
        distance="Cosine",
        member_count=1,
        manifest_sha256="a" * 64,
        consistency={"member_count_match": True},
        failure_code=None,
        row_version="2",
        job_id=JOB_ID,
        job_status="succeeded",
        created_at=NOW,
        activated_at=None,
    )


def _dataset() -> EvaluationDatasetData:
    return EvaluationDatasetData(
        id=DATASET_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        version_no=1,
        name="smoke-v1",
        tier=EvaluationTier.SMOKE,
        status="draft",
        answer_score_threshold="0.5",
        case_count=5,
        manifest_sha256="b" * 64,
        submitted_by=None,
        submitted_at=None,
        approved_by=None,
        approved_at=None,
        row_version="1",
    )


def _run() -> EvaluationRunData:
    return EvaluationRunData(
        id=RUN_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        index_version_id=INDEX_ID,
        dataset_id=DATASET_ID,
        tier=EvaluationTier.SMOKE,
        status="running",
        case_count=5,
        completed_case_count=0,
        metrics={},
        failure_code=None,
        job_id=JOB_ID,
        job_status="queued",
    )


def _query() -> QaQueryData:
    citation = QaCitationData(
        policy_document_id=POLICY_ID,
        policy_version="1.0",
        markdown_version_id=MARKDOWN_ID,
        chunk_id=CHUNK_ID,
        block_ids=(BLOCK_ID,),
        index_version_id=INDEX_ID,
        page_range="1",
        title_path=("差旅",),
        quote="住宿费标准为每晚五百元。",
        content_sha256="c" * 64,
    )
    return QaQueryData(
        id=QUERY_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        index_version_id=INDEX_ID,
        baseline_date=date(2026, 8, 14),
        status="answered",
        answer="根据制度：住宿费标准为每晚五百元。",
        reason_code=None,
        citations=(citation,),
        retrieved_count=1,
        created_at=NOW,
    )


def _management_service() -> Mock:
    service = Mock(spec=KnowledgeIndexManagementService)
    service.build_index.return_value = IndexMutationResult(_index(), False, 202)
    service.get_index.return_value = _index()
    service.activate_index.return_value = IndexMutationResult(_index(), False, 200)
    service.create_dataset.return_value = DatasetMutationResult(_dataset(), False, 201)
    service.get_dataset.return_value = _dataset()
    service.transition_dataset.return_value = DatasetMutationResult(_dataset(), False, 200)
    service.create_evaluation_run.return_value = EvaluationRunMutationResult(_run(), False, 202)
    service.get_evaluation_run.return_value = _run()
    return service


def _rag_service() -> Mock:
    service = Mock(spec=RagQueryService)
    service.query.return_value = QaQueryMutationResult(_query(), False)
    service.feedback.return_value = QaFeedbackMutationResult(
        QaFeedbackData(
            id=FEEDBACK_ID,
            qa_query_id=QUERY_ID,
            rating="helpful",
            correction_text=None,
            created_at=NOW,
        ),
        False,
    )
    return service


def _application(policy_file: Path, management: Mock, rag: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = _auth_service
    app.dependency_overrides[get_knowledge_index_management_service] = lambda: management
    app.dependency_overrides[get_rag_query_service] = lambda: rag
    return app


def test_knowledge_runtime_routes_are_private_and_idempotent(
    exact_policy_file: Path,
) -> None:
    management = _management_service()
    rag = _rag_service()
    headers = {
        "Authorization": "Bearer token",
        "Idempotency-Key": "knowledge-operation-001",
    }
    with TestClient(_application(exact_policy_file, management, rag)) as client:
        built = client.post(
            f"/api/v1/knowledge-bases/{KNOWLEDGE_BASE_ID}/index-versions",
            headers=headers,
            json={},
        )
        evaluated = client.post(
            f"/api/v1/knowledge-bases/{KNOWLEDGE_BASE_ID}/index-versions/{INDEX_ID}/evaluations",
            headers=headers,
            json={"dataset_id": str(DATASET_ID)},
        )
        queried = client.post(
            f"/api/v1/knowledge-bases/{KNOWLEDGE_BASE_ID}/qa-queries",
            headers=headers,
            json={"question": "住宿费标准是多少？", "baseline_date": "2026-08-14"},
        )
        feedback = client.post(
            f"/api/v1/qa-queries/{QUERY_ID}/feedback",
            headers=headers,
            json={"rating": "helpful", "correction_text": None},
        )

    assert built.status_code == 202, built.text
    assert evaluated.status_code == 202, evaluated.text
    assert queried.status_code == 200, queried.text
    assert feedback.status_code == 201, feedback.text
    for response in (built, evaluated, queried, feedback):
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["idempotency-replayed"] == "false"
    assert queried.json()["data"]["citations"][0]["block_ids"] == [str(BLOCK_ID)]
    management.build_index.assert_called_once_with(
        ANY, KNOWLEDGE_BASE_ID, "knowledge-operation-001", ANY
    )
    rag.query.assert_called_once_with(ANY, KNOWLEDGE_BASE_ID, ANY, "knowledge-operation-001", ANY)


def test_evaluation_dataset_accepts_its_public_json_contract(exact_policy_file: Path) -> None:
    management = _management_service()
    cases = [
        {
            "label": "no_answer",
            "query_text": f"No evidence case {number}",
            "baseline_date": "2026-08-14",
            "allowed_policy_ids": [],
            "expected_chunk_ids": [],
            "forbidden_chunk_ids": [],
        }
        for number in range(1, 6)
    ]

    with TestClient(_application(exact_policy_file, management, _rag_service())) as client:
        response = client.post(
            f"/api/v1/knowledge-bases/{KNOWLEDGE_BASE_ID}/retrieval-eval-datasets",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "knowledge-dataset-json-001",
            },
            json={
                "name": "smoke-v1",
                "tier": "smoke",
                "answer_score_threshold": "0.5",
                "cases": cases,
            },
        )

    assert response.status_code == 201, response.text
    payload = management.create_dataset.call_args.args[2]
    assert payload.tier is EvaluationTier.SMOKE
    assert type(payload.cases) is tuple
    assert all(type(case.allowed_policy_ids) is tuple for case in payload.cases)


def test_knowledge_openapi_freezes_management_and_rag_paths(exact_policy_file: Path) -> None:
    with TestClient(
        _application(exact_policy_file, _management_service(), _rag_service())
    ) as client:
        paths = client.get("/openapi.json").json()["paths"]
    expected = {
        (
            "/api/v1/knowledge-bases/{knowledge_base_id}/index-versions",
            "post",
        ): "build_knowledge_index_v1",
        (
            "/api/v1/knowledge-bases/{knowledge_base_id}/index-versions/{index_version_id}",
            "get",
        ): "get_knowledge_index_v1",
        (
            "/api/v1/knowledge-bases/{knowledge_base_id}/index-versions/"
            "{index_version_id}/evaluations",
            "post",
        ): "evaluate_knowledge_index_v1",
        (
            "/api/v1/knowledge-bases/{knowledge_base_id}/index-versions/"
            "{index_version_id}/activate",
            "post",
        ): "activate_knowledge_index_v1",
        (
            "/api/v1/knowledge-bases/{knowledge_base_id}/retrieval-eval-datasets",
            "post",
        ): "create_retrieval_eval_dataset_v1",
        (
            "/api/v1/knowledge-bases/{knowledge_base_id}/qa-queries",
            "post",
        ): "query_knowledge_base_v1",
        ("/api/v1/qa-queries/{query_id}/feedback", "post"): "create_qa_feedback_v1",
    }
    for (path, method), operation_id in expected.items():
        assert paths[path][method]["operationId"] == operation_id


def test_knowledge_permission_and_schema_fail_before_services(
    exact_policy_file: Path,
) -> None:
    management = _management_service()
    rag = _rag_service()
    auth = _auth_service()
    auth.authenticate.return_value = (
        AuthenticatedActor(
            USER_ID,
            ORGANIZATION_ID,
            SESSION_ID,
            ("read_only",),
            ("financial.read",),
        ),
        auth.authenticate.return_value[1],
    )
    app = _application(exact_policy_file, management, rag)
    app.dependency_overrides[get_auth_service] = lambda: auth
    with TestClient(app) as client:
        forbidden = client.post(
            f"/api/v1/knowledge-bases/{KNOWLEDGE_BASE_ID}/qa-queries",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "knowledge-denied-001",
            },
            json={"question": "住宿费标准？", "baseline_date": "2026-08-14"},
        )
        assert forbidden.status_code == 403

        app.dependency_overrides[get_auth_service] = _auth_service
        invalid = client.post(
            f"/api/v1/knowledge-bases/{KNOWLEDGE_BASE_ID}/index-versions",
            headers={
                "Authorization": "Bearer token",
                "Idempotency-Key": "knowledge-invalid-001",
            },
            json={"unexpected": True},
        )
        assert invalid.status_code == 422
    management.build_index.assert_not_called()
    rag.query.assert_not_called()
