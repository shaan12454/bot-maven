import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import yt_dlp
from collections import defaultdict, deque


YTDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}
FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class MusicQueue:
    def __init__(self):
        self.queue: deque = deque()
        self.current = None
        self.loop = False
        self.volume = 1.0


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._queues: dict[int, MusicQueue] = {}

    def _get_q(self, guild_id) -> MusicQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = MusicQueue()
        return self._queues[guild_id]

    async def _ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        if not interaction.user.voice:
            await interaction.response.send_message("❌ You must be in a voice channel!", ephemeral=True)
            return None
        vc = interaction.guild.voice_client
        if not vc:
            vc = await interaction.user.voice.channel.connect()
        elif vc.channel != interaction.user.voice.channel:
            await vc.move_to(interaction.user.voice.channel)
        return vc

    def _play_next(self, guild_id: int, vc: discord.VoiceClient):
        q = self._get_q(guild_id)
        if q.loop and q.current:
            track = q.current
        elif q.queue:
            track = q.queue.popleft()
            q.current = track
        else:
            q.current = None
            return
        source = discord.FFmpegPCMAudio(track["url"], **FFMPEG_OPTS)
        source = discord.PCMVolumeTransformer(source, volume=q.volume)
        vc.play(source, after=lambda e: self._play_next(guild_id, vc))

    @app_commands.command(name="play", description="Play a song from YouTube/Spotify")
    @app_commands.describe(query="Song name or URL")
    async def play(self, interaction: discord.Interaction, query: str):
        vc = await self._ensure_voice(interaction)
        if not vc:
            return
        await interaction.response.defer()
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ytdl:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=False))
        if "entries" in data:
            data = data["entries"][0]
        track = {"url": data["url"], "title": data.get("title", "Unknown"), "duration": data.get("duration", 0)}
        q = self._get_q(interaction.guild.id)
        q.queue.append(track)
        if not vc.is_playing():
            self._play_next(interaction.guild.id, vc)
            await interaction.followup.send(f"▶️ Now playing: **{track['title']}**")
        else:
            await interaction.followup.send(f"📋 Added to queue: **{track['title']}** (position #{len(q.queue)})")

    @app_commands.command(name="skip", description="Skip current song")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("⏭️ Skipped!")
        else:
            await interaction.response.send_message("❌ Nothing playing.")

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Paused.")
        else:
            await interaction.response.send_message("❌ Nothing playing.")

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc and vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed.")
        else:
            await interaction.response.send_message("❌ Nothing paused.")

    @app_commands.command(name="stop", description="Stop music and clear queue")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if vc:
            self._get_q(interaction.guild.id).queue.clear()
            vc.stop()
            await vc.disconnect()
            await interaction.response.send_message("⏹️ Stopped and disconnected.")
        else:
            await interaction.response.send_message("❌ Not in a voice channel.")

    @app_commands.command(name="queue", description="Show music queue")
    async def queue(self, interaction: discord.Interaction):
        q = self._get_q(interaction.guild.id)
        embed = discord.Embed(title="🎵 Music Queue", color=discord.Color.purple())
        if q.current:
            embed.add_field(name="Now Playing", value=q.current["title"], inline=False)
        if q.queue:
            tracks = list(q.queue)[:10]
            embed.add_field(name="Up Next", value="\n".join(f"`{i+1}.` {t['title']}" for i, t in enumerate(tracks)), inline=False)
        else:
            embed.description = "Queue is empty."
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loop", description="Toggle loop mode")
    async def loop(self, interaction: discord.Interaction):
        q = self._get_q(interaction.guild.id)
        q.loop = not q.loop
        await interaction.response.send_message(f"🔁 Loop {'enabled' if q.loop else 'disabled'}.")

    @app_commands.command(name="volume", description="Set volume (0-100)")
    async def volume(self, interaction: discord.Interaction, level: int):
        vc = interaction.guild.voice_client
        q = self._get_q(interaction.guild.id)
        q.volume = max(0, min(level, 100)) / 100
        if vc and vc.source:
            vc.source.volume = q.volume
        await interaction.response.send_message(f"🔊 Volume set to {level}%")


async def setup(bot):
    await bot.add_cog(Music(bot))
