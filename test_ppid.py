import os
import subprocess
def _get_ppid(pid):
    out = subprocess.check_output(["ps", "-o", "ppid=", "-p", str(pid)], text=True).strip()
    return int(out)
pid_chain = []
current = os.getpid()
for _ in range(5):
    current = _get_ppid(current)
    if current <= 1:
        break
    pid_chain.append(current)
print(f"PID chain: {pid_chain}")
