"""
api.py — Teen Maven Ranks Bot REST API
"""
from aiohttp import web
import asyncpg
import os
import json
import hmac
import discord
import logging
from functools import wraps
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
DB_URL = os.getenv("DATABASE_URL")
API_SECRET = os.getenv("API_SECRET", "changeme")


def require_auth(handler):
    @wraps(handler)
    async def wrapper(request, *args, **kwargs):
        token = request.headers.get("X-API-Key", "")
        if not hmac.compare_digest(token, API_SECRET):
            return web.json_response({"error": "Unauthorized"}, status=401)
        return await handler(request, *args, **kwargs)
    return wrapper


def json_resp(data, status=200):
    return web.Response(text=json.dumps(data, default=str), content_type="application/json", status=status)


async def _get_channel(bot, channel_id: int):
    try:
        return bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    except Exception as e:
        logger.error(f"Could not get channel {channel_id}: {e}")
        return None


@require_auth
async def get_guild_config(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM guild_config WHERE guild_id=$1", guild_id)
    return json_resp(dict(row) if row else {"guild_id": guild_id})


@require_auth
async def update_guild_config(request):
    guild_id = int(request.match_info["guild_id"])
    body = await request.json()
    allowed = [
        "prefix", "welcome_channel", "welcome_message", "welcome_image",
        "goodbye_channel", "goodbye_message", "log_channel", "mod_log_channel",
        "auto_role", "mute_role", "language", "modules", "automod", "leveling",
        "warn_thresholds", "starboard_channel", "starboard_threshold", "bot_admin_role"
    ]
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return json_resp({"error": "No valid fields"}, status=400)
    for k in ["automod", "leveling", "modules", "warn_thresholds"]:
        if k in updates and isinstance(updates[k], dict):
            updates[k] = json.dumps(updates[k])
    sets = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    async with request.app["db"].acquire() as conn:
        await conn.execute("INSERT INTO guild_config(guild_id) VALUES($1) ON CONFLICT (guild_id) DO NOTHING", guild_id)
        await conn.execute(f"UPDATE guild_config SET {sets} WHERE guild_id=$1", guild_id, *updates.values())
    return json_resp({"success": True})


@require_auth
async def get_members_leaderboard(request):
    guild_id = int(request.match_info["guild_id"])
    limit = int(request.rel_url.query.get("limit", 20))
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("""
            SELECT m.user_id,
                   COALESCE(m.display_name, m.username, u.username, CAST(m.user_id AS TEXT)) as display_name,
                   COALESCE(m.username, u.username) as username,
                   COALESCE(m.avatar_url, u.avatar_url) as avatar_url,
                   m.xp, m.level, m.rep, m.credits
            FROM members m
            LEFT JOIN user_cache u ON u.user_id = m.user_id
            WHERE m.guild_id=$1 ORDER BY m.xp DESC LIMIT $2
        """, guild_id, limit)
    return json_resp([dict(r) for r in rows])


@require_auth
async def get_member(request):
    guild_id = int(request.match_info["guild_id"])
    user_id = int(request.match_info["user_id"])
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("""
            SELECT m.*, COALESCE(m.display_name, u.display_name, CAST(m.user_id AS TEXT)) as display_name,
                   COALESCE(m.username, u.username) as username
            FROM members m
            LEFT JOIN user_cache u ON u.user_id = m.user_id
            WHERE m.guild_id=$1 AND m.user_id=$2
        """, guild_id, user_id)
    return json_resp(dict(row) if row else {})


@require_auth
async def get_warnings(request):
    guild_id = int(request.match_info["guild_id"])
    user_id = request.rel_url.query.get("user_id")
    async with request.app["db"].acquire() as conn:
        if user_id:
            rows = await conn.fetch(
                "SELECT * FROM warnings WHERE guild_id=$1 AND user_id=$2 ORDER BY created_at DESC",
                guild_id, int(user_id))
        else:
            rows = await conn.fetch(
                "SELECT * FROM warnings WHERE guild_id=$1 ORDER BY created_at DESC LIMIT 50", guild_id)
    return json_resp([dict(r) for r in rows])


@require_auth
async def delete_warning(request):
    warning_id = int(request.match_info["warning_id"])
    async with request.app["db"].acquire() as conn:
        await conn.execute("DELETE FROM warnings WHERE id=$1", warning_id)
    return json_resp({"success": True})


@require_auth
async def get_mod_actions(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM mod_actions WHERE guild_id=$1 ORDER BY created_at DESC LIMIT 50", guild_id)
    return json_resp([dict(r) for r in rows])


@require_auth
async def get_reaction_roles(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("SELECT * FROM reaction_roles WHERE guild_id=$1", guild_id)
        btn_rows = await conn.fetch("SELECT * FROM button_roles WHERE guild_id=$1", guild_id)
    return json_resp({"reaction": [dict(r) for r in rows], "button": [dict(r) for r in btn_rows]})


@require_auth
async def get_custom_commands(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("SELECT * FROM custom_commands WHERE guild_id=$1", guild_id)
    return json_resp([dict(r) for r in rows])


@require_auth
async def upsert_custom_command(request):
    guild_id = int(request.match_info["guild_id"])
    body = await request.json()
    name = body.get("name", "").lower()
    response = body.get("response", "")
    if not name or not response:
        return json_resp({"error": "name and response required"}, status=400)
    async with request.app["db"].acquire() as conn:
        await conn.execute(
            "INSERT INTO custom_commands(guild_id,name,response) VALUES($1,$2,$3) ON CONFLICT (guild_id,name) DO UPDATE SET response=$3",
            guild_id, name, response)
    return json_resp({"success": True})


@require_auth
async def delete_custom_command(request):
    guild_id = int(request.match_info["guild_id"])
    name = request.match_info["name"]
    async with request.app["db"].acquire() as conn:
        await conn.execute("DELETE FROM custom_commands WHERE guild_id=$1 AND name=$2", guild_id, name)
    return json_resp({"success": True})


@require_auth
async def get_level_roles(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("SELECT * FROM level_roles WHERE guild_id=$1 ORDER BY level", guild_id)
    return json_resp([dict(r) for r in rows])


@require_auth
async def upsert_level_role(request):
    guild_id = int(request.match_info["guild_id"])
    body = await request.json()
    async with request.app["db"].acquire() as conn:
        await conn.execute(
            "INSERT INTO level_roles(guild_id,level,role_id,role_name) VALUES($1,$2,$3,$4) ON CONFLICT (guild_id,level) DO UPDATE SET role_id=$3, role_name=$4",
            guild_id, int(body["level"]), int(body["role_id"]), body.get("role_name", ""))
    return json_resp({"success": True})


@require_auth
async def delete_level_role(request):
    guild_id = int(request.match_info["guild_id"])
    level = int(request.match_info["level"])
    async with request.app["db"].acquire() as conn:
        await conn.execute("DELETE FROM level_roles WHERE guild_id=$1 AND level=$2", guild_id, level)
    return json_resp({"success": True})


@require_auth
async def get_scheduled(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("SELECT * FROM scheduled_messages WHERE guild_id=$1", guild_id)
    return json_resp([dict(r) for r in rows])


@require_auth
async def add_scheduled(request):
    guild_id = int(request.match_info["guild_id"])
    body = await request.json()
    channel_id = int(body["channel_id"])
    interval = int(body["interval_seconds"])
    next_run = datetime.now(timezone.utc) + timedelta(seconds=interval)
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO scheduled_messages(guild_id,channel_id,message,interval_seconds,next_run)
            VALUES($1,$2,$3,$4,$5) RETURNING id
        """, guild_id, channel_id, body["message"], interval, next_run)
    return json_resp({"success": True, "id": row["id"]})


@require_auth
async def delete_scheduled(request):
    guild_id = int(request.match_info["guild_id"])
    msg_id = int(request.match_info["id"])
    async with request.app["db"].acquire() as conn:
        await conn.execute("DELETE FROM scheduled_messages WHERE id=$1 AND guild_id=$2", msg_id, guild_id)
    return json_resp({"success": True})


@require_auth
async def toggle_scheduled(request):
    guild_id = int(request.match_info["guild_id"])
    msg_id = int(request.match_info["id"])
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE scheduled_messages SET enabled=NOT enabled WHERE id=$1 AND guild_id=$2 RETURNING enabled",
            msg_id, guild_id)
    return json_resp({"enabled": row["enabled"] if row else False})


@require_auth
async def get_invites(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("""
            SELECT inviter_id, inviter_name, SUM(uses) as total
            FROM invite_tracker WHERE guild_id=$1
            GROUP BY inviter_id, inviter_name ORDER BY total DESC LIMIT 20
        """, guild_id)
    return json_resp([dict(r) for r in rows])


async def health(request):
    return json_resp({"status": "ok", "bot": "Teen Maven Ranks"})


@require_auth
async def get_analytics(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        total_members = await conn.fetchval("SELECT COUNT(*) FROM members WHERE guild_id=$1", guild_id)
        total_warnings = await conn.fetchval("SELECT COUNT(*) FROM warnings WHERE guild_id=$1", guild_id)
        total_mod_actions = await conn.fetchval("SELECT COUNT(*) FROM mod_actions WHERE guild_id=$1", guild_id)
        top_user = await conn.fetchrow(
            "SELECT username, display_name, xp, level FROM members WHERE guild_id=$1 ORDER BY xp DESC LIMIT 1", guild_id)
        recent_joins = await conn.fetchval(
            "SELECT COUNT(*) FROM invite_joins WHERE guild_id=$1 AND joined_at > NOW() - INTERVAL '7 days'", guild_id)
    return json_resp({
        "total_members": total_members or 0,
        "total_warnings": total_warnings or 0,
        "total_mod_actions": total_mod_actions or 0,
        "top_user": dict(top_user) if top_user else None,
        "recent_joins_7d": recent_joins or 0,
    })


@require_auth
async def get_guild_stats(request):
    guild_id = int(request.match_info["guild_id"])
    bot = request.app.get("bot")
    discord_member_count = None
    if bot:
        guild = bot.get_guild(guild_id)
        if guild:
            discord_member_count = guild.member_count
    async with request.app["db"].acquire() as conn:
        db_members = await conn.fetchval("SELECT COUNT(*) FROM members WHERE guild_id=$1", guild_id)
        total_warnings = await conn.fetchval("SELECT COUNT(*) FROM warnings WHERE guild_id=$1", guild_id)
        total_mod_actions = await conn.fetchval("SELECT COUNT(*) FROM mod_actions WHERE guild_id=$1", guild_id)
        recent_joins = await conn.fetchval(
            "SELECT COUNT(*) FROM invite_joins WHERE guild_id=$1 AND joined_at > NOW() - INTERVAL '7 days'", guild_id)
        top_user = await conn.fetchrow(
            "SELECT display_name, username, xp, level FROM members WHERE guild_id=$1 ORDER BY xp DESC LIMIT 1", guild_id)
        cache = await conn.fetchrow(
            "SELECT roles, channels, members, updated_at FROM guild_cache WHERE guild_id=$1", guild_id)
    return json_resp({
        "total_members": discord_member_count or db_members or 0,
        "total_warnings": total_warnings or 0,
        "total_mod_actions": total_mod_actions or 0,
        "recent_joins_7d": recent_joins or 0,
        "top_user": dict(top_user) if top_user else None,
        "cache": {
            "roles": json.loads(cache["roles"]) if cache and cache["roles"] else [],
            "channels": json.loads(cache["channels"]) if cache and cache["channels"] else [],
            "members": json.loads(cache["members"]) if cache and cache["members"] else [],
            "updated_at": str(cache["updated_at"]) if cache and cache["updated_at"] else None,
        },
    })


async def login(request):
    try:
        data = await request.json()
    except Exception:
        return json_resp({"error": "Invalid JSON"}, status=400)
    password = data.get("password")
    if not password:
        return json_resp({"error": "Password required"}, status=400)
    if hmac.compare_digest(password, API_SECRET):
        return json_resp({"success": True})
    return json_resp({"error": "Unauthorized"}, status=401)


@require_auth
async def get_guild_cache(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM guild_cache WHERE guild_id=$1", guild_id)
    if not row:
        return json_resp({"roles": [], "channels": [], "members": [], "updated_at": None})
    return json_resp({
        "roles": json.loads(row["roles"]),
        "channels": json.loads(row["channels"]),
        "members": json.loads(row["members"]),
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None
    })


@require_auth
async def refresh_guild_cache(request):
    guild_id = int(request.match_info["guild_id"])
    bot = request.app.get("bot")
    success_live = False
    if bot:
        guild = bot.get_guild(guild_id)
        if guild:
            cog = bot.get_cog("GuildSync")
            if cog:
                await cog.sync_guild(guild)
                success_live = True
    if not success_live:
        async with request.app["db"].acquire() as conn:
            await conn.execute(
                "UPDATE guild_cache SET updated_at = NOW() - interval '1 hour' WHERE guild_id=$1", guild_id)
    return json_resp({"success": True, "live": success_live})


@require_auth
async def get_admins(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("""
            SELECT b.user_id, u.username, u.display_name, u.avatar_url
            FROM bot_admins b
            LEFT JOIN user_cache u ON b.user_id = u.user_id
            WHERE b.guild_id=$1
        """, guild_id)
        cfg = await conn.fetchrow("SELECT bot_admin_role FROM guild_config WHERE guild_id=$1", guild_id)
    return json_resp({
        "admins": [dict(r) for r in rows],
        "bot_admin_role": str(cfg["bot_admin_role"]) if cfg and cfg["bot_admin_role"] else None
    })


@require_auth
async def add_admin(request):
    guild_id = int(request.match_info["guild_id"])
    data = await request.json()
    user_id = int(data.get("user_id"))
    async with request.app["db"].acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_admins (guild_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            guild_id, user_id)
    return json_resp({"success": True})


@require_auth
async def remove_admin(request):
    guild_id = int(request.match_info["guild_id"])
    user_id = int(request.match_info["user_id"])
    async with request.app["db"].acquire() as conn:
        await conn.execute("DELETE FROM bot_admins WHERE guild_id=$1 AND user_id=$2", guild_id, user_id)
    return json_resp({"success": True})


@require_auth
async def get_giveaways(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("SELECT * FROM giveaways WHERE guild_id=$1 ORDER BY created_at DESC", guild_id)
    return json_resp([dict(r) for r in rows])


@require_auth
async def create_giveaway(request):
    guild_id = int(request.match_info["guild_id"])
    data = await request.json()
    bot = request.app.get("bot")
    channel_id = int(data["channel_id"])
    prize = data["prize"]
    winner_count = int(data["winner_count"])
    duration = int(data["duration_seconds"])
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO giveaways (guild_id, channel_id, prize, winner_count, ends_at)
            VALUES ($1, $2, $3, $4, NOW() + interval '1 second' * $5)
            RETURNING id, ends_at
        """, guild_id, channel_id, prize, winner_count, duration)
    if bot:
        channel = await _get_channel(bot, channel_id)
        if channel:
            ends_at = row["ends_at"]
            embed = discord.Embed(title="🎉 GIVEAWAY 🎉", description=f"**{prize}**", color=discord.Color.gold())
            embed.add_field(name="Winners", value=str(winner_count))
            embed.add_field(name="Ends", value=f"<t:{int(ends_at.timestamp())}:R>")
            embed.set_footer(text="React with 🎉 to enter!")
            try:
                msg = await channel.send(embed=embed)
                await msg.add_reaction("🎉")
                async with request.app["db"].acquire() as conn:
                    await conn.execute("UPDATE giveaways SET message_id=$1 WHERE id=$2", msg.id, row["id"])
                logger.info(f"Giveaway sent to channel {channel_id}")
            except Exception as e:
                logger.error(f"Giveaway send error: {e}")
        else:
            logger.error(f"Could not find channel {channel_id} for giveaway")
    return json_resp({"success": True})


@require_auth
async def end_giveaway(request):
    giveaway_id = int(request.match_info["id"])
    async with request.app["db"].acquire() as conn:
        await conn.execute("UPDATE giveaways SET ends_at = NOW() WHERE id=$1", giveaway_id)
    return json_resp({"success": True})


@require_auth
async def reroll_giveaway(request):
    return json_resp({"success": True})


@require_auth
async def get_polls(request):
    guild_id = int(request.match_info["guild_id"])
    async with request.app["db"].acquire() as conn:
        rows = await conn.fetch("SELECT * FROM polls WHERE guild_id=$1 ORDER BY created_at DESC", guild_id)
    return json_resp([{**dict(r), "options": json.loads(r["options"]), "votes": json.loads(r["votes"])} for r in rows])


@require_auth
async def create_poll(request):
    guild_id = int(request.match_info["guild_id"])
    data = await request.json()
    bot = request.app.get("bot")
    channel_id = int(data["channel_id"])
    question = data["question"]
    options = data["options"]
    duration = int(data["duration_seconds"])
    async with request.app["db"].acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO polls (guild_id, channel_id, question, options, ends_at)
            VALUES ($1, $2, $3, $4, NOW() + interval '1 second' * $5)
            RETURNING id, ends_at
        """, guild_id, channel_id, question, json.dumps(options), duration)
    if bot:
        channel = await _get_channel(bot, channel_id)
        if channel:
            emojis = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
            embed = discord.Embed(title=f"📊 {question}", color=discord.Color.blurple())
            embed.description = "\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(options[:10]))
            embed.set_footer(text=f"Poll ID: {row['id']} • React to vote!")
            try:
                msg = await channel.send(embed=embed)
                for i in range(min(len(options), 10)):
                    await msg.add_reaction(emojis[i])
                async with request.app["db"].acquire() as conn:
                    await conn.execute("UPDATE polls SET message_id=$1 WHERE id=$2", msg.id, row["id"])
                logger.info(f"Poll sent to channel {channel_id}")
            except Exception as e:
                logger.error(f"Poll send error: {e}")
        else:
            logger.error(f"Could not find channel {channel_id} for poll")
    return json_resp({"success": True})


@require_auth
async def send_embed(request):
    guild_id = int(request.match_info["guild_id"])
    data = await request.json()
    async with request.app["db"].acquire() as conn:
        await conn.execute("""
            INSERT INTO pending_embeds (guild_id, channel_id, title, description, color, footer, image_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, guild_id, int(data["channel_id"]), data.get("title", ""), data.get("description", ""),
            data.get("color"), data.get("footer"), data.get("image_url"))
    return json_resp({"success": True})


async def create_app(bot_instance=None):
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app["bot"] = bot_instance
    app["db"] = await asyncpg.create_pool(DB_URL)

    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            resp = web.Response()
        else:
            try:
                resp = await handler(request)
            except Exception as e:
                logger.error(f"API unhandled error: {e}")
                resp = json_resp({"error": str(e)}, status=500)
        resp.headers["Access-Control-Allow-Origin"] = os.getenv("DASHBOARD_ORIGIN", "*")
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type,X-API-Key"
        return resp

    app.middlewares.append(cors_middleware)

    app.router.add_get("/health", health)
    app.router.add_get("/api/guilds/{guild_id}/config", get_guild_config)
    app.router.add_post("/api/guilds/{guild_id}/config", update_guild_config)
    app.router.add_get("/api/guilds/{guild_id}/leaderboard", get_members_leaderboard)
    app.router.add_get("/api/guilds/{guild_id}/members/{user_id}", get_member)
    app.router.add_get("/api/guilds/{guild_id}/warnings", get_warnings)
    app.router.add_delete("/api/warnings/{warning_id}", delete_warning)
    app.router.add_get("/api/guilds/{guild_id}/mod-actions", get_mod_actions)
    app.router.add_get("/api/guilds/{guild_id}/reaction-roles", get_reaction_roles)
    app.router.add_get("/api/guilds/{guild_id}/level-roles", get_level_roles)
    app.router.add_post("/api/guilds/{guild_id}/level-roles", upsert_level_role)
    app.router.add_delete("/api/guilds/{guild_id}/level-roles/{level}", delete_level_role)
    app.router.add_get("/api/guilds/{guild_id}/custom-commands", get_custom_commands)
    app.router.add_post("/api/guilds/{guild_id}/custom-commands", upsert_custom_command)
    app.router.add_delete("/api/guilds/{guild_id}/custom-commands/{name}", delete_custom_command)
    app.router.add_get("/api/guilds/{guild_id}/scheduled", get_scheduled)
    app.router.add_post("/api/guilds/{guild_id}/scheduled", add_scheduled)
    app.router.add_delete("/api/guilds/{guild_id}/scheduled/{id}", delete_scheduled)
    app.router.add_post("/api/guilds/{guild_id}/scheduled/{id}/toggle", toggle_scheduled)
    app.router.add_get("/api/guilds/{guild_id}/invites", get_invites)
    app.router.add_get("/api/guilds/{guild_id}/analytics", get_analytics)
    app.router.add_get("/api/guilds/{guild_id}/stats", get_guild_stats)
    app.router.add_post("/api/auth/login", login)
    app.router.add_get("/api/guilds/{guild_id}/cache", get_guild_cache)
    app.router.add_post("/api/guilds/{guild_id}/cache/refresh", refresh_guild_cache)
    app.router.add_get("/api/guilds/{guild_id}/admins", get_admins)
    app.router.add_post("/api/guilds/{guild_id}/admins", add_admin)
    app.router.add_delete("/api/guilds/{guild_id}/admins/{user_id}", remove_admin)
    app.router.add_get("/api/guilds/{guild_id}/giveaways", get_giveaways)
    app.router.add_post("/api/guilds/{guild_id}/giveaways", create_giveaway)
    app.router.add_post("/api/guilds/{guild_id}/giveaways/{id}/end", end_giveaway)
    app.router.add_post("/api/guilds/{guild_id}/giveaways/{id}/reroll", reroll_giveaway)
    app.router.add_get("/api/guilds/{guild_id}/polls", get_polls)
    app.router.add_post("/api/guilds/{guild_id}/polls", create_poll)
    app.router.add_post("/api/guilds/{guild_id}/send-embed", send_embed)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    web.run_app(create_app(), port=port)
