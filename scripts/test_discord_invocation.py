#!/usr/bin/env python3
import asyncio
import os
import sys
import urllib.request
import urllib.error
import json

async def run_test():
    print("Starting Ganymede E2E Discord Invocation Test...")
    
    # Read the IPC port from the data directory
    data_dir = os.path.expanduser("~/.ganymede/data")
    port_file = os.path.join(data_dir, "rpc_port.txt")
    
    if not os.path.exists(port_file):
        print(f"Error: IPC port file not found at {port_file}. Is Ganymede running?")
        sys.exit(1)
        
    with open(port_file, "r") as f:
        port = f.read().strip()
        
    print(f"Connecting to local IPC server on port {port}...")
    
    # Define the payload
    # Channel ID here should be a real test channel if we want the bot to actually send the reply there.
    # We can use the test channel ID provided in the arguments, or a default one.
    channel_id = sys.argv[1] if len(sys.argv) > 1 else "1480417496002461758"
    prompt = sys.argv[2] if len(sys.argv) > 2 else "Please reply with exactly the word BANANA and nothing else."
    
    payload = {
        "channel_id": channel_id,
        "content": prompt,
        "author_id": "1480417496002461759", # dummy
        "author_name": "TestRunner"
    }
    
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/test/invoke",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        response = urllib.request.urlopen(req, timeout=5.0)
        res_data = json.loads(response.read().decode("utf-8"))
        print(f"Invocation status: {res_data}")
        
        if res_data.get("status") == "invoked":
            print("✅ Successfully injected mock Discord message to Ganymede.")
            print("Check your Discord client or the logs to see the bot's response in real-time.")
            print("To wait for the final message and fetch it programmatically, we can query /api/channel/history.")
            
            # Optionally poll SQLite DB to wait for BANANA
            import sqlite3
            db_path = os.path.expanduser("~/.ganymede/data/ganymede.db")
            
            if "BANANA" in prompt:
                print("Polling local database for BANANA...")
                for i in range(30):
                    await asyncio.sleep(2.0)
                    try:
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        cursor.execute("SELECT content FROM conversations WHERE context_channel = ? AND role = 'assistant' ORDER BY created_at DESC LIMIT 5", (channel_id,))
                        rows = cursor.fetchall()
                        conn.close()
                        
                        for row in rows:
                            if "BANANA" in row[0].upper():
                                print(f"\n✅ Success! Found expected response from bot in database: {row[0]}")
                                sys.exit(0)
                    except Exception as e:
                        pass
                    print(".", end="", flush=True)
                
                print("\n❌ Timed out waiting for expected response in database.")
                sys.exit(1)
            
    except urllib.error.URLError as e:
        print(f"Failed to connect to IPC server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_test())
