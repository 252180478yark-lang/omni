from kombu import Exchange, Queue

from app.config import settings

broker_url = settings.redis_url
result_backend = settings.redis_url

task_default_queue = "default"
task_default_exchange = "default"
task_default_routing_key = "default"
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True
task_track_started = True
task_time_limit = 300
task_soft_time_limit = 300
task_default_retry_delay = 2
task_routes = {
    "celery_app.tasks.health_check_task": {"queue": "default"},
}

task_queues = (
    Queue("default", Exchange("default"), routing_key="default"),
    Queue("content", Exchange("content"), routing_key="content"),
    Queue("crawl", Exchange("crawl"), routing_key="crawl"),
    Queue("training", Exchange("training"), routing_key="training"),
)
