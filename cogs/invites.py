import discord
from discord.ext import commands
from discord import app_commands


class Invites(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._invite_cache: dict[int, dict[str, int]] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                invites = await guild.invites()
                self._invite_cache[guild.id] = {inv.code: inv.uses for inv in invites}
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        if invite.guild:
            cache = self._invite_cache.setdefault(invite.guild.id, {})
            cache[invite.code] = invite.uses or 0

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.bot.cache_user(member)
        try:
            new_invites = await member.guild.invites()
        except Exception:
            return

        old_cache = self._invite_cache.get(member.guild.id, {})
        used_invite = None
        for inv in new_invites:
            if old_cache.get(inv.code, 0) < (inv.uses or 0):
                used_invite = inv
                break

        self._invite_cache[member.guild.id] = {inv.code: inv.uses for inv in new_invites}

        if used_invite and used_invite.inviter:
            inviter = used_invite.inviter
            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO invite_tracker(guild_id, invite_code, inviter_id, inviter_name, uses)
                    VALUES($1,$2,$3,$4,1)
                    ON CONFLICT (guild_id, invite_code) DO UPDATE SET uses=invite_tracker.uses+1
                """, member.guild.id, used_invite.code, inviter.id, str(inviter))
                await conn.execute("""
                    INSERT INTO invite_joins(guild_id, user_id, username, inviter_id, inviter_name, invite_code)
                    VALUES($1,$2,$3,$4,$5,$6)
                """, member.guild.id, member.id, str(member), inviter.id, str(inviter), used_invite.code)

    @app_commands.command(name="invites", description="Check invite stats for a user")
    async def invites(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        async with self.bot.db.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COALESCE(SUM(uses),0) FROM invite_tracker WHERE guild_id=$1 AND inviter_id=$2",
                interaction.guild.id, member.id)
            recent = await conn.fetch(
                "SELECT username, joined_at FROM invite_joins WHERE guild_id=$1 AND inviter_id=$2 ORDER BY joined_at DESC LIMIT 5",
                interaction.guild.id, member.id)

        embed = discord.Embed(title=f"📨 Invites for {member}", color=discord.Color.green())
        embed.add_field(name="Total Invites", value=str(total))
        if recent:
            embed.add_field(
                name="Recent Invites",
                value="\n".join(f"• {r['username']} ({r['joined_at'].strftime('%Y-%m-%d')})" for r in recent),
                inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="inviteboard", description="Top inviters leaderboard")
    async def inviteboard(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("""
                SELECT inviter_id, inviter_name, SUM(uses) as total
                FROM invite_tracker WHERE guild_id=$1
                GROUP BY inviter_id, inviter_name
                ORDER BY total DESC LIMIT 10
            """, interaction.guild.id)

        embed = discord.Embed(title="🏆 Invite Leaderboard", color=discord.Color.gold())
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            prefix = medals[i] if i < 3 else f"#{i+1}"
            embed.add_field(
                name=f"{prefix} {row['inviter_name']}",
                value=f"{row['total']} invites",
                inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Invites(bot))
