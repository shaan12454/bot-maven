import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from utils.helpers import log_action, parse_duration
from utils.permissions import is_bot_admin


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_mutes.start()

    def cog_unload(self):
        self.check_mutes.cancel()

    # ── Persistent mute checker ───────────────────────────
    @tasks.loop(seconds=30)
    async def check_mutes(self):
        """Re-apply mutes that survived a restart."""
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM mod_actions
                WHERE action='mute' AND active=TRUE AND expires_at IS NOT NULL AND expires_at > NOW()
            """)
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                continue
            member = guild.get_member(row["user_id"])
            if member and not member.is_timed_out():
                try:
                    await member.timeout(row["expires_at"], reason="Mute re-applied after restart")
                except Exception:
                    pass

    @check_mutes.before_loop
    async def before_check_mutes(self):
        await self.bot.wait_until_ready()

    # ── /ban ──────────────────────────────────────────────
    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.describe(member="The member to ban", reason="Reason for the ban", delete_days="Days of messages to delete (0-7)")
    async def ban(self, interaction: discord.Interaction, member: discord.Member,
                  reason: str = "No reason provided", delete_days: int = 0):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        if member == interaction.user:
            return await interaction.response.send_message("❌ You cannot ban yourself.", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ I cannot ban this member (role hierarchy).", ephemeral=True)
        try:
            try:
                await member.send(f"🔨 You have been **banned** from **{interaction.guild.name}**\nReason: {reason}")
            except Exception:
                pass
            await member.ban(reason=reason, delete_message_days=max(0, min(7, delete_days)))
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I lack permissions to ban this member.", ephemeral=True)
        await interaction.response.send_message(embed=self._mod_embed("🔨 Banned", member, reason, interaction.user))
        await log_action(self.bot, interaction.guild, "ban", member, interaction.user, reason)
        await self._record(interaction.guild.id, member, interaction.user, "ban", reason)

    # ── /kick ─────────────────────────────────────────────
    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.describe(member="The member to kick", reason="Reason for the kick")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        if member == interaction.user:
            return await interaction.response.send_message("❌ You cannot kick yourself.", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ I cannot kick this member (role hierarchy).", ephemeral=True)
        try:
            try:
                await member.send(f"👢 You have been **kicked** from **{interaction.guild.name}**\nReason: {reason}")
            except Exception:
                pass
            await member.kick(reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I lack permissions to kick this member.", ephemeral=True)
        await interaction.response.send_message(embed=self._mod_embed("👢 Kicked", member, reason, interaction.user))
        await log_action(self.bot, interaction.guild, "kick", member, interaction.user, reason)
        await self._record(interaction.guild.id, member, interaction.user, "kick", reason)

    # ── /mute ─────────────────────────────────────────────
    @app_commands.command(name="mute", description="Timeout a member (e.g. 10m, 2h, 1d)")
    @app_commands.describe(member="The member to mute", duration="Duration e.g. 10m, 2h, 1d (max 28d)", reason="Reason for the mute")
    async def mute(self, interaction: discord.Interaction, member: discord.Member,
                   duration: str = "10m", reason: str = "No reason provided"):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        if member == interaction.user:
            return await interaction.response.send_message("❌ You cannot mute yourself.", ephemeral=True)
        if member.top_role >= interaction.guild.me.top_role:
            return await interaction.response.send_message("❌ I cannot mute this member (role hierarchy).", ephemeral=True)
        seconds = parse_duration(duration)
        seconds = min(seconds, 28 * 24 * 3600)
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        try:
            await member.timeout(until, reason=reason)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I lack permissions to mute this member.", ephemeral=True)
        try:
            await member.send(f"🔇 You have been **muted** in **{interaction.guild.name}** for {duration}\nReason: {reason}")
        except Exception:
            pass
        await interaction.response.send_message(embed=self._mod_embed(f"🔇 Muted ({duration})", member, reason, interaction.user))
        await log_action(self.bot, interaction.guild, "mute", member, interaction.user, reason)
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO mod_actions(guild_id,user_id,username,moderator_id,moderator_name,action,reason,duration,expires_at,active)
                VALUES($1,$2,$3,$4,$5,'mute',$6,$7,$8,TRUE)
            """, interaction.guild.id, member.id, str(member), interaction.user.id, str(interaction.user),
                reason, seconds, until)

    # ── /unmute ───────────────────────────────────────────
    @app_commands.command(name="unmute", description="Remove timeout from a member")
    @app_commands.describe(member="The member to unmute")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        try:
            await member.timeout(None)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ I lack permissions to unmute this member.", ephemeral=True)
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                UPDATE mod_actions SET active=FALSE
                WHERE guild_id=$1 AND user_id=$2 AND action='mute' AND active=TRUE
            """, interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Unmuted {member.mention}")
        await log_action(self.bot, interaction.guild, "unmute", member, interaction.user, "Unmuted by moderator")

    # ── /warn ─────────────────────────────────────────────
    @app_commands.command(name="warn", description="Issue a warning to a member")
    @app_commands.describe(member="The member to warn", reason="Reason for the warning")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ You cannot warn bots.", ephemeral=True)
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO warnings(guild_id,user_id,username,moderator_id,moderator_name,reason) VALUES($1,$2,$3,$4,$5,$6)",
                interaction.guild.id, member.id, str(member), interaction.user.id, str(interaction.user), reason)
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM warnings WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, member.id)

        try:
            await member.send(
                f"⚠️ You have been **warned** in **{interaction.guild.name}**\n"
                f"Reason: {reason}\nTotal warnings: {count}"
            )
        except Exception:
            pass

        embed = self._mod_embed(f"⚠️ Warned (#{count})", member, reason, interaction.user)
        embed.set_footer(text=f"This member now has {count} warning(s).")
        await interaction.response.send_message(embed=embed)
        await log_action(self.bot, interaction.guild, "warn", member, interaction.user, reason)

    # ── /warnings ─────────────────────────────────────────
    @app_commands.command(name="warnings", description="View warnings for a member")
    @app_commands.describe(member="The member to check warnings for")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM warnings WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC LIMIT 10",
                interaction.guild.id, member.id)
        if not rows:
            return await interaction.response.send_message(f"✅ {member.mention} has no warnings.", ephemeral=True)
        embed = discord.Embed(title=f"⚠️ Warnings for {member}", color=discord.Color.orange())
        embed.set_thumbnail(url=member.display_avatar.url)
        for r in rows:
            embed.add_field(
                name=f"#{r['id']} — {r['created_at'].strftime('%Y-%m-%d %H:%M')}",
                value=f"**Reason:** {r['reason']}\n**By:** {r['moderator_name'] or r['moderator_id']}",
                inline=False)
        embed.set_footer(text=f"Showing up to 10 most recent warnings")
        await interaction.response.send_message(embed=embed)

    # ── /clearwarnings ────────────────────────────────────
    @app_commands.command(name="clearwarnings", description="Clear all warnings for a member")
    @app_commands.describe(member="The member to clear warnings for")
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        async with self.bot.db.acquire() as conn:
            deleted = await conn.fetchval(
                "SELECT COUNT(*) FROM warnings WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, member.id)
            await conn.execute("DELETE FROM warnings WHERE guild_id=$1 AND user_id=$2", interaction.guild.id, member.id)
        await interaction.response.send_message(f"✅ Cleared **{deleted}** warning(s) for {member.mention}")

    # ── /clear ────────────────────────────────────────────
    @app_commands.command(name="clear", description="Delete messages in the current channel")
    @app_commands.describe(amount="Number of messages to delete (1-100)", member="Only delete messages from this member")
    async def clear(self, interaction: discord.Interaction, amount: int = 10, member: discord.Member = None):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        amount = max(1, min(100, amount))
        await interaction.response.defer(ephemeral=True)
        def check(m): return member is None or m.author == member
        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(f"🗑️ Deleted {len(deleted)} message(s).", ephemeral=True)

    # ── /slowmode ─────────────────────────────────────────
    @app_commands.command(name="slowmode", description="Set slowmode on the current channel")
    @app_commands.describe(seconds="Slowmode delay in seconds (0 to disable, max 21600)")
    async def slowmode(self, interaction: discord.Interaction, seconds: int = 0):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        seconds = max(0, min(21600, seconds))
        await interaction.channel.edit(slowmode_delay=seconds)
        msg = f"⏱️ Slowmode set to **{seconds}s**" if seconds else "⏱️ Slowmode **disabled**"
        await interaction.response.send_message(msg)

    # ── /lock /unlock ─────────────────────────────────────
    @app_commands.command(name="lock", description="Lock the current channel")
    async def lock(self, interaction: discord.Interaction):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔒 Channel locked. Only staff can send messages.")

    @app_commands.command(name="unlock", description="Unlock the current channel")
    async def unlock(self, interaction: discord.Interaction):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        await interaction.response.send_message("🔓 Channel unlocked.")

    # ── /unban ────────────────────────────────────────────
    @app_commands.command(name="unban", description="Unban a user by their Discord ID")
    @app_commands.describe(user_id="The Discord user ID to unban", reason="Reason for the unban")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=reason)
            await interaction.response.send_message(f"✅ Unbanned **{user}**")
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        except discord.NotFound:
            await interaction.response.send_message("❌ That user is not banned.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I lack permissions to unban.", ephemeral=True)

    # ── helpers ───────────────────────────────────────────
    def _mod_embed(self, title, member, reason, mod):
        e = discord.Embed(title=title, color=discord.Color.red())
        e.add_field(name="Member", value=f"{member.mention}\n{member} ({member.id})")
        e.add_field(name="Reason", value=reason)
        e.add_field(name="Moderator", value=str(mod))
        e.set_thumbnail(url=member.display_avatar.url)
        e.timestamp = discord.utils.utcnow()
        return e

    async def _record(self, guild_id, member, mod, action, reason, duration=None):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO mod_actions(guild_id,user_id,username,moderator_id,moderator_name,action,reason,duration) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
                guild_id, member.id, str(member), mod.id, str(mod), action, reason, duration)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
