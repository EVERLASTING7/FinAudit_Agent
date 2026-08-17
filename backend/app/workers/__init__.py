"""Celery Worker 消息与应用边界。"""

from app.workers.messages import JOB_EVENT_SCHEMA_VERSION, JobDispatchMessage

__all__ = ["JOB_EVENT_SCHEMA_VERSION", "JobDispatchMessage"]
