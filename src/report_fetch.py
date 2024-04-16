import json
import logging
import uuid
from pathlib import Path
from typing import List, Tuple

from . import analysis_results
from . import utils


def flatten_results(
    results: analysis_results.GenericObject,
) -> Tuple[
    List[analysis_results.Config],
    List[analysis_results.Blob],
    List[analysis_results.Binary],
]:
    output = []
    queue = results.children
    while queue:
        top = queue.pop()
        output.append(top)
        queue += top.children

    configs = list(filter(lambda x: type(x) is analysis_results.Config, output))
    blobs = list(filter(lambda x: type(x) is analysis_results.Blob, output))
    binaries = list(filter(lambda x: type(x) is analysis_results.Binary, output))
    return (configs, blobs, binaries)  # type: ignore


def report_stdout(config_hash: str, results: analysis_results.GenericObject) -> None:
    logging.info("Reporting results to stdout")
    print(f"Got dynamic config for {config_hash}")

    configs, blobs, binaries = flatten_results(results)
    print(f"Got {len(configs)} configs")
    print(f"Got {len(blobs)} blobs")
    print(f"Got {len(binaries)} binaries")


def report_file(config_hash: str, results: analysis_results.GenericObject) -> None:
    logging.info("Reporting results to file")
    configs, blobs, binaries = flatten_results(results)

    random_name = uuid.uuid4()
    out_path = Path("./results") / str(random_name)
    out_path.mkdir()

    print(f"Got {len(configs)} configs")
    print(f"Got {len(blobs)} blobs")
    print(f"Got {len(binaries)} binaries")

    for i, cfg in enumerate(configs):
        (out_path / f"config_{i}").write_text(json.dumps(cfg.config))

    for i, binary in enumerate(binaries):
        (out_path / f"binary_{i}_{binary.name}").write_bytes(binary.data)

    for i, blob in enumerate(blobs):
        (out_path / f"blob_{i}_{blob.name}").write_text(blob.content)


def report_mwdb(config_hash: str, results: analysis_results.GenericObject) -> None:
    logging.info("Reporting results to mwdb")
    result_json = results.to_dict_recursive()
    mwdb = utils.get_mwdb()
    utils.report_mwdb_tree(mwdb, result_json, config_hash)
