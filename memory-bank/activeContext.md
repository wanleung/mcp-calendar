# Active Context

## Current Focus
- Calendar MCP Service — Apple Calendar Feature Parity (initial build completed)
- FastAPI-based Calendar MCP service with HTTP MCP protocol supporting Google Calendar and Outlook Calendar providers
- Webhook manager for real-time notifications and notification service for RSVP flows
- CalendarChangeEvent data model with full provider_metadata
- Background scheduler for webhook subscription renewal (48-hour expiry check)

## Recent Changes
- Architecture design document creation (missing module breakdown, data flows, security model, acceptance matrix)
- Decision needed: build fresh MVP vs evolve existing codebase
- Pipeline run completed brainstorming/design phase for MCP Email Service errors module
- Error handling strategy selected: Option B (Consolidate + MCP mapping)
- PRD drafted defining MCP tools for email operations

## Immediate Next Steps
1. Fix `src/models/notification.py` models (NotificationEvent, WebhookSubscription) — blocking core functionality
2. Review and address security concerns from code review comments
3. Implement comprehensive error handling throughout all modules
4. Cross-reference full PRD to verify all user stories covered (Power User, Team Coordinator, Developer personas)
5. Identify missing Apple Calendar features from full PRD spec
6. Run linter and code review on actual source code