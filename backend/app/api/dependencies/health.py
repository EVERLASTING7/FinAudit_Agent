from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from app.api.dependencies.settings import SettingsDependency
from app.services.dependency_health import DependencyHealthService


def get_dependency_health_service(
    settings: SettingsDependency,
) -> Iterator[DependencyHealthService]:
    service = DependencyHealthService(settings)
    try:
        yield service
    finally:
        service.close()


DependencyHealthServiceDependency = Annotated[
    DependencyHealthService,
    Depends(get_dependency_health_service),
]
