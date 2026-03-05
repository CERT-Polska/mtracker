import argparse
import json
import logging
from random import choice
import sys

from .config import app_config
from . import report_fetch
from . import utils
from .bot import ModuleBase
from .loader import ModuleManager
from .model import Proxy


logging.basicConfig(level=logging.DEBUG)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash", help="input hash")
    parser.add_argument(
        "--proxy", 
        help="specify proxy two-letter country code (e.g. 'gb')", 
        nargs="?", 
        default=app_config.proxy.default
    )
    parser.add_argument(
        "--file", "-f", help="use static config read from file"
    )
    parser.add_argument(
        "--modules", "-m", help="Path to mtracker modules", required=True,
    )
    parser.add_argument(
        "--out",
        help="specify how the results should be presented",
        nargs="?",
        default="stdout",
        choices=["stdout", "db", "file"],
    )
    args = parser.parse_args()

    if not args.file and not args.hash:
        logging.error("Either --hash or --file is mandatory")
        return 1

    trackers = ModuleManager.load(args.modules)

    if args.file:
        with open(args.file, "r") as f:
            static_config = json.loads(f.read())
        config_hash = utils.config_dhash(static_config)
    else:
        mwdb = utils.get_mwdb()
        mwdb_cfg = mwdb.query_config(hash=args.hash, raise_not_found=False)
        if not mwdb_cfg:
            logging.error("Couldn't find the requestsed config on mwdb")
            return 1
        static_config = mwdb_cfg.cfg
        config_hash = args.hash

    config_type = static_config.get("type", None)
    if not config_type:
        logging.error("Config type can't be empty")
        return 1

    if config_type not in trackers:
        logging.error("Couldn't find a matching module")
        return 1

    proxies = utils.get_proxies()

    try:
        proxy = choice([
            proxy for proxy in proxies if proxy['country'] == args.proxy
        ])
    except IndexError:
        logging.error(
            "Couldn't find any proxy with country %s",
            args.proxy,
        )
        return 1

    connection_string = Proxy.deserialize(proxy).connection_string

    static_config["_id"] = config_hash
    cls = trackers[config_type]
    mod = cls(config=static_config, used_proxy=connection_string, state={})

    if not isinstance(mod, ModuleBase):
        logging.error("%s is not a valid ModuleBase!")
        return 1

    task_result = mod.execute_task()

    # Reporting the results according to the --out arg
    report_fcn = report_fetch.report_stdout
    if args.out == "stdout":
        report_fcn = report_fetch.report_stdout
    elif args.out == "db":
        report_fcn = report_fetch.report_mwdb
    elif args.out == "file":
        report_fcn = report_fetch.report_file

    report_fcn(config_hash, task_result.results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
