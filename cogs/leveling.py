import discord
from discord.ext import commands
from discord import app_commands
from discord.ext import tasks
import random
from datetime import datetime, timedelta, timezone
import json
import aiohttp
import io
from PIL import Image, ImageDraw, ImageFont

# ── XP config ─────────────────────────────────────────────────────────────────
XP_PER_MESSAGE = (15, 25)       # random range per message
XP_COOLDOWN_SECONDS = 60        # how often a user can earn XP from messages
VOICE_XP_PER_MINUTE = 5        # XP awarded per minute in a voice channel

# ── XP formula ────────────────────────────────────────────────────────────────
# xp_for_level(n) = total XP needed to reach level n FROM level n-1
# This uses the same formula in both bot and dashboard.
def xp_for_level(level: int) -> int:
    """XP required to go from level `level` to level `level+1`."""
    return 5 * (level ** 2) + 50 * level + 100

def get_level_from_xp(total_xp: int) -> int:
    """Compute the current level from total accumulated XP."""
    level = 0
    accumulated = 0
    while True:
        needed = xp_for_level(level)
        if accumulated + needed > total_xp:
            return level
        accumulated += needed
        level += 1

def xp_progress(total_xp: int):
    """Returns (level, xp_into_current_level, xp_needed_for_next_level)."""
    level = 0
    accumulated = 0
    while True:
        needed = xp_for_level(level)
        if accumulated + needed > total_xp:
            return level, total_xp - accumulated, needed
        accumulated += needed
        level += 1

def total_xp_for_level(target_level: int) -> int:
    """Total XP needed to reach a given level from 0."""
    return sum(xp_for_level(l) for l in range(target_level))


class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_xp_task.start()

    def cog_unload(self):
        self.voice_xp_task.cancel()

    def _parse_cfg(self, raw) -> dict:
        if not raw:
            return {}
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return dict(raw)

    # ── Voice XP task ─────────────────────────────────────
    @tasks.loop(minutes=1)
    async def voice_xp_task(self):
        for guild in self.bot.guilds:
            async with self.bot.db.acquire() as conn:
                cfg = await conn.fetchrow("SELECT leveling FROM guild_config WHERE guild_id=$1", guild.id)
            lvl_cfg = self._parse_cfg(cfg["leveling"] if cfg else {})
            if not lvl_cfg.get("enabled", True) or not lvl_cfg.get("voice_xp", True):
                continue
            for vc in guild.voice_channels:
                # Must have at least 2 real (non-muted) members to earn XP
                active = [m for m in vc.members if not m.bot and not m.voice.self_mute and not m.voice.self_deaf]
                if len(active) < 2:
                    continue
                for member in active:
                    await self._add_xp(guild, member, VOICE_XP_PER_MINUTE, source="voice")

    @voice_xp_task.before_loop
    async def before_voice_xp(self):
        await self.bot.wait_until_ready()

    # ── Message XP listener ───────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        # Ignore very short messages (< 5 chars) to prevent spam
        if len(message.content.strip()) < 5:
            return

        async with self.bot.db.acquire() as conn:
            cfg = await conn.fetchrow("SELECT leveling FROM guild_config WHERE guild_id=$1", message.guild.id)
            lvl_cfg = self._parse_cfg(cfg["leveling"] if cfg else {})
            if not lvl_cfg.get("enabled", True):
                return
            no_xp = [str(x) for x in lvl_cfg.get("no_xp_channels", [])]
            if str(message.channel.id) in no_xp:
                return
            row = await conn.fetchrow(
                "SELECT last_message FROM members WHERE guild_id=$1 AND user_id=$2",
                message.guild.id, message.author.id)
            now = datetime.now(timezone.utc)
            if row and row["last_message"]:
                last = row["last_message"]
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last).total_seconds() < XP_COOLDOWN_SECONDS:
                    return

        xp_gain = random.randint(*XP_PER_MESSAGE)
        await self._add_xp(message.guild, message.author, xp_gain, source="message", channel=message.channel)

    # ── Core XP add function ──────────────────────────────
    async def _add_xp(self, guild, member, xp_gain, source="message", channel=None):
        avatar_url = str(member.display_avatar.url) if member.display_avatar else None
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT xp, level FROM members WHERE guild_id=$1 AND user_id=$2",
                guild.id, member.id)
            now = datetime.now(timezone.utc)

            if row:
                new_xp = row["xp"] + xp_gain
                old_level = row["level"]
                new_level = get_level_from_xp(new_xp)
                if source == "message":
                    await conn.execute("""
                        UPDATE members SET xp=$1, level=$2, last_message=$3,
                        username=$4, display_name=$5, avatar_url=$6
                        WHERE guild_id=$7 AND user_id=$8
                    """, new_xp, new_level, now, str(member),
                        member.display_name, avatar_url, guild.id, member.id)
                else:
                    await conn.execute("""
                        UPDATE members SET xp=$1, level=$2,
                        username=$3, display_name=$4, avatar_url=$5
                        WHERE guild_id=$6 AND user_id=$7
                    """, new_xp, new_level, str(member),
                        member.display_name, avatar_url, guild.id, member.id)
            else:
                new_xp = xp_gain
                old_level = 0
                new_level = 0
                await conn.execute("""
                    INSERT INTO members(guild_id,user_id,username,display_name,xp,level,last_message,avatar_url)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (guild_id,user_id) DO UPDATE SET
                        xp=EXCLUDED.xp, level=EXCLUDED.level,
                        last_message=EXCLUDED.last_message,
                        username=EXCLUDED.username,
                        display_name=EXCLUDED.display_name,
                        avatar_url=EXCLUDED.avatar_url
                """, guild.id, member.id, str(member),
                    member.display_name, new_xp, new_level, now, avatar_url)

        if new_level > old_level:
            await self._on_level_up(guild, member, new_level, channel)

    # ── Level-up handler ──────────────────────────────────
    async def _on_level_up(self, guild, member, level, channel=None):
        async with self.bot.db.acquire() as conn:
            cfg = await conn.fetchrow("SELECT leveling FROM guild_config WHERE guild_id=$1", guild.id)
            role_row = await conn.fetchrow(
                "SELECT role_id FROM level_roles WHERE guild_id=$1 AND level<=$2 ORDER BY level DESC LIMIT 1",
                guild.id, level)

        lvl_cfg = self._parse_cfg(cfg["leveling"] if cfg else {})
        announce_channel = channel
        ch_id = lvl_cfg.get("announce_channel")
        if ch_id:
            announce_channel = guild.get_channel(int(ch_id)) or channel

        if announce_channel:
            embed = discord.Embed(
                title="🎉 Level Up!",
                description=f"{member.mention} reached **Level {level}**!",
                color=discord.Color.gold())
            embed.set_thumbnail(url=member.display_avatar.url)
            # Show what's needed for next level
            _, _, xp_needed = xp_progress(sum(xp_for_level(l) for l in range(level)) + 1)
            embed.set_footer(text=f"Next level in {xp_needed:,} XP")
            try:
                await announce_channel.send(embed=embed)
            except Exception:
                pass

        # Assign level role reward
        if role_row:
            role = guild.get_role(role_row["role_id"])
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Level {level} reward")
                except Exception:
                    pass

    # ── Rank card renderer ────────────────────────────────
    async def _make_rank_card(self, member, xp, level, rank_pos) -> io.BytesIO:
        W, H = 900, 280
        img = Image.new("RGBA", (W, H), (24, 24, 36))
        draw = ImageDraw.Draw(img)

        # Gradient background stripe
        for i in range(H):
            alpha = int(25 * (i / H))
            draw.line([(0, i), (W, i)], fill=(88, 101, 242, alpha))

        # Avatar with circular mask + border
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(member.display_avatar.url)) as resp:
                    av_data = await resp.read()
            avatar = Image.open(io.BytesIO(av_data)).convert("RGBA").resize((180, 180))
            mask = Image.new("L", (180, 180), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 180, 180), fill=255)
            border_img = Image.new("RGBA", (188, 188), (88, 101, 242, 255))
            border_mask = Image.new("L", (188, 188), 0)
            ImageDraw.Draw(border_mask).ellipse((0, 0, 188, 188), fill=255)
            img.paste(border_img, (36, 46), border_mask)
            img.paste(avatar, (40, 50), mask)
        except Exception:
            draw.ellipse((40, 50, 220, 230), fill=(88, 101, 242, 80))

        # Fonts
        try:
            font_name = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
            font_sub  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
            font_big  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 50)
            font_sm   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
            font_lbl  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        except Exception:
            font_name = font_sub = font_big = font_sm = font_lbl = ImageFont.load_default()

        # Name + tag
        draw.text((250, 38), member.display_name[:24], font=font_name, fill=(255, 255, 255))
        draw.text((250, 80), f"@{str(member)[:28]}", font=font_sub, fill=(140, 140, 170))

        # Rank number
        draw.text((252, 120), "RANK", font=font_lbl, fill=(100, 100, 140))
        draw.text((250, 138), f"#{rank_pos}", font=font_big, fill=(88, 101, 242))

        # Level number
        draw.text((420, 120), "LEVEL", font=font_lbl, fill=(100, 100, 140))
        draw.text((420, 138), str(level), font=font_big, fill=(255, 255, 255))

        # XP progress bar
        cur_level, xp_into, xp_needed = xp_progress(xp)
        bar_x, bar_y, bar_w, bar_h = 250, 213, 600, 22
        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=11, fill=(45, 45, 65))
        fill_pct = xp_into / xp_needed if xp_needed > 0 else 0
        fill_w = max(22, int(bar_w * fill_pct)) if fill_pct > 0 else 0
        if fill_w > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + bar_h], radius=11, fill=(88, 101, 242))

        pct_text = f"{int(fill_pct * 100)}%"
        draw.text((bar_x + bar_w // 2, bar_y + 2), pct_text, font=font_sm, fill=(255, 255, 255))
        draw.text((250, 242), f"{xp_into:,} / {xp_needed:,} XP to next level", font=font_sm, fill=(160, 160, 190))
        draw.text((848, 242), f"Total: {xp:,}", font=font_sm, fill=(100, 100, 140))

        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return buf

    # ── /rank ─────────────────────────────────────────────
    @app_commands.command(name="rank", description="Show your rank card (or someone else's)")
    @app_commands.describe(member="The member to check (leave blank for yourself)")
    async def rank(self, interaction: discord.Interaction, member: discord.Member = None):
        await interaction.response.defer()
        member = member or interaction.user
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM members WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, member.id)
            rank_pos = await conn.fetchval(
                "SELECT COUNT(*)+1 FROM members WHERE guild_id=$1 AND xp > $2",
                interaction.guild.id, row["xp"] if row else 0)

        if not row:
            return await interaction.followup.send(
                f"📊 {member.mention} hasn't earned any XP yet! Start chatting to earn XP.", ephemeral=True)

        card = await self._make_rank_card(member, row["xp"], row["level"], rank_pos)
        await interaction.followup.send(file=discord.File(card, filename="rank.png"))

    # ── /top ──────────────────────────────────────────────
    @app_commands.command(name="top", description="Show the XP leaderboard for this server")
    async def top(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT user_id, username, display_name, xp, level, rep
                   FROM members WHERE guild_id=$1 ORDER BY xp DESC LIMIT 10""",
                interaction.guild.id)
        if not rows:
            return await interaction.response.send_message("📊 No leaderboard data yet!", ephemeral=True)

        embed = discord.Embed(title="🏆 XP Leaderboard", color=discord.Color.gold())
        embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(rows):
            name = row["display_name"] or row["username"] or f"User {row['user_id']}"
            prefix = medals[i] if i < 3 else f"`#{i+1}`"
            cur_lvl, xp_into, xp_needed = xp_progress(row["xp"])
            bar_filled = int((xp_into / xp_needed) * 10) if xp_needed > 0 else 0
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            lines.append(
                f"{prefix} **{name}** — Lv **{row['level']}** • {row['xp']:,} XP\n"
                f"　`{bar}` {xp_into:,}/{xp_needed:,} XP"
            )
        embed.description = "\n".join(lines)
        embed.set_footer(text="Earn XP by chatting and being in voice channels!")
        await interaction.response.send_message(embed=embed)

    # ── /setxp (admin only) ───────────────────────────────
    @app_commands.command(name="setxp", description="Set a member's XP (Bot Admin only)")
    @app_commands.describe(member="The member to set XP for", xp="The total XP amount to set")
    async def setxp(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        from utils.permissions import is_bot_admin
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message(
                "❌ You need to be a bot admin to use this command.", ephemeral=True)
        if xp < 0:
            return await interaction.response.send_message("❌ XP cannot be negative.", ephemeral=True)

        level = get_level_from_xp(xp)
        avatar_url = str(member.display_avatar.url) if member.display_avatar else None
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO members(guild_id,user_id,username,display_name,xp,level,avatar_url)
                VALUES($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (guild_id,user_id) DO UPDATE SET xp=$5, level=$6
            """, interaction.guild.id, member.id, str(member), member.display_name, xp, level, avatar_url)

        _, xp_into, xp_needed = xp_progress(xp)
        embed = discord.Embed(
            title="✅ XP Updated",
            description=f"Set {member.mention}'s XP to **{xp:,}**",
            color=discord.Color.green())
        embed.add_field(name="Level", value=str(level))
        embed.add_field(name="Progress", value=f"{xp_into:,} / {xp_needed:,} to next level")
        await interaction.response.send_message(embed=embed)

    # ── /addxp (admin only) ───────────────────────────────
    @app_commands.command(name="addxp", description="Add XP to a member (Bot Admin only)")
    @app_commands.describe(member="The member to give XP to", amount="Amount of XP to add")
    async def addxp(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        from utils.permissions import is_bot_admin
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message(
                "❌ You need to be a bot admin to use this command.", ephemeral=True)
        if amount <= 0 or amount > 1_000_000:
            return await interaction.response.send_message("❌ Amount must be between 1 and 1,000,000.", ephemeral=True)

        await self._add_xp(interaction.guild, member, amount, source="admin")
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT xp, level FROM members WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, member.id)
        embed = discord.Embed(
            title="✅ XP Added",
            description=f"Added **{amount:,} XP** to {member.mention}",
            color=discord.Color.green())
        if row:
            _, xp_into, xp_needed = xp_progress(row["xp"])
            embed.add_field(name="New Level", value=str(row["level"]))
            embed.add_field(name="Total XP", value=f"{row['xp']:,}")
            embed.add_field(name="Progress", value=f"{xp_into:,}/{xp_needed:,}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Leveling(bot))
