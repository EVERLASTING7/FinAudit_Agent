from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.config import Settings


def get_settings(request: Request) -> Settings:
    """从应用生命周期状态读取已完成校验的配置。"""
    return cast(Settings, request.app.state.settings)


SettingsDependency = Annotated[Settings, Depends(get_settings)]
