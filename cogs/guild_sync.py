import discord
from discord.ext import commands, tasks
import json
from datetime import datetime, timezone


class GuildSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cache_loop.start()

    def cog_unload(self):
        self.cache_loop.cancel()

    @tasks.loop(minutes=5)
    async def cache_loop(self):
        """Periodically cache guild data every 5 minutes."""
        for guild in self.bot.guilds:
            await self.sync_guild(guild)

    @cache_loop.before_loop
    async def before_cache_loop(self):
        await self.bot.wait_until_ready()
        # Initial sync on startup
        for guild in self.bot.guilds:
            await self.sync_guild(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.sync_guild(guild)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Sync member list when someone joins
        await self.sync_guild(member.guild)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await self.sync_guild(role.guild)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.sync_guild(role.guild)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.sync_guild(channel.guild)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.sync_guild(channel.guild)

    async def sync_guild(self, guild: discord.Guild):
        """Sync roles, channels, and members for a guild into the cache table."""
        try:
            # Roles — include color as hex string, exclude @everyone
            roles = [
                {
                    "id": str(r.id),
                    "name": r.name,
                    "color": str(r.color) if r.color.value else "0",
                    "position": r.position,
                    "mentionable": r.mentionable,
                    "hoist": r.hoist,
                }
                for r in sorted(guild.roles, key=lambda r: r.position, reverse=True)
                if r.name != "@everyone"
            ]

            # Channels — text and voice
            channels = []
            for c in sorted(guild.channels, key=lambda c: c.position):
                if isinstance(c, discord.TextChannel):
                    channels.append({
                        "id": str(c.id),
                        "name": c.name,
                        "type": "text",
                        "category": c.category.name if c.category else None,
                    })
                elif isinstance(c, discord.VoiceChannel):
                    channels.append({
                        "id": str(c.id),
                        "name": c.name,
                        "type": "voice",
                        "category": c.category.name if c.category else None,
                    })

            # Members — top 500 sorted by XP (from DB) or by join date
            sorted_members = sorted(
                [m for m in guild.members if not m.bot],
                key=lambda m: m.joined_at or datetime.now(timezone.utc)
            )
            members = [
                {
                    "id": str(m.id),
                    "username": str(m),
                    "display_name": m.display_name,
                    "avatar_url": str(m.display_avatar.url),
                    "roles": [str(r.id) for r in m.roles if r.name != "@everyone"],
                }
                for m in sorted_members[:500]
            ]

            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO guild_cache (guild_id, roles, channels, members, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (guild_id) DO UPDATE SET
                        roles = $2, channels = $3, members = $4, updated_at = NOW()
                """, guild.id, json.dumps(roles), json.dumps(channels), json.dumps(members))

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"guild_sync error for {guild.id}: {e}")


async def setup(bot):
    await bot.add_cog(GuildSync(bot))
