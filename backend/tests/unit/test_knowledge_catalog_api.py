from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.knowledge_catalog import get_knowledge_catalog_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.knowledge_bases import (
    KnowledgeBaseData,
    KnowledgeBaseListData,
    KnowledgeBaseStatus,
)
from app.services.auth import AuthenticatedActor, AuthService
from app.services.knowledge_catalog import KnowledgeCatalogService
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

ORGANIZATION_ID = UUID("6a000000-0000-4000-8000-000000000001")
USER_ID = UUID("6a000000-0000-4000-8000-000000000002")
SESSION_ID = UUID("6a000000-0000-4000-8000-000000000003")
KNOWLEDGE_BASE_ID = UUID("6a000000-0000-4000-8000-000000000004")


def _knowledge_base() -> KnowledgeBaseData:
    return KnowledgeBaseData(
        id=KNOWLEDGE_BASE_ID,
        code="finance-policy",
        name="财务制度知识库",
        description="当前组织已授权的财务制度",
        status=KnowledgeBaseStatus.ACTIVE,
        default_top_k=5,
        row_version="2",
    )


def _auth_service() -> Mock:
    service = Mock(spec=AuthService)
    actor = AuthenticatedActor(
        USER_ID,
        ORGANIZATION_ID,
        SESSION_ID,
        ("finance_reviewer",),
        ("knowledge.use",),
    )
    current = CurrentUserData(
        id=USER_ID,
        display_name="财务复核人",
        roles=("finance_reviewer",),
        permissions=("knowledge.use",),
    )
    service.authenticate.return_value = actor, current
    return service


def _catalog_service() -> Mock:
    service = Mock(spec=KnowledgeCatalogService)
    service.list_page.return_value = KnowledgeBaseListData(
        items=(_knowledge_base(),),
        page_size=20,
        next_cursor=None,
    )
    service.get_detail.return_value = _knowledge_base()
    return service


def _application(policy_file: Path, auth: Mock, catalog: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_knowledge_catalog_service] = lambda: catalog
    return app


def test_knowledge_catalog_reads_are_private_and_actor_scoped(
    exact_policy_file: Path,
) -> None:
    auth = _auth_service()
    catalog = _catalog_service()
    with TestClient(_application(exact_policy_file, auth, catalog)) as client:
        listing = client.get(
            "/api/v1/knowledge-bases?page_size=20",
            headers={"Authorization": "Bearer token"},
        )
        detail = client.get(
            f"/api/v1/knowledge-bases/{KNOWLEDGE_BASE_ID}",
            headers={"Authorization": "Bearer token"},
        )

    assert listing.status_code == 200, listing.text
    assert detail.status_code == 200, detail.text
    assert listing.headers["cache-control"] == "private, no-store"
    assert detail.headers["cache-control"] == "private, no-store"
    assert detail.json()["data"]["default_top_k"] == 5
    catalog.list_page.assert_called_once_with(ORGANIZATION_ID, None, 20)
    catalog.get_detail.assert_called_once_with(ORGANIZATION_ID, KNOWLEDGE_BASE_ID)


def test_knowledge_catalog_rejects_unknown_query_before_service(
    exact_policy_file: Path,
) -> None:
    catalog = _catalog_service()
    with TestClient(_application(exact_policy_file, _auth_service(), catalog)) as client:
        response = client.get(
            "/api/v1/knowledge-bases?unknown=true",
            headers={"Authorization": "Bearer token"},
        )

    assert response.status_code == 422
    catalog.list_page.assert_not_called()


def test_knowledge_catalog_openapi_freezes_read_operations(
    exact_policy_file: Path,
) -> None:
    app = _application(exact_policy_file, _auth_service(), _catalog_service())
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert paths["/api/v1/knowledge-bases"]["get"]["operationId"] == ("list_knowledge_bases_v1")
    assert (
        paths["/api/v1/knowledge-bases/{knowledge_base_id}"]["get"]["operationId"]
        == "get_knowledge_base_v1"
    )
