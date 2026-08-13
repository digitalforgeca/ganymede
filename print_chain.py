import os
import subprocess
def _get_ppid(pid):
    out = subprocess.check_output(["ps", "-o", "ppid=", "-p", str(pid)], text=True).strip()
    return int(out)
chain = []
curr = os.getpid()
for _ in range(7):
    curr = _get_ppid(curr)
    if curr <= 1: break
    chain.append(curr)
print("CHAIN:", chain)
