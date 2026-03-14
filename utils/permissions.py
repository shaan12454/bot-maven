import discord

async def is_bot_admin(bot, guild: discord.Guild, user: discord.Member) -> bool:
    """Returns True if the user is a guild owner, has the admin role, or is in bot_admins table."""
    if user.id == guild.owner_id:
        return True
    try:
        async with bot.db.acquire() as conn:
            cfg = await conn.fetchrow("SELECT bot_admin_role FROM guild_config WHERE guild_id=$1", guild.id)
            if cfg and cfg["bot_admin_role"]:
                role = guild.get_role(cfg["bot_admin_role"])
                if role and role in user.roles:
                    return True
            row = await conn.fetchrow("SELECT 1 FROM bot_admins WHERE guild_id=$1 AND user_id=$2", guild.id, user.id)
            return row is not None
    except Exception:
        return False
