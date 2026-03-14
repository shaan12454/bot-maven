import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
import aiohttp
import io
import os


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        async with self.bot.db.acquire() as conn:
            cfg = await conn.fetchrow(
                "SELECT welcome_channel, welcome_message, welcome_image, auto_role FROM guild_config WHERE guild_id=$1",
                member.guild.id)
        if not cfg:
            return

        # Auto-role
        if cfg["auto_role"]:
            role = member.guild.get_role(cfg["auto_role"])
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                except Exception:
                    pass

        if not cfg["welcome_channel"]:
            return

        channel = member.guild.get_channel(cfg["welcome_channel"])
        if not channel:
            return

        msg = (cfg["welcome_message"] or "Welcome {mention} to **{server}**! You are member #{count}.").format(
            mention=member.mention,
            username=str(member),
            server=member.guild.name,
            count=member.guild.member_count)

        if cfg["welcome_image"]:
            img = await self._make_welcome_card(member)
            file = discord.File(img, filename="welcome.png")
            await channel.send(content=msg, file=file)
        else:
            embed = discord.Embed(description=msg, color=discord.Color.green())
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        async with self.bot.db.acquire() as conn:
            cfg = await conn.fetchrow(
                "SELECT goodbye_channel, goodbye_message FROM guild_config WHERE guild_id=$1",
                member.guild.id)
        if not cfg or not cfg["goodbye_channel"]:
            return

        channel = member.guild.get_channel(cfg["goodbye_channel"])
        if not channel:
            return

        msg = (cfg["goodbye_message"] or "**{username}** has left the server. Goodbye!").format(
            username=str(member), mention=member.mention, server=member.guild.name)

        embed = discord.Embed(description=msg, color=discord.Color.red())
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

    async def _make_welcome_card(self, member: discord.Member) -> io.BytesIO:
        """Generate a welcome card using PIL."""
        W, H = 800, 250
        img = Image.new("RGBA", (W, H), (30, 30, 46))
        draw = ImageDraw.Draw(img)

        # Gradient overlay
        for i in range(H):
            alpha = int(40 * (1 - i / H))
            draw.line([(0, i), (W, i)], fill=(88, 101, 242, alpha))

        # Avatar
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(str(member.display_avatar.url)) as resp:
                    avatar_data = await resp.read()
            avatar = Image.open(io.BytesIO(avatar_data)).convert("RGBA").resize((160, 160))
            # Circle mask
            mask = Image.new("L", (160, 160), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 160, 160), fill=255)
            img.paste(avatar, (45, 45), mask)
        except Exception:
            pass

        # Text
        try:
            font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        except Exception:
            font_big = ImageFont.load_default()
            font_small = font_big

        draw.text((240, 70), f"Welcome!", font=font_big, fill=(255, 255, 255))
        draw.text((240, 120), str(member), font=font_big, fill=(88, 101, 242))
        draw.text((240, 170), f"Member #{member.guild.member_count} • {member.guild.name}", font=font_small, fill=(180, 180, 180))

        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        return buf


async def setup(bot):
    await bot.add_cog(Welcome(bot))
