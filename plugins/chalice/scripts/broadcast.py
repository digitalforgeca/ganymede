import sys
import json
import urllib.request
import urllib.error
import os

# Path where Ganymede writes agy-PID → conversation-ID mappings.
# Each spawned agy process gets a file named by its PID containing our internal ID.
_PID_MAP_DIR = os.path.expanduser("~/.ganymede/data/pid_map")

def _resolve_ganymede_conv_id():
    """Walk up the process tree to find which Ganymede ManagedAgent spawned us.
    
    The hook runs as: ganymede → agy → [shell?] → python3 broadcast.py
    We walk the PPID chain upward checking for a PID mapping file at each level.
    """
    try:
        pid_chain = []
        current = os.getpid()
        # Walk up to 5 levels (broadcast → shell → agy → ganymede → init)
        for _ in range(5):
            current = _get_ppid(current)
            if current <= 1:
                break
            pid_chain.append(current)
            map_file = os.path.join(_PID_MAP_DIR, str(current))
            if os.path.exists(map_file):
                with open(map_file, "r") as f:
                    return f.read().strip()
    except Exception:
        pass
    return None

def _get_ppid(pid):
    """Get parent PID of a given PID (macOS compatible)."""
    try:
        import subprocess
        out = subprocess.check_output(["ps", "-o", "ppid=", "-p", str(pid)], text=True).strip()
        return int(out)
    except Exception:
        return 0

def main():
    if not sys.stdin.isatty():
        try:
            # Antigravity CLI passes context JSON into the hook's stdin
            hook_context = json.load(sys.stdin)
            hook_type = os.environ.get("AGY_HOOK_EVENT", "Agent Lifecycle Hook")
            
            # Extract basic context ID if present
            conversation_id = hook_context.get("conversationId", "unknown")
            
            # Formulate the telemetry payload
            # ganymede_conv_id is resolved via PID mapping since agy strips env vars.
            payload = {
                "event": hook_type,
                "level": "info",
                "context": conversation_id,
                "ganymede_conv_id": _resolve_ganymede_conv_id(),
                "payload": hook_context
            }
            
            req = urllib.request.Request(
                "http://127.0.0.1:8080/api/telemetry",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=2.0)
            
        except Exception:
            # Silently fail if gateway is down so we don't break the agent
            pass

if __name__ == "__main__":
    main()
