import sys
import json
import urllib.request
import urllib.error
import os

def main():
    if not sys.stdin.isatty():
        try:
            # Antigravity CLI passes context JSON into the hook's stdin
            hook_context = json.load(sys.stdin)
            hook_type = os.environ.get("AGY_HOOK_EVENT", "Agent Lifecycle Hook")
            
            # Extract basic context ID if present
            conversation_id = hook_context.get("conversation_id", "unknown")
            
            # Formulate the telemetry payload
            payload = {
                "event": hook_type,
                "level": "info",
                "context": conversation_id,
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
