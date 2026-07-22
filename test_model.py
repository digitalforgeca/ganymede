from src.ganymede.config import load_config
import argparse
args = argparse.Namespace(config="~/.ganymede/config.yaml")
config = load_config(args)
print(f"Model is: {config.agent.model}")
