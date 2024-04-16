import logging
import traceback

from . import model
from .config import app_config


log = logging.getLogger(__name__)


def report_crashed(job, exc_type, exc_value, tb):
    log.info("Reporting crashed job to the db")

    bot_id = job.kwargs["bot_id"]
    task_id = job.kwargs["task_id"]

    # save short exception as "last error" and store the full exception in the logfile
    exc_full_text = "".join(traceback.format_exception(exc_type, exc_value, tb))
    if app_config.log.provider == "filesystem":
        with model.Task.get_log_path(task_id).open("a") as f:
            f.write(exc_full_text)
    else:
        raise NotImplementedError

    with model.database_connection() as connection:
        cur = connection.cursor()
        exc_text = "".join(traceback.format_exception_only(exc_type, exc_value))
        model.Bot.set_crashed(cur=cur, bot_id=bot_id, reason=exc_text)
        model.Task.update_after_run(
            cur=cur, task_id=task_id, status=model.Status.CRASHED
        )
