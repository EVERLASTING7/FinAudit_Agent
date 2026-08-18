from __future__ import annotations

import hashlib
import io
import os
import stat
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

from app.core.password_policy import validate_new_password


class SmokeError(RuntimeError):
    pass


def _read_password(path_value: str | None) -> str:
    if not path_value:
        raise SmokeError("PASSWORD_FILE_REQUIRED")
    path = Path(path_value)
    if not path.is_absolute() or path.is_symlink():
        raise SmokeError("PASSWORD_FILE_INVALID")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size < 12 or info.st_size > 512:
        raise SmokeError("PASSWORD_FILE_INVALID")
    password = path.read_text(encoding="utf-8")
    if password != password.strip() or "\x00" in password:
        raise SmokeError("PASSWORD_FILE_INVALID")
    return password


def _synthetic_pdf() -> bytes:
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(240, 160))
    document.drawString(20, 110, "FinAudit local Compose ClamAV smoke")
    document.save()
    payload = output.getvalue()
    if not payload.startswith(b"%PDF") or not payload.rstrip().endswith(b"%%EOF"):
        raise SmokeError("PDF_FIXTURE_INVALID")
    return payload


def _require_envelope(response: httpx.Response, status_code: int) -> dict[str, object]:
    if response.status_code != status_code:
        raise SmokeError("HTTP_STATUS_INVALID")
    value = response.json()
    if not isinstance(value, dict) or value.get("code") != "OK":
        raise SmokeError("HTTP_ENVELOPE_INVALID")
    data = value.get("data")
    if not isinstance(data, dict):
        raise SmokeError("HTTP_ENVELOPE_INVALID")
    return data


def _login(client: httpx.Client, username: str, initial_password: str) -> str:
    changed_password = validate_new_password(initial_password + "-changed")
    first = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": initial_password, "remember_me": False},
    )
    if first.status_code == 403:
        payload = first.json()
        token = payload.get("data", {}).get("password_change_token")
        if payload.get("code") != "AUTH_PASSWORD_CHANGE_REQUIRED" or not isinstance(
            token, str
        ):
            raise SmokeError("PASSWORD_CHANGE_CONTRACT_INVALID")
        changed = client.post(
            "/api/v1/auth/password/change",
            headers={"Authorization": f"Bearer {token}"},
            json={"new_password": changed_password},
        )
        if changed.status_code != 204:
            raise SmokeError("PASSWORD_CHANGE_FAILED")
    elif first.status_code == 200:
        data = _require_envelope(first, 200)
        token = data.get("access_token")
        if isinstance(token, str) and token:
            return token
        raise SmokeError("ACCESS_TOKEN_MISSING")
    elif first.status_code != 401:
        raise SmokeError("INITIAL_LOGIN_STATUS_INVALID")

    second = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": changed_password, "remember_me": False},
    )
    data = _require_envelope(second, 200)
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        raise SmokeError("ACCESS_TOKEN_MISSING")
    return token


def run() -> None:
    base_url = os.environ.get("FINAUDIT_SMOKE_BASE_URL")
    origin = os.environ.get("AUTH_PUBLIC_ORIGIN")
    username = os.environ.get("BOOTSTRAP_ADMIN_USERNAME")
    if (
        base_url != "http://frontend:8443"
        or not origin
        or not origin.startswith("http://localhost:")
        or not username
    ):
        raise SmokeError("SMOKE_PROFILE_INVALID")
    password = _read_password(os.environ.get("BOOTSTRAP_ADMIN_PASSWORD_FILE"))
    pdf = _synthetic_pdf()
    host = origin.removeprefix("http://")

    with httpx.Client(
        base_url=base_url,
        verify=False,
        timeout=httpx.Timeout(15),
        headers={"Origin": origin, "Host": host},
    ) as client:
        admin_token = _login(client, username, password)
        uploader_suffix = uuid4().hex[:12]
        uploader_username = f"local-smoke-{uploader_suffix}"
        uploader_password = validate_new_password(
            f"{password}-uploader-{uploader_suffix}"
        )
        created_user = client.post(
            "/api/v1/users",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Idempotency-Key": f"local-compose-user-smoke.{uuid4()}",
            },
            json={
                "username": uploader_username,
                "display_name": "本地文件上传验收账号",
                "initial_password": uploader_password,
                "fixed_roles": ["finance_reviewer"],
            },
        )
        _require_envelope(created_user, 201)
        access_token = _login(client, uploader_username, uploader_password)
        authorization = {"Authorization": f"Bearer {access_token}"}
        accepted = client.post(
            "/api/v1/files",
            headers={
                **authorization,
                "Idempotency-Key": f"local-compose-file-smoke.{uuid4()}",
            },
            data={
                "intended_business_type": "contract",
                "auto_process_requested": "false",
            },
            files={
                "file": ("local-compose-clamav-smoke.pdf", pdf, "application/pdf"),
            },
        )
        accepted_data = _require_envelope(accepted, 202)
        file_id = accepted_data.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            raise SmokeError("FILE_ID_MISSING")

        final: dict[str, object] | None = None
        for _ in range(120):
            response = client.get(f"/api/v1/files/{file_id}", headers=authorization)
            data = _require_envelope(response, 200)
            if data.get("job_status") in {"succeeded", "failed", "cancelled"}:
                final = data
                break
            time.sleep(0.5)
        if final is None:
            raise SmokeError("FILE_JOB_TIMEOUT")
        if (
            final.get("job_status") != "succeeded"
            or final.get("status") != "stored"
            or final.get("security_scan_status") != "clean"
        ):
            raise SmokeError("FILE_JOB_RESULT_INVALID")

        preview = client.get(f"/api/v1/files/{file_id}/preview", headers=authorization)
        if (
            preview.status_code != 200
            or preview.content != pdf
            or preview.headers.get("etag") != f'"{hashlib.sha256(pdf).hexdigest()}"'
            or preview.headers.get("x-file-status") != "stored"
        ):
            raise SmokeError("FILE_PREVIEW_INVALID")


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            raise SmokeError("ARGUMENTS_NOT_SUPPORTED")
        run()
    except SmokeError as error:
        print("LOCAL_FILE_UPLOAD_SMOKE=FAIL")
        print(f"LOCAL_FILE_UPLOAD_REASON={error}")
        return 1
    except Exception:
        print("LOCAL_FILE_UPLOAD_SMOKE=FAIL")
        print("LOCAL_FILE_UPLOAD_REASON=UNEXPECTED_FAILURE")
        return 1
    print("LOCAL_FILE_UPLOAD_SMOKE=PASS")
    print("LOCAL_FILE_MULTIPART_HTTP_GATE=PASS")
    print("LOCAL_FILE_ROLE_BOUNDARY_GATE=PASS")
    print("LOCAL_FILE_CLAMAV_WORKER_GATE=PASS")
    print("LOCAL_FILE_PREVIEW_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
