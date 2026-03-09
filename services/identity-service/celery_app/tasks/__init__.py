from datetime import UTC, datetime

from celery import Task

from celery_app import celery_app


class BaseTask(Task):
    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 30
    retry_jitter = True


@celery_app.task(bind=True, base=BaseTask, name="celery_app.tasks.health_check_task")
def health_check_task(self) -> dict[str, str]:
    return {
        "status": "ok",
        "worker_task_id": self.request.id or "",
        "timestamp": datetime.now(UTC).isoformat(),
    }
