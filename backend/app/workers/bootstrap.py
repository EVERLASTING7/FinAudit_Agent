from __future__ import annotations

from typing import TYPE_CHECKING

from app.ai.policy_loader import load_validated_policy
from app.core.config import Settings

if TYPE_CHECKING:
    from celery import Celery as CeleryType  # type: ignore[import-untyped]


class ExactTaskRouter:
    """仅路由已批准的七个 Worker task name，未知 task 失败关闭。"""

    def __init__(self, routes: dict[str, dict[str, str]]) -> None:
        self._routes = routes

    def route_for_task(
        self,
        task: str,
        args: tuple[object, ...] | None = None,
        kwargs: dict[str, object] | None = None,
    ) -> dict[str, str]:
        del args, kwargs
        try:
            return dict(self._routes[task])
        except KeyError:
            raise ValueError("Celery task 未进入批准的精确路由") from None


def _queue_names(settings: Settings) -> dict[str, str]:
    return {
        "document": settings.celery_queue_document,
        "extraction": settings.celery_queue_extraction,
        "knowledge": settings.celery_queue_knowledge,
        "evaluation": settings.celery_queue_evaluation,
        "audit": settings.celery_queue_audit,
        "report": settings.celery_queue_report,
        "maintenance": settings.celery_queue_maintenance,
    }


def create_celery_app(settings: Settings | None = None) -> CeleryType:
    """验证 Settings 与本地 Policy 后构造唯一可启动的 Worker 应用。"""

    active_settings = settings or Settings()
    policy_snapshot = load_validated_policy(active_settings)

    # Celery 及 Broker 配置只能在 Policy 启动门禁之后接触。
    from celery import Celery

    queue_names = _queue_names(active_settings)
    application = Celery(
        "finaudit",
        broker=active_settings.celery_broker_url.get_secret_value(),
        backend=active_settings.celery_result_backend.get_secret_value(),
    )
    application._finaudit_policy_snapshot = policy_snapshot
    application.conf.update(
        accept_content=("json",),
        broker_connection_retry_on_startup=True,
        enable_utc=True,
        result_serializer="json",
        task_acks_late=True,
        task_create_missing_queues=False,
        task_default_exchange=queue_names["maintenance"],
        task_default_queue=queue_names["maintenance"],
        task_default_routing_key=queue_names["maintenance"],
        task_ignore_result=True,
        task_publish_retry=False,
        task_protocol=2,
        task_queues={
            queue_name: {
                "exchange": queue_name,
                "routing_key": queue_name,
            }
            for queue_name in queue_names.values()
        },
        task_reject_on_worker_lost=True,
        task_routes=(
            ExactTaskRouter(
                {
                    f"app.workers.tasks.{logical_queue}.execute_job": {
                        "queue": queue_name,
                        "routing_key": queue_name,
                    }
                    for logical_queue, queue_name in queue_names.items()
                }
            ),
        ),
        task_serializer="json",
        task_soft_time_limit=active_settings.celery_task_soft_time_limit_seconds,
        task_store_errors_even_if_ignored=False,
        task_time_limit=active_settings.celery_task_time_limit_seconds,
        timezone=active_settings.timezone,
    )
    from app.workers.tasks import register_worker_tasks

    register_worker_tasks(application, active_settings)
    return application
