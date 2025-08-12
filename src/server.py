import json
import logging
import re
from rq import Queue
from redis import Redis
from typing import cast, Dict
import time

import rq_dashboard
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    request,
    render_template,
    send_from_directory,
    redirect,
    url_for,
)
from flask.typing import ResponseReturnValue
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Gauge,
    generate_latest,
)

from . import model
from . import scheduler
from . import utils
from .config import app_config

PAGE_SIZE = 15

AVAILABLE_MODULES: Dict[str, model.TrackerModule] = {}

redis_conn = Redis(
    host=app_config.redis.host, port=app_config.redis.port
)
track_queue = Queue("track", connection=redis_conn)

log = logging.getLogger()
app = Flask(__name__, static_folder="./static")

mwdb = utils.get_mwdb()

redis_url = f"redis://{app_config.redis.host}:{app_config.redis.port}"
app.config["RQ_DASHBOARD_REDIS_URL"] = redis_url
rq_dashboard.web.setup_rq_connection(app)
app.register_blueprint(rq_dashboard.blueprint, url_prefix="/rq")


mtracker_bots = Gauge("mtracker_bots", "Bots", ("family", "status"))
mtracker_tasks = Gauge("mtracker_tasks", "Tasks", ("status",))
mtracker_trackers = Gauge("mtracker_trackers", "Trackers")


@app.route("/varz", methods=["GET"])
def varz() -> ResponseReturnValue:
    """Update and get prometheus metrics"""
    with model.database_connection() as conn:
        metrics = model.get_metrics(conn.cursor())

    mtracker_bots._metrics.clear()
    mtracker_tasks._metrics.clear()

    bots = metrics.bot_stats
    tasks = metrics.task_stats
    mtracker_trackers.set(metrics.trackers)

    for family, status, count in bots:
        mtracker_bots.labels(family, status).set(count)
    for status, count in tasks:
        mtracker_tasks.labels(status).set(count)

    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


def track_config(family: str, config_dict: Dict) -> Dict:
    dhash = utils.config_dhash(config_dict)

    if family not in AVAILABLE_MODULES:
        log.warning("Family not supported")
        return { "error": "unsupported family" }

    log.info("Tracking %s (%s)", dhash, family)

    with model.database_connection() as connection:
        cur = connection.cursor()

        tracker = model.Tracker.get_by_hash(cur, dhash)
        new_tracker = tracker is None

        bot_ids = []
        tracked_countries = []

        if tracker is not None:
            # get more tracker information
            tracker_id = tracker.tracker_id
            bots = model.Bot.fetch_by_tracker_id(cur=cur, tracker_id=tracker_id)
            for b in bots:
                bot_ids.append(b.bot_id)
                tracked_countries.append(b.country)
        else:
            # insert a tracker into the database
            tracker_id = model.Tracker.create(
                cur, dhash, json.dumps(config_dict), family
            )

        proxy_countries = model.Proxy.get_countries(cur).keys()
        module_proxy_whitelist = AVAILABLE_MODULES[family].proxy_whitelist

        for country in proxy_countries:
            log.info("Creating a bot for %s", country)
            if country in tracked_countries:
                log.info("Skipping %s because it's already tracked", country)
                continue

            if (
                module_proxy_whitelist is not None
                and country not in module_proxy_whitelist
            ):
                log.info(
                    "Skipping %s because it's not whitelisted in the module", country
                )
                continue

            bot_id = model.Bot.create(
                cur=cur, tracker_id=tracker_id, country=country, family=family
            )
            bot_ids.append(bot_id)

    return {"new": new_tracker, "trackerId": tracker_id, "botIds": bot_ids}


def proxy_count():
    with model.database_connection() as connection:
        proxies = model.Proxy.fetch_all(connection.cursor())
        return len(proxies)


@app.route("/api/trackers", methods=["POST"])
def track_config_api() -> ResponseReturnValue:
    """Tracker creation API.
    The API request format is just {"config": {...config data}}.
    Config key should contain a config (as found in mwdb), and other
    keys are ignored.
    """
    if proxy_count() == 0:
        return {
            "error": "No proxies configured. Edit the config, and go to /proxies to update."
        }, 500

    data = request.get_json()
    config = data["config"]
    family = config.get("type")
    if not family:
        family = config.get("family")  # Fallback for legacy format

    return jsonify(track_config(family, config))


@app.route("/track/<dhash>", methods=["POST"])
def track_config_old(dhash: str) -> ResponseReturnValue:
    """Tracker submission API with mwdb integration.

    Given config is downloaded from mwdb automatically.

    :param dhash: config dhash, to be downloaded from mwdb
    """
    if proxy_count() == 0:
        return {
            "error": "No proxies configured. Edit the config, and go to /proxies to update."
        }, 500

    dhash = dhash.lower()

    if not re.match("^[a-f0-9]+$", dhash):
        abort(400)

    mwdb_cfg = mwdb.query_config(hash=dhash, raise_not_found=False)
    if mwdb_cfg is None:
        log.error("Config %s does not exist", dhash)
        abort(400)

    if mwdb_cfg.type != "static":
        log.warning("Refusing to track non-static configs")
        return jsonify("not a static config")

    response = track_config(mwdb_cfg.family, mwdb_cfg.config_dict)
    return jsonify(response)


@app.route("/api/tasks/<int:task_id>/log", methods=["GET"])
def get_task_log(task_id: int) -> ResponseReturnValue:
    log_path = model.Task.get_log_path(task_id)

    if not log_path.exists():
        abort(404)
    return jsonify({"data": log_path.read_text()})


@app.route("/api/results/")
def get_results() -> ResponseReturnValue:
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))

    with model.database_connection() as conn:
        entities = model.Result.fetch_all(
            cur=conn.cursor(), limit=count, start=start
        )
    return jsonify([e.serialize() for e in entities])


@app.route("/api/tasks/")
def get_tasks() -> ResponseReturnValue:
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))
    status = request.args.get("status")
    family = request.args.get("family")

    with model.database_connection() as conn:
        entities = model.TaskView.fetch_all(
            cur=conn.cursor(), limit=count, start=start, status=status, family=family
        )
    return jsonify([e.serialize() for e in entities])


@app.route("/api/tasks/<int:task_id>/results", methods=["GET"])
def get_task_results(task_id: int) -> ResponseReturnValue:
    with model.database_connection() as connection:
        results = model.Result.fetch_by_task_id(
            cur=connection.cursor(),
            task_id=task_id
        )
        return jsonify([r.serialize() for r in results])


@app.route("/api/tasks/<int:task_id>")
def get_task(task_id: int) -> ResponseReturnValue:
    with model.database_connection() as conn:
        task = model.TaskView.get_by_id(conn.cursor(), task_id)
    if not task:
        abort(404)
    return jsonify(task.serialize())


@app.route("/api/trackers/", methods=["GET"])
def get_trackers() -> ResponseReturnValue:
    status = request.args.get("status")
    family = request.args.get("family")
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))

    with model.database_connection() as conn:
        entities = model.Tracker.fetch_all(
            cur=conn.cursor(),
            limit=count,
            start=start,
            status=status,
            family=family,
        )
    return jsonify([e.serialize() for e in entities])


def tracker_action(tracker_id: int, action: str) -> None:
    with model.database_connection() as connection:
        cur = connection.cursor()

        bots = model.Bot.fetch_by_tracker_id(cur=cur, tracker_id=tracker_id)
        bot_ids = [b.bot_id for b in bots]

        if action == "resetSpree":
            model.Bot.clear_sprees(cur=cur, bot_ids=bot_ids)
        elif action == "archive":
            model.Bot.set_statuses(
                cur=cur, bot_ids=bot_ids, status=model.Status.ARCHIVED
            )
        elif action == "revive":
            model.Bot.revive(cur=cur, bot_ids=bot_ids)
        elif action == "rerun":
            for bot_id in bot_ids:
                scheduler.run_bot_task(bot_id)
        else:
            abort(400)


@app.route("/trackers/<int:tracker_id>", methods=["POST"])
def tracker_action_form(tracker_id: int) -> ResponseReturnValue:
    tracker_action(tracker_id, request.form["action"])
    return redirect(url_for("tracker", tracker_id=tracker_id))


@app.route("/api/trackers/<int:tracker_id>", methods=["POST"])
def tracker_action_api(tracker_id: int) -> ResponseReturnValue:
    action = request.get_json().get("action")
    tracker_action(tracker_id, action)
    return jsonify({})


@app.route("/api/trackers/<int:tracker_id>/bots")
def get_tracker_bots(tracker_id) -> ResponseReturnValue:
    status = request.args.get("status")
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))

    with model.database_connection() as conn:
        bots = model.Bot.fetch_by_tracker_id(
            cur=conn.cursor(),
            start=start,
            limit=count,
            status=status,
            tracker_id=tracker_id
        )

    return jsonify([e.serialize() for e in bots])


@app.route("/api/trackers/<int:tracker_id>")
def get_tracker(tracker_id: int) -> ResponseReturnValue:
    with model.database_connection() as conn:
        tracker = model.Tracker.get_by_id(conn.cursor(), tracker_id)
    if not tracker:
        abort(404)
    return jsonify(tracker.serialize())


@app.route("/api/trackers/<int:tracker_id>/results", methods=["GET"])
def get_tracker_results(tracker_id: int) -> ResponseReturnValue:
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))

    with model.database_connection() as connection:
        results = model.Result.fetch_by_tracker_id(
            cur=connection.cursor(),
            tracker_id=tracker_id,
            start=start,
            limit=count
        )
        return jsonify([r.serialize() for r in results])


@app.route("/api/bots/")
def get_bots() -> ResponseReturnValue:
    status = request.args.get("status")
    family = request.args.get("family")
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))

    with model.database_connection() as conn:
        entities = model.Bot.fetch_all(
            cur=conn.cursor(),
            limit=count,
            start=start,
            status=status,
            family=family,
        )

    return jsonify([e.serialize() for e in entities])


@app.route("/api/bots/<int:bot_id>", methods=["GET"])
def get_bot(bot_id: int) -> ResponseReturnValue:
    with model.database_connection() as connection:
        bot = model.Bot.get_by_id(connection.cursor(), bot_id)
    if not bot:
        abort(404)
    return jsonify(bot.serialize())


@app.route("/api/bots/<int:bot_id>/results", methods=["GET"])
def get_bot_results(bot_id: int) -> ResponseReturnValue:
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))

    with model.database_connection() as connection:
        results = model.Result.fetch_by_bot_id(
            cur=connection.cursor(),
            bot_id=bot_id,
            start=start,
            limit=count
        )
        return jsonify([r.serialize() for r in results])


def bot_action(bot_id: int, action: str) -> None:
    with model.database_connection() as connection:
        cur = connection.cursor()
        if action == "resetSpree":
            model.Bot.clear_sprees(cur=cur, bot_ids=[bot_id])
        elif action == "archive":
            model.Bot.set_statuses(
                cur=cur, bot_ids=[bot_id], status=model.Status.ARCHIVED
            )
        elif action == "revive":
            model.Bot.revive(cur=cur, bot_ids=[bot_id])
        elif action == "rerun":
            scheduler.run_bot_task(bot_id)
        else:
            abort(400)


@app.route("/api/bots/<int:bot_id>", methods=["POST"])
def bot_action_api(bot_id: int) -> ResponseReturnValue:
    action = request.get_json().get("action")
    bot_action(bot_id, action)
    return jsonify({})


@app.route("/bots/<int:bot_id>", methods=["POST"])
def bot_action_form(bot_id: int) -> ResponseReturnValue:
    action = request.form["action"]
    bot_action(bot_id, action)
    return redirect(url_for("bot", bot_id=bot_id))


@app.route("/api/bots/<int:bot_id>/tasks", methods=["GET"])
def get_bot_tasks(bot_id: int) -> ResponseReturnValue:
    status = request.args.get("status")
    start = int(request.args.get("start", "0"))
    count = int(request.args.get("count", "10"))

    with model.database_connection() as connection:
        entities = model.TaskView.get_by_bot_id(
            connection.cursor(), bot_id=bot_id, start=start, count=count, status=status
        )
    return jsonify([e.serialize() for e in entities])


@app.route("/api/bots/<int:bot_id>/log", methods=["GET"])
def get_bot_last_log(bot_id: int) -> ResponseReturnValue:
    with model.database_connection() as connection:
        tasks = model.TaskView.get_by_bot_id(connection.cursor(), bot_id)

    if not tasks:
        return jsonify({"data": "No historic tasks"})

    log_path = model.Task.get_log_path(tasks[0].task_id)
    if not log_path.exists():
        return jsonify({"data": "Log file does not exist"})
    return jsonify({"data": log_path.read_text()})


@app.route("/api/proxies/", methods=["GET"])
def fetch_proxies() -> ResponseReturnValue:
    with model.database_connection() as connection:
        entities = model.Proxy.fetch_all(connection.cursor())
    return jsonify([e.serialize() for e in entities])


@app.route("/api/proxies/update", methods=["POST"])
def update_proxies() -> ResponseReturnValue:
    with model.database_connection() as connection:
        new_proxies = utils.get_proxies()
        new_proxies = [p for p in new_proxies if p.get("is_alive")]
        proxy_changes = model.Proxy.synchronize_proxies(
            connection.cursor(), new_proxies
        )
        return jsonify(proxy_changes)


@app.route("/api/heartbeat/", methods=["GET"])
def heartbeat() -> ResponseReturnValue:
    with model.database_connection() as conn:
        return jsonify(model.get_status(conn.cursor()))


@app.route("/src/<path:path>")
def static_file_src(path: str) -> ResponseReturnValue:
    return send_from_directory(cast(str, app.static_folder), "src/" + path)


@app.route("/build/<path:path>")
def static_file_build(path: str) -> ResponseReturnValue:
    return send_from_directory(cast(str, app.static_folder), "build/" + path)


@app.route("/css/<path:path>")
def static_file_css(path: str) -> ResponseReturnValue:
    return send_from_directory(cast(str, app.static_folder), "css/" + path)


@app.route("/flags/<path:path>")
def static_file_flags(path: str) -> ResponseReturnValue:
    return send_from_directory(cast(str, app.static_folder), "flags/" + path)


@app.route("/proxies")
def proxies() -> ResponseReturnValue:
    with model.database_connection() as conn:
        entities = model.Proxy.fetch_all(cur=conn.cursor())

    return render_template("proxies.html", rows=entities)


@app.route("/proxies/update")
def proxies_update() -> ResponseReturnValue:
    with model.database_connection() as connection:
        new_proxies = utils.get_proxies()
        new_proxies = [p for p in new_proxies if p.get("is_alive")]
        proxy_changes = model.Proxy.synchronize_proxies(
            connection.cursor(), new_proxies
        )
        # TODO: maybe flash the proxy_changes
    return redirect(url_for("proxies"))


@app.route("/results")
def results() -> ResponseReturnValue:
    page = int(request.args.get("page", "1"))
    start = (page - 1) * PAGE_SIZE
    count = int(request.args.get("count", PAGE_SIZE))

    with model.database_connection() as conn:
        entities = model.Result.fetch_all(
            cur=conn.cursor(),
            limit=count,
            start=start,
        )
        count = model.Result.count(cur=conn.cursor())
        pages = (count + PAGE_SIZE - 1) // PAGE_SIZE

    return render_template("results.html", rows=entities, page=page, pages=pages)


@app.route("/tasks")
def tasks() -> ResponseReturnValue:
    status = request.args.get("status")
    page = int(request.args.get("page", "1"))
    start = (page - 1) * PAGE_SIZE
    count = int(request.args.get("count", PAGE_SIZE))

    with model.database_connection() as conn:
        entities = model.TaskView.fetch_all(
            cur=conn.cursor(),
            limit=count,
            start=start,
            status=status,
        )
        count = model.Task.count(cur=conn.cursor(), status=status)
        pages = (count + PAGE_SIZE - 1) // PAGE_SIZE

    return render_template("tasks.html", rows=entities, page=page, pages=pages)


@app.route("/tasks/<task_id>")
def task(task_id: int) -> ResponseReturnValue:
    with model.database_connection() as conn:
        entity = model.TaskView.get_by_id(cur=conn.cursor(), task_id=task_id)
        if entity is None:
            abort(404)
        results = model.Result.fetch_by_task_id(cur=conn.cursor(), task_id=task_id)

    log_path = model.Task.get_log_path(task_id=task_id)
    if log_path.exists():
        log = log_path.read_text()
    else:
        log = "(missing)"

    return render_template("task.html", entity=entity, results=results, log=log)


@app.route("/bots")
def bots() -> ResponseReturnValue:
    status = request.args.get("status")
    family = request.args.get("family")
    page = int(request.args.get("page", "1"))
    start = (page - 1) * PAGE_SIZE
    count = int(request.args.get("count", PAGE_SIZE))

    with model.database_connection() as conn:
        entities = model.Bot.fetch_all(
            cur=conn.cursor(),
            limit=count,
            start=start,
            status=status,
            family=family,
        )
        count = model.Bot.count(cur=conn.cursor(), status=status, family=family)
        pages = (count + PAGE_SIZE - 1) // PAGE_SIZE

    return render_template("bots.html", rows=entities, page=page, pages=pages)


@app.route("/bots/<bot_id>")
def bot(bot_id: int) -> ResponseReturnValue:
    with model.database_connection() as conn:
        entity = model.Bot.get_by_id(cur=conn.cursor(), bot_id=bot_id)
        if entity is None:
            abort(404)
        tasks = model.TaskView.get_by_bot_id(cur=conn.cursor(), bot_id=bot_id)
    last_task_log = None
    if tasks:
        log_path = model.Task.get_log_path(tasks[0].task_id)
        if log_path.exists():
            last_task_log = log_path.read_text()
    return render_template("bot.html", entity=entity, tasks=tasks, last_task_log=last_task_log)


@app.route("/trackers")
def trackers() -> ResponseReturnValue:
    status = request.args.get("status")
    family = request.args.get("family")
    page = int(request.args.get("page", "1"))
    start = (page - 1) * PAGE_SIZE
    count = int(request.args.get("count", PAGE_SIZE))

    with model.database_connection() as conn:
        entities = model.TrackerWithBots.fetch_all(
            cur=conn.cursor(),
            limit=count,
            start=start,
            status=status,
            family=family,
        )
        count = model.Tracker.count(cur=conn.cursor(), status=status, family=family)
        pages = (count + PAGE_SIZE - 1) // PAGE_SIZE

    return render_template("trackers.html", rows=entities, page=page, pages=pages)


@app.route("/trackers/<tracker_id>")
def tracker(tracker_id) -> ResponseReturnValue:
    with model.database_connection() as conn:
        cur = conn.cursor()
        entity = model.Tracker.get_by_id(cur=cur, tracker_id=tracker_id)
        if entity is None:
            abort(404)
        bots = model.Bot.fetch_by_tracker_id(cur=cur, tracker_id=tracker_id)

    return render_template("tracker.html", entity=entity, bots=bots)


@app.route("/")
def index() -> ResponseReturnValue:
    with model.database_connection() as conn:
        status = model.get_status(conn.cursor())
        tasks = model.TaskView.fetch_all(
            cur=conn.cursor(),
            limit=10,
            start=0,
        )

    return render_template("index.html", counters=status["counters"], tasks=tasks)


if __name__ == "__main__":
    log.info("Getting available modules from workers")
    q = track_queue.enqueue(
        "mtracker.track.get_available_trackers",
    )
    while q.result is None:
        log.info("Still waiting")
        time.sleep(1)

    AVAILABLE_MODULES = {x.family: x for x in q.result}
    log.info("Got %d supported modules", len(AVAILABLE_MODULES))
    app.run(host="0.0.0.0", port=5000)
