from rq import Queue  # type: ignore
from redis import Redis
from typing import Optional
from datetime import datetime, timedelta
import logging
import json
import time
import random

from .config import app_config
from . import model

redis_conn = Redis(
    host=app_config.redis.host, port=app_config.redis.port
)
track_queue = Queue("track", connection=redis_conn)
report_queue = Queue("report", connection=redis_conn)


logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def run_bot_task(bot_id: int) -> Optional[str]:
    with model.database_connection() as connection:
        cur = connection.cursor()
        bot = model.Bot.get_by_id(cur, bot_id)
        if not bot:
            return None

        tracker = model.Tracker.get_by_id(cur, bot.tracker_id)
        if not tracker:
            raise Exception("Found a bot without tracker, db is corrupted")

        log.info("Getting proxies")
        proxy_countries = model.Proxy.get_countries(cur)

        proxy_candidates = proxy_countries[bot.country]
        if not proxy_candidates:
            log.error(
                "Couldn't find any proxy for bot %d with country %s",
                bot_id,
                bot.country,
            )
            model.Bot.update_after_run(
                cur=cur,
                bot_id=bot_id,
                state=None,
                status=model.Status.FAILING,
                next_execution=datetime.now() + timedelta(hours=24),
                last_error="No matching proxy found",
            )
            return None
        selected_proxy = random.choice(proxy_candidates)

        log.info("Starting task for bot %s", bot.bot_id)

        task_id = model.Task.create(cur, bot_id, model.Status.INPROGRESS)
        model.Bot.set_statuses(
            cur=cur, bot_ids=[bot_id], status=model.Status.INPROGRESS
        )

        static_config = json.loads(tracker.config)
        static_config["_id"] = tracker.config_hash

        job = track_queue.enqueue(
            "mtracker.track.execute",
            kwargs={
                "static_config": static_config,
                "saved_state": json.loads(bot.state),
                "proxy": selected_proxy.connection_string,
                "bot_id": bot.bot_id,
                "task_id": task_id,
            },
            job_timeout=app_config.mtracker.task_timeout,
        )
        report_queue.enqueue(
            "mtracker.reporter.report_results",
            kwargs={
                "bot_id": bot.bot_id,
                "config_hash": tracker.config_hash,
                "tracker_job_id": job.id,
                "task_id": task_id,
            },
            depends_on=job,
        )
        return job.id


def run_tasks() -> None:
    with model.database_connection() as connection:
        cur = connection.cursor()
        pending_bots = model.Bot.fetch_pending(cur, datetime.now())
        log.info("There are %d pending bots, starting", len(pending_bots))

        for bot in pending_bots:
            log.info("Enqueueing bot %d", bot.bot_id)
            run_bot_task(bot.bot_id)


if __name__ == "__main__":
    while True:
        run_tasks()
        time.sleep(60)
