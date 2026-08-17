from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_auth_service
from app.api.dependencies.reports import get_report_management_service
from app.bootstrap import create_app
from app.schemas.auth import CurrentUserData
from app.schemas.reports import AuditReportData, AuditReportListData
from app.services.auth import AuthenticatedActor, AuthService
from app.services.report_management import (
    ReportArtifactResult,
    ReportManagementService,
)
from tests.unit.startup_policy_support import (
    _exact_policy_file,  # noqa: F401
    build_startup_settings,
)

_ORGANIZATION_ID = UUID("b5000000-0000-4000-8000-000000000001")
_USER_ID = UUID("b5000000-0000-4000-8000-000000000002")
_SESSION_ID = UUID("b5000000-0000-4000-8000-000000000003")
_TASK_ID = UUID("b5000000-0000-4000-8000-000000000004")
_EXECUTION_ID = UUID("b5000000-0000-4000-8000-000000000005")
_REPORT_ID = UUID("b5000000-0000-4000-8000-000000000006")
_JOB_ID = UUID("b5000000-0000-4000-8000-000000000007")
_NOW = datetime(2026, 8, 14, 9, tzinfo=timezone.utc)
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _report() -> AuditReportData:
    return AuditReportData(
        id=_REPORT_ID,
        audit_task_id=_TASK_ID,
        execution_id=_EXECUTION_ID,
        report_version=1,
        status="ready",
        payload_sha256="a" * 64,
        generator_version="formal-report-generator-v2",
        pdf_sha256="b" * 64,
        pdf_size_bytes=12,
        pdf_mime_type="application/pdf",
        xlsx_sha256="c" * 64,
        xlsx_size_bytes=14,
        xlsx_mime_type=_XLSX_MIME,
        job_id=_JOB_ID,
        failure_code=None,
        row_version="2",
        created_by=_USER_ID,
        created_at=_NOW,
        generated_at=_NOW,
        outdated_at=None,
        archived_at=None,
        is_outdated=False,
    )


def _auth_service(permissions: tuple[str, ...]) -> Mock:
    service = Mock(spec=AuthService)
    sorted_permissions = tuple(sorted(permissions))
    actor = AuthenticatedActor(
        _USER_ID,
        _ORGANIZATION_ID,
        _SESSION_ID,
        ("finance_reviewer",),
        sorted_permissions,
    )
    current = CurrentUserData(
        id=_USER_ID,
        display_name="财务审核员",
        roles=("finance_reviewer",),
        permissions=sorted_permissions,
    )
    service.authenticate.return_value = actor, current
    return service


def _report_service() -> Mock:
    service = Mock(spec=ReportManagementService)
    service.list_reports.return_value = AuditReportListData(
        execution_id=_EXECUTION_ID,
        items=(_report(),),
    )
    service.get_report.return_value = _report()
    service.preview_pdf.return_value = ReportArtifactResult(
        content=b"%PDF-report",
        filename=f"audit-report-{_REPORT_ID}-v1.pdf",
        mime_type="application/pdf",
        sha256="b" * 64,
        status="ready",
        is_outdated=False,
    )
    service.download_xlsx.return_value = ReportArtifactResult(
        content=b"PK-report-xlsx",
        filename=f"audit-report-{_REPORT_ID}-v1-risks.xlsx",
        mime_type=_XLSX_MIME,
        sha256="c" * 64,
        status="outdated",
        is_outdated=True,
    )
    return service


def _application(policy_file: Path, auth: Mock, reports: Mock) -> FastAPI:
    app = create_app(build_startup_settings(policy_file))
    app.dependency_overrides[get_auth_service] = lambda: auth
    app.dependency_overrides[get_report_management_service] = lambda: reports
    return app


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer token"}


def test_report_metadata_routes_are_private_and_do_not_expose_storage_locator(
    exact_policy_file: Path,
) -> None:
    reports = _report_service()
    with TestClient(
        _application(
            exact_policy_file,
            _auth_service(("reports.read", "reports.export")),
            reports,
        )
    ) as client:
        listing = client.get(
            f"/api/v1/audit-executions/{_EXECUTION_ID}/reports",
            headers=_headers(),
        )
        detail = client.get(f"/api/v1/audit-reports/{_REPORT_ID}", headers=_headers())

    assert listing.status_code == detail.status_code == 200
    assert listing.headers["cache-control"] == "private, no-store"
    assert detail.headers["cache-control"] == "private, no-store"
    rendered = listing.text + detail.text
    assert "bucket" not in rendered
    assert "object_key" not in rendered
    assert "minio" not in rendered.lower()
    reports.list_reports.assert_called_once_with(_ORGANIZATION_ID, _EXECUTION_ID)
    reports.get_report.assert_called_once_with(_ORGANIZATION_ID, _REPORT_ID)


def test_pdf_is_inline_and_xlsx_is_attachment_with_outdated_header(
    exact_policy_file: Path,
) -> None:
    reports = _report_service()
    with TestClient(
        _application(
            exact_policy_file,
            _auth_service(("reports.read", "reports.export")),
            reports,
        )
    ) as client:
        preview = client.get(
            f"/api/v1/audit-reports/{_REPORT_ID}/preview",
            headers=_headers(),
        )
        download = client.get(
            f"/api/v1/audit-reports/{_REPORT_ID}/download",
            headers=_headers(),
        )

    assert preview.status_code == download.status_code == 200
    assert preview.content == b"%PDF-report"
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.headers["content-disposition"].startswith("inline;")
    assert preview.headers["x-report-outdated"] == "false"
    assert download.content == b"PK-report-xlsx"
    assert download.headers["content-type"] == _XLSX_MIME
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-report-outdated"] == "true"
    reports.preview_pdf.assert_called_once()
    reports.download_xlsx.assert_called_once()


def test_read_only_actor_cannot_export(exact_policy_file: Path) -> None:
    reports = _report_service()
    with TestClient(
        _application(exact_policy_file, _auth_service(("reports.read",)), reports)
    ) as client:
        preview = client.get(
            f"/api/v1/audit-reports/{_REPORT_ID}/preview",
            headers=_headers(),
        )
        download = client.get(
            f"/api/v1/audit-reports/{_REPORT_ID}/download",
            headers=_headers(),
        )

    assert preview.status_code == 200
    assert download.status_code == 403
    reports.download_xlsx.assert_not_called()


def test_report_openapi_freezes_metadata_preview_and_download_operations(
    exact_policy_file: Path,
) -> None:
    app = _application(
        exact_policy_file,
        _auth_service(("reports.read", "reports.export")),
        _report_service(),
    )
    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    expected = {
        "/api/v1/audit-executions/{execution_id}/reports": "list_audit_reports_v1",
        "/api/v1/audit-reports/{report_id}": "get_audit_report_v1",
        "/api/v1/audit-reports/{report_id}/preview": "preview_audit_report_pdf_v1",
        "/api/v1/audit-reports/{report_id}/download": "download_audit_report_xlsx_v1",
    }
    for path, operation_id in expected.items():
        assert paths[path]["get"]["operationId"] == operation_id
