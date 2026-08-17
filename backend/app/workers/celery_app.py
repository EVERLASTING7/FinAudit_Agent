"""Celery CLI 部署入口；导入时先完成本地 Policy 启动门禁。"""

from app.workers.bootstrap import create_celery_app as _create_celery_app

celery_app = _create_celery_app()
app = celery_app
