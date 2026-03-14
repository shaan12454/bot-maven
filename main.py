"""
main.py — Starts both the Discord bot and the REST API server in one process.
Railway should be configured to run: python main.py
"""
import asyncio
import os
import logging
import discord
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    # Import here to avoid circular imports
    from bot import TeenMavenBot
    from api import create_app

    bot = TeenMavenBot()

    # Start the aiohttp API server
    api_app = await create_app(bot)
    runner = web.AppRunner(api_app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"API server started on port {port}")

    # Start the bot (this blocks until bot closes)
    async with bot:
        await bot.start(os.getenv("DISCORD_TOKEN"))

    # Cleanup API when bot stops
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
