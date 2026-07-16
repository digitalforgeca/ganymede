import sys, os
from ganymede.config import AppConfig
from ganymede.cli import stop_daemon

config = AppConfig()
config.data_dir = os.path.expanduser("~/.ganymede")
stop_daemon(config)
