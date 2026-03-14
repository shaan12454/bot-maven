# Teen Maven Ranks Bot

A Discord bot + web dashboard for the Teen Maven server. Backend runs on Railway, dashboard on Lovable.

## Required Environment Variables

### Bot (Railway service)

| Variable | Description |
|----------|-------------|
| `DISCORD_TOKEN` | Bot token from [Discord Developer Portal](https://discord.com/developers/applications) |
| `DATABASE_URL` | Auto-set by the Railway Postgres plugin |
| `API_SECRET` | A long random string — **must match `VITE_API_KEY` in the dashboard** |
| `DASHBOARD_ORIGIN` | Full URL of your deployed dashboard e.g. `https://yourapp.lovable.app` |
| `PORT` | Auto-set by Railway (defaults to `8080`) |

### Dashboard (Lovable / `.env.local`)

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Full URL of your Railway bot deployment e.g. `https://yourbot.up.railway.app` |
| `VITE_API_KEY` | **Same value as `API_SECRET` above** |

## Deployment

### Bot (Railway)
1. Connect your `bot-maven` GitHub repo to Railway
2. Set all env vars above in the Railway service settings
3. Railway auto-deploys on push to `main`

### Dashboard (Lovable)
1. Set `VITE_API_URL` and `VITE_API_KEY` in the Lovable project settings
2. Deploy from your `guild-manager-dashboard` repo

## Architecture
- **Bot** (`bot.py`) — discord.py bot with cogs, also runs an aiohttp REST API server
- **API** (`api.py`) — REST API served by the bot, reads/writes PostgreSQL
- **Dashboard** — React/Vite/TypeScript frontend, calls the bot API
- **Database** — PostgreSQL (Railway plugin), tables auto-created on bot startup
