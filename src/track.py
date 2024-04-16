import logging
from typing import Any, Dict, Tuple, cast, List

from .bot import ModuleBase
from .model import Status, Task, TrackerModule
from .loader import ModuleManager

log = logging.getLogger("rq.worker")
log.setLevel(logging.DEBUG)


trackers = ModuleManager.get()


def get_available_trackers() -> List[TrackerModule]:
    output = []
    for family, tracker in trackers.items():
        output.append(TrackerModule(
            family=family,
            critical_params=tracker.CRITICAL_PARAMS,
            proxy_whitelist=tracker.PROXY_WHITELIST
        ))
    return output


def execute(
    static_config: Dict[str, Any],
    saved_state: Dict[str, Any],
    proxy: str,
    task_id: int,
    bot_id: int,
) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
    """execute task for a given config and a proxy

    :param static_config: static config
    :param saved_state: state from previous executions for this bot
    :param proxy: socks proxy to be used for communication
    :return: return a tuple of status, fetched results, updated saved_state
    """
    family = static_config["type"]

    log_path = Task.get_log_path(task_id)
    fh = logging.FileHandler(log_path.as_posix())
    log.addHandler(fh)
    log.propagate = False
    log.setLevel(logging.DEBUG)

    if family not in trackers:
        logging.error("No module for %s family", family)
        log.removeHandler(fh)
        return Status.CRASHED, {}, saved_state

    cls = trackers[family]

    if cls.CRITICAL_PARAMS:
        if any(x not in static_config for x in cls.CRITICAL_PARAMS):
            logging.error(
                "Insufficient config parameters for %s, archiving bot", family
            )
            return Status.ARCHIVED, {}, saved_state

    mod = cls(  # type:ignore
        config=static_config, used_proxy=proxy, state=saved_state
    )

    if isinstance(mod, ModuleBase):
        bot_module = cast(ModuleBase, mod)
        ret_val = bot_module.execute_task()
    else:
        raise Exception("Unknown module base type")

    log.removeHandler(fh)
    return ret_val.status, ret_val.results.to_dict_recursive(), ret_val.state
