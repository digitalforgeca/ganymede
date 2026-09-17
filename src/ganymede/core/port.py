"""
Port configuration, conflict detection, and interactive resolution for Ganymede.
"""
import io
import os
import socket
import sys
from typing import Optional
import structlog

logger = structlog.get_logger("ganymede.port")


def is_port_busy(port: int, host: str = "0.0.0.0") -> bool:
    """
    Check if a TCP port is currently in use or bound by another process.
    Tests both active connection (listening server) and socket binding.
    """
    # 1. Probe if a service is actively listening on localhost:port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        try:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        except Exception:
            pass

    # 2. Probe if host:port can be bound
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        except OSError:
            return True

    # 3. If host is 0.0.0.0, also verify 127.0.0.1
    if host == "0.0.0.0":
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
            except OSError:
                return True

    return False


def find_next_available_port(start_port: int, host: str = "0.0.0.0", max_attempts: int = 100) -> int:
    """Find the next available port starting from start_port."""
    for candidate in range(start_port, start_port + max_attempts):
        if not is_port_busy(candidate, host=host):
            return candidate
    raise RuntimeError(f"Could not find an available port in range {start_port} - {start_port + max_attempts}")


def prompt_and_resolve_port(
    initial_port: int,
    host: str = "0.0.0.0",
    interactive: Optional[bool] = None
) -> int:
    """
    Verifies that initial_port is available. If busy, provides feedback to the user:
    "port {x} is busy.  Start up on port {next}?"
    
    If the user accepts (Enter, 'y', or 'yes'), proceeds with the next port.
    If the user declines, exits cleanly.
    In non-interactive environments, logs an informative error and exits.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()

    current_port = initial_port

    while is_port_busy(current_port, host=host):
        next_port = current_port + 1
        prompt_text = f"port {current_port} is busy.  Start up on port {next_port}? "

        if not interactive:
            print(
                f"Error: port {current_port} is busy. Cannot prompt in non-interactive mode. "
                f"Please free port {current_port} or use --port to select an available port.",
                file=sys.stderr
            )
            sys.exit(1)

        try:
            response = input(prompt_text).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)

        if response in ("", "y", "yes"):
            current_port = next_port
        else:
            print(f"Aborted: port {current_port} is busy. Please free port {current_port} or specify another port using --port.")
            sys.exit(1)

    return current_port
