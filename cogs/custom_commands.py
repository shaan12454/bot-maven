import discord
from discord.ext import commands
from discord import app_commands
import json


class CustomCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        async with self.bot.db.acquire() as conn:
            prefix_row = await conn.fetchrow("SELECT prefix FROM guild_config WHERE guild_id=$1", message.guild.id)
            prefix = prefix_row["prefix"] if prefix_row else "!"
            if not message.content.startswith(prefix):
                return
            cmd_name = message.content[len(prefix):].split()[0].lower()
            row = await conn.fetchrow(
                "SELECT * FROM custom_commands WHERE guild_id=$1 AND name=$2",
                message.guild.id, cmd_name)
        if not row:
            return
        response = row["response"].format(
            user=message.author.mention,
            username=str(message.author),
            server=message.guild.name,
            channel=message.channel.mention)
        if row["embed"]:
            embed_data = row["embed"]
            embed = discord.Embed(
                title=embed_data.get("title", ""),
                description=response,
                color=discord.Color.blurple())
            if embed_data.get("image"):
                embed.set_image(url=embed_data["image"])
            await message.channel.send(embed=embed)
        else:
            await message.channel.send(response)

    cc = app_commands.Group(name="cc", description="Custom command management")

    @cc.command(name="add", description="Add a custom command")
    @app_commands.default_permissions(manage_guild=True)
    async def cc_add(self, interaction: discord.Interaction, name: str, response: str):
        name = name.lower()
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO custom_commands(guild_id, name, response) VALUES($1,$2,$3) ON CONFLICT (guild_id,name) DO UPDATE SET response=$3",
                interaction.guild.id, name, response)
        await interaction.response.send_message(f"✅ Custom command `{name}` added!")

    @cc.command(name="remove", description="Remove a custom command")
    @app_commands.default_permissions(manage_guild=True)
    async def cc_remove(self, interaction: discord.Interaction, name: str):
        async with self.bot.db.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM custom_commands WHERE guild_id=$1 AND name=$2",
                interaction.guild.id, name.lower())
        if result == "DELETE 0":
            return await interaction.response.send_message(f"❌ Command `{name}` not found.")
        await interaction.response.send_message(f"✅ Removed `{name}`")

    @cc.command(name="list", description="List all custom commands")
    async def cc_list(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name FROM custom_commands WHERE guild_id=$1 ORDER BY name", interaction.guild.id)
        if not rows:
            return await interaction.response.send_message("No custom commands yet.")
        names = ", ".join(f"`{r['name']}`" for r in rows)
        await interaction.response.send_message(f"**Custom Commands:** {names}")


async def setup(bot):
    await bot.add_cog(CustomCommands(bot))
