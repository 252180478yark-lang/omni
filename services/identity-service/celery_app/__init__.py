from celery import Celery

celery_app = Celery("identity-service")
celery_app.config_from_object("celery_app.celery_config")
celery_app.autodiscover_tasks(["celery_app.tasks"])
