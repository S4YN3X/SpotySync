from celery import Celery
import os


def make_celery(app_name=__name__):
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return Celery(
        app_name,
        backend=redis_url,
        broker=redis_url
    )


celery = make_celery()
