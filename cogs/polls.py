import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from datetime import datetime, timezone, timedelta
from utils.permissions import is_bot_admin

class Polls(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_polls.start()

    def cog_unload(self):
        self.check_polls.cancel()

    @tasks.loop(seconds=60)
    async def check_polls(self):
        """Check for expired polls."""
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM polls WHERE ended=FALSE AND ends_at <= NOW()")
        for row in rows:
            await self._end_poll(row)

    @check_polls.before_loop
    async def before_check_polls(self):
        await self.bot.wait_until_ready()

    async def _end_poll(self, row):
        guild = self.bot.get_guild(row["guild_id"])
        if not guild: return
        channel = guild.get_channel(row["channel_id"])
        if not channel: return
        
        try:
            message = await channel.fetch_message(row["message_id"])
        except:
            return

        votes = json.loads(row["votes"])
        options = json.loads(row["options"])
        
        # Calculate results
        results_text = ""
        total_votes = sum(votes.values())
        for i, opt in enumerate(options):
            count = votes.get(str(i+1), 0)
            percentage = (count / total_votes * 100) if total_votes > 0 else 0
            results_text += f"{i+1}️⃣ **{opt}**: {count} votes ({percentage:.1f}%)\n"

        embed = message.embeds[0]
        embed.title = "📊 Poll Results"
        embed.description = f"**Question:** {row['question']}\n\n{results_text}"
        embed.color = discord.Color.dark_grey()
        await message.edit(embed=embed)
        await channel.send(f"The poll **{row['question']}** has ended! Check the original message for results.")

        async with self.bot.db.acquire() as conn:
            await conn.execute("UPDATE polls SET ended=TRUE WHERE id=$1", row["id"])

    @app_commands.command(name="poll", description="Create a poll")
    @app_commands.describe(question="What is the poll about?", options="Comma-separated list (max 9)", duration="e.g. 1h, 10m")
    async def poll_cmd(self, interaction: discord.Interaction, question: str, options: str, duration: str = "1h"):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)

        opts = [o.strip() for o in options.split(",")][:9]
        if len(opts) < 2:
            return await interaction.response.send_message("❌ You need at least 2 options.", ephemeral=True)

        from utils.helpers import parse_duration
        seconds = parse_duration(duration)
        ends_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)

        description = ""
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        for i, opt in enumerate(opts):
            description += f"{emojis[i]} {opt}\n"

        embed = discord.Embed(title="📊 New Poll", description=f"**{question}**\n\n{description}", color=discord.Color.blue())
        embed.set_footer(text=f"Ends: {ends_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        await interaction.response.send_message("Creating poll...", ephemeral=True)
        msg = await interaction.channel.send(embed=embed)
        for i in range(len(opts)):
            await msg.add_reaction(emojis[i])

        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO polls (guild_id, channel_id, message_id, question, options, ends_at)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, interaction.guild.id, interaction.channel_id, msg.id, question, json.dumps(opts), ends_at)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id: return
        
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
        if payload.emoji.name not in emojis: return

        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM polls WHERE message_id=$1 AND ended=FALSE", payload.message_id)
            if not row: return
            
            votes = json.loads(row["votes"])
            vote_idx = str(emojis.index(payload.emoji.name) + 1)
            votes[vote_idx] = votes.get(vote_idx, 0) + 1
            
            await conn.execute("UPDATE polls SET votes=$1 WHERE id=$2", json.dumps(votes), row["id"])

async def setup(bot):
    await bot.add_cog(Polls(bot))
