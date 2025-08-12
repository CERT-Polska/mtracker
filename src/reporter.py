import json
import logging
from typing import Any, Dict, List
from redis import Redis
from rq.job import Job

from datetime import datetime, timedelta

from . import utils
from . import model
from .config import app_config


logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
redis_conn = Redis(
    host=app_config.redis.host, port=app_config.redis.port
)


def update_bot(bot_id: int, status: model.Status, saved_state: Dict[str, Any]) -> None:
    """Update bot information
    :param bot_id: bot id
    :param status: bots status
    :param saved_state: updated save state
    """
    log.info("Updating bot state stored in db")

    # setting the next execution at the tasks end will allow a natural task diffusion
    next_execution = datetime.now() + timedelta(seconds=app_config.mtracker.task_period)
    with model.database_connection() as connection:
        cur = connection.cursor()
        model.Bot.update_after_run(
            cur=cur,
            bot_id=bot_id,
            state=json.dumps(saved_state),
            status=model.Status(status),
            next_execution=next_execution,
        )


def finalize_task(task_id, results: List[Dict[str, Any]], status: model.Status) -> None:
    """Update the tasks status after complection
    :param task_id: task_id
    :param results: fetched dynamic configuration
    :param status: task status
    """
    log.info("Setting the task after run")

    with model.database_connection() as connection:
        cur = connection.cursor()
        model.Task.update_after_run(cur, task_id, model.Status(status))

        result_data = [
            (task_id, x["type"], x["name"], x["sha256"], x["tags"]) for x in results
        ]
        # do this in a single query maybe?
        for r in result_data:
            model.Result.create(cur, *r)


def report_results(
    task_id: int, bot_id: int, config_hash: str, tracker_job_id: str
) -> None:
    log.info("Reporting results for tracker job %s", tracker_job_id)
    tracker_job = Job(tracker_job_id, redis_conn)

    mwdb = utils.get_mwdb()
    reported_results: List[Dict[str, Any]] = []

    results = tracker_job.result
    if not results:
        log.error("Tracker result is empty, has something gone wrong?")
        return

    status, dynamic_config, saved_state = results

    # Upload results in cases of Working and Archived
    if status in [model.Status.WORKING, model.Status.ARCHIVED]:
        if status == model.Status.WORKING:
            log.info("Tracker executed successfully")
        elif status == model.Status.ARCHIVED:
            log.info("Archiving this config")
        if dynamic_config:
            log.info("Pushing results to mwdb")
            reported_results = utils.report_mwdb_tree(mwdb, dynamic_config, config_hash)
    elif status == model.Status.FAILING:
        log.warning("Tracker couldn't fetch config")
    elif status == model.Status.CRASHED:
        log.error("Tracker has crashed")

    finalize_task(task_id, reported_results, status)
    update_bot(bot_id, status, saved_state)
