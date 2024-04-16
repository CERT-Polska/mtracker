import logging
import pkgutil
import sys
from importlib.util import module_from_spec, spec_from_file_location
from typing import Type, Dict

from .bot import ModuleBase


log = logging.getLogger(__name__)


class ModuleManager:
    @classmethod
    def load(cls, modules_path: str):
        cls.trackers = load_trackers(modules_path)
        return cls.trackers

    @classmethod
    def get(cls):
        return cls.trackers


def load_trackers(modules_path: str) -> Dict[str, Type[ModuleBase]]:
    """Load trackers from a given modules directory. The path must point
    at a directory with a __init__.py file, that contains a dictionary
    called trackers with a list of trackers. A valid __init__.py file
    may look like this:

    from .isfb.isfb import ISFB
    trackers = {
        "isfb" : ISFB,
    }

    This will return a single module for ISFB malware, called "isfb".
    """
    for finder, module_name, x in pkgutil.iter_modules([modules_path], "mtracker.modules."):
        log.info(f"Loading %s", module_name)
        module_spec = finder.find_spec(module_name)
        assert module_spec is not None  # We just got it from pkgutil
        module = module_from_spec(module_spec)
        sys.modules[module_name] = module

    spec = spec_from_file_location("mtracker.modules", modules_path + "/__init__.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Modules directory is missing the __init__.py file.")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    log.info("Loaded the following modules: %s", ", ".join(module.trackers.keys()))
    return module.trackers
