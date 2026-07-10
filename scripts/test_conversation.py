#!/usr/bin/env python3
import asyncio
import sys

async def run_test():
    print("Starting Ganymede E2E Conversation Test...")
    
    # Start the ganymede console provider via the global binary
    process = await asyncio.create_subprocess_exec(
        "ganymede", "run", "--platform", "console",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    print("Sending prompt to agent...")
    prompt = "Please reply with exactly the word BANANA and nothing else.\n"
    process.stdin.write(prompt.encode('utf-8'))
    await process.stdin.drain()
    
    # Safety timeout to exit if the agent hangs
    async def send_exit():
        await asyncio.sleep(15)
        if process.returncode is None:
            print("Timeout reached. Sending /exit...")
            process.stdin.write("/exit\n".encode('utf-8'))
            await process.stdin.drain()
        
    asyncio.create_task(send_exit())
    
    print("Waiting for streaming response...")
    success = False
    
    try:
        # Create tasks to read both stdout and stderr
        async def read_stream(stream, prefix):
            nonlocal success
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode('utf-8').strip()
                if text:
                    print(f"{prefix} {text}")
                    if "BANANA" in text.upper():
                        print("\n✅ Success! Real LLM conversation round-trip completed.")
                        success = True

        await asyncio.gather(
            read_stream(process.stdout, "[STDOUT]"),
            read_stream(process.stderr, "[STDERR]")
        )
    except Exception as e:
        print(f"Error reading stdout: {e}")
        
    # Cleanup
    if process.returncode is None:
        process.stdin.write("/exit\n".encode('utf-8'))
        await process.stdin.drain()
    await process.wait()
    
    if success:
        sys.exit(0)
    else:
        print("\n❌ Test failed. Agent did not stream the expected response.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_test())
