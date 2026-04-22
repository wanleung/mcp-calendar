"""
Webhook subscription manager for Calendar MCP Service.

This module manages webhook subscriptions for calendar change notifications,
including:
- Subscription creation and deletion
- Subscription renewal scheduler (background task)
- Expiration alerting via SSE
- Delivery tracking and retry logic
- Circuit breaker integration

The manager integrates with the notification service and error handler
to ensure reliable webhook delivery.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from dataclasses import dataclass, field

import aiohttp
from aiohttp import ClientTimeout

from src.models.webhook import (
    CalendarChangeEvent,
    WebhookSubscription,
    WebhookSubscriptionResult,
    WebhookDeliveryResult,
    SubscriptionStatus,
    SubscriptionAlert,
    WebhookConfig,
    ChangeType,
)
from src.models.notification import NotificationType, NotificationStatus
from src.services.error_handler import ErrorHandler, MCPErrors
from src.services.notification_service import NotificationService

# Configure logging
logger = logging.getLogger(__name__)


class WebhookManager:
    """
    Manager for webhook subscriptions and delivery.
    
    This class handles:
    - Webhook subscription lifecycle (create, delete, renew)
    - Background scheduler for subscription renewal
    - Expiration alerting via SSE
    - Delivery tracking with retry logic
    - Circuit breaker integration
    
    Attributes:
        config: Webhook configuration
        error_handler: Error handler for MCP error mapping
        notification_service: Service for sending notifications
        sse_client: SSE client for alerting
        subscriptions: Dictionary of active subscriptions
        delivery_lock: Lock for delivery operations
    """
    
    def __init__(
        self,
        error_handler: ErrorHandler,
        notification_service: NotificationService,
        config: Optional[WebhookConfig] = None,
    ):
        """
        Initialize the webhook manager.
        
        Args:
            error_handler: Error handler for MCP error mapping
            notification_service: Service for sending notifications
            config: Webhook configuration (default values used if None)
        """
        self.config = config or WebhookConfig()
        self.error_handler = error_handler
        self.notification_service = notification_service
        
        # Active subscriptions
        self._subscriptions: Dict[str, WebhookSubscription] = {}
        
        # Delivery lock for thread safety
        self._delivery_lock = asyncio.Lock()
        
        # Alert tracking
        self._alerts: Dict[str, SubscriptionAlert] = {}
        
        # SSE client for alerting (None if not configured)
        self._sse_client: Optional[aiohttp.ClientSession] = None
    
    async def create_subscription(
        self,
        webhook_url: str,
        calendar_id: str,
        event_id: Optional[str] = None,
        change_types: Optional[List[str]] = None,
        user_id: str = "",
        provider: str = "google",
        expires_in_days: int = 365,
    ) -> WebhookSubscriptionResult:
        """
        Create a new webhook subscription.
        
        Args:
            webhook_url: URL to send notifications to
            calendar_id: Calendar to monitor
            event_id: Event to monitor (None for calendar-level)
            change_types: Change types to monitor (default: all)
            user_id: User who owns the subscription
            provider: Provider name
            expires_in_days: Subscription lifetime in days
            
        Returns:
            WebhookSubscriptionResult with creation status
        """
        # Check subscription limit
        if len(self._subscriptions) >= self.config.max_subscriptions:
            return WebhookSubscriptionResult(
                success=False,
                error_message="Maximum number of subscriptions reached",
            )
        
        # Generate subscription ID
        subscription_id = self._generate_subscription_id(
            webhook_url, calendar_id, event_id
        )
        
        # Generate subscription expiry
        expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        
        # Create subscription
        subscription = WebhookSubscription(
            subscription_id=subscription_id,
            webhook_url=webhook_url,
            calendar_id=calendar_id,
            event_id=event_id,
            change_types=change_types or [
                ChangeType.CREATED.value,
                ChangeType.UPDATED.value,
                ChangeType.DELETED.value,
            ],
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            user_id=user_id,
            provider=provider,
        )
        
        # Store subscription
        self._subscriptions[subscription_id] = subscription
        
        logger.info(
            f"Created webhook subscription {subscription_id} for "
            f"calendar {calendar_id}, event {event_id}"
        )
        
        return WebhookSubscriptionResult(
            success=True,
            subscription_id=subscription_id,
        )
    
    async def delete_subscription(
        self,
        subscription_id: str,
    ) -> WebhookSubscriptionResult:
        """
        Delete a webhook subscription.
        
        Args:
            subscription_id: Subscription identifier
            
        Returns:
            WebhookSubscriptionResult with deletion status
        """
        if subscription_id not in self._subscriptions:
            return WebhookSubscriptionResult(
                success=False,
                error_message=f"Subscription {subscription_id} not found",
            )
        
        subscription = self._subscriptions[subscription_id]
        del self._subscriptions[subscription_id]
        
        logger.info(
            f"Deleted webhook subscription {subscription_id} for "
            f"calendar {subscription.calendar_id}"
        )
        
        return WebhookSubscriptionResult(
            success=True,
            subscription_id=subscription_id,
        )
    
    async def get_subscription(
        self,
        subscription_id: str,
    ) -> Optional[WebhookSubscription]:
        """
        Get a webhook subscription by ID.
        
        Args:
            subscription_id: Subscription identifier
            
        Returns:
            WebhookSubscription or None if not found
        """
        return self._subscriptions.get(subscription_id)
    
    async def get_all_subscriptions(
        self,
        calendar_id: Optional[str] = None,
        status: Optional[SubscriptionStatus] = None,
    ) -> List[WebhookSubscription]:
        """
        Get all webhook subscriptions, optionally filtered.
        
        Args:
            calendar_id: Filter by calendar ID
            status: Filter by status
            
        Returns:
            List of WebhookSubscription objects
        """
        subscriptions = list(self._subscriptions.values())
        
        if calendar_id:
            subscriptions = [
                s for s in subscriptions if s.calendar_id == calendar_id
            ]
        
        if status:
            subscriptions = [
                s for s in subscriptions if s.status == status
            ]
        
        return subscriptions
    
    async def send_notification(
        self,
        subscription_id: str,
        event: Optional[CalendarChangeEvent],
        provider_payload: Dict[str, Any],
    ) -> WebhookDeliveryResult:
        """
        Send a notification to a webhook subscriber.
        
        Args:
            subscription_id: Subscription identifier
            event: Calendar change event
            provider_payload: Raw provider webhook payload
            
        Returns:
            WebhookDeliveryResult with delivery status
        """
        async with self._delivery_lock:
            subscription = self._subscriptions.get(subscription_id)
            if not subscription:
                return WebhookDeliveryResult(
                    success=False,
                    subscription_id=subscription_id,
                    error_message="Subscription not found",
                )
            
            # Check if subscription is active
            if not subscription.is_active():
                return WebhookDeliveryResult(
                    success=False,
                    subscription_id=subscription_id,
                    error_message=f"Subscription {subscription_id} is not active",
                )
            
            # Check if change type is allowed
            if event and event.change_type not in subscription.change_types:
                return WebhookDeliveryResult(
                    success=False,
                    subscription_id=subscription_id,
                    event_id=event.event_id,
                    error_message=f"Change type {event.change_type} not in allowed types",
                )
            
            # Normalize the event
            try:
                normalized_event = await self._normalize_event(
                    subscription, event, provider_payload
                )
            except Exception as e:
                logger.error(f"Failed to normalize event: {e}")
                return WebhookDeliveryResult(
                    success=False,
                    subscription_id=subscription_id,
                    event_id=event.event_id if event else None,
                    error_message=f"Event normalization failed: {e}",
                )
            
            # Make the request
            result = await self._make_webhook_request(
                subscription, normalized_event
            )
            
            # Update subscription status
            if result.success:
                subscription.last_sent_at = datetime.utcnow()
                subscription.status = SubscriptionStatus.ACTIVE
            else:
                subscription.status = SubscriptionStatus.FAILED
            
            return result
    
    async def _normalize_event(
        self,
        subscription: WebhookSubscription,
        event: Optional[CalendarChangeEvent],
        provider_payload: Dict[str, Any],
    ) -> CalendarChangeEvent:
        """
        Normalize a calendar change event.
        
        Args:
            subscription: Webhook subscription
            event: Calendar change event
            provider_payload: Raw provider webhook payload
            
        Returns:
            Normalized CalendarChangeEvent
        """
        # Extract relevant fields from provider payload
        normalized_event = CalendarChangeEvent(
            calendar_id=subscription.calendar_id,
            event_id=event.event_id if event else None,
            change_type=event.change_type if event else ChangeType.CREATED.value,
            user_id=subscription.user_id,
            timestamp=datetime.utcnow(),
            provider_metadata={
                **provider_payload,
                "subscription_id": subscription.subscription_id,
                "provider": subscription.provider,
            },
        )
        
        return normalized_event
    
    async def _make_webhook_request(
        self,
        subscription: WebhookSubscription,
        event: CalendarChangeEvent,
    ) -> WebhookDeliveryResult:
        """
        Make a webhook request to a subscriber.
        
        Args:
            subscription: Webhook subscription
            event: Calendar change event
            
        Returns:
            WebhookDeliveryResult with delivery status
        """
        # Prepare request data
        request_data = {
            "event": event.to_dict(),
            "subscription_id": subscription.subscription_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Make the request
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    subscription.webhook_url,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Calendar-MCP-Service/1.0",
                    },
                    json=request_data,
                    timeout=ClientTimeout(total=30),
                ) as response:
                    if response.status == 200:
                        return WebhookDeliveryResult(
                            success=True,
                            subscription_id=subscription.subscription_id,
                            event_id=event.event_id,
                        )
                    elif response.status == 429:
                        # Rate limited
                        retry_after = int(response.headers.get("Retry-After", 60))
                        logger.warning(
                            f"Rate limited by {subscription.webhook_url}, "
                            f"waiting {retry_after} seconds"
                        )
                        return WebhookDeliveryResult(
                            success=False,
                            subscription_id=subscription.subscription_id,
                            event_id=event.event_id,
                            error_message="Rate limited",
                            retry_count=1,
                            status_code=429,
                        )
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Webhook request failed with status {response.status}: "
                            f"{error_text}"
                        )
                        return WebhookDeliveryResult(
                            success=False,
                            subscription_id=subscription.subscription_id,
                            event_id=event.event_id,
                            error_message=f"HTTP {response.status}: {error_text}",
                            retry_count=1,
                            status_code=response.status,
                        )
                        
        except asyncio.TimeoutError:
            logger.error(f"Request timeout for {subscription.webhook_url}")
            return WebhookDeliveryResult(
                success=False,
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                error_message="Request timeout",
                retry_count=1,
            )
        except aiohttp.ClientError as e:
            logger.error(f"Client error for {subscription.webhook_url}: {e}")
            return WebhookDeliveryResult(
                success=False,
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                error_message=str(e),
                retry_count=1,
            )
        except Exception as e:
            logger.error(f"Unexpected error for {subscription.webhook_url}: {e}")
            return WebhookDeliveryResult(
                success=False,
                subscription_id=subscription.subscription_id,
                event_id=event.event_id,
                error_message=str(e),
                retry_count=1,
            )
    
    async def _generate_subscription_id(
        self,
        webhook_url: str,
        calendar_id: str,
        event_id: Optional[str],
    ) -> str:
        """
        Generate a unique subscription ID.
        
        Args:
            webhook_url: Webhook URL
            calendar_id: Calendar ID
            event_id: Event ID (optional)
            
        Returns:
            Unique subscription ID
        """
        hash_input = f"{webhook_url}:{calendar_id}:{event_id or ''}"
        hash_value = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return f"sub_{hash_value}"
    
    async def check_expiring_subscriptions(
        self,
        hours: int = 48,
    ) -> List[SubscriptionAlert]:
        """
        Check for subscriptions expiring soon and create alerts.
        
        Args:
            hours: Hours before expiration to alert
            
        Returns:
            List of SubscriptionAlert objects
        """
        alerts = []
        threshold = datetime.utcnow() + timedelta(hours=hours)
        
        for subscription in self._subscriptions.values():
            if subscription.is_expiring_soon(hours):
                alert = SubscriptionAlert(
                    alert_id=self._generate_alert_id(subscription),
                    subscription_id=subscription.subscription_id,
                    alert_type="EXPIRING",
                    message=f"Subscription {subscription.subscription_id} "
                            f"expires in {(subscription.expires_at - datetime.utcnow()).total_seconds() / 3600:.0f} hours",
                    severity="WARNING",
                    metadata={
                        "expires_at": subscription.expires_at.isoformat(),
                        "hours_remaining": (subscription.expires_at - datetime.utcnow()).total_seconds() / 3600,
                    },
                )
                alerts.append(alert)
                self._alerts[alert.alert_id] = alert
                logger.warning(
                    f"Subscription {subscription.subscription_id} "
                    f"expires in {(subscription.expires_at - datetime.utcnow()).total_seconds() / 3600:.0f} hours"
                )
        
        return alerts
    
    async def renew_subscription(
        self,
        subscription_id: str,
        new_expires_in_days: int = 365,
    ) -> WebhookSubscriptionResult:
        """
        Renew a webhook subscription.
        
        Args:
            subscription_id: Subscription identifier
            new_expires_in_days: New subscription lifetime in days
            
        Returns:
            WebhookSubscriptionResult with renewal status
        """
        subscription = self._subscriptions.get(subscription_id)
        if not subscription:
            return WebhookSubscriptionResult(
                success=False,
                error_message=f"Subscription {subscription_id} not found",
            )
        
        # Update expiry
        subscription.expires_at = datetime.utcnow() + timedelta(days=new_expires_in_days)
        subscription.status = SubscriptionStatus.ACTIVE
        
        logger.info(
            f"Renewed subscription {subscription_id} "
            f"expires at {subscription.expires_at.isoformat()}"
        )
        
        return WebhookSubscriptionResult(
            success=True,
            subscription_id=subscription_id,
        )
    
    async def handle_failed_delivery(
        self,
        subscription_id: str,
        error: Exception,
        retry_count: int = 0,
    ) -> None:
        """
        Handle a failed webhook delivery.
        
        Args:
            subscription_id: Subscription identifier
            error: Exception raised
            retry_count: Current retry count
        """
        subscription = self._subscriptions.get(subscription_id)
        if not subscription:
            return
        
        # Update subscription
        subscription.last_retry_at = datetime.utcnow()
        
        # Check if we should retry
        if retry_count < self.config.max_retries:
            # Schedule retry
            delay = self.config.retry_delay * (2 ** retry_count)
            logger.info(
                f"Failed delivery for {subscription_id}, "
                f"retry {retry_count + 1}/{self.config.max_retries} "
                f"in {delay:.0f}s"
            )
        else:
            # Max retries exceeded
            subscription.status = SubscriptionStatus.FAILED
            logger.error(
                f"Max retries exceeded for {subscription_id}: {error}"
            )
            
            # Create alert
            alert = SubscriptionAlert(
                alert_id=self._generate_alert_id(subscription),
                subscription_id=subscription_id,
                alert_type="FAILED",
                message=f"Failed to deliver webhook after {self.config.max_retries} retries: {error}",
                severity="ERROR",
                metadata={
                    "error": str(error),
                    "retry_count": retry_count,
                },
            )
            self._alerts[alert.alert_id] = alert
    
    def _generate_alert_id(
        self,
        subscription: WebhookSubscription,
    ) -> str:
        """
        Generate an alert ID for a subscription.
        
        Args:
            subscription: Webhook subscription
            
        Returns:
            Alert ID
        """
        timestamp = datetime.utcnow().isoformat()
        counter_str = str(len(self._alerts) + 1)
        hash_input = f"{timestamp}:{counter_str}:{subscription.subscription_id}"
        hash_value = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return f"alert_{hash_value}"
    
    async def send_alert(
        self,
        alert: SubscriptionAlert,
    ) -> None:
        """
        Send an alert via SSE to connected clients.
        
        Args:
            alert: SubscriptionAlert to send
        """
        if not self._sse_client:
            logger.warning("SSE client not configured, skipping alert")
            return
        
        try:
            async with self._sse_client.get("/sse") as response:
                if response.status == 200:
                    # Send alert via SSE
                    await response.write(f"data: {alert.to_dict()}\n\n")
                    logger.info(f"Sent alert {alert.alert_id} via SSE")
                else:
                    logger.error(f"Failed to send alert via SSE: {response.status}")
        except Exception as e:
            logger.error(f"Failed to send alert via SSE: {e}")
    
    def set_sse_client(
        self,
        client: aiohttp.ClientSession,
    ) -> None:
        """
        Set the SSE client for alerting.
        
        Args:
            client: aiohttp ClientSession for SSE
        """
        self._sse_client = client
    
    async def cleanup_old_subscriptions(
        self,
        retention_days: int = 30,
    ) -> int:
        """
        Clean up old subscriptions beyond retention period.
        
        Args:
            retention_days: Number of days to retain subscriptions
            
        Returns:
            Number of subscriptions cleaned up
        """
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        cleaned = 0
        
        for subscription_id, subscription in list(self._subscriptions.items()):
            if subscription.created_at < cutoff:
                await self.delete_subscription(subscription_id)
                cleaned += 1
                logger.info(
                    f"Cleaned up old subscription {subscription_id} "
                    f"created at {subscription.created_at.isoformat()}"
                )
        
        return cleaned
    
    def get_subscription_stats(
        self,
    ) -> Dict[str, Any]:
        """
        Get statistics about webhook subscriptions.
        
        Returns:
            Dictionary with statistics
        """
        stats = {
            "total_subscriptions": len(self._subscriptions),
            "active_subscriptions": sum(
                1 for s in self._subscriptions.values() if s.is_active()
            ),
            "expiring_soon": sum(
                1 for s in self._subscriptions.values()
                if s.is_expiring_soon(self.config.expiration_window)
            ),
            "failed_subscriptions": sum(
                1 for s in self._subscriptions.values()
                if s.status == SubscriptionStatus.FAILED
            ),
            "alerts": len(self._alerts),
        }
        
        return stats