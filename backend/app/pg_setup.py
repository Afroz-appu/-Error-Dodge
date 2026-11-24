"""Run once as a release step after the application migrations."""

from langgraph.checkpoint.postgres import PostgresSaver
from .runtime_config import secret_setting


if __name__ == "__main__":
    with PostgresSaver.from_conn_string(secret_setting("ERROR_DODGE_DATABASE_URL")) as saver:
        saver.setup()
