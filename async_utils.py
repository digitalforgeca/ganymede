import asyncio
from asyncio import subprocess

async def async_run(*args, capture_output=False, text=True, check=False, env=None, input=None):
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        stdin=subprocess.PIPE if input is not None else None,
        env=env
    )
    stdout, stderr = await proc.communicate(input=input.encode() if input and text else input)
    
    if text and stdout is not None:
        stdout = stdout.decode()
    if text and stderr is not None:
        stderr = stderr.decode()
        
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command {' '.join(args)} failed with return code {proc.returncode}")
        
    class _Res:
        def __init__(self, rc, out, err):
            self.returncode = rc
            self.stdout = out
            self.stderr = err
            
    return _Res(proc.returncode, stdout, stderr)
