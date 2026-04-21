import os
from celery import Celery
from celery.schedules import crontab
import platform


# Windows specific fixes
if platform.system() == 'Windows':
    # Fix for windows mutiprocessing
    os.environ.setdefault('FORKED_BY_MULTIPROCESSING', '1')
    # Force spawn method for better windows compatibility
    import multiprocessing
    try:
        multiprocessing.set_start_method('spawn', force=True)
    except RuntimeError:
        pass


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tracker.settings')

# HARDCODE REDIS URL - Don't load from Django settings
REDIS_URL = 'redis://172.28.179.241:6379/0'

# Create Celery app with explicit broker URL
app = Celery('tracker')

# CRITICAL: Don't use config_from_object - it causes localhost issue on Windows
# app.config_from_object('django.conf:settings', namespace='CELERY')

# Manually set all configuration
app.conf.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    accept_content=['application/json'],
    task_serializer='json',
    result_serializer='json',
    timezone='Asia/Karachi',
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=5,

    # Use thread pool instead of process pool
    worker_pool='threads',

    # Lower concurrenct for windows to avoid handle exhaustion
    worker_concurrency=2,

    # Prevent worker from restarting process
    worker_pool_restart=False,

    # Task settings for better windows compatibility
    task_acks_late=True,    # Don't ack until task is complete
    task_reject_on_worker_lost=True,     #Reject if worker dies
    task_track_started=True,      #Track when task starts

    # Beat schedule storage (prevents multiple beats)
    beat_scheduler='celery.beat.PersistentScheduler',
    beat_max_loop_interval=300,       # 5 minutes max loop

    # Avoid pickle on windows
    task_always_eager=False,       # Don't run tasks locally

    # Additional windows comaptibility
    worker_redirect_stdouts=True,
    worker_redierect_stdouts_level='INFO',
    worker_hijack_root_logger=False,
)


# Print to verify
print(f"🔴 Celery broker URL: {app.conf.broker_url}")
print(f"🔴 Celery backend URL: {app.conf.result_backend}")
print(f"🔴 Using pool: {app.conf.worker_pool} with concurrency: {app.conf.worker_concurrency}")
print(f"🔴 Running on: {platform.system()}")

# Schedule periodic tasks
app.conf.beat_schedule = {
    'fetch-kse100-every-minute': {
        'task': 'assets.tasks.fetch_kse100_data',
        'schedule': crontab(minute='*/1'),
    },
    'fetch-gold-silver-every-5-minutes': {
        'task': 'assets.tasks.fetch_gold_silver_prices',
        'schedule': crontab(minute='*/5'),
    },
    'fetch-bitcoin-every-2-minutes': {
        'task': 'assets.tasks.fetch_bitcoin_price',
        'schedule': crontab(minute='*/2'),
    },
    'cleanup-old-data-daily': {
        'task': 'assets.tasks.cleanup_old_data',
        'schedule': crontab(hour=0, minute=0),
    },
    'update-portfolio-values-every-5-minutes': {
        'task': 'assets.tasks.update_portfolio_values',
        'schedule': crontab(minute='*/5'),
    },
    'calculate-technical-indicators-hourly': {
        'task': 'assets.tasks.calculate_technical_indicators',
        'schedule': crontab(minute='0'),
    },
    'fetch-market-news-hourly': {
        'task': 'assets.tasks.fetch_market_news',
        'schedule': crontab(minute='30'),
    },
    'fetch-oil-prices-every-5-minutes': {
        'task': 'assets.tasks.fetch_oil_prices',
        'schedule': crontab(minute='*/5')
    },
}

app.autodiscover_tasks()