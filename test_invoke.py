import asyncio
from ganymede.core.agent_manager import AgentManager, ContextKey

async def main():
    manager = AgentManager(bot_namespace="test")
    ctx = ContextKey(platform="discord", channel_id="12345", thread_id=None)
    
    agent = await manager.get_or_create(ctx)
    print("Agent spawned:", agent.conversation_id)
    
    # Send a fast prompt that exits quickly
    print("Sending prompt...")
    async for item in manager.chat(ctx, "echo exactly 'hello world'"):
        print("Chat Output:", item)
        break

if __name__ == "__main__":
    asyncio.run(main())
