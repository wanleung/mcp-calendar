"""
Background scheduler for webhook subscription renewal.

This module provides background tasks for:
- Checking expiring subscriptions
- Auto-renewing subscriptions within renewal window
- Alerting on failed renewals via SSE
- Daily subscription health checks

The scheduler runs as a background task in FastAPI lifespan.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable

from src.models.webhook import SubscriptionAlert, SubscriptionStatus
from src.services.webhook_manager import WebhookManager

# Configure logging
logger = logging.getLogger(__name__)


class Scheduler:
    """
    Background scheduler for webhook subscription management.
    
    This class handles:
    - Daily subscription health checks
    - Expiring subscription detection
    - Auto-renewal within renewal window
    - Alert generation for failures
    
    Attributes:
        webhook_manager: Webhook manager for subscription operations
        check_interval: Interval between health checks in seconds
        renewal_window: Hours before expiration to auto-renew
        expiration_window: Hours before expiration to alert
    """
    
    def __init__(
        self,
        webhook_manager: WebhookManager,
        check_interval: int = 3600,  # 1 hour
        renewal_window: int = 48,
        expiration_window: int = 48,
    ):
        """
        Initialize the scheduler.
        
        Args:
            webhook_manager: Webhook manager for subscription operations
            check_interval: Interval between health checks in seconds
            renewal_window: Hours before expiration to auto-renew
            expiration_window: Hours before expiration to alert
        """
        self.webhook_manager = webhook_manager
        self.check_interval = check_interval
        self.renewal_window = renewal_window
        self.expiration_window = expiration_window
        
        # Task for running the scheduler
        self._scheduler_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """
        Start the scheduler.
        
        This should be called from FastAPI lifespan.
        """
        logger.info("Starting webhook subscription scheduler")
        self._running = True
        self._scheduler_task = asyncio.create_task(self._run_scheduler())
    
    async def stop(self) -> None:
        """
        Stop the scheduler.
        """
        logger.info("Stopping webhook subscription scheduler")
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
    
    async def _run_scheduler(self) -> None:
        """
        Main scheduler loop.
        
        This runs continuously, checking for expiring subscriptions
        and performing auto-renewal.
        """
        while self._running:
            try:
                await self._check_subscriptions()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            
            # Wait for next check interval
            await asyncio.sleep(self.check_interval)
    
    async def _check_subscriptions(self) -> None:
        """
        Check for expiring subscriptions and perform actions.
        """
        # Check for expiring subscriptions
        alerts = await self.webhook_manager.check_expiring_subscriptions(
            hours=self.renewal_window
        )
        
        for alert in alerts:
            # Determine action based on time remaining
            time_remaining = (
                alert.metadata.get("hours_remaining", 0)
            )
            
            if time_remaining <= 24:
                # Auto-renew if within 24 hours
                await self._auto_renew_subscription(
                    alert.subscription_id,
                    new_expires_in_days=365
                )
            elif time_remaining <= self.renewal_window:
                # Alert if within renewal window
                await self.webhook_manager.send_alert(alert)
        
        # Check for failed subscriptions
        failed_subscriptions = await self._check_failed_subscriptions()
        
        # Cleanup old subscriptions
        await self.webhook_manager.cleanup_old_subscriptions(
            retention_days=30
        )
    
    async def _auto_renew_subscription(
        self,
        subscription_id: str,
        new_expires_in_days: int = 365,
    ) -> None:
        """
        Auto-renew a subscription.
        
        Args:
            subscription_id: Subscription identifier
            new_expires_in_days: New subscription lifetime in days
        """
        result = await self.webhook_manager.renew_subscription(
            subscription_id=subscription_id,
            new_expires_in_days=new_expires_in_days,
        )
        
        if result.success:
            logger.info(
                f"Auto-renewed subscription {subscription_id} "
                f"expires at {await self._get_subscription_expiry(subscription_id)}"
            )
        else:
            logger.error(
                f"Failed to auto-renew subscription {subscription_id}: "
                f"{result.error_message}"
            )
            
            # Create alert for failed renewal
            subscription = await self.webhook_manager.get_subscription(subscription_id)
            if subscription:
                alert = SubscriptionAlert(
                    alert_id=self._generate_alert_id(subscription),
                    subscription_id=subscription_id,
                    alert_type="RENEWAL_FAILED",
                    message=f"Failed to auto-renew subscription: {result.error_message}",
                    severity="ERROR",
                    metadata={
                        "error": result.error_message,
                    },
                )
                await self.webhook_manager.send_alert(alert)
    
    async def _check_failed_subscriptions(self) -> list:
        """
        Check for failed subscriptions and alert.
        
        Returns:
            List of failed subscription IDs
        """
        failed_ids = []
        
        for subscription in self.webhook_manager._subscriptions.values():
            if subscription.status == SubscriptionStatus.FAILED:
                failed_ids.append(subscription.subscription_id)
                logger.error(
                    f"Subscription {subscription.subscription_id} "
                    f"has failed status"
                )
        
        return failed_ids
    
    async def _get_subscription_expiry(
        self,
        subscription_id: str,
    ) -> Optional[str]:
        """
        Get the expiry time for a subscription.
        
        Args:
            subscription_id: Subscription identifier
            
        Returns:
            Expiry time as ISO string or None
        """
        subscription = await self.webhook_manager.get_subscription(subscription_id)
        if subscription:
            return subscription.expires_at.isoformat()
        return None
    
    def _generate_alert_id(
        self,
        subscription: Optional[SubscriptionAlert],
    ) -> str:
        """
        Generate an alert ID.
        
        Args:
            subscription: Subscription or alert
            
        Returns:
            Alert ID
        """
        if subscription:
            return subscription.alert_id
        return ""
    
    async def manual_check(
        self,
        hours: int = 48,
    ) -> None:
        """
        Manually trigger a subscription check.
        
        Args:
            hours: Hours before expiration to check
        """
        logger.info(f"Manual subscription check for subscriptions expiring in {hours} hours")
        alerts = await self.webhook_manager.check_expiring_subscriptions(hours=hours)
        
        for alert in alerts:
            await self.webhook_manager.send_alert(alert)
        
        logger.info(f"Manual check complete, sent {len(alerts)} alerts")
    
    async def manual_renewal(
        self,
        subscription_id: str,
        new_expires_in_days: int = 365,
    ) -> bool:
        """
        Manually renew a subscription.
        
        Args:
            subscription_id: Subscription identifier
            new_expires_in_days: New subscription lifetime in days
            
        Returns:
            True if renewal succeeded
        """
        result = await self.webhook_manager.renew_subscription(
            subscription_id=subscription_id,
            new_expires_in_days=new_expires_in_days,
        )
        
        if result.success:
            logger.info(f"Manually renewed subscription {subscription_id}")
            return True
        else:
            logger.error(f"Failed to manually renew subscription {subscription_id}: {result.error_message}")
            return False