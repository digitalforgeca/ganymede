import asyncio
import os
import sys

async def mock_agy():
    print("Mocking AGY...")
    sys.stdout.flush()
    for i in range(10):
        print(f"Token {i} ", end="")
        sys.stdout.flush()
        await asyncio.sleep(0.1)
    print("\nDone.")
    sys.stdout.flush()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mock":
        asyncio.run(mock_agy())
    else:
        from ganymede.core.agent_manager import CliResponse
        from unittest.mock import AsyncMock
        import pty
        
        async def main():
            master_fd, slave_fd = pty.openpty()
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "test_stream.py", "mock",
                stdout=slave_fd,
                stderr=slave_fd
            )
            os.close(slave_fd)
            
            resp = CliResponse(proc, "test", master_fd)
            async for chunk in resp.chunks:
                print(f"CHUNK: {chunk.text!r}")
                
        asyncio.run(main())
