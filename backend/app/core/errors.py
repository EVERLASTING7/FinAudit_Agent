from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    """仅承载可安全返回给调用方的已分类应用错误。"""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: list[dict[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []
        self.data = data
        self.headers = headers
