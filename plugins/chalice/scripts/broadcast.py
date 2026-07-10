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
            
            # Formulate the telemetry payload
            payload = {
                "event": "Tool Execution Hook",
                "level": "info",
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
