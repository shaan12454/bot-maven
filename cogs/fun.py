import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta, timezone
import random
import asyncio


EIGHT_BALL_RESPONSES = [
    # Positive
    "✅ It is certain.", "✅ It is decidedly so.", "✅ Without a doubt.",
    "✅ Yes, definitely!", "✅ You may rely on it.", "✅ As I see it, yes.",
    "✅ Most likely.", "✅ Outlook good.", "✅ Yes!", "✅ Signs point to yes.",
    # Neutral
    "🔮 Reply hazy, try again.", "🔮 Ask again later.", "🔮 Better not tell you now.",
    "🔮 Cannot predict now.", "🔮 Concentrate and ask again.",
    # Negative
    "❌ Don't count on it.", "❌ My reply is no.", "❌ My sources say no.",
    "❌ Outlook not so good.", "❌ Very doubtful.",
]

SHIP_PHRASES = [
    "A match made in heaven! 💕",
    "The stars align for these two! ⭐",
    "Surprisingly compatible! 😮",
    "An average pair, but who knows! 🤷",
    "They balance each other out! ⚖️",
    "A work in progress... 🛠️",
    "Maybe in another universe? 🌌",
    "The odds are not in their favour... 💔",
]

HUG_GIFS = [
    "https://media.giphy.com/media/od5H3PmEG5EVq/giphy.gif",
    "https://media.giphy.com/media/lrr9rHuoJOE0w/giphy.gif",
    "https://media.giphy.com/media/3M4NpbLCTxBqU/giphy.gif",
]

PAT_GIFS = [
    "https://media.giphy.com/media/5tmRHwTlHAA9WkVxTU/giphy.gif",
    "https://media.giphy.com/media/ARSp9T7wwxNcs/giphy.gif",
]

TRIVIA_QUESTIONS = [
    {"q": "What is the chemical symbol for Gold?", "a": "au", "choices": ["AG", "AU", "GD", "GO"], "correct": 1},
    {"q": "How many sides does a hexagon have?", "a": "6", "choices": ["5", "6", "7", "8"], "correct": 1},
    {"q": "What planet is known as the Red Planet?", "a": "mars", "choices": ["Venus", "Jupiter", "Mars", "Saturn"], "correct": 2},
    {"q": "Who painted the Mona Lisa?", "a": "da vinci", "choices": ["Picasso", "Michelangelo", "Da Vinci", "Raphael"], "correct": 2},
    {"q": "What is the largest ocean on Earth?", "a": "pacific", "choices": ["Atlantic", "Indian", "Arctic", "Pacific"], "correct": 3},
    {"q": "How many continents are there on Earth?", "a": "7", "choices": ["5", "6", "7", "8"], "correct": 2},
    {"q": "What is the fastest land animal?", "a": "cheetah", "choices": ["Lion", "Cheetah", "Horse", "Leopard"], "correct": 1},
    {"q": "What is 12 × 12?", "a": "144", "choices": ["132", "140", "144", "148"], "correct": 2},
    {"q": "Which element has the symbol 'O'?", "a": "oxygen", "choices": ["Osmium", "Oxygen", "Oganesson", "None"], "correct": 1},
    {"q": "What year did World War II end?", "a": "1945", "choices": ["1943", "1944", "1945", "1946"], "correct": 2},
]


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._active_trivia: dict[int, bool] = {}

    # ── /rep ──────────────────────────────────────────────
    @app_commands.command(name="rep", description="Give reputation to another member (once per 24h)")
    @app_commands.describe(member="The member to give rep to")
    async def rep(self, interaction: discord.Interaction, member: discord.Member):
        if member == interaction.user:
            return await interaction.response.send_message("❌ You can't rep yourself!", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ Can't rep bots!", ephemeral=True)

        async with self.bot.db.acquire() as conn:
            giver = await conn.fetchrow(
                "SELECT last_rep FROM members WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, interaction.user.id)
            now = datetime.now(timezone.utc)
            if giver and giver["last_rep"]:
                last = giver["last_rep"]
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                remaining = timedelta(hours=24) - (now - last)
                if remaining.total_seconds() > 0:
                    h, rem = divmod(int(remaining.total_seconds()), 3600)
                    m = rem // 60
                    return await interaction.response.send_message(
                        f"❌ You can give rep again in **{h}h {m}m**", ephemeral=True)

            await conn.execute(
                """INSERT INTO members(guild_id,user_id,username,display_name,rep,last_rep) VALUES($1,$2,$3,$4,1,$5)
                   ON CONFLICT (guild_id,user_id) DO UPDATE SET rep=members.rep+1, last_rep=$5""",
                interaction.guild.id, member.id, str(member), member.display_name, now)
            await conn.execute(
                """INSERT INTO members(guild_id,user_id,username,display_name,last_rep) VALUES($1,$2,$3,$4,$5)
                   ON CONFLICT (guild_id,user_id) DO UPDATE SET last_rep=$5""",
                interaction.guild.id, interaction.user.id, str(interaction.user), interaction.user.display_name, now)
            new_rep = await conn.fetchval(
                "SELECT rep FROM members WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, member.id)

        embed = discord.Embed(
            description=f"⭐ {interaction.user.mention} gave rep to {member.mention}!\nThey now have **{new_rep}** rep.",
            color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    # ── /profile ──────────────────────────────────────────
    @app_commands.command(name="profile", description="View your profile or another member's")
    @app_commands.describe(member="The member to view (leave blank for yourself)")
    async def profile(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM members WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, member.id)
            rank = await conn.fetchval(
                "SELECT COUNT(*)+1 FROM members WHERE guild_id=$1 AND xp > $2",
                interaction.guild.id, row["xp"] if row else 0)

        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            color=member.color if member.color.value else discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        if row:
            embed.add_field(name="🏆 Rank", value=f"#{rank}")
            embed.add_field(name="⚡ Level", value=str(row["level"]))
            embed.add_field(name="✨ XP", value=f"{row['xp']:,}")
            embed.add_field(name="⭐ Rep", value=str(row["rep"] or 0))
            embed.add_field(name="💰 Credits", value=f"{row['credits']:,}")
        else:
            embed.description = "No activity yet — start chatting to earn XP!"
        embed.add_field(name="📅 Joined", value=member.joined_at.strftime("%b %d, %Y") if member.joined_at else "Unknown")
        embed.add_field(name="🎭 Roles", value=f"{max(0, len(member.roles)-1)} roles")
        embed.set_footer(text=f"User ID: {member.id}")
        await interaction.response.send_message(embed=embed)

    # ── /credits ──────────────────────────────────────────
    @app_commands.command(name="credits", description="Check your credits balance or another member's")
    @app_commands.describe(member="The member to check (leave blank for yourself)")
    async def credits(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT credits FROM members WHERE guild_id=$1 AND user_id=$2",
                interaction.guild.id, member.id)
        credits_val = row["credits"] if row else 0
        embed = discord.Embed(
            description=f"💰 {member.mention} has **{credits_val:,}** credits.",
            color=discord.Color.gold())
        await interaction.response.send_message(embed=embed)

    # ── /8ball ────────────────────────────────────────────
    @app_commands.command(name="8ball", description="Ask the magic 8-ball a yes/no question")
    @app_commands.describe(question="Your yes/no question")
    async def eight_ball(self, interaction: discord.Interaction, question: str):
        response = random.choice(EIGHT_BALL_RESPONSES)
        embed = discord.Embed(color=discord.Color.dark_purple())
        embed.add_field(name="🎱 Question", value=question, inline=False)
        embed.add_field(name="Answer", value=response, inline=False)
        embed.set_footer(text=f"Asked by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    # ── /coinflip ─────────────────────────────────────────
    @app_commands.command(name="coinflip", description="Flip a coin — heads or tails!")
    async def coinflip(self, interaction: discord.Interaction):
        result = random.choice(["Heads", "Tails"])
        emoji = "🪙"
        embed = discord.Embed(
            title=f"{emoji} Coin Flip!",
            description=f"The coin landed on **{result}**!",
            color=discord.Color.gold())
        embed.set_footer(text=f"Flipped by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    # ── /dice ─────────────────────────────────────────────
    @app_commands.command(name="dice", description="Roll one or more dice (e.g. /dice 2 20 = roll 2 twenty-sided dice)")
    @app_commands.describe(count="Number of dice (1-10)", sides="Number of sides (2-100)")
    async def dice(self, interaction: discord.Interaction, count: int = 1, sides: int = 6):
        count = max(1, min(10, count))
        sides = max(2, min(100, sides))
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        embed = discord.Embed(
            title=f"🎲 Rolling {count}d{sides}",
            color=discord.Color.blue())
        embed.add_field(name="Rolls", value=" + ".join(str(r) for r in rolls))
        if count > 1:
            embed.add_field(name="Total", value=str(total))
        embed.set_footer(text=f"Rolled by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)

    # ── /ship ─────────────────────────────────────────────
    @app_commands.command(name="ship", description="Check the compatibility between two members 💕")
    @app_commands.describe(member1="First member", member2="Second member (leave blank to ship with yourself)")
    async def ship(self, interaction: discord.Interaction, member1: discord.Member, member2: discord.Member = None):
        member2 = member2 or interaction.user
        # Deterministic based on IDs so same pair always gets same result
        seed = (min(member1.id, member2.id) * 31 + max(member1.id, member2.id)) % 101
        percent = seed
        if percent < 20:
            bar = "💔" * 2 + "🤍" * 8
            phrase = SHIP_PHRASES[7]
        elif percent < 40:
            bar = "❤️" * 2 + "🤍" * 8
            phrase = SHIP_PHRASES[6]
        elif percent < 55:
            bar = "❤️" * 4 + "🤍" * 6
            phrase = SHIP_PHRASES[5]
        elif percent < 70:
            bar = "❤️" * 5 + "🤍" * 5
            phrase = SHIP_PHRASES[4]
        elif percent < 80:
            bar = "❤️" * 6 + "🤍" * 4
            phrase = SHIP_PHRASES[3]
        elif percent < 90:
            bar = "❤️" * 8 + "🤍" * 2
            phrase = SHIP_PHRASES[2]
        elif percent < 97:
            bar = "❤️" * 9 + "🤍" * 1
            phrase = SHIP_PHRASES[1]
        else:
            bar = "❤️" * 10
            phrase = SHIP_PHRASES[0]

        ship_name = member1.display_name[:len(member1.display_name)//2] + member2.display_name[len(member2.display_name)//2:]
        embed = discord.Embed(
            title=f"💕 Compatibility Check",
            description=f"**{member1.display_name}** & **{member2.display_name}**\n\n{bar}\n\n**{percent}%** — {phrase}",
            color=discord.Color.pink() if hasattr(discord.Color, "pink") else discord.Color.magenta())
        embed.set_footer(text=f"Ship name: {ship_name}")
        await interaction.response.send_message(embed=embed)

    # ── /hug ──────────────────────────────────────────────
    @app_commands.command(name="hug", description="Hug someone! 🤗")
    @app_commands.describe(member="The member to hug")
    async def hug(self, interaction: discord.Interaction, member: discord.Member):
        if member == interaction.user:
            return await interaction.response.send_message("You hugged yourself. That's okay, self-love matters! 🤗", ephemeral=True)
        embed = discord.Embed(
            description=f"🤗 **{interaction.user.display_name}** hugged **{member.display_name}**!",
            color=discord.Color.pink() if hasattr(discord.Color, "pink") else discord.Color.magenta())
        embed.set_image(url=random.choice(HUG_GIFS))
        await interaction.response.send_message(embed=embed)

    # ── /pat ──────────────────────────────────────────────
    @app_commands.command(name="pat", description="Give someone a pat on the head 👋")
    @app_commands.describe(member="The member to pat")
    async def pat(self, interaction: discord.Interaction, member: discord.Member):
        embed = discord.Embed(
            description=f"👋 **{interaction.user.display_name}** patted **{member.display_name}**!",
            color=discord.Color.blurple())
        embed.set_image(url=random.choice(PAT_GIFS))
        await interaction.response.send_message(embed=embed)

    # ── /trivia ───────────────────────────────────────────
    @app_commands.command(name="trivia", description="Answer a trivia question and earn 50 credits!")
    async def trivia(self, interaction: discord.Interaction):
        channel_id = interaction.channel_id
        if self._active_trivia.get(channel_id):
            return await interaction.response.send_message(
                "❌ There's already an active trivia question in this channel!", ephemeral=True)

        q = random.choice(TRIVIA_QUESTIONS)
        choices = q["choices"]
        letters = ["🇦", "🇧", "🇨", "🇩"]
        self._active_trivia[channel_id] = True

        embed = discord.Embed(
            title="🎯 Trivia Time!",
            description=q["q"],
            color=discord.Color.blurple())
        for i, choice in enumerate(choices):
            embed.add_field(name=letters[i], value=choice, inline=True)
        embed.set_footer(text="Type A, B, C, or D within 20 seconds!")
        await interaction.response.send_message(embed=embed)

        def check(m):
            return (
                m.channel == interaction.channel
                and not m.author.bot
                and m.content.upper() in ["A", "B", "C", "D"]
            )

        try:
            msg = await self.bot.wait_for("message", timeout=20.0, check=check)
            answer_idx = ["A", "B", "C", "D"].index(msg.content.upper())
            correct_idx = q["correct"]
            if answer_idx == correct_idx:
                # Give 50 credits
                async with self.bot.db.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO members(guild_id,user_id,username,display_name,credits) VALUES($1,$2,$3,$4,50)
                           ON CONFLICT (guild_id,user_id) DO UPDATE SET credits=members.credits+50""",
                        interaction.guild.id, msg.author.id, str(msg.author), msg.author.display_name)
                result_embed = discord.Embed(
                    title="✅ Correct!",
                    description=f"{msg.author.mention} got it right! The answer was **{choices[correct_idx]}**.\n💰 +50 credits awarded!",
                    color=discord.Color.green())
            else:
                result_embed = discord.Embed(
                    title="❌ Wrong!",
                    description=f"{msg.author.mention} answered **{choices[answer_idx]}** but the correct answer was **{choices[correct_idx]}**.",
                    color=discord.Color.red())
            await interaction.channel.send(embed=result_embed)
        except asyncio.TimeoutError:
            correct_idx = q["correct"]
            timeout_embed = discord.Embed(
                title="⏰ Time's Up!",
                description=f"Nobody answered in time! The correct answer was **{choices[correct_idx]}**.",
                color=discord.Color.orange())
            await interaction.channel.send(embed=timeout_embed)
        finally:
            self._active_trivia.pop(channel_id, None)

    # ── /rps ──────────────────────────────────────────────
    @app_commands.command(name="rps", description="Play Rock, Paper, Scissors against the bot!")
    @app_commands.describe(choice="Your choice: rock, paper, or scissors")
    @app_commands.choices(choice=[
        app_commands.Choice(name="Rock 🪨", value="rock"),
        app_commands.Choice(name="Paper 📄", value="paper"),
        app_commands.Choice(name="Scissors ✂️", value="scissors"),
    ])
    async def rps(self, interaction: discord.Interaction, choice: str):
        options = ["rock", "paper", "scissors"]
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        bot_choice = random.choice(options)

        if choice == bot_choice:
            result = "It's a **tie**! 🤝"
            color = discord.Color.yellow()
        elif (
            (choice == "rock" and bot_choice == "scissors") or
            (choice == "paper" and bot_choice == "rock") or
            (choice == "scissors" and bot_choice == "paper")
        ):
            result = "You **win**! 🎉"
            color = discord.Color.green()
        else:
            result = "You **lose**! 😢"
            color = discord.Color.red()

        embed = discord.Embed(title="Rock, Paper, Scissors!", color=color)
        embed.add_field(name="Your pick", value=f"{emojis[choice]} {choice.capitalize()}")
        embed.add_field(name="My pick", value=f"{emojis[bot_choice]} {bot_choice.capitalize()}")
        embed.add_field(name="Result", value=result, inline=False)
        await interaction.response.send_message(embed=embed)

    # ── /choose ───────────────────────────────────────────
    @app_commands.command(name="choose", description="Can't decide? Let the bot pick for you!")
    @app_commands.describe(options="Comma-separated options to choose from (e.g. pizza, sushi, tacos)")
    async def choose(self, interaction: discord.Interaction, options: str):
        choices = [o.strip() for o in options.split(",") if o.strip()]
        if len(choices) < 2:
            return await interaction.response.send_message("❌ Give me at least 2 options to choose from!", ephemeral=True)
        if len(choices) > 20:
            return await interaction.response.send_message("❌ Too many options! Max 20.", ephemeral=True)
        picked = random.choice(choices)
        embed = discord.Embed(
            title="🎲 Decision Made!",
            description=f"Out of {len(choices)} options, I choose...\n\n**{picked}**",
            color=discord.Color.blurple())
        embed.set_footer(text=f"Options: {', '.join(choices)}")
        await interaction.response.send_message(embed=embed)

    # ── /serverinfo ───────────────────────────────────────
    @app_commands.command(name="serverinfo", description="Show server information")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        bots = sum(1 for m in guild.members if m.bot)
        humans = guild.member_count - bots

        embed = discord.Embed(title=f"📊 {guild.name}", color=discord.Color.blurple())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        if guild.banner:
            embed.set_image(url=guild.banner.url)
        embed.add_field(name="👑 Owner", value=guild.owner.mention if guild.owner else "Unknown")
        embed.add_field(name="👥 Members", value=f"{humans:,} humans, {bots} bots")
        embed.add_field(name="💬 Text Channels", value=str(text_channels))
        embed.add_field(name="🔊 Voice Channels", value=str(voice_channels))
        embed.add_field(name="🎭 Roles", value=str(len(guild.roles) - 1))
        embed.add_field(name="✨ Boosts", value=f"Level {guild.premium_tier} ({guild.premium_subscription_count} boosts)")
        embed.add_field(name="📅 Created", value=f"<t:{int(guild.created_at.timestamp())}:D>")
        embed.add_field(name="🌍 Region", value=str(guild.preferred_locale).upper())
        embed.set_footer(text=f"Server ID: {guild.id}")
        await interaction.response.send_message(embed=embed)

    # ── /userinfo ─────────────────────────────────────────
    @app_commands.command(name="userinfo", description="Show info about a user")
    @app_commands.describe(member="The member to look up (leave blank for yourself)")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        roles = [r.mention for r in reversed(member.roles) if r.name != "@everyone"]
        embed = discord.Embed(
            title=f"👤 {member}",
            color=member.color if member.color.value else discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Display Name", value=member.display_name)
        embed.add_field(name="Bot?", value="✅ Yes" if member.bot else "❌ No")
        embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:D>")
        embed.add_field(name="Joined Server", value=f"<t:{int(member.joined_at.timestamp())}:D>" if member.joined_at else "Unknown")
        embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:10]) or "None", inline=False)
        embed.set_footer(text=f"User ID: {member.id}")
        await interaction.response.send_message(embed=embed)

    # ── /avatar ───────────────────────────────────────────
    @app_commands.command(name="avatar", description="Get a high-quality version of someone's avatar")
    @app_commands.describe(member="The member whose avatar to show (leave blank for yourself)")
    async def avatar(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        embed = discord.Embed(
            title=f"🖼️ {member.display_name}'s Avatar",
            color=member.color if member.color.value else discord.Color.blurple())
        embed.set_image(url=member.display_avatar.url)
        embed.set_footer(text=f"User ID: {member.id}")
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))
