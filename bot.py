import discord
from discord.ext import commands
import os
import asyncpg
import aiohttp
import asyncio
import logging
from dotenv import load_dotenv


sdfsd
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COGS = [
    "cogs.moderation",
    "cogs.leveling",
    "cogs.welcome",
    "cogs.logging",
    "cogs.reaction_roles",
    "cogs.custom_commands",
    "cogs.fun",
    "cogs.utility",
    "cogs.scheduled",
    "cogs.invites",
    "cogs.admin_control",
    "cogs.guild_sync",
    "cogs.giveaways",
    "cogs.polls",
    "cogs.starboard",
]

class TeenMavenBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix=self.get_prefix, intents=intents, help_command=None)
        self.db: asyncpg.Pool = None
        self.session: aiohttp.ClientSession = None
        self.api_secret = os.getenv("API_SECRET", "changeme")

    async def get_prefix(self, message):
        if not message.guild:
            return "!"
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow("SELECT prefix FROM guild_config WHERE guild_id=$1", message.guild.id)
            return row["prefix"] if row and row["prefix"] else "!"
        except Exception:
            return "!"

    async def setup_hook(self):
        self.db = await asyncpg.create_pool(os.getenv("DATABASE_URL"))
        self.session = aiohttp.ClientSession()
        await self._create_tables()
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info(f"Loaded {cog}")
            except Exception as e:
                logger.error(f"Failed to load {cog}: {e}")
        asyncio.create_task(self._check_pending_embeds())
        await self.tree.sync()
        logger.info("Slash commands synced")

    async def _create_tables(self):
        async with self.db.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id BIGINT PRIMARY KEY,
                    prefix TEXT DEFAULT '!',
                    welcome_channel BIGINT,
                    welcome_message TEXT,
                    welcome_image BOOLEAN DEFAULT TRUE,
                    goodbye_channel BIGINT,
                    goodbye_message TEXT,
                    log_channel BIGINT,
                    mod_log_channel BIGINT,
                    auto_role BIGINT,
                    mute_role BIGINT,
                    language TEXT DEFAULT 'en',
                    modules JSONB DEFAULT '{}'::jsonb,
                    automod JSONB DEFAULT '{}'::jsonb,
                    leveling JSONB DEFAULT '{}'::jsonb,
                    warn_thresholds JSONB DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS members (
                    guild_id BIGINT,
                    user_id BIGINT,
                    username TEXT,
                    display_name TEXT,
                    avatar_url TEXT,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 0,
                    credits INTEGER DEFAULT 0,
                    rep INTEGER DEFAULT 0,
                    last_message TIMESTAMPTZ,
                    last_rep TIMESTAMPTZ,
                    last_voice TIMESTAMPTZ,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_cache (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    display_name TEXT,
                    avatar_url TEXT,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    username TEXT,
                    moderator_id BIGINT,
                    moderator_name TEXT,
                    reason TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS reaction_roles (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    channel_id BIGINT,
                    message_id BIGINT,
                    emoji TEXT,
                    role_id BIGINT,
                    role_name TEXT,
                    type TEXT DEFAULT 'reaction'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS button_roles (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    channel_id BIGINT,
                    message_id BIGINT,
                    role_id BIGINT,
                    role_name TEXT,
                    label TEXT,
                    style TEXT DEFAULT 'primary'
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS custom_commands (
                    guild_id BIGINT,
                    name TEXT,
                    response TEXT,
                    embed JSONB,
                    PRIMARY KEY (guild_id, name)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS level_roles (
                    guild_id BIGINT,
                    level INTEGER,
                    role_id BIGINT,
                    role_name TEXT,
                    PRIMARY KEY (guild_id, level)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS mod_actions (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    username TEXT,
                    moderator_id BIGINT,
                    moderator_name TEXT,
                    action TEXT,
                    reason TEXT,
                    duration INTEGER,
                    expires_at TIMESTAMPTZ,
                    active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    channel_id BIGINT,
                    message TEXT,
                    interval_seconds INTEGER,
                    next_run TIMESTAMPTZ,
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS invite_tracker (
                    guild_id BIGINT,
                    invite_code TEXT,
                    inviter_id BIGINT,
                    inviter_name TEXT,
                    uses INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, invite_code)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS invite_joins (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    username TEXT,
                    inviter_id BIGINT,
                    inviter_name TEXT,
                    invite_code TEXT,
                    joined_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bot_admins (
                    guild_id BIGINT,
                    user_id BIGINT,
                    added_by BIGINT,
                    added_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    channel_id BIGINT,
                    message_id BIGINT,
                    host_id BIGINT,
                    prize TEXT,
                    winner_count INTEGER DEFAULT 1,
                    ends_at TIMESTAMPTZ,
                    ended BOOLEAN DEFAULT FALSE,
                    winners JSONB DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS polls (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    channel_id BIGINT,
                    message_id BIGINT,
                    question TEXT,
                    options JSONB,
                    votes JSONB DEFAULT '{}'::jsonb,
                    ends_at TIMESTAMPTZ,
                    ended BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS starboard_entries (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    original_message_id BIGINT UNIQUE,
                    starboard_message_id BIGINT,
                    channel_id BIGINT,
                    author_id BIGINT,
                    star_count INTEGER DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_cache (
                    guild_id BIGINT PRIMARY KEY,
                    roles JSONB DEFAULT '[]'::jsonb,
                    channels JSONB DEFAULT '[]'::jsonb,
                    members JSONB DEFAULT '[]'::jsonb,
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_embeds (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    channel_id BIGINT,
                    title TEXT,
                    description TEXT,
                    color TEXT DEFAULT '5865F2',
                    footer TEXT,
                    image_url TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='guild_config' AND column_name='starboard_channel') THEN
                        ALTER TABLE guild_config ADD COLUMN starboard_channel BIGINT;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='guild_config' AND column_name='starboard_threshold') THEN
                        ALTER TABLE guild_config ADD COLUMN starboard_threshold INTEGER DEFAULT 3;
                    END IF;
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='guild_config' AND column_name='bot_admin_role') THEN
                        ALTER TABLE guild_config ADD COLUMN bot_admin_role BIGINT;
                    END IF;
                END $$
            """)

    async def _check_pending_embeds(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                async with self.db.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM pending_embeds ORDER BY created_at ASC LIMIT 10")
                    for row in rows:
                        try:
                            channel = self.get_channel(row["channel_id"]) or await self.fetch_channel(row["channel_id"])
                        except Exception:
                            channel = None
                        if channel:
                            try:
                                color_val = 0x5865F2
                                if row["color"]:
                                    color_val = int(row["color"].lstrip("#"), 16)
                                embed = discord.Embed(
                                    title=row["title"] or "",
                                    description=row["description"] or "",
                                    color=color_val)
                                if row["footer"]:
                                    embed.set_footer(text=row["footer"])
                                if row["image_url"]:
                                    embed.set_image(url=row["image_url"])
                                await channel.send(embed=embed)
                            except Exception as e:
                                logger.error(f"Embed send error: {e}")
                        await conn.execute("DELETE FROM pending_embeds WHERE id=$1", row["id"])
            except Exception as e:
                logger.error(f"Pending embeds error: {e}")
            await asyncio.sleep(5)

    async def get_username(self, user_id: int) -> str:
        try:
            async with self.db.acquire() as conn:
                row = await conn.fetchrow("SELECT username FROM user_cache WHERE user_id=$1", user_id)
            if row:
                return row["username"]
        except Exception:
            pass
        try:
            user = await self.fetch_user(user_id)
            return str(user)
        except Exception:
            return f"Unknown User ({user_id})"

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} ({self.user.id})")
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="pls help me im under the water 😭"))

    async def on_member_join(self, member: discord.Member):
        pass

    async def on_message(self, message: discord.Message):
        await self.process_commands(message)

    async def close(self):
        if self.session:
            await self.session.close()
        if self.db:
            await self.db.close()
        await super().close()


bot = TeenMavenBot()

if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))
