import abc
import logging
import re
from abc import ABC, abstractmethod
from enum import auto, IntFlag
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union, NamedTuple

from requests import get
from werkzeug.http import parse_options_header

from .model import Status, Task
from .analysis_results import GenericObject, Binary, Blob, Config


class BotResult(IntFlag):
    """Flags to be used as a return value from an execution of a server in a bot. A bot can return
    any combination of these flags to provide MTracker with instructions how to handle the execution.
    """
    # The default value of 0 means that the bot is not working, but don't continue nor archive it.
    # This goes without saying, but there's no point in combining this "flag" with anything.
    # EMPTY | WORKING means just WORKING.
    # In most cases returning CONTINUE is a much better option.
    EMPTY = 0

    # If this flag is set, the execution will be treated as a success.
    # Otherwise, it'll be treated as a soft-fail (independed of if anything was downloaded).
    WORKING = auto()

    # If this flag is set, mtracker will continue downloading samples from this config.
    # This matters only when there is more than one C2 server available.
    CONTINUE = auto()

    # If this flag is set, bot will be archived after completing the execution.
    # It's pointless to set this both flag and WORKING (ARCHIVE takes precedence).
    # This can be used carefully with CONTINUE - bot will continue other C2s, but will
    # be archived in the end regardless of what happens.
    ARCHIVE = auto()



CNC = Union[str, Tuple[str, int]]


def convert_proxy(proxy_string: str) -> Tuple[str, str, int]:
    if "://" not in proxy_string:
        raise RuntimeError(f"Expected socks*://host:port, got {proxy_string}")
    proxy_type, proxy_loc = proxy_string.split("://")
    proxy_host = proxy_loc.split(":")[0]
    proxy_port = int(proxy_loc.split(":")[-1])
    return proxy_type, proxy_host, proxy_port


class TaskResult(NamedTuple):
    status: Status
    results: GenericObject
    state: Dict[str, Any]

    @staticmethod
    def empty(status: Status, state: Dict[str, Any]) -> "TaskResult":
        return TaskResult(status, GenericObject(), state)

    @staticmethod
    def archived() -> "TaskResult":
        return TaskResult.empty(Status.ARCHIVED, {})

    @staticmethod
    def failing() -> "TaskResult":
        return TaskResult.empty(Status.ARCHIVED, {})


class ModuleBase(ABC):
    """A base class for all module types
    CRITICAL_PARAMS - list of static config parameters that are *crucial* to the working of the tracker
    FAMILY - name of the family that the tracker should report results for
    PROXY_WHITELIST - list of proxy countries to run this module on, None = all
    """

    CRITICAL_PARAMS: List[str] = []
    FAMILY: str = ""
    PROXY_WHITELIST: Optional[List[str]] = None

    def __init__(
        self, config: Dict[str, Any], used_proxy: str, state: Dict[str, Any]
    ) -> None:
        """Initialization function for module, executed only once.
        :param config: input static config
        :param used_proxy: proxy to be used for communication
        :param state: saved state, gets copied between runs for the same config, must be json-serializable
        """
        self.config = config
        self.state = state
        self.log = logging.getLogger("rq.worker")
        self.used_proxy = used_proxy
        self.proxy_type, self.proxy_host, self.proxy_port = convert_proxy(used_proxy)
        self.proxy_dict = {"http": used_proxy, "https": used_proxy}

    @abstractmethod
    def execute_task(self) -> TaskResult:
        raise NotImplementedError()


class BotModule(ModuleBase):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._results = GenericObject()

    @abc.abstractclassmethod
    def get_cnc_servers(
        cls, config: Dict[str, Any], state: Dict[str, Any]
    ) -> Iterator[CNC]:
        """Use config items and/or saved state items to c2s to connect to
        :param config: static config
        :param state: bots saved state
        :raises NotImplementedError: this needs to be implemented in each module
        """
        raise NotImplementedError("get_cnc_servers() not implemented()")

    @abc.abstractmethod
    def run(self, c2: CNC) -> BotResult:
        """Module entry point, any errors here will be treated as a normal bot fail
        :raises NotImplementedError: this needs to be implemented in each module
        :return: was the run successful, if not, another c2 will be tried
        """
        raise NotImplementedError("run() not implemented")

    def push_binary(
        self,
        data: bytes,
        name: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> Binary:
        """Add a result binary
        :param data: binary data
        :param name: binary filename
        :param tags: binary tags to be added on mwdb, defaults to None
        :param attributes: attributes to be added on mwdb, defaults to None
        :param comments: comments to be added on mwdb, defaults to None
        :return: appended binary object
        """
        return self._results.push_binary(data, name, tags, attributes, comments)

    def push_blob(
        self,
        content: str,
        name: str,
        blob_type: str,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> Blob:
        """Add a result blob
        :param content: blob data
        :param name: blob filename
        :param blob_type: blob type, usually `dyn_cfg`
        :param tags: blob tags to be added on mwdb, defaults to None
        :param attributes: attributes to be added on mwdb, defaults to None
        :param comments: comments to be added on mwdb, defaults to None
        :return: appended blob object
        """
        return self._results.push_blob(
            content, name, blob_type, tags, attributes, comments
        )

    def push_config(
        self,
        config: Dict[str, Any],
        config_type: str,
        tags: List[str] = None,
        family: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        comments: Optional[List[str]] = None,
    ) -> Config:
        """Add a result config
        :param config: config data
        :param config_type: config type, probably `dynamic` or `static`
        :param tags: config tags to be added on mwdb (default: {None}), defaults to None
        :param family: config family, defaults to None
        :param attributes: attributes to be added on mwdb, defaults to None
        :param comments: comments to be added on mwdb, defaults to None
        :return: appended config object
        """
        config["type"] = family or self.FAMILY
        return self._results.push_config(config, config_type, tags, attributes, comments)

    def execute_task(self) -> TaskResult:
        status = Status.FAILING

        final_working = 0
        final_archive = 0

        for c2 in self.__class__.get_cnc_servers(self.config, self.state):  # type: ignore
            self.log.info("Running module.run for %s", c2)
            try:
                run_result = self.run(c2)

                # Check if the status of this config should be WORKING
                final_working |= run_result & BotResult.WORKING

                # Check if this config should be archived when finishing
                final_archive |= run_result & BotResult.ARCHIVE

                if run_result & BotResult.WORKING:
                    logging.info("Found config using %s", c2)

                # Check whether we should continue to the next C2 in the config
                if not run_result & BotResult.CONTINUE:
                    break

            except Exception as e:
                self.log.exception("run() failed with %s", str(e))

        if final_archive:
            status = Status.ARCHIVED
        elif final_working:
            status = Status.WORKING

        return TaskResult(status, self._results, self.state)


class Dropper(BotModule):
    """An extension class for simple dropper modules"""

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/4.0 (compatible; Win32; WinHttp.WinHttpRequest.5)"
    }

    def download_drop(self, url: str, headers: Optional[Dict[str, str]]=None) -> Optional[Tuple[bytes, str]]:
        """Add a result binary
        :param url: url to download
        :param headers: override the default headers
        :return: tuple of response data and downloaded filename
        """
        if headers is None:
            headers = self.DEFAULT_HEADERS

        response = get(
            url, proxies=self.proxy_dict, headers=headers, stream=True, timeout=10.0
        )
        if response.status_code != 200:
            return None

        filename = None
        if "Content-Disposition" in response.headers.keys():
            parsed = parse_options_header(response.headers["Content-Disposition"])
            if "filename" in parsed[1]:
                filename = parsed[1]["filename"]

        if not filename:
            filename = url[url.rfind("/") + 1 :] or "sample"
        return (response.content, filename)
