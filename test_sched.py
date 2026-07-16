import asyncio
from apscheduler import AsyncScheduler

async def main():
    scheduler = AsyncScheduler()
    async with scheduler:
        print("Scheduler started!")
        await asyncio.sleep(2)
        print("Done sleeping.")

asyncio.run(main())
