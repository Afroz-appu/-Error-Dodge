"""Read a setting from its environment value or a mounted secret file."""
import os
from pathlib import Path


def secret_setting(name: str) -> str:
    value = os.getenv(name, "")
    file_name = os.getenv(name + "_FILE", "")
    if value and file_name:
        raise ValueError(f"Configure either {name} or {name}_FILE")
    if file_name:
        with Path(file_name).open(encoding="utf-8") as stream:
            value = stream.read(4097)
        if len(value) > 4096:
            raise ValueError(f"{name}_FILE exceeds the supported size")
        value = value.rstrip("\r\n")
    return value
