#!/usr/bin/env python3
#
# NOTE: The Chalice watchdog approach is no longer the play.
# It has been commented out and deprecated. We should rely on standard
# supervision (like systemd in prod, or direct script in dev) instead
# of a custom polling watchdog script that fights the dev tools.
#

"""
import time
import os
import sys
import json
import subprocess
import argparse

def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock-file", default="/Users/dv00003-00/.config/ganymede/ganymede.lock", help="Path to the ganymede.lock file")
    parser.add_argument("--start-script", default="/Users/dv00003-00/dev/ganymede/scripts/dev_run.sh", help="Path to the restart script")
    parser.add_argument("--poll-interval", type=int, default=3, help="Polling interval in seconds")
    args = parser.parse_args()
    
    print(f"Chalice Watchdog starting... Monitoring lock file: {args.lock_file}")
    
    while True:
        try:
            if os.path.exists(args.lock_file):
                with open(args.lock_file, "r") as f:
                    content = f.read().strip()
                    if not content:
                        continue
                    try:
                        data = json.loads(content)
                        pid = data.get("pid")
                    except json.JSONDecodeError:
                        # Fallback for old simple PID lock file format
                        pid = int(content) if content.isdigit() else None
                
                if pid and not is_process_running(pid):
                    print(f"[!] CRASH DETECTED: ganymede.lock exists but PID {pid} is dead!")
                    env = os.environ.get("GANYMEDE_ENV", "production").lower()
                    if env in ("dev", "development"):
                        dev_script = os.environ.get("GANYMEDE_DEV_SCRIPT", args.start_script)
                        print(f"[*] Development environment detected. Triggering restart via {dev_script}...")
                        subprocess.Popen(["bash", dev_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        print("[*] Production environment detected. Triggering systemd restart...")
                        subprocess.Popen(["systemctl", "--user", "restart", "ganymede"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    # Validation Loop
                    print("[*] Entering validation phase...")
                    validations = 0
                    while validations < 3:
                        time.sleep(5)
                        if os.path.exists(args.lock_file):
                            print(f"[+] Validation {validations + 1}/3 passed. Gateway lock exists.")
                            validations += 1
                        else:
                            print("[-] Validation failed. Gateway crashed immediately.")
                            break
                    print("[*] Crash recovery sequence complete. Resuming monitoring.")
                    time.sleep(10) # Cooldown before resuming fast polling
        except Exception as e:
            print(f"Watchdog loop error: {e}")
            
        time.sleep(args.poll_interval)

if __name__ == "__main__":
    main()
"""
