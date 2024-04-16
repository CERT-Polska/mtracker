from urllib.parse import urlparse
from typing import Optional, Dict, Any, List


def normalise_url(raw_url):
    return urlparse(raw_url).geturl()


class ConfigData:
    def __init__(self, family: str) -> None:
        self.__data: Dict[str, Any] = {"type": family}

    def __bool__(self) -> bool:
        # the config structure has more than data than just the family
        return len(self.__data.keys()) > 1

    def __add(self, type: str, value: Any):
        if type not in self.__data:
            self.__data[type] = []
        if value not in self.__data[type]:
            self.__data[type].append(value)

    def __add_action(
        self,
        type: str,
        url_pattern: str,
        keys: Optional[Dict[str, Any]] = None,
    ) -> None:
        data = {"type": type, "url_pattern": url_pattern}
        if keys:
            data.update(keys)
        self.__add("actions", data)

    def __add_malicious_url(self, raw_url: str) -> None:
        self.__add("malicious_url", normalise_url(raw_url))

    def serialize(self) -> Dict[str, Any]:
        return self.__data

    def add_c2(self, url: str) -> None:
        self.__add("c2", url)
        self.__add_malicious_url(url)

    def add_malicious_netloc(self, netloc: str) -> None:
        self.__add("malicious_netloc", netloc)

    def add_malicious_url(self, url: str) -> None:
        self.__add_malicious_url(url)

    def add_screenshot_action(self, target: str) -> None:
        self.__add_action("screenshot", target)

    def add_record_action(self, target: str) -> None:
        self.__add_action("record", target)

    def add_block_action(self, target: str) -> None:
        self.__add_action("block", target)

    def add_redirect_action(self, from_: str, to: str):
        self.__add_action("redirect", from_, {"to": to})

    def add_hide_action(self, target: str) -> None:
        self.__add_action("hide", target)

    def add_filter_action(self, target: str) -> None:
        self.__add_action("filter", target)

    def add_vnc_action(self, target: str, sources: List[str]):
        self.__add_action("vnc", target, {"servers": sources})

    def add_dynamic_inject(self, url_pattern: str, server_url: str) -> None:
        self.__add(
            "dynamic_injects",
            {"url_pattern": url_pattern, "server_url": server_url},
        )
        self.add_malicious_url(server_url)

    def add_data_steal(self, url_pattern: str, server_url: str) -> None:
        self.__add_action("steal_data", url_pattern, {"server_url": server_url})
        self.add_malicious_url(server_url)

    def validate_and_add_action(self, raw_action: Dict[str, Any]) -> None:
        act_type = raw_action["type"]
        url_pattern = raw_action["url_pattern"]

        params = dict(raw_action)
        del params["type"]
        del params["url_pattern"]
        keys = list(params.keys())
        keys.sort()

        expected_keys: Dict[str, List[str]] = {
            "redirect": ["to"],
            "hide": [],
            "vnc": ["servers"],
            "dynamic_injects": ["url_pattern", "server_url"],
            "steal_data": ["server_url"],
        }
        if act_type not in expected_keys:
            raise RuntimeError(f"Adding action of unrecognised type: {act_type}")
        expected = expected_keys[act_type]
        expected.sort()

        if keys != expected:
            raise RuntimeError(f"Invalid keys. Has {keys} expected {expected}")

        self.__add_action(act_type, url_pattern, params)

    def add_inject(
        self,
        url_pattern: str,
        data_before: str,
        data_inject: str,
        data_after: Optional[str] = None,
    ) -> None:
        elm = {
            "url_pattern": url_pattern,
            "data_before": data_before,
            "data_inject": data_inject,
        }
        if data_after:
            elm["data_after"] = data_after
        self.__add("injects", elm)
