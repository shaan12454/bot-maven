import discord
from discord.ext import commands


class Logging(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _get_log_channel(self, guild_id):
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("SELECT log_channel FROM guild_config WHERE guild_id=$1", guild_id)
        if row and row["log_channel"]:
            guild = self.bot.get_guild(guild_id)
            return guild.get_channel(row["log_channel"]) if guild else None
        return None

    # ── Message Events ────────────────────────────────────
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        ch = await self._get_log_channel(message.guild.id)
        if not ch:
            return
        e = discord.Embed(title="🗑️ Message Deleted", color=discord.Color.red())
        e.add_field(name="Author", value=f"{message.author.mention} ({message.author.id})")
        e.add_field(name="Channel", value=message.channel.mention)
        e.add_field(name="Content", value=message.content[:1024] or "*empty*", inline=False)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        ch = await self._get_log_channel(before.guild.id)
        if not ch:
            return
        e = discord.Embed(title="✏️ Message Edited", color=discord.Color.orange())
        e.add_field(name="Author", value=before.author.mention)
        e.add_field(name="Channel", value=before.channel.mention)
        e.add_field(name="Before", value=before.content[:512] or "*empty*", inline=False)
        e.add_field(name="After", value=after.content[:512] or "*empty*", inline=False)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    # ── Member Events ─────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        ch = await self._get_log_channel(guild.id)
        if not ch:
            return
        e = discord.Embed(title="🔨 Member Banned", color=discord.Color.dark_red())
        e.add_field(name="User", value=f"{user} ({user.id})")
        e.set_thumbnail(url=user.display_avatar.url)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        ch = await self._get_log_channel(guild.id)
        if not ch:
            return
        e = discord.Embed(title="✅ Member Unbanned", color=discord.Color.green())
        e.add_field(name="User", value=f"{user} ({user.id})")
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        ch = await self._get_log_channel(before.guild.id)
        if not ch:
            return
        if before.nick != after.nick:
            e = discord.Embed(title="📝 Nickname Changed", color=discord.Color.blurple())
            e.add_field(name="Member", value=before.mention)
            e.add_field(name="Before", value=before.nick or "*none*")
            e.add_field(name="After", value=after.nick or "*none*")
            e.timestamp = discord.utils.utcnow()
            await ch.send(embed=e)
        if before.roles != after.roles:
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added or removed:
                e = discord.Embed(title="🎭 Roles Updated", color=discord.Color.purple())
                e.add_field(name="Member", value=before.mention)
                if added:
                    e.add_field(name="Added", value=" ".join(r.mention for r in added))
                if removed:
                    e.add_field(name="Removed", value=" ".join(r.mention for r in removed))
                e.timestamp = discord.utils.utcnow()
                await ch.send(embed=e)

    # ── Voice Events ──────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        ch = await self._get_log_channel(member.guild.id)
        if not ch:
            return
        if before.channel is None and after.channel:
            e = discord.Embed(title="🎙️ Joined Voice", color=discord.Color.green())
            e.add_field(name="Member", value=member.mention)
            e.add_field(name="Channel", value=after.channel.name)
        elif before.channel and after.channel is None:
            e = discord.Embed(title="🎙️ Left Voice", color=discord.Color.red())
            e.add_field(name="Member", value=member.mention)
            e.add_field(name="Channel", value=before.channel.name)
        elif before.channel != after.channel:
            e = discord.Embed(title="🎙️ Moved Voice", color=discord.Color.orange())
            e.add_field(name="Member", value=member.mention)
            e.add_field(name="From", value=before.channel.name)
            e.add_field(name="To", value=after.channel.name)
        else:
            return
        e.set_thumbnail(url=member.display_avatar.url)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    # ── Server Events ─────────────────────────────────────
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        ch = await self._get_log_channel(channel.guild.id)
        if not ch:
            return
        e = discord.Embed(title="📁 Channel Created", color=discord.Color.green())
        e.add_field(name="Name", value=channel.mention)
        e.add_field(name="Type", value=str(channel.type))
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        ch = await self._get_log_channel(channel.guild.id)
        if not ch:
            return
        e = discord.Embed(title="🗑️ Channel Deleted", color=discord.Color.red())
        e.add_field(name="Name", value=f"#{channel.name}")
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        ch = await self._get_log_channel(role.guild.id)
        if not ch:
            return
        e = discord.Embed(title="🎭 Role Created", color=role.color)
        e.add_field(name="Name", value=role.mention)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        ch = await self._get_log_channel(role.guild.id)
        if not ch:
            return
        e = discord.Embed(title="🎭 Role Deleted", color=discord.Color.red())
        e.add_field(name="Name", value=role.name)
        e.timestamp = discord.utils.utcnow()
        await ch.send(embed=e)


async def setup(bot):
    await bot.add_cog(Logging(bot))
