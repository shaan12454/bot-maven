import discord
from discord.ext import commands
from discord import app_commands
from utils.permissions import is_bot_admin

class Starboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.emoji.name != "⭐": return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild: return
        
        async with self.bot.db.acquire() as conn:
            cfg = await conn.fetchrow("SELECT starboard_channel, starboard_threshold FROM guild_config WHERE guild_id=$1", guild.id)
        
        if not cfg or not cfg["starboard_channel"]: return
        
        starboard_channel = guild.get_channel(cfg["starboard_channel"])
        if not starboard_channel: return
        
        threshold = cfg["starboard_threshold"] or 3
        
        channel = guild.get_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        
        reaction = discord.utils.get(message.reactions, emoji="⭐")
        count = reaction.count if reaction else 0
        
        if count < threshold: return
        
        async with self.bot.db.acquire() as conn:
            entry = await conn.fetchrow("SELECT * FROM starboard_entries WHERE original_message_id=$1", message.id)
            
            embed = discord.Embed(description=message.content, color=0xFFAC33)
            embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
            embed.add_field(name="Original", value=f"[Jump to message]({message.jump_url})")
            embed.set_footer(text=f"ID: {message.id}")
            embed.timestamp = message.created_at
            
            if message.attachments:
                embed.set_image(url=message.attachments[0].url)

            if entry:
                try:
                    star_message = await starboard_channel.fetch_message(entry["starboard_message_id"])
                    await star_message.edit(content=f"⭐ **{count}** | {channel.mention}", embed=embed)
                    await conn.execute("UPDATE starboard_entries SET star_count=$1 WHERE id=$2", count, entry["id"])
                except:
                    # Message likely deleted, recreate it
                    star_message = await starboard_channel.send(content=f"⭐ **{count}** | {channel.mention}", embed=embed)
                    await conn.execute("UPDATE starboard_entries SET starboard_message_id=$1, star_count=$2 WHERE id=$3", star_message.id, count, entry["id"])
            else:
                star_message = await starboard_channel.send(content=f"⭐ **{count}** | {channel.mention}", embed=embed)
                await conn.execute("""
                    INSERT INTO starboard_entries (guild_id, original_message_id, starboard_message_id, channel_id, author_id, star_count)
                    VALUES ($1, $2, $3, $4, $5, $6)
                """, guild.id, message.id, star_message.id, channel.id, message.author.id, count)

    @app_commands.command(name="starboard", description="Configure starboard")
    @app_commands.describe(channel="Channel for starboard posts", threshold="Star threshold to post")
    async def starboard_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel = None, threshold: int = None):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        
        async with self.bot.db.acquire() as conn:
            if channel:
                await conn.execute("""
                    INSERT INTO guild_config (guild_id, starboard_channel) VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO UPDATE SET starboard_channel = $2
                """, interaction.guild.id, channel.id)
            if threshold is not None:
                await conn.execute("""
                    INSERT INTO guild_config (guild_id, starboard_threshold) VALUES ($1, $2)
                    ON CONFLICT (guild_id) DO UPDATE SET starboard_threshold = $2
                """, interaction.guild.id, threshold)
        
        msg = "✅ Updated starboard settings."
        if channel: msg += f" Channel: {channel.mention}."
        if threshold is not None: msg += f" Threshold: {threshold} stars."
        await interaction.response.send_message(msg)

async def setup(bot):
    await bot.add_cog(Starboard(bot))
