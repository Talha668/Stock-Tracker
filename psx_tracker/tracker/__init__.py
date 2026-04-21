# This will make sure that the app is always imported when django starts so that shared_app will use this app
from .celery import app as celery_app

__all__ = ('celery_app',)