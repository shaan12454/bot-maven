import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta, timezone
import asyncio


class Scheduled(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.send_scheduled.start()

    def cog_unload(self):
        self.send_scheduled.cancel()

    @tasks.loop(seconds=30)
    async def send_scheduled(self):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM scheduled_messages
                WHERE enabled=TRUE AND next_run <= NOW()
            """)
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                continue
            channel = guild.get_channel(row["channel_id"])
            if not channel:
                continue
            try:
                await channel.send(row["message"])
            except Exception:
                pass
            next_run = datetime.now(timezone.utc) + timedelta(seconds=row["interval_seconds"])
            async with self.bot.db.acquire() as conn:
                await conn.execute(
                    "UPDATE scheduled_messages SET next_run=$1 WHERE id=$2",
                    next_run, row["id"])

    @send_scheduled.before_loop
    async def before_send(self):
        await self.bot.wait_until_ready()

    schedule = app_commands.Group(name="schedule", description="Scheduled messages")

    @schedule.command(name="add", description="Add a scheduled message")
    @app_commands.describe(channel="Channel", interval="Interval e.g. 1h, 30m, 1d", message="Message to send")
    @app_commands.default_permissions(manage_guild=True)
    async def schedule_add(self, interaction: discord.Interaction,
                            channel: discord.TextChannel, interval: str, message: str):
        from utils.helpers import parse_duration
        seconds = parse_duration(interval)
        next_run = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO scheduled_messages(guild_id,channel_id,message,interval_seconds,next_run)
                VALUES($1,$2,$3,$4,$5) RETURNING id
            """, interaction.guild.id, channel.id, message, seconds, next_run)
        await interaction.response.send_message(
            f"✅ Scheduled message #{row['id']} set — will post in {channel.mention} every **{interval}**")

    @schedule.command(name="list", description="List scheduled messages")
    @app_commands.default_permissions(manage_guild=True)
    async def schedule_list(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM scheduled_messages WHERE guild_id=$1", interaction.guild.id)
        if not rows:
            return await interaction.response.send_message("No scheduled messages.")
        embed = discord.Embed(title="📅 Scheduled Messages", color=discord.Color.blurple())
        for r in rows:
            ch = interaction.guild.get_channel(r["channel_id"])
            every = f"{r['interval_seconds']//60}m" if r['interval_seconds'] < 3600 else f"{r['interval_seconds']//3600}h"
            embed.add_field(
                name=f"#{r['id']} — {'✅' if r['enabled'] else '❌'} every {every}",
                value=f"Channel: {ch.mention if ch else r['channel_id']}\nMessage: {r['message'][:80]}",
                inline=False)
        await interaction.response.send_message(embed=embed)

    @schedule.command(name="delete", description="Delete a scheduled message")
    @app_commands.default_permissions(manage_guild=True)
    async def schedule_delete(self, interaction: discord.Interaction, id: int):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "DELETE FROM scheduled_messages WHERE id=$1 AND guild_id=$2",
                id, interaction.guild.id)
        await interaction.response.send_message(f"✅ Deleted scheduled message #{id}")

    @schedule.command(name="toggle", description="Enable or disable a scheduled message")
    @app_commands.default_permissions(manage_guild=True)
    async def schedule_toggle(self, interaction: discord.Interaction, id: int):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE scheduled_messages SET enabled=NOT enabled WHERE id=$1 AND guild_id=$2 RETURNING enabled",
                id, interaction.guild.id)
        if row:
            await interaction.response.send_message(
                f"{'✅ Enabled' if row['enabled'] else '❌ Disabled'} scheduled message #{id}")
        else:
            await interaction.response.send_message("❌ Not found.")


async def setup(bot):
    await bot.add_cog(Scheduled(bot))
