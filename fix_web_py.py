with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'r') as f:
    lines = f.readlines()
    
# Find start of the bottom imports and we'll insert before it
insert_idx = 0
for i, line in enumerate(lines):
    if line.startswith('from ganymede.core.routes.dashboard'):
        insert_idx = i
        break

new_methods = """
    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        port = getattr(self.config.agent, "dashboard_port", 8180)
        self.site = web.TCPSite(self.runner, '0.0.0.0', port)
        await self.site.start()
        logger.info(f"Dashboard started on port {port}", url=f"http://localhost:{port}")
        
        # Start SSE MCP server on 8081 natively
        self.mcp_task = asyncio.create_task(self.start_mcp_server())

    async def stop(self):
        if getattr(self, 'mcp_task', None):
            self.mcp_task.cancel()
        if getattr(self, 'runner', None):
            await self.runner.cleanup()
        logger.info("Dashboard stopped")

"""

# Clean the lines appended at the end
clean_lines = []
for line in lines:
    if line.strip() == "async def start(self):" or "logger.info(\"Dashboard stopped\")" in line:
        break
    clean_lines.append(line)

clean_lines.insert(insert_idx, new_methods)

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'w') as f:
    f.writelines(clean_lines)

print("Fixed web.py")
