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
        # Walk up to 20 levels (broadcast → shell → agy → ganymede → init)
        for _ in range(20):
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
        if os.path.exists(f"/proc/{pid}/stat"):
            with open(f"/proc/{pid}/stat", "r") as f:
                stat = f.read()
                rparen = stat.rfind(')')
                if rparen != -1:
                    parts = stat[rparen+2:].split()
                    return int(parts[1])
        
        import subprocess
        try:
            out = subprocess.check_output(["/bin/ps", "-o", "ppid=", "-p", str(pid)], text=True).strip()
        except FileNotFoundError:
            out = subprocess.check_output(["ps", "-o", "ppid=", "-p", str(pid)], text=True).strip()
        return int(out)
    except Exception:
        return 0

def main():
    if not sys.stdin.isatty():
        try:
            # Antigravity CLI passes context JSON into the hook's stdin
            hook_context = json.load(sys.stdin)
            
            # Infer hook type from payload structure since agy strips most env vars.
            # Order matters: Stop and PreInvocation first (most specific),
            # then PostToolUse (toolCall + error), then PreToolUse (toolCall only).
            if "terminationReason" in hook_context:
                hook_type = "Stop"
            elif "initialNumSteps" in hook_context:
                hook_type = "PreInvocation"
            elif "toolCall" in hook_context and "error" in hook_context:
                hook_type = "PostToolUse"
            elif "toolCall" in hook_context:
                hook_type = "PreToolUse"
            else:
                hook_type = "Agent Lifecycle Hook"
            
            # Extract basic context ID if present
            conversation_id = hook_context.get("conversationId", "unknown")
            
            # Only broadcast if this agy session was spawned by Ganymede.
            # _resolve_ganymede_conv_id() walks the PPID chain looking for a
            # PID mapping file created by ManagedAgent.  If none is found,
            # this is a standalone agy session (IDE, terminal) and we should
            # not send telemetry to the gateway.
            ganymede_id = _resolve_ganymede_conv_id()
            if not ganymede_id:
                # Not a Ganymede-managed session — exit silently.
                return

            payload = {
                "event": hook_type,
                "level": "info",
                "context": conversation_id,
                "ganymede_conv_id": ganymede_id,
                "payload": hook_context
            }
            
            def _get_dashboard_port():
                port = os.environ.get("GANYMEDE_PORT")
                if port and port.isdigit():
                    return int(port)
                
                rpc_port_path = os.path.expanduser("~/.ganymede/data/rpc_port.txt")
                if os.path.exists(rpc_port_path):
                    try:
                        with open(rpc_port_path, "r") as f:
                            val = f.read().strip()
                            if val.isdigit():
                                return int(val)
                    except Exception:
                        pass
                
                config_path = os.path.expanduser("~/.ganymede/config.yaml")
                if os.path.exists(config_path):
                    try:
                        with open(config_path, "r") as f:
                            for line in f:
                                if line.strip().startswith("dashboard_port:"):
                                    val = line.split(":", 1)[1].strip()
                                    if val.isdigit():
                                        return int(val)
                    except Exception:
                        pass
                return 8180

            port = _get_dashboard_port()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/telemetry",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=2.0)
            
        except Exception:
            pass

if __name__ == "__main__":
    main()
