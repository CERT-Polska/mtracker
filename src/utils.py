import hashlib
import json

from base64 import b64decode
from typing import Any, Dict, List, Optional

from mwdblib import MWDB, MWDBObject

from requests import get

from .config import app_config


def get_proxies() -> List[Dict[str, Any]]:
    if ProxyConfig.METHOD == "url":
        # Get a list of proxies from defined URL
        return get(ProxyConfig.URL).json()
    elif ProxyConfig.METHOD == "file":
        # Read a list of proxies from defined file path
        with open(ProxyConfig.PATH) as f:
            return json.load(f)
    raise RuntimeError("Invalid proxy configuration: unknown method")


def config_dhash(obj: Any) -> str:
    if isinstance(obj, list):
        return config_dhash(str(sorted([config_dhash(o) for o in obj])))
    elif isinstance(obj, dict):
        return config_dhash([[o, config_dhash(obj[o])] for o in sorted(obj.keys())])
    else:
        return hashlib.sha256(bytes(str(obj), "utf-8")).hexdigest()


def get_mwdb() -> MWDB:
    return MWDB(api_url=app_config.mwdb.api_url, api_key=app_config.mwdb.token)


def report_mwdb_tree(
    mwdb: MWDB, node: Dict[str, Any], parent: Optional[str], depth: int = 0
) -> List[Dict[str, Any]]:
    """Uploaded the result tree to mwdb
    :param mwdb: MWDB object
    :param node: tree containing the results to report
    :param parent: current parent
    :param depth: current reporting depth, defaults to 0
    :return: List of reported hashes grouped by their object types
    """
    if depth > 10:
        raise Exception(
            "Maximum reporting depth reached, are there cycles in the result object?"
        )
    results: List[Dict[str, Any]] = []

    this_obj: Optional[MWDBObject] = None
    this_hash = None
    if node["object"] == "object":
        this_hash = parent
    elif node["object"] == "config":
        this_obj = mwdb.upload_config(
            family=node["config"]["type"],
            cfg=node["config"],
            config_type=node["config_type"],
            attributes=node["attributes"],
            parent=parent,
        )
        this_hash = this_obj.sha256
        results.append(
            {
                "type": "config",
                "name": node["config_type"],
                "tags": node["tags"],
                "sha256": this_obj.sha256,
            }
        )
    elif node["object"] == "binary":
        this_obj = mwdb.upload_file(
            name=node["name"],
            content=b64decode(node["data"]),
            attributes=node["attributes"],
            parent=parent,
        )
        this_hash = this_obj.sha256
        results.append(
            {
                "type": "binary",
                "name": node["name"],
                "tags": node["tags"],
                "sha256": this_obj.sha256,
            }
        )
    elif node["object"] == "blob":
        this_obj = mwdb.upload_blob(
            name=node["name"],
            type=node["blob_type"],
            content=node["content"],
            attributes=node["attributes"],
            parent=parent,
        )
        results.append(
            {
                "type": "blob",
                "name": node["name"] + "_" + node["blob_type"],
                "tags": node["tags"],
                "sha256": this_obj.sha256,
            }
        )
        this_hash = this_obj.sha256

    if this_hash is None:
        raise Exception(
            "Something has gone wrong while reporting results, got unknown object in the result object"
        )
    if this_obj:
        for tag in node["tags"]:
            this_obj.add_tag(tag)
        for comment in node["comments"]:
            this_obj.add_comment(comment)

    for child in node["children"]:
        result = report_mwdb_tree(mwdb, child, this_hash, depth + 1)
        results += result
    return results
