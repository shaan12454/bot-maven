import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import asyncio
from datetime import datetime, timezone, timedelta
from utils.permissions import is_bot_admin

class Giveaways(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        """Check for ended giveaways and pick winners."""
        async with self.bot.db.acquire() as conn:
            # Pick giveaways that ended but aren't marked as ended
            rows = await conn.fetch("""
                SELECT * FROM giveaways 
                WHERE ended=FALSE AND ends_at <= NOW()
            """)
        
        for row in rows:
            await self._end_giveaway(row)

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    async def _end_giveaway(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if not guild: return
        channel = guild.get_channel(row["channel_id"])
        if not channel: return
        
        try:
            message = await channel.fetch_message(row["message_id"])
        except Exception:
            return # Message deleted?

        reaction = discord.utils.get(message.reactions, emoji="🎉")
        if not reaction:
            users = []
        else:
            users = [u async for u in reaction.users() if not u.bot]

        if len(users) < row["winner_count"]:
            winners = users
        else:
            winners = random.sample(users, row["winner_count"])

        winner_ids = [w.id for w in winners]
        winner_mentions = ", ".join([w.mention for w in winners]) if winners else "No one"

        # Update embed
        embed = message.embeds[0]
        embed.title = "🎊 Giveaway Ended 🎊"
        embed.description = f"**Prize:** {row['prize']}\n**Winners:** {winner_mentions}"
        embed.color = discord.Color.greyple()
        await message.edit(embed=embed)
        
        if winners:
            await channel.send(f"Congratulations {winner_mentions}! You won **{row['prize']}**!")
            for w in winners:
                try:
                    await w.send(f"🥳 Congratulations! You won **{row['prize']}** in **{guild.name}**!")
                except:
                    pass
        else:
            await channel.send(f"The giveaway for **{row['prize']}** has ended, but no one joined. ☹️")

        async with self.bot.db.acquire() as conn:
            import json
            await conn.execute("""
                UPDATE giveaways SET ended=TRUE, winners=$1 
                WHERE id=$2
            """, json.dumps(winner_ids), row["id"])

    @app_commands.command(name="giveaway", description="Giveaway management")
    @app_commands.describe(action="start, end, reroll", prize="Prize to win", duration="e.g. 1h, 30m, 1d", winners="Number of winners")
    async def giveaway_cmd(self, interaction: discord.Interaction, action: str, prize: str = None, duration: str = "1h", winners: int = 1):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)

        if action == "start":
            from utils.helpers import parse_duration
            seconds = parse_duration(duration)
            ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            
            embed = discord.Embed(
                title="🎉 Giveaway Started 🎉",
                description=f"**Prize:** {prize}\n**Winners:** {winners}\n**Ends:** <t:{int(ends_at.timestamp())}:R>",
                color=discord.Color.gold()
            )
            embed.set_footer(text="React with 🎉 to enter!")
            
            await interaction.response.send_message("Creating giveaway...", ephemeral=True)
            msg = await interaction.channel.send(embed=embed)
            await msg.add_reaction("🎉")
            
            async with self.bot.db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO giveaways (guild_id, channel_id, message_id, host_id, prize, winner_count, ends_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                """, interaction.guild.id, interaction.channel_id, msg.id, interaction.user.id, prize, winners, ends_at)
        
        elif action == "end":
            # Logic to find the last giveaway in this channel
            async with self.bot.db.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT * FROM giveaways 
                    WHERE guild_id=$1 AND channel_id=$2 AND ended=FALSE 
                    ORDER BY created_at DESC LIMIT 1
                """, interaction.guild.id, interaction.channel_id)
            
            if not row:
                return await interaction.response.send_message("❌ No active giveaway found in this channel.", ephemeral=True)
            
            await self._end_giveaway(row)
            await interaction.response.send_message("✅ Giveaway ended.", ephemeral=True)

        elif action == "reroll":
             # Implementation for reroll
             pass

async def setup(bot):
    await bot.add_cog(Giveaways(bot))
