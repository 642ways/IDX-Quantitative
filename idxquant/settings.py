"""Where the app runs. Local defaults need nothing, and servers set environment variables."""
from dataclasses import dataclass
import os

LOCAL_HOSTS = ("127.0.0.1", "localhost")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_path: str
    is_server: bool


def load_settings(env=os.environ) -> Settings:
    host = env.get("HOST", "127.0.0.1")
    try:
        port = int(env.get("PORT", "8765"))
    except ValueError:
        raise SystemExit("PORT must be a number.") from None
    return Settings(
        host=host,
        port=port,
        data_path=env.get("DATA_PATH", "data/idxquant.sqlite"),
        is_server=host not in LOCAL_HOSTS,
    )
