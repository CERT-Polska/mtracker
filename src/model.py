import json
from collections import defaultdict, namedtuple
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, NamedTuple

import psycopg2  # type: ignore
from psycopg2.extensions import connection, cursor  # type: ignore

from .config import app_config


def database_connection() -> connection:
    return psycopg2.connect(app_config.database.url)


class TrackerModule(NamedTuple):
    family: str
    critical_params: List[str] = []
    proxy_whitelist: Optional[List[str]] = None


class Status(IntEnum):
    """Generic status codes, the idea is to chose such values so that
    a status for an upper member can be calculated using min(children.status)
    """

    CRASHED = 0
    INPROGRESS = 1
    WORKING = 2
    FAILING = 3
    NEW = 4
    ARCHIVED = 5


ServiceMetrics = namedtuple("ServiceMetrics", ["bot_stats", "task_stats", "trackers"])


STATUS_DB: Dict[Status, str] = {
    Status.CRASHED: "crashed",
    Status.INPROGRESS: "inprogress",
    Status.WORKING: "working",
    Status.FAILING: "failing",
    Status.NEW: "new",
    Status.ARCHIVED: "archived",
}


def get_metrics(cur: cursor) -> ServiceMetrics:
    cur.execute(
        """SELECT b.family, b.status, COUNT(*)
        FROM bots b
        GROUP BY b.status, b.family"""
    )
    bot_stats = cur.fetchall()

    cur.execute(
        """SELECT t.status, COUNT(*)
        FROM tasks t
        GROUP BY t.status"""
    )
    task_stats = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM trackers")
    trackers = cur.fetchone()[0]
    return ServiceMetrics(bot_stats, task_stats, trackers)


def get_status(cur: cursor) -> Dict[str, Any]:
    cur.execute(
        """SELECT
        coalesce(SUM(CASE WHEN status = 'crashed' THEN 1 ELSE 0 END), 0),
        coalesce(SUM(CASE WHEN status = 'inprogress' THEN 1 ELSE 0 END), 0),
        coalesce(SUM(CASE WHEN status = 'working' OR status = 'new' THEN 1 ELSE 0 END), 0),
        coalesce(SUM(CASE WHEN status = 'failing' THEN 1 ELSE 0 END), 0),
        coalesce(SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END), 0)
        FROM bots"""
    )
    crashed, progress, alive, failing, archived = cur.fetchall()[0]

    return {
        "counters": {
            "alive": alive,
            "archived": archived,
            "crashed": crashed,
            "failing": failing,
            "progress": progress,
        }
    }


class Proxy:
    def __init__(
        self,
        proxy_id: int,
        host: str,
        port: int,
        country: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        """Class used for mapping proxies from database
        :param proxy_id: proxy id
        :param host: proxy host
        :param port: proxy port
        :param country: ISO 3166 2-letter country code for proxy
        :param username: proxy username (optional)
        :param password: proxy password (optional)
        """
        self.proxy_id = proxy_id
        self.host = host
        self.port = port
        self.country = country
        self.username = username
        self.password = password

    def serialize(self) -> Dict[str, Any]:
        return {
            "proxy_id": self.proxy_id,
            "host": self.host,
            "port": self.port,
            "country": self.country,
            "username": self.username,
            "password": self.password,
        }

    @property
    def connection_string(self) -> str:
        if self.username and self.password:
            # Authenticate using username and password
            return f"socks5h://{self.username}:{self.password}@{self.host}:{self.port}"
        else:
            return f"socks5h://{self.host}:{self.port}"

    @staticmethod
    def fetch_all(cur: cursor) -> List["Proxy"]:
        cur.execute("SELECT * FROM proxies ORDER BY country")
        return [Proxy(*x) for x in cur.fetchall()]

    @staticmethod
    def insert(
        cur: cursor,
        host: str,
        port: int,
        country: str,
        username: Optional[str],
        password: Optional[str],
    ) -> int:
        cur.execute(
            "INSERT INTO proxies(host, port, country, username, password) VALUES(%s, %s, %s, %s, %s) RETURNING proxy_id",
            (host, port, country, username, password),
        )
        return int(cur.fetchone()[0])

    @staticmethod
    def delete(cur: cursor, host: str, port: int, country: str) -> None:
        cur.execute(
            "DELETE FROM proxies WHERE host=%s AND port=%s AND country=%s",
            (host, port, country),
        )

    @staticmethod
    def get_countries(cur: cursor) -> Dict[str, List["Proxy"]]:
        proxies = Proxy.fetch_all(cur)
        countries: Dict[str, List["Proxy"]] = defaultdict(list)
        for proxy in proxies:
            countries[proxy.country].append(proxy)
        return countries

    @staticmethod
    def synchronize_proxies(
        cur: cursor, new_proxies: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Calculate the difference between current proxies and a list of new proxies"""
        proxies = [
            {
                "host": p.host,
                "port": p.port,
                "country": p.country,
                "username": p.username,
                "password": p.password,
            }
            for p in Proxy.fetch_all(cur)
        ]
        delete_list: List[Dict[str, Any]] = proxies
        insert_list: List[Dict[str, Any]] = []

        for new in new_proxies:
            n = {
                "host": new["host"],
                "port": new["port"],
                "country": new["country"],
                "username": new.get("username"),
                "password": new.get("password"),
            }
            if n in proxies:
                delete_list.remove(n)
            else:
                assert n not in insert_list
                insert_list.append(n)

        for d in delete_list:
            Proxy.delete(cur, d["host"], d["port"], d["country"])
        for i in insert_list:
            Proxy.insert(
                cur, i["host"], i["port"], i["country"], i["username"], i["password"]
            )

        return {"added": insert_list, "deleted": delete_list}

    @staticmethod
    def deserialize(proxy: Dict[str, Any]) -> "Proxy":
        return Proxy(
            proxy["id"],
            proxy["host"],
            int(proxy["port"]),
            proxy["country"],
            proxy.get("username", None),
            proxy.get("password", None),
        )


class TaskView:
    """A variant of Task with included joined elements from other tables - number of results, family and last error."""
    def __init__(
        self,
        task_id: int,
        bot_id: int,
        status: Status,
        report_time: datetime,
        logs: str,
        family: str,
        fail_reason: str,
        results_no: int,
    ) -> None:
        self.task_id = task_id
        self.bot_id = bot_id
        self.status = status
        self.report_time = report_time
        self.logs = logs
        self.family = family
        self.results_no = results_no
        self.fail_reason = fail_reason

    QUERY = """SELECT t.task_id, t.bot_id, t.status, t.report_time, t.logs, MIN(b.family), MIN(b.last_error), COUNT(r.*)
        FROM tasks t
        LEFT JOIN results r ON t.task_id=r.task_id
        INNER JOIN bots b ON b.bot_id=t.bot_id"""

    def serialize(self) -> Dict[str, Any]:
        return {
            "taskId": str(self.task_id),
            "botId": self.bot_id,
            "startTime": self.report_time.isoformat(),
            "status": self.status,
            "resultsNo": self.results_no,
            "family": self.family,
            "failReason": self.fail_reason
        }

    @staticmethod
    def get_by_id(cur: cursor, task_id: int) -> Optional["TaskView"]:
        cur.execute(
            f"""{TaskView.QUERY}
            WHERE t.task_id=%s
            GROUP BY t.task_id""",
            (task_id,)
        )
        data = cur.fetchone()
        if not data:
            return None
        return TaskView(*data)

    @staticmethod
    def get_by_bot_id(
        cur: cursor, bot_id: int, count: int = 100, start: int = 0, status: Optional[Status] = None
    ) -> List["TaskView"]:
        cur.execute(
            f"""{TaskView.QUERY}
            WHERE t.status=%s OR %s IS NULL
            GROUP BY t.task_id
            HAVING t.bot_id=%s
            ORDER BY t.task_id DESC
            LIMIT %s OFFSET %s""",
            (status, status, bot_id, count, start),
        )
        data = cur.fetchall()
        return [TaskView(*x) for x in data]

    @staticmethod
    def fetch_all(cur: cursor, limit: int = 100, start: int = 0, status: Optional[Status] = None) -> List["TaskView"]:
        cur.execute(
            f"""{TaskView.QUERY}
            WHERE t.status=%s OR %s IS NULL
            GROUP BY t.task_id
            ORDER BY t.task_id DESC
            OFFSET %s LIMIT %s""",
            (status, status, start, limit),
        )
        data = cur.fetchall()
        return [TaskView(*x) for x in data]


class Task:
    def __init__(
        self,
        task_id: int,
        bot_id: int,
        status: Status,
        report_time: datetime,
        logs: str,
    ) -> None:
        """Class used for mapping tasks from database
        :param task_id: task id
        :param job_id: RQ job id
        :param bot_id: parent bot id
        :param report_time: when the task has been reported
        :param status: last tasks status
        :param logs: worker log
        """
        self.task_id = task_id
        self.bot_id = bot_id
        self.status = status
        self.report_time = report_time
        self.logs = logs

    @staticmethod
    def get_log_path(task_id: int) -> Path:
        Path(app_config.log.dir).mkdir(exist_ok=True)
        return Path(app_config.log.dir) / f"{task_id}.log"

    def serialize(self) -> Dict[str, Any]:
        return {
            "taskId": str(self.task_id),
            "botId": self.bot_id,
            "startTime": self.report_time.isoformat(),
            "status": self.status,
        }

    @staticmethod
    def create(cur: cursor, bot_id: int, status: Status) -> int:
        report_time = datetime.now()
        cur.execute(
            "INSERT INTO tasks(bot_id, status, report_time)"
            "VALUES (%s, %s, %s) RETURNING task_id",
            (bot_id, STATUS_DB[status], report_time),
        )
        (task_id,) = cur.fetchone()
        return task_id

    @staticmethod
    def update_after_run(cur: cursor, task_id: int, status: Status) -> None:
        cur.execute(
            "UPDATE tasks SET status=%s WHERE task_id=%s",
            (STATUS_DB[status], task_id),
        )

    @staticmethod
    def count(cur: cursor, status: Optional[Status] = None) -> int:
        cur.execute("SELECT COUNT(*) FROM tasks WHERE status=%s OR %s IS NULL", (status, status))
        return int(cur.fetchone()[0])


class Bot:
    def __init__(
        self,
        bot_id: int,
        tracker_id: int,
        status: Status,
        state: str,
        failing_spree: int,
        next_execution: datetime,
        country: str,
        last_error: str,
        family: str,
    ) -> None:
        """Class used for mapping bots from database
        :param bot_id: bots id
        :param tracker_id: tracker id
        :param state: json encoded bots state that is passed between executions
        :param failing_spree: how many times has this bot failed in a row
        :param next_execution: time of next scheduled execution
        :param country: country this bot represents
        :param status: bots status
        :param family: bot family
        """
        self.bot_id = bot_id
        self.tracker_id = tracker_id
        self.status = status
        self.state = state
        self.failing_spree = failing_spree
        self.next_execution = next_execution
        self.country = country
        self.last_error = last_error
        self.family = family

        self.configs: List[Result] = []
        self.blobs: List[Result] = []
        self.binaries: List[Result] = []

    @staticmethod
    def update_after_run(
        cur: cursor,
        bot_id: int,
        state: Optional[str],
        status: Status,
        next_execution: datetime,
        last_error: Optional[str] = None,
    ) -> None:
        """Update the bot object after a run
        :param cur: database connection cursor
        :param bot_id: bot id
        :param state: serialized bot internal state
        :param status: task status
        :param next_execution: time of next execution to be scheduled
        :param last_error: (Optional) fail reason
        """
        if status == Status.WORKING:
            # clear the spree and set status
            Bot.set_worked(cur=cur, bot_id=bot_id)
        elif status == Status.FAILING:
            # increment spree, set status and archive if over maximum failing spree
            Bot.set_failed(
                cur=cur, bot_id=bot_id, reason=last_error or "Failed to get config"
            )
        elif status == Status.ARCHIVED:
            Bot.set_archived(cur=cur, bot_id=bot_id)
        elif status == Status.CRASHED:
            # No need to update anything, bot is already marked as crashed
            # by the error handler.
            return
        else:
            raise Exception(f"Unexpected bot status {status}")

        cur.execute(
            """UPDATE bots
            SET state=COALESCE(%s, state), next_execution=%s
            WHERE bot_id=%s
            """,
            (state, next_execution, bot_id),
        )

    def serialize(self) -> Dict[str, Any]:
        return {
            "botId": self.bot_id,
            "trackerId": self.tracker_id,
            "trackerName": f"{self.tracker_id}_{self.family}",
            "failingSpree": self.failing_spree,
            "status": self.status,
            "proxyCountry": self.country,
            "running": self.status == Status.INPROGRESS,
            "nextExecution": self.next_execution.isoformat(),
            "lastError": self.last_error,
            "state": self.state,
            "binaries": [b.serialize() for b in self.binaries],
            "blobs": [b.serialize() for b in self.blobs],
            "configs": [b.serialize() for b in self.configs],
        }

    @staticmethod
    def set_statuses(cur: cursor, bot_ids: List[int], status: Status) -> None:
        cur.execute(
            "UPDATE bots SET status=%s WHERE bot_id = ANY (%s)",
            (STATUS_DB[status], bot_ids),
        )
        cur.execute(
            """SELECT DISTINCT tracker_id
            FROM bots
            WHERE bot_id = ANY (%s)""",
            (bot_ids,),
        )
        tracker_ids = [x[0] for x in cur.fetchall()]
        Tracker.update_statuses(cur=cur, tracker_ids=tracker_ids)

    @staticmethod
    def clear_sprees(cur: cursor, bot_ids: List[int]) -> None:
        cur.execute(
            "UPDATE bots SET failing_spree=0 WHERE bot_id = ANY (%s)", (bot_ids,)
        )

    @staticmethod
    def revive(cur: cursor, bot_ids: List[int]) -> None:
        Bot.clear_sprees(cur, bot_ids)
        Bot.set_statuses(cur, bot_ids, Status.WORKING)

    @staticmethod
    def set_crashed(cur: cursor, bot_id: int, reason: str) -> None:
        cur.execute(
            """UPDATE bots
            SET status=%s, last_error=%s
            WHERE bot_id=%s
            RETURNING tracker_id""",
            (STATUS_DB[Status.CRASHED], reason, bot_id),
        )
        tracker_id = int(cur.fetchone()[0])
        Tracker.update_statuses(cur, [tracker_id])

    @staticmethod
    def set_worked(cur: cursor, bot_id: int) -> None:
        cur.execute(
            """UPDATE bots
            SET status=%s, last_error=%s, failing_spree=0
            WHERE bot_id=%s
            RETURNING tracker_id""",
            (STATUS_DB[Status.WORKING], "", bot_id),
        )
        tracker_id = int(cur.fetchone()[0])
        Tracker.update_statuses(cur, [tracker_id])

    @staticmethod
    def set_failed(cur: cursor, bot_id: int, reason: str) -> None:
        status = Status.FAILING
        cur.execute("SELECT failing_spree FROM bots WHERE bot_id=%s", (bot_id,))
        (failing_spree,) = cur.fetchone()

        failing_spree += 1
        if failing_spree > app_config.mtracker.max_failing_spree:
            status = Status.ARCHIVED

        cur.execute(
            """UPDATE bots
            SET status=%s, last_error=%s, failing_spree=%s
            WHERE bot_id=%s
            RETURNING tracker_id""",
            (STATUS_DB[status], reason, failing_spree, bot_id),
        )
        tracker_id = int(cur.fetchone()[0])
        Tracker.update_statuses(cur, [tracker_id])

    @staticmethod
    def set_archived(cur: cursor, bot_id: int) -> None:
        cur.execute(
            """UPDATE bots
            SET status=%s, last_error=%s, failing_spree=0
            WHERE bot_id=%s
            RETURNING tracker_id""",
            (STATUS_DB[Status.ARCHIVED], "", bot_id),
        )
        tracker_id = int(cur.fetchone()[0])
        Tracker.update_statuses(cur, [tracker_id])

    @staticmethod
    def get_by_id(cur: cursor, bot_id: int) -> Optional["Bot"]:
        cur.execute("SELECT * FROM bots WHERE bot_id=%s", (bot_id,))
        data = cur.fetchone()
        if not data:
            return None
        return Bot(*data)

    @staticmethod
    def create(cur: cursor, tracker_id: int, country: str, family: str) -> int:
        state = json.dumps({})
        status = STATUS_DB[Status.NEW]
        failing_spree = 0
        next_execution = datetime.now()
        cur.execute(
            """INSERT INTO bots(tracker_id, status, state, failing_spree, next_execution, country, family)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING bot_id""",
            (tracker_id, status, state, failing_spree, next_execution, country, family),
        )
        (bot_id,) = cur.fetchone()
        return bot_id

    @staticmethod
    def fetch_pending(cur: cursor, before: datetime) -> List["Bot"]:
        """Fetch bots that should be executed
        :return: List of pending bots
        """
        cur.execute(
            """SELECT * FROM bots
            WHERE (next_execution < %s OR next_execution IS NULL)
            AND status IN ('working', 'failing', 'new')
            ORDER BY next_execution ASC""",
            (before,),
        )
        data = cur.fetchall()
        return [Bot(*x) for x in data]

    @staticmethod
    def fetch_all(
        cur: cursor,
        limit: int = 100,
        start: int = 0,
        status: Optional[Status] = None,
        family: Optional[str] = None
    ) -> List["Bot"]:
        cur.execute("""SELECT *
            FROM bots
            WHERE (status=%s OR %s IS NULL)
              AND (family=%s OR %s IS NULL)
            ORDER BY bot_id DESC
            LIMIT %s OFFSET %s""",
            (status, status, family, family, limit, start)
        )
        return [Bot(*x) for x in cur.fetchall()]

    @staticmethod
    def count(cur: cursor, status: Optional[Status] = None, family: Optional[str] = None) -> int:
        cur.execute("""SELECT COUNT(*)
            FROM bots
            WHERE (status=%s OR %s IS NULL)
              AND (family=%s OR %s IS NULL)""",
            (status, status, family, family)
        )
        return int(cur.fetchone()[0])

    @staticmethod
    def fetch_by_tracker_id(
        cur: cursor, tracker_id: int, limit: int = 100, start: int = 0
    ) -> List["Bot"]:
        cur.execute(
            "SELECT * FROM bots WHERE tracker_id=%s LIMIT %s OFFSET %s",
            (tracker_id, limit, start),
        )
        return [Bot(*x) for x in cur.fetchall()]

    @staticmethod
    def fetch_by_tracker_ids(
        cur: cursor, tracker_ids: List[int]
    ) -> List["Bot"]:
        if not tracker_ids:
            return []
        cur.execute(
            "SELECT * FROM bots WHERE tracker_id IN %s",
            (tuple(tracker_ids),),
        )
        return [Bot(*x) for x in cur.fetchall()]

class TrackerWithBots:
    """A model class that contains information about both tracker, and its bots."""
    def __init__(self, tracker, bots) -> None:
        self.tracker_id = tracker.tracker_id
        self.config_hash = tracker.config_hash
        self.config = tracker.config
        self.family = tracker.family
        self.status = tracker.status
        self.bots = bots

    @staticmethod
    def fetch_all(cur: cursor, limit: int = 100, start: int = 0, status: Optional[Status] = None,  family: Optional[str] = None) -> List["TrackerWithBots"]:
        trackers = Tracker.fetch_all(cur, limit, start, status, family)
        bots = Bot.fetch_by_tracker_ids(cur, [t.tracker_id for t in trackers])
        return [
            TrackerWithBots(t, [b for b in bots if b.tracker_id == t.tracker_id]) for t in trackers
        ]


class Tracker:
    def __init__(
        self,
        tracker_id: int,
        config_hash: str,
        config: str,
        family: str,
        status: Status,
    ) -> None:
        """Class used for mapping trackers from database
        :param tracker_id: tracker id
        :param config_hash: configs dhash
        :param config: saved config
        :param family: config family/type
        :param status: trackers status
        """
        self.tracker_id = tracker_id
        self.config_hash = config_hash
        self.config = config
        self.family = family
        self.status = status

    def serialize(self) -> Dict[str, Any]:
        return {
            "trackerId": self.tracker_id,
            "mwdbId": self.config_hash,
            "name": f"{self.tracker_id}_{self.family}",
            "status": self.status,
        }

    @property
    def config_url(self) -> str:
        return f"{app_config.mwdb.url}/config/{self.config_hash}"

    @staticmethod
    def get_by_id(cur: cursor, tracker_id: int) -> Optional["Tracker"]:
        cur.execute("SELECT * FROM trackers WHERE tracker_id=%s", (tracker_id,))
        data = cur.fetchone()
        if not data:
            return None
        return Tracker(*data)

    @staticmethod
    def get_by_hash(cur: cursor, config_hash: str) -> Optional["Tracker"]:
        cur.execute("SELECT * FROM trackers WHERE config_hash=%s", (config_hash,))
        data = cur.fetchone()
        if not data:
            return None
        return Tracker(*data)

    @staticmethod
    def create(cur: cursor, config_hash: str, config: str, family: str) -> int:
        cur.execute(
            "INSERT INTO trackers(config_hash, config, family) VALUES (%s, %s, %s) RETURNING tracker_id",
            (config_hash, config, family),
        )
        (tracker_id,) = cur.fetchone()
        return tracker_id

    @staticmethod
    def fetch_all(cur: cursor, limit: int = 100, start: int = 0, status: Optional[Status] = None, family: Optional[str] = None) -> List["Tracker"]:
        cur.execute(
            """SELECT *
            FROM trackers
            WHERE (status=%s OR %s IS NULL)
              AND (family=%s OR %s IS NULL)
            ORDER BY tracker_id DESC
            OFFSET %s LIMIT %s""",
            (status, status, family, family, start, limit),
        )
        data = cur.fetchall()
        return [Tracker(*x) for x in data]

    @staticmethod
    def update_statuses(cur: cursor, tracker_ids: List[int]) -> None:
        """Propagate bot statuses to trackers
        :param cur: database cursor
        :param tracker_ids: list of tracker ids to update
        """
        cur.execute(
            """UPDATE trackers t_
            SET status=x.new_status
            FROM (
                SELECT
                    t.tracker_id "tracker_id",
                    MIN(b.status) "new_status"
                FROM trackers t
                LEFT JOIN bots b ON t.tracker_id=b.tracker_id
                GROUP BY t.tracker_id
                HAVING t.tracker_id = ANY (%s)
            ) x
            WHERE t_.tracker_id = x.tracker_id""",
            (tracker_ids,),
        )

    @staticmethod
    def count(cur: cursor, status: Optional[Status] = None, family: Optional[str] = None) -> int:
        cur.execute("""SELECT COUNT(*)
            FROM trackers
            WHERE (status=%s OR %s IS NULL)
              AND (family=%s OR %s is NULL)""", (status, status, family, family))
        return int(cur.fetchone()[0])


class Result:
    def __init__(
        self,
        result_id: int,
        task_id: int,
        result_type: str,
        name: str,
        sha256: str,
        tags: List[str],
        upload_time: datetime,
    ) -> None:
        self.result_id = result_id
        self.task_id = task_id
        self.result_type = result_type
        self.name = name
        self.sha256 = sha256
        self.tags = tags
        self.upload_time = upload_time

    @property
    def mwdb_url(self) -> str:
        path = {
            "binary": "file",
            "config": "config",
            "blob": "blob",
        }[self.result_type]
        return f"{app_config.mwdb.url}/{path}/{self.sha256}"

    @staticmethod
    def create(
        cur: cursor,
        task_id: str,
        result_type: str,
        name: str,
        sha256: str,
        tags: List[str],
    ) -> int:
        cur.execute(
            """INSERT INTO
            results(task_id, type, name, sha256, tags, upload_time)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING result_id""",
            (task_id, result_type, name, sha256, tags, datetime.now()),
        )
        (result_id,) = cur.fetchone()
        return result_id

    def serialize(self) -> Dict[str, Any]:
        return {
            "resultId": self.result_id,
            "taskId": self.task_id,
            "resultType": self.result_type,
            "sha256": self.sha256,
            "name": self.name,
            "tags": self.tags,
            "uploadTime": self.upload_time.isoformat(),
        }

    @staticmethod
    def count(cur: cursor) -> int:
        cur.execute("SELECT COUNT(*) FROM results")
        return int(cur.fetchone()[0])

    @staticmethod
    def fetch_all(cur: cursor, limit: int = 100, start: int = 0) -> List["Result"]:
        cur.execute(
            """SELECT r.result_id, r.task_id, r.type, r.name, r.sha256, r.tags, r.upload_time
            FROM results r
            ORDER BY result_id DESC
            LIMIT %s OFFSET %s""",
            (limit, start),
        )
        return [Result(*x) for x in cur.fetchall()]

    @staticmethod
    def fetch_by_task_id(cur: cursor, task_id: int) -> List["Result"]:
        cur.execute("SELECT * FROM results WHERE task_id=%s", (task_id,))
        return [Result(*x) for x in cur.fetchall()]

    @staticmethod
    def fetch_by_bot_id(
        cur: cursor, bot_id: int, start: int = 0, limit: int = 100
    ) -> List["Result"]:
        cur.execute(
            """SELECT r.result_id, r.task_id, r.type, r.name, r.sha256, r.tags, r.upload_time
            FROM results r
            JOIN tasks t ON r.task_id=t.task_id
            WHERE t.bot_id=%s
            ORDER BY r.result_id DESC
            LIMIT %s OFFSET %s""",
            (bot_id, limit, start),
        )
        return [Result(*x) for x in cur.fetchall()]

    @staticmethod
    def fetch_by_tracker_id(
        cur: cursor, tracker_id: int, start: int = 0, limit: int = 100
    ) -> List["Result"]:
        cur.execute(
            """SELECT r.result_id, r.task_id, r.type, r.name, r.sha256, r.tags, r.upload_time
            FROM results r
            JOIN tasks t ON r.task_id=t.task_id
            JOIN bots b on b.bot_id = t.bot_id
            WHERE b.tracker_id=%s
            ORDER BY r.result_id DESC
            LIMIT %s OFFSET %s""",
            (tracker_id, limit, start),
        )
        return [Result(*x) for x in cur.fetchall()]


def run_migrations() -> None:
    from sqlturk.migration import MigrationTool  # type: ignore

    tool = MigrationTool(app_config.database.url, migration_dir="db")
    tool.install()
    migrations = tool.find_migrations()
    if migrations:
        print("Applying migrations: {}".format(migrations))
    tool.run_migrations()


if __name__ == "__main__":
    run_migrations()
