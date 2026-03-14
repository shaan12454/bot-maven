import discord
import re


def parse_duration(duration: str) -> int:
    """Convert duration string like '10m', '2h', '1d' to seconds."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    match = re.fullmatch(r"(\d+)([smhd]?)", duration.strip().lower())
    if not match:
        return 600  # default 10 minutes
    value, unit = int(match.group(1)), match.group(2) or "s"
    return value * units.get(unit, 1)


async def log_action(bot, guild: discord.Guild, action: str,
                     target: discord.Member, moderator: discord.Member,
                     reason: str = None):
    """Send a moderation log entry to the mod-log channel."""
    async with bot.db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT mod_log_channel FROM guild_config WHERE guild_id=$1", guild.id)
    if not row or not row["mod_log_channel"]:
        return
    channel = guild.get_channel(row["mod_log_channel"])
    if not channel:
        return

    colors = {
        "ban": discord.Color.red(),
        "kick": discord.Color.orange(),
        "mute": discord.Color.yellow(),
        "warn": discord.Color.gold(),
        "unban": discord.Color.green(),
    }
    icons = {
        "ban": "🔨", "kick": "👢", "mute": "🔇",
        "warn": "⚠️", "unban": "✅",
    }
    embed = discord.Embed(
        title=f"{icons.get(action, '⚙️')} {action.capitalize()}",
        color=colors.get(action, discord.Color.blurple()))
    embed.add_field(name="Member", value=f"{target.mention} (`{target.id}`)")
    embed.add_field(name="Moderator", value=moderator.mention)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.timestamp = discord.utils.utcnow()
    await channel.send(embed=embed)
