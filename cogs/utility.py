import discord
from discord.ext import commands
from discord import app_commands


class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="moveme", description="Move to another voice channel")
    async def moveme(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ You're not in a voice channel!", ephemeral=True)
        await interaction.user.move_to(channel)
        await interaction.response.send_message(f"✅ Moved you to {channel.name}", ephemeral=True)

    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! `{latency}ms`")

    @app_commands.command(name="color", description="Show a color by hex")
    async def color(self, interaction: discord.Interaction, hex_code: str):
        hex_code = hex_code.strip("#")
        try:
            color_int = int(hex_code, 16)
            r, g, b = (color_int >> 16) & 0xFF, (color_int >> 8) & 0xFF, color_int & 0xFF
        except ValueError:
            return await interaction.response.send_message("❌ Invalid hex color!", ephemeral=True)
        embed = discord.Embed(
            title=f"#{hex_code.upper()}",
            description=f"RGB: `{r}, {g}, {b}`",
            color=color_int)
        embed.set_thumbnail(url=f"https://singlecolorimage.com/get/{hex_code}/100x100")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="embed", description="Create a custom embed")
    @app_commands.default_permissions(manage_messages=True)
    async def embed_cmd(self, interaction: discord.Interaction, title: str, description: str,
                        color: str = "5865F2", image: str = None):
        try:
            c = int(color.strip("#"), 16)
        except ValueError:
            c = 0x5865F2
        embed = discord.Embed(title=title, description=description, color=c)
        if image:
            embed.set_image(url=image)
        embed.set_footer(text=f"Posted by {interaction.user}")
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Embed sent!", ephemeral=True)

    @app_commands.command(name="setwelcome", description="Configure welcome settings")
    @app_commands.default_permissions(manage_guild=True)
    async def setwelcome(self, interaction: discord.Interaction,
                         channel: discord.TextChannel,
                         message: str = "Welcome {mention} to **{server}**! You are member #{count}."):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                """INSERT INTO guild_config(guild_id, welcome_channel, welcome_message)
                   VALUES($1,$2,$3)
                   ON CONFLICT (guild_id) DO UPDATE SET welcome_channel=$2, welcome_message=$3""",
                interaction.guild.id, channel.id, message)
        await interaction.response.send_message(f"✅ Welcome messages will be sent to {channel.mention}")

    @app_commands.command(name="setlogchannel", description="Set the log channel")
    @app_commands.default_permissions(manage_guild=True)
    async def setlogchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config(guild_id, log_channel) VALUES($1,$2) ON CONFLICT (guild_id) DO UPDATE SET log_channel=$2",
                interaction.guild.id, channel.id)
        await interaction.response.send_message(f"✅ Log channel set to {channel.mention}")

    @app_commands.command(name="setprefix", description="Set the command prefix")
    @app_commands.default_permissions(manage_guild=True)
    async def setprefix(self, interaction: discord.Interaction, prefix: str):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config(guild_id, prefix) VALUES($1,$2) ON CONFLICT (guild_id) DO UPDATE SET prefix=$2",
                interaction.guild.id, prefix)
        await interaction.response.send_message(f"✅ Prefix set to `{prefix}`")

    @app_commands.command(name="setautorole", description="Set auto-role for new members")
    @app_commands.default_permissions(manage_guild=True)
    async def setautorole(self, interaction: discord.Interaction, role: discord.Role):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_config(guild_id, auto_role) VALUES($1,$2) ON CONFLICT (guild_id) DO UPDATE SET auto_role=$2",
                interaction.guild.id, role.id)
        await interaction.response.send_message(f"✅ Auto-role set to {role.mention}")

    @app_commands.command(name="levelrole", description="Set a role reward for reaching a level")
    @app_commands.default_permissions(manage_guild=True)
    async def levelrole(self, interaction: discord.Interaction, level: int, role: discord.Role):
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO level_roles(guild_id,level,role_id) VALUES($1,$2,$3) ON CONFLICT (guild_id,level) DO UPDATE SET role_id=$3",
                interaction.guild.id, level, role.id)
        await interaction.response.send_message(f"✅ {role.mention} will be awarded at Level {level}")


async def setup(bot):
    await bot.add_cog(Utility(bot))
