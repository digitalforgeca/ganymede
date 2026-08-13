import os, sys, json, subprocess, sqlite3
from datetime import datetime
import time

def print_status(config):
    print("Ganymede Gateway Status")
    print("=======================\n")
    
    # 1. Daemon Status
    lock_path = os.path.join(config.data_dir, "ganymede.lock")
    is_running = False
    pid = None
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                data = json.load(f)
                pid = data.get("pid")
            if pid:
                os.kill(int(pid), 0)
                is_running = True
        except OSError:
            pass
        except Exception:
            pass
            
    print(f"Daemon State : {'🟢 ONLINE' if is_running else '🔴 OFFLINE'}")
    if is_running:
        print(f"Daemon PID   : {pid}")
    
    db_path = os.path.join(config.data_dir, "ganymede.db")
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                c = conn.cursor()
                c.execute("SELECT sum(tokens_total) FROM telemetry WHERE created_at >= datetime('now', '-1 hour')")
                row = c.fetchone()
                tokens_hr = int(row[0]) if row and row[0] else 0
                print(f"Tokens (1hr) : {tokens_hr:,}")
                
                c.execute("SELECT count(*) FROM conversations WHERE role = 'assistant' AND created_at >= datetime('now', 'start of day')")
                row = c.fetchone()
                quota = int(row[0]) if row and row[0] else 0
                max_quota = getattr(config.quota, "max_requests_per_day", 18)
                print(f"Quota (Day)  : {quota} / {max_quota}")
        except Exception:
            pass
            
    print("\nActive Channels:")
    print("----------------")
    
    # Check tmux sessions
    try:
        out = subprocess.check_output(["tmux", "ls"], text=True, stderr=subprocess.DEVNULL)
        sessions = [line.split(":")[0] for line in out.splitlines() if line.startswith("ganymede-")]
        if not sessions:
            print("  No active channels.")
        else:
            for s in sessions:
                # Get the window name or pane command if possible, or just the UUID
                # Actually, the UUID maps to a discord channel. 
                uuid_part = s.replace("ganymede-", "")
                
                # Check for active tasks
                brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{uuid_part}")
                tasks_dir = os.path.join(brain_dir, ".system_generated", "tasks")
                
                active_tasks = 0
                if os.path.exists(tasks_dir):
                    for f in os.listdir(tasks_dir):
                        if f.endswith(".pid"):
                            try:
                                with open(os.path.join(tasks_dir, f), "r") as pid_f:
                                    task_pid = int(pid_f.read().strip())
                                os.kill(task_pid, 0)
                                active_tasks += 1
                            except Exception:
                                pass
                                
                model = "unknown"
                model_txt = os.path.join(brain_dir, "model.txt")
                if os.path.exists(model_txt):
                    with open(model_txt, "r") as f:
                        model = f.read().strip()
                elif hasattr(config.agent, "model"):
                    model = config.agent.model
                    
                status_line = f"  • {s} | Model: {model}"
                if active_tasks > 0:
                    status_line += f" | ⚙️ {active_tasks} active tasks"
                print(status_line)
                
    except subprocess.CalledProcessError:
        print("  No active channels (tmux not running).")
    except Exception as e:
        print(f"  Error reading channels: {e}")
        
    print("")

