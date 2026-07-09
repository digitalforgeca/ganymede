import discord
from discord import app_commands
import asyncio
import uuid
import structlog
import time
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage
from apscheduler.triggers.cron import CronTrigger

logger = structlog.get_logger()

def setup_commands(adapter: discord.Client):
    tree = adapter.tree

    @tree.command(name="ask", description="Ask the agent a question and get a streamed response")
    @app_commands.describe(prompt="The prompt to send to the agent")
    async def ask(interaction: discord.Interaction, prompt: str):
        # 1. Send initial response acknowledging the command
        await interaction.response.send_message(f"💬 *Processing query...*", ephemeral=True)

        # 2. Construct PlatformMessage
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        context = ContextKey(
            platform="discord",
            channel_id=channel_id,
            thread_id=thread_id
        )

        message = PlatformMessage(
            context=context,
            author_id=str(interaction.user.id),
            author_name=interaction.user.name,
            content=prompt,
            is_bot=interaction.user.bot,
            mentions_us=False,
            attachments=[],
            reply_to=None,
            raw=interaction
        )

        # 3. run asyncio.create_task(adapter.router.handle_message(msg)) in the background
        asyncio.create_task(adapter.router.handle_message(message))

    @tree.command(name="task", description="Start a background task managed by the agent")
    @app_commands.describe(description="The task description")
    async def task(interaction: discord.Interaction, description: str):
        task_id = str(uuid.uuid4())
        
        # Initial response acknowledging the task has started
        await interaction.response.send_message(f"⏳ Task started. ID: `{task_id}`", ephemeral=True)

        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        context = ContextKey(
            platform="discord",
            channel_id=channel_id,
            thread_id=thread_id
        )

        # Save to DB with status 'running'
        db = adapter.router.db
        if db:
            await db.save_task(task_id, context, str(interaction.user.id), description, "running")

        # Run the agent in the background
        async def run_task_in_background():
            try:
                agent_manager = adapter.router.agent_manager
                managed_agent = await agent_manager.get_or_create(context)
                
                # Run chat
                response = await managed_agent.chat(description)
                
                # Drain/resolve response to get text
                result_text = await response.text()
                
                # Get usage stats if available
                usage = response.usage_metadata
                tokens_count = usage.total_token_count if usage and usage.total_token_count is not None else 0
                
                if agent_manager.quota_tracker:
                    await agent_manager.quota_tracker.record_usage(context, tokens_count)

                # Save response to history if DB available
                if db:
                    await db.save_message(
                        context=context,
                        author_id=str(adapter.user.id) if adapter.user else "bot",
                        role="assistant",
                        content=result_text,
                        tokens=tokens_count
                    )
                    # Update task status to completed
                    await db.update_task(task_id, "completed", result_text)

                # Send completed embed to channel
                embed = discord.Embed(
                    title="✅ Task Completed",
                    description=f"**Task ID**: `{task_id}`\n**Description**: {description}\n\n**Result**:\n{result_text[:1800]}",
                    color=discord.Color.green()
                )
                channel = await adapter._resolve_channel(context)
                if channel:
                    await channel.send(embed=embed)

                # DM the user with results
                try:
                    await interaction.user.send(content=f"👋 Your background task `{task_id}` completed successfully!\n\n**Description**: {description}\n\n**Result**:\n{result_text}")
                except Exception as dm_err:
                    logger.warning("Failed to DM user task completion", user_id=interaction.user.id, error=str(dm_err))

            except Exception as err:
                logger.error("Background task execution failed", task_id=task_id, error=str(err))
                if db:
                    await db.update_task(task_id, "failed", str(err))
                
                # Post failure to channel
                embed = discord.Embed(
                    title="❌ Task Failed",
                    description=f"**Task ID**: `{task_id}`\n**Description**: {description}\n\n**Error**:\n`{str(err)}`",
                    color=discord.Color.red()
                )
                channel = await adapter._resolve_channel(context)
                if channel:
                    await channel.send(embed=embed)

        asyncio.create_task(run_task_in_background())

    @tree.command(name="status", description="Check the status of background tasks")
    @app_commands.describe(task_id="Optional Task UUID to check")
    async def status(interaction: discord.Interaction, task_id: str | None = None):
        db = adapter.router.db
        if not db:
            await interaction.response.send_message("❌ Database is not enabled.", ephemeral=True)
            return

        if task_id:
            task_info = await db.get_task(task_id)
            if not task_info:
                await interaction.response.send_message("❌ Task not found.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"📋 Task Status: {task_id}",
                color=discord.Color.blue() if task_info['status'] == 'running' else (discord.Color.green() if task_info['status'] == 'completed' else discord.Color.red())
            )
            embed.add_field(name="Description", value=task_info['description'], inline=False)
            embed.add_field(name="Status", value=task_info['status'].upper(), inline=True)
            embed.add_field(name="Creator", value=f"<@{task_info['creator_id']}>", inline=True)
            embed.add_field(name="Created At", value=task_info['created_at'], inline=True)
            if task_info['completed_at']:
                embed.add_field(name="Completed At", value=task_info['completed_at'], inline=True)
            
            if task_info['result']:
                result_display = task_info['result'][:1000] + ("..." if len(task_info['result']) > 1000 else "")
                embed.add_field(name="Result / Error", value=f"```\n{result_display}\n```", inline=False)
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            recent = await db.get_recent_tasks(10)
            if not recent:
                await interaction.response.send_message("No tasks found.", ephemeral=True)
                return

            embed = discord.Embed(title="📋 Recent Background Tasks", color=discord.Color.blue())
            description_lines = []
            for t in recent:
                status_emoji = "⏳" if t['status'] == 'running' else ("✅" if t['status'] == 'completed' else "❌")
                description_lines.append(f"{status_emoji} `{t['id'][:8]}...`: {t['description'][:40]} ({t['status']})")
            
            embed.description = "\n".join(description_lines)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="session", description="Manage or inspect the active agent session")
    @app_commands.choices(action=[
        app_commands.Choice(name="info", value="info"),
        app_commands.Choice(name="reset", value="reset")
    ])
    async def session(interaction: discord.Interaction, action: str):
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        context = ContextKey(
            platform="discord",
            channel_id=channel_id,
            thread_id=thread_id
        )

        agent_manager = adapter.router.agent_manager
        if not agent_manager:
            await interaction.response.send_message("❌ Agent Manager is not configured.", ephemeral=True)
            return

        if action == "reset":
            await agent_manager.destroy(context)
            await interaction.response.send_message("🔄 Agent session for this channel reset successfully.", ephemeral=True)
        elif action == "info":
            managed = agent_manager._agents.get(context)
            
            embed = discord.Embed(title="🤖 Active Session Information", color=discord.Color.blue())
            embed.add_field(name="Platform", value=context.platform, inline=True)
            embed.add_field(name="Channel ID", value=context.channel_id, inline=True)
            if context.thread_id:
                embed.add_field(name="Thread ID", value=context.thread_id, inline=True)

            workspace = agent_manager.config.agent.workspace
            embed.add_field(name="Workspace", value=workspace, inline=False)

            if managed:
                idle_sec = time.time() - managed.last_active
                idle_str = f"{int(idle_sec // 60)}m {int(idle_sec % 60)}s"
                embed.add_field(name="Session Status", value=f"Active (Idle for {idle_str})", inline=True)
            else:
                embed.add_field(name="Session Status", value="Inactive (No agent spawned)", inline=True)

            if agent_manager.quota_tracker:
                summary = await agent_manager.quota_tracker.get_usage_summary(context)
                embed.add_field(name="Context Hourly Usage", value=f"{summary['context_usage']} / {summary['context_limit']} tokens", inline=True)
                embed.add_field(name="Global Hourly Usage", value=f"{summary['global_usage']} / {summary['global_limit']} tokens", inline=True)

            await interaction.response.send_message(embed=embed, ephemeral=True)

    @tree.command(name="schedule", description="Schedule a recurring agent prompt using cron trigger")
    @app_commands.describe(
        cron="Cron expression (e.g. '*/5 * * * *')",
        prompt="The prompt to send to the agent recurringly"
    )
    async def schedule(interaction: discord.Interaction, cron: str, prompt: str):
        # Validate cron expression
        try:
            CronTrigger.from_crontab(cron)
        except Exception as e:
            await interaction.response.send_message(f"❌ Invalid cron expression: `{str(e)}`", ephemeral=True)
            return

        # Check if callback is registered
        schedule_cb = getattr(adapter, "schedule_callback", None)
        if not schedule_cb and hasattr(adapter, "ipc_server") and adapter.ipc_server:
            schedule_cb = getattr(adapter.ipc_server, "schedule_callback", None)

        if not schedule_cb:
            await interaction.response.send_message("❌ Scheduler callback is not registered on the adapter.", ephemeral=True)
            return

        try:
            job_id = await schedule_cb(cron, prompt, str(interaction.channel.id))
            embed = discord.Embed(
                title="📅 Recurring Prompt Scheduled",
                description=f"**Job ID**: `{job_id}`\n**Cron**: `{cron}`\n**Prompt**: {prompt}",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error("Failed to schedule cron job from command", error=str(e))
            await interaction.response.send_message(f"❌ Failed to schedule job: {str(e)}", ephemeral=True)

    @tree.command(name="config", description="Configure agent capability toggles (Admin only)")
    @app_commands.choices(capability=[
        app_commands.Choice(name="write_tools", value="write_tools"),
        app_commands.Choice(name="run_commands", value="run_commands")
    ])
    @app_commands.choices(enabled=[
        app_commands.Choice(name="true", value="true"),
        app_commands.Choice(name="false", value="false")
    ])
    async def config_capability(interaction: discord.Interaction, capability: str, enabled: str):
        # 1. Gate to administrators
        is_admin = False
        if interaction.guild:
            perms = interaction.user.guild_permissions
            is_admin = perms.administrator
        
        if not is_admin:
            await interaction.response.send_message("❌ Only server administrators can update agent capabilities.", ephemeral=True)
            return

        # 2. Update config
        val = enabled == "true"
        adapter.config.agent.capabilities[capability] = val

        # 3. destroy_all active sessions to pick up config change
        agent_manager = adapter.router.agent_manager
        if agent_manager:
            await agent_manager.destroy_all()

        await interaction.response.send_message(f"🔧 Capability `{capability}` set to `{val}`. All active sessions reloaded.", ephemeral=True)

    @tree.command(name="plan", description="Ask the agent to create a step-by-step plan before execution")
    @app_commands.describe(prompt="The task or objective to plan for")
    async def plan(interaction: discord.Interaction, prompt: str):
        await interaction.response.send_message(f"📝 *Planning execution...*", ephemeral=True)
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        message = PlatformMessage(
            context=ContextKey(platform="discord", channel_id=channel_id, thread_id=thread_id),
            author_id=str(interaction.user.id),
            author_name=interaction.user.name,
            content=f"/plan {prompt}",
            is_bot=interaction.user.bot,
            mentions_us=False,
            attachments=[],
            reply_to=None,
            raw=interaction
        )
        asyncio.create_task(adapter.router.handle_message(message))

    @tree.command(name="goal", description="Set a long-running goal and run until achieved")
    @app_commands.describe(prompt="The long-running goal description")
    async def goal(interaction: discord.Interaction, prompt: str):
        await interaction.response.send_message(f"🎯 *Executing goal cascade...*", ephemeral=True)
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        message = PlatformMessage(
            context=ContextKey(platform="discord", channel_id=channel_id, thread_id=thread_id),
            author_id=str(interaction.user.id),
            author_name=interaction.user.name,
            content=f"/goal {prompt}",
            is_bot=interaction.user.bot,
            mentions_us=False,
            attachments=[],
            reply_to=None,
            raw=interaction
        )
        asyncio.create_task(adapter.router.handle_message(message))

    @tree.command(name="grill-me", description="Align on a plan through an interactive interview")
    @app_commands.describe(prompt="Optional context or topic to align on")
    async def grill_me(interaction: discord.Interaction, prompt: str | None = None):
        await interaction.response.send_message(f"🔥 *Starting interview alignment...*", ephemeral=True)
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        content = f"/grill-me {prompt}" if prompt else "/grill-me"
        message = PlatformMessage(
            context=ContextKey(platform="discord", channel_id=channel_id, thread_id=thread_id),
            author_id=str(interaction.user.id),
            author_name=interaction.user.name,
            content=content,
            is_bot=interaction.user.bot,
            mentions_us=False,
            attachments=[],
            reply_to=None,
            raw=interaction
        )
        asyncio.create_task(adapter.router.handle_message(message))

    @tree.command(name="learn", description="Persist a behavioral pattern or solution for future tasks")
    @app_commands.describe(prompt="The instruction or rule to persist")
    async def learn(interaction: discord.Interaction, prompt: str):
        await interaction.response.send_message(f"🧠 *Saving behavioral instruction...*", ephemeral=True)
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        message = PlatformMessage(
            context=ContextKey(platform="discord", channel_id=channel_id, thread_id=thread_id),
            author_id=str(interaction.user.id),
            author_name=interaction.user.name,
            content=f"/learn {prompt}",
            is_bot=interaction.user.bot,
            mentions_us=False,
            attachments=[],
            reply_to=None,
            raw=interaction
        )
        asyncio.create_task(adapter.router.handle_message(message))

    @tree.command(name="teamwork-preview", description="Preview teamwork options with autonomous agents")
    @app_commands.describe(prompt="Optional description of the project or team setup")
    async def teamwork_preview(interaction: discord.Interaction, prompt: str | None = None):
        await interaction.response.send_message(f"👥 *Previewing team setup...*", ephemeral=True)
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        
        content = f"/teamwork-preview {prompt}" if prompt else "/teamwork-preview"
        message = PlatformMessage(
            context=ContextKey(platform="discord", channel_id=channel_id, thread_id=thread_id),
            author_id=str(interaction.user.id),
            author_name=interaction.user.name,
            content=content,
            is_bot=interaction.user.bot,
            mentions_us=False,
            attachments=[],
            reply_to=None,
            raw=interaction
        )
        asyncio.create_task(adapter.router.handle_message(message))

    @tree.command(name="stop", description="Abruptly terminate the active agent execution in this channel")
    async def stop(interaction: discord.Interaction):
        # Construct ContextKey
        thread_id = str(interaction.channel.id) if isinstance(interaction.channel, discord.Thread) else None
        channel_id = str(interaction.channel.parent_id) if thread_id else str(interaction.channel.id)
        context = ContextKey(platform="discord", channel_id=channel_id, thread_id=thread_id)
        
        agent_manager = adapter.router.agent_manager
        if agent_manager:
            managed_agent = agent_manager._agents.get(context)
            if managed_agent:
                await managed_agent.terminate()
                await agent_manager.destroy(context)
                await interaction.response.send_message("🛑 *Active agent execution aborted and session cleared successfully.*", ephemeral=False)
            else:
                await interaction.response.send_message("❌ *No active agent execution found for this channel.*", ephemeral=True)
        else:
            await interaction.response.send_message("❌ *Agent manager not configured.*", ephemeral=True)

    @tree.command(name="about", description="Display information about the bot, active workspace, and credits")
    async def about(interaction: discord.Interaction):
        db = adapter.router.db
        agent_manager = adapter.router.agent_manager
        
        embed = discord.Embed(
            title="🤖 About Ganymede Agent Bridge",
            description="The communication, scheduling, and agent execution sidecar for Google Antigravity.",
            color=discord.Color.blue()
        )
        
        # Add credits/company information
        embed.add_field(
            name="🏢 Created By",
            value="**Digital Forge Studios Inc.**",
            inline=False
        )
        
        # Add bot user details
        embed.add_field(
            name="🤖 Bot User",
            value=f"{adapter.user} (ID: `{adapter.user.id}`)" if adapter.user else "Unknown Bot",
            inline=True
        )
        
        # Add DB status
        db_status = "Enabled" if db else "Disabled"
        embed.add_field(
            name="💾 Database Status",
            value=db_status,
            inline=True
        )
        
        # Add workspace details if agent manager is configured
        if agent_manager:
            workspace = agent_manager.config.agent.workspace
            embed.add_field(name="📂 Active Workspace", value=workspace, inline=False)
            
            # Check capabilities
            caps = agent_manager.config.agent.capabilities
            caps_str = ", ".join(f"`{k}`" for k, v in caps.items() if v) or "None"
            embed.add_field(name="🔧 Enabled Capabilities", value=caps_str, inline=False)
            
        embed.set_footer(text="Digital Forge Studios Inc. © 2026")
        await interaction.response.send_message(embed=embed, ephemeral=True)
