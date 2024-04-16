# module development

Mtracker is just a framework, and **won't work** without implementing modules. Module is a piece of code responsible for tracking a particular family.

To run mtracker worker, you need to pass modules path to it, like

```
python3 -m mtracker.worker /opt/modules/path
```

The directory passed to mtracker worker must contain an `__init__` file that exposes a directory `trackers` with all supported modules.

### a simple example

Let's start with a trivial example. Assume that modules will reside in a `/opt/mtrackermodules` path. This means that you should create the following files:

`/opt/mtrackermodules/__init__.py`:
```python
# Import your module from another file.
# Of course you can do everything in a single file,
# but that's a bad software development habit.
from .testmod.testmod import TestModule

trackers = {
    "testmod": TestModule,
}
```

And now we need to implement the module. We recommend to use a separate directory for every module, so create a directory `testmod` and add an empty file called `__init__.py`:

```
touch /opt/mtrackermodules/testmod/__init__.py
```

Finally, implement the module:

`/opt/mtrackermodules/testmod/testmod.py`
```python
from typing import Dict, Any, Iterator
import time

# Mtracker is a normal module, and you can import things from it.
from mtracker.bot import BotModule, BotResult, CNC


# In most cases, your module should derive from BotModule.
class TestModule(BotModule):
    # Critical parameters - a bot won't be created if config is missing one of this parameters.
    # In practice, put all things that must be in the config
    # for the bot to work, like host IP and port. 
    CRITICAL_PARAMS = ["status", "sleep", "memory"]

    # Constructor is not required, but you might want to do some bot initialisation first.
    def __init__(
        self, config: Dict[str, Any], used_proxy: str, state: Dict[str, Any]
    ) -> None:
        super().__init__(config, used_proxy, state)
        self.sleep = self.config["sleep"]
        self.status = self.config["status"]

    # This method is required. `run` is called for every item returned from this method.
    # For example, if there are 10 IPs in the config, you might want to iterate over them
    # and yield every IP separately.
    # In this example we just hardcode 127.0.0.1 as CNC.
    @classmethod
    def get_cnc_servers(
        cls, config: Dict[str, Any], state: Dict[str, Any]
    ) -> Iterator[CNC]:
        yield "127.0.0.1"

    # This method should connect to C2 (using address c2) and
    # download everything interesting. Read below for more information.
    def run(self, c2: CNC) -> bool:
        time.sleep(self.sleep)
        
        if self.status == "working":
            # This will push blob result to mwdb and database. 
            self.push_blob(
                content="This module is working",
                name="test_blob",
                blob_type="dyn_cfg",
                tags=["testmod", "test"],
            )
            # We got the results we needed
            return BotResult.WORKING
        else:
            # We failed, continue to the next C2, if exists
            return BotResult.CONTINUE
```

### Technical details

There are some important technical details here.

First, run() method is just a regular Python code. This means that you must implement proxy handling yourself.
Every module knows which proxy it should use when running, so
in most cases you can just use `self.proxy_dict`. For example:

```python
result = requests.get(url, headers=headers, proxies=self.proxy_dict)
```

Second, to submit result you must use `self.push_*` methods. There are three kinds of data you can push, same as in MWDB: [samples](https://mwdb.readthedocs.io/en/latest/user-guide/2-Storing-malware-samples.html), [configurations](https://mwdb.readthedocs.io/en/latest/user-guide/3-Storing-malware-configurations.html) and [blobs](https://mwdb.readthedocs.io/en/latest/user-guide/4-Storing-blobs.html).

Uploading files:
```python
self.push_binary(
    data=self.dropped,  # Bytes of the downloaded file
    name=self.dropname or "ostap_drop.exe",  # Name of the downloaded file
    tags=["ostap_drop"],  # Mwdb tags to include
)
```

Uploading configs:
```python
# `config` is a python dictionary with config data
self.push_config(config, "dynamic", ["dynamic:danabot"])
```

Uploading blobs:
```python
self.push_blob(
    content=commands,  # Python string with blob data
    name="gcleaner_commands",
    blob_type="dyn_cfg",
    tags=["dynamic:gcleaner"],
)
```

Of course, since it's a regular Python, you don't have to use these methods to upload data somewhere else.
For example, you may write your own push methods it if you don't want to store your data in mwdb.

Finally, the result of run() method is a BotResult bitflag. There are three flags, `continue`, `workign` and `archive`.
There are a few combinations of flags that make most sense:

* BotResult.WORKING - successfully downloaded data from C2, don't check other C2 servers (from `get_cnc_servers`)
* BotResult.WORKING | BotResult.CONTINUE - successfully downloaded data from C2, but check other C2 servers just in case
* BotResult.CONTINUE - didn't download data from C2. Continue checking other C2 servers just in case
* BotResult.ARCHIVE - archive this bot after the execution, no matter what happens (useful when invalid config is detected)

### Local development

(todo)

That's it - that's everything you need to know to start writing your own mtracker modules.
