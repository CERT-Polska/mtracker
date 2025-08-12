import sys

from redis import Redis
from rq import Queue, Worker

from . import error_handler
from .config import app_config
from .loader import ModuleManager


def main():
    if len(sys.argv) != 2:
        print("Usage: worker [modules_path]")
        exit(1)

    ModuleManager.load(sys.argv[1])
    redis = Redis(host=app_config.redis.host, port=app_config.redis.port)

    queues = [
        Queue("report", connection=redis),
        Queue("track", connection=redis),
    ]
    w = Worker(
        queues=queues,
        connection=redis,
        exception_handlers=[error_handler.report_crashed],
        log_job_description=False,
    )
    w.work()


if __name__ == "__main__":
    main()
