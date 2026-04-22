# Tech Context

## Stack
- **Python** — primary language
- **FastAPI** — web framework, lifespan task management
- **HTTP MCP protocol** — Model Context Protocol transport

## Calendar Providers
- Google Calendar API
- Outlook Calendar API

## Infrastructure
- Webhook subscriptions for real-time calendar event notifications
- Background scheduler for subscription renewal (daily cadence, 48-hour expiry threshold)

## Known Constraints
- Notification models incomplete — blocking subscribe_to_calendar and list_subscriptions MCP methods
- Security concerns flagged — must be resolved before production deployment
- Error handling not yet at production standards