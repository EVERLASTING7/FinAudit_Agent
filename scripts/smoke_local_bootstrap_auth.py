from __future__ import annotations

import os
import sys

import httpx

from app.bootstrap_admin import load_config
from app.core.password_policy import validate_new_password


class SmokeError(RuntimeError):
    pass


def _require_status(response: httpx.Response, status_code: int, code: str) -> None:
    if response.status_code != status_code:
        raise SmokeError(code)


def run() -> None:
    base_url = os.environ.get("FINAUDIT_SMOKE_BASE_URL")
    origin = os.environ.get("AUTH_PUBLIC_ORIGIN")
    if base_url != "http://backend:8000" or not origin or not origin.startswith(
        "https://localhost:"
    ):
        raise SmokeError("SMOKE_PROFILE_INVALID")
    config = load_config(os.environ)
    changed_password = validate_new_password(config.admin_password + "-changed")

    with httpx.Client(
        base_url=base_url,
        headers={"Origin": origin},
        timeout=httpx.Timeout(10),
    ) as client:
        first_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": config.admin_username,
                "password": config.admin_password,
                "remember_me": False,
            },
        )
        if first_login.status_code == 403:
            first_payload = first_login.json()
            if (
                first_payload.get("code") != "AUTH_PASSWORD_CHANGE_REQUIRED"
                or first_login.headers.get("cache-control") != "no-store"
            ):
                raise SmokeError("INITIAL_LOGIN_CONTRACT_INVALID")
            password_change_token = first_payload.get("data", {}).get("password_change_token")
            if not isinstance(password_change_token, str) or not password_change_token:
                raise SmokeError("PASSWORD_CHANGE_TOKEN_MISSING")

            changed = client.post(
                "/api/v1/auth/password/change",
                headers={"Authorization": f"Bearer {password_change_token}"},
                json={"new_password": changed_password},
            )
            _require_status(changed, 204, "PASSWORD_CHANGE_STATUS_INVALID")
        elif first_login.status_code != 401:
            raise SmokeError("INITIAL_LOGIN_STATUS_INVALID")

        second_login = client.post(
            "/api/v1/auth/login",
            json={
                "username": config.admin_username,
                "password": changed_password,
                "remember_me": False,
            },
        )
        _require_status(second_login, 200, "SECOND_LOGIN_STATUS_INVALID")
        second_payload = second_login.json()
        access_token = second_payload.get("data", {}).get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SmokeError("ACCESS_TOKEN_MISSING")
        current_user = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        _require_status(current_user, 200, "CURRENT_USER_STATUS_INVALID")
        user_payload = current_user.json().get("data", {})
        if user_payload.get("roles") != ["system_admin"]:
            raise SmokeError("CURRENT_USER_ROLE_INVALID")


def main() -> int:
    try:
        if sys.argv != [sys.argv[0]]:
            raise SmokeError("ARGUMENTS_NOT_SUPPORTED")
        run()
    except SmokeError as error:
        print("LOCAL_BOOTSTRAP_AUTH_SMOKE=FAIL")
        print(f"LOCAL_BOOTSTRAP_AUTH_REASON={error}")
        return 1
    except Exception:
        print("LOCAL_BOOTSTRAP_AUTH_SMOKE=FAIL")
        print("LOCAL_BOOTSTRAP_AUTH_REASON=UNEXPECTED_FAILURE")
        return 1
    print("LOCAL_BOOTSTRAP_AUTH_SMOKE=PASS")
    print("LOCAL_BOOTSTRAP_FORCE_CHANGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
