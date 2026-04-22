# System Patterns

## Architecture
- **FastAPI-based MCP service** using HTTP MCP protocol
- **Multi-provider abstraction layer** for calendar APIs (Google Calendar, Outlook Calendar)
- **Webhook-driven real-time notifications** via webhook_manager.py
- **RSVP notification service** via notification_service.py (falls back to provider default behavior)

## Core Modules
- `webhook_manager.py` — manages webhook subscriptions, real-time notification handling
- `notification_service.py` — RSVP notification flows, fallback to provider auto-notify
- `src/models/notification.py` — data models (incomplete: missing NotificationEvent, WebhookSubscription)

## Data Models
- **CalendarChangeEvent**: calendar_id, event_id, change_type, user_id, timestamp, provider_metadata
- provider_metadata included for full debugging context

## Background Tasks
- **Webhook subscription renewal**: FastAPI lifespan task, daily check, auto-renews subscriptions expiring within 48 hours

## Design Decisions
- Multi-provider abstraction enables pluggable calendar backends
- RSVP notifications leverage provider default behavior (auto-notify organizer); notification_service.py serves as fallback
- Change events carry full provider_metadata for debugging