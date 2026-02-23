from typedconfig import Config, key, section, group_key  # type: ignore
from typedconfig.source import EnvironmentConfigSource, IniFileConfigSource  # type: ignore
import os


@section("mtracker")
class MtrackerConfig(Config):
    # How many times can a task fail before being archived
    max_failing_spree = key(cast=int, required=False, default=5)
    # How long can a single task take before being killed, in seconds
    task_timeout = key(cast=int, required=False, default=900)
    # How often should tasks be restarted/tried again
    task_period = key(cast=int, required=False, default=43200)
    # A default timeout that should be used for HTTP requests
    default_http_timeout = key(cast=int, required=False, default=3)
    # Run flask in debug mode?
    debug = key(cast=int, required=False, default=0)


@section("log")
class LogConfig(Config):
    # Only "filesystem" provider is supported
    provider = key(cast=str, required=False, default="filesystem")
    # Directory where to store the logs
    dir = key(cast=str, required=False, default="/tmp/logs")


@section("mwdb")
class MwdbConfig(Config):
    # Mwdb base URL without trailing slash, for example "https://mwdb.cert.pl"
    url = key(cast=str, required=False, default="https://mwdb.cert.pl")
    # If the desired MWDB API is *not* just MWDB_URL/api, you can override it here
    api_url_override = key(cast=str, required=False, default=None)
    # Token used to authenticate to mwdb.
    token = key(cast=str, required=True, default="")

    @property
    def api_url(self):
        """Gets a correct MWDB API URL (either the default, or override)."""
        return self.api_url_override or self.url + "/api"


@section("database")
class DatabaseConfig(Config):
    # URL of a configured sql database.
    url = key(
        cast=str, required=False, default="postgresql://mtracker3:postgres@localhost:5432/mtracker3"
    )


@section("proxy")
class ProxyConfig(Config):
    # Default proxy country, for example "us"
    default = key(cast=str, required=True, default=None)
    # One of "url" or "file"
    method = key(cast=str, required=True, default=None)
    # Relevant if METHOD is "url"
    url = key(cast=str, required=False, default=None)
    # Relevant if METHOD is "file"
    path = key(cast=str, required=False, default="/etc/proxies/proxies.json")


@section("redis")
class RedisConfig(Config):
    # Hostname of a configured redis instance.
    host = key(cast=str, required=False, default="localhost")
    # Port of a configured redis instance.
    port = key(cast=int, required=False, default=6379)


class AppConfig(Config):
    mtracker: MtrackerConfig = group_key(MtrackerConfig)
    log: LogConfig = group_key(LogConfig)
    mwdb: MwdbConfig = group_key(MwdbConfig)
    redis: RedisConfig = group_key(RedisConfig)
    database: DatabaseConfig = group_key(DatabaseConfig)
    proxy: ProxyConfig = group_key(ProxyConfig)


def _config_sources():
    return [
        EnvironmentConfigSource(),
        IniFileConfigSource("mtracker.ini", must_exist=False),
        IniFileConfigSource(
            os.path.expanduser("~/.config/mtracker/mtracker.ini"), must_exist=False
        ),
        IniFileConfigSource("/etc/mtracker/mtracker.ini", must_exist=False),
    ]


app_config = AppConfig(sources=_config_sources())
