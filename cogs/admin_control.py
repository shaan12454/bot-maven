import discord
from discord.ext import commands
from discord import app_commands
from utils.permissions import is_bot_admin

class AdminControl(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="addadmin", description="Add a user as a bot admin")
    async def add_admin(self, interaction: discord.Interaction, user: discord.Member):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO bot_admins (guild_id, user_id, added_by)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, user_id) DO NOTHING
            """, interaction.guild.id, user.id, interaction.user.id)
        
        await interaction.response.send_message(f"✅ Added {user.mention} as a bot admin for this guild.")

    @app_commands.command(name="removeadmin", description="Remove a user from bot admins")
    async def remove_admin(self, interaction: discord.Interaction, user: discord.Member):
        if not await is_bot_admin(self.bot, interaction.guild, interaction.user):
            return await interaction.response.send_message("❌ You need to be a bot admin to use this command.", ephemeral=True)
        
        if user.id == interaction.guild.owner_id:
            return await interaction.response.send_message("❌ You cannot remove the guild owner from admins.", ephemeral=True)

        async with self.bot.db.acquire() as conn:
            await conn.execute("DELETE FROM bot_admins WHERE guild_id=$1 AND user_id=$2", interaction.guild.id, user.id)
        
        await interaction.response.send_message(f"✅ Removed {user.mention} from bot admins.")

    @app_commands.command(name="listadmins", description="List all bot admins for this guild")
    async def list_admins(self, interaction: discord.Interaction):
        async with self.bot.db.acquire() as conn:
            rows = await conn.fetch("SELECT user_id FROM bot_admins WHERE guild_id=$1", interaction.guild.id)
            cfg = await conn.fetchrow("SELECT bot_admin_role FROM guild_config WHERE guild_id=$1", interaction.guild.id)
        
        admin_role = interaction.guild.get_role(cfg["bot_admin_role"]) if cfg and cfg["bot_admin_role"] else None
        
        embed = discord.Embed(title="🛡️ Bot Administrators", color=discord.Color.blue())
        
        admin_list = []
        for r in rows:
            member = interaction.guild.get_member(r["user_id"])
            name = member.mention if member else f"User {r['user_id']}"
            admin_list.append(name)
        
        embed.add_field(name="Individual Admins", value=", ".join(admin_list) if admin_list else "None", inline=False)
        embed.add_field(name="Bot Admin Role", value=admin_role.mention if admin_role else "Not set", inline=False)
        embed.add_field(name="Guild Owner", value=interaction.guild.owner.mention, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setadminrole", description="Set the role that grants bot admin access")
    async def set_admin_role(self, interaction: discord.Interaction, role: discord.Role):
        if interaction.user.id != interaction.guild.owner_id:
            return await interaction.response.send_message("❌ Only the guild owner can use this command.", ephemeral=True)
        
        async with self.bot.db.acquire() as conn:
            await conn.execute("""
                INSERT INTO guild_config (guild_id, bot_admin_role) VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE SET bot_admin_role = $2
            """, interaction.guild.id, role.id)
        
        await interaction.response.send_message(f"✅ Set {role.mention} as the bot admin role.")

async def setup(bot):
    await bot.add_cog(AdminControl(bot))
