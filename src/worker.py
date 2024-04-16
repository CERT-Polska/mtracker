import sys

from redis import Redis  # type: ignore
from rq import Connection, Worker  # type: ignore

from . import error_handler
from .config import app_config
from .loader import ModuleManager


def main():
    if len(sys.argv) != 2:
        print("Usage: worker [modules_path]")
        exit(1)

    ModuleManager.load(sys.argv[1])
    redis = Redis(host=app_config.redis.host, port=app_config.redis.port)

    with Connection(connection=redis):
        queues = ["report", "track"]
        w = Worker(
            queues,
            exception_handlers=[error_handler.report_crashed],
            log_job_description=False,
        )
        w.work()


if __name__ == "__main__":
    main()
