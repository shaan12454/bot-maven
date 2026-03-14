import discord
from discord.ext import commands
from discord import app_commands


class RoleButton(discord.ui.Button):
    def __init__(self, role_id: int, label: str, style: discord.ButtonStyle):
        super().__init__(label=label, style=style, custom_id=f"role_{role_id}")
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message("❌ Role not found.", ephemeral=True)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"✅ Removed **{role.name}**", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Given **{role.name}**", ephemeral=True)


class RoleDropdown(discord.ui.Select):
    def __init__(self, roles: list[discord.Role]):
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in roles[:25]]
        super().__init__(placeholder="Select a role...", options=options, custom_id="role_dropdown")

    async def callback(self, interaction: discord.Interaction):
        role_id = int(self.values[0])
        role = interaction.guild.get_role(role_id)
        if not role:
            return await interaction.response.send_message("❌ Role not found.", ephemeral=True)
        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"✅ Removed **{role.name}**", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"✅ Given **{role.name}**", ephemeral=True)


class ReactionRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Re-register persistent button views on restart."""
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("SELECT DISTINCT message_id, guild_id, channel_id FROM button_roles")
        for row in rows:
            guild = self.bot.get_guild(row["guild_id"])
            if not guild:
                continue
            async with self.bot.db.acquire() as conn:
                btn_rows = await conn.fetch(
                    "SELECT * FROM button_roles WHERE guild_id=$1 AND message_id=$2",
                    row["guild_id"], row["message_id"])
            view = discord.ui.View(timeout=None)
            for b in btn_rows:
                style_map = {"primary": discord.ButtonStyle.primary, "success": discord.ButtonStyle.success,
                             "danger": discord.ButtonStyle.danger, "secondary": discord.ButtonStyle.secondary}
                style = style_map.get(b["style"], discord.ButtonStyle.primary)
                view.add_item(RoleButton(b["role_id"], b["label"] or b["role_name"], style))
            self.bot.add_view(view)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        await self._handle_reaction(payload, add=True)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        await self._handle_reaction(payload, add=False)

    async def _handle_reaction(self, payload, add: bool):
        if not payload.guild_id:
            return
        emoji = str(payload.emoji)
        async with self.bot.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT role_id FROM reaction_roles WHERE guild_id=$1 AND message_id=$2 AND emoji=$3",
                payload.guild_id, payload.message_id, emoji)
        if not row:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        role = guild.get_role(row["role_id"])
        member = guild.get_member(payload.user_id)
        if not role or not member or member.bot:
            return
        try:
            if add:
                await member.add_roles(role)
            else:
                await member.remove_roles(role)
        except Exception:
            pass

    rr = app_commands.Group(name="rr", description="Reaction role management")

    @rr.command(name="add", description="Add a reaction role")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_add(self, interaction: discord.Interaction, message_id: str, emoji: str, role: discord.Role):
        msg_id = int(message_id)
        try:
            msg = await interaction.channel.fetch_message(msg_id)
            await msg.add_reaction(emoji)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Error: {e}")
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO reaction_roles(guild_id,channel_id,message_id,emoji,role_id,role_name) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING",
                interaction.guild.id, interaction.channel.id, msg_id, emoji, role.id, role.name)
        await interaction.response.send_message(f"✅ {emoji} → {role.mention} added!")

    @rr.command(name="button", description="Create a button role message")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_button(self, interaction: discord.Interaction, role: discord.Role,
                        label: str = None, style: str = "primary"):
        style_map = {"primary": discord.ButtonStyle.primary, "success": discord.ButtonStyle.success,
                     "danger": discord.ButtonStyle.danger, "secondary": discord.ButtonStyle.secondary}
        btn_style = style_map.get(style, discord.ButtonStyle.primary)
        view = discord.ui.View(timeout=None)
        view.add_item(RoleButton(role.id, label or role.name, btn_style))
        msg = await interaction.channel.send(f"Click to get the **{role.name}** role!", view=view)
        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO button_roles(guild_id,channel_id,message_id,role_id,role_name,label,style) VALUES($1,$2,$3,$4,$5,$6,$7)",
                interaction.guild.id, interaction.channel.id, msg.id, role.id, role.name, label or role.name, style)
        await interaction.response.send_message("✅ Button role created!", ephemeral=True)

    @rr.command(name="dropdown", description="Create a dropdown role selector")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_dropdown(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Mention the roles you want in the dropdown (space-separated role mentions):", ephemeral=True)
        def check(m): return m.author == interaction.user and m.channel == interaction.channel
        try:
            msg = await self.bot.wait_for("message", check=check, timeout=30)
            roles = msg.role_mentions
            if not roles:
                return await interaction.followup.send("❌ No roles mentioned.", ephemeral=True)
            view = discord.ui.View(timeout=None)
            view.add_item(RoleDropdown(roles))
            sent = await interaction.channel.send("🎭 Select a role:", view=view)
            await msg.delete()
            await interaction.followup.send(f"✅ Dropdown created with {len(roles)} roles!", ephemeral=True)
        except Exception:
            await interaction.followup.send("❌ Timed out.", ephemeral=True)

    @rr.command(name="list", description="List all reaction roles")
    @app_commands.default_permissions(manage_roles=True)
    async def rr_list(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM reaction_roles WHERE guild_id=$1", interaction.guild.id)
            btn_rows = await conn.fetch("SELECT * FROM button_roles WHERE guild_id=$1", interaction.guild.id)
        embed = discord.Embed(title="Reaction & Button Roles", color=discord.Color.blurple())
        for row in rows:
            embed.add_field(name=f"{row['emoji']} → {row['role_name']}", value=f"Message: `{row['message_id']}`", inline=False)
        for row in btn_rows:
            embed.add_field(name=f"🔘 Button → {row['role_name']}", value=f"Label: {row['label']}", inline=False)
        if not rows and not btn_rows:
            embed.description = "No reaction/button roles set up."
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(ReactionRoles(bot))
