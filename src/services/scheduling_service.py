"""
Scheduling service for token refresh locking and background tasks.

This module provides:
- Token refresh locking to prevent concurrent refresh storms
- Background task scheduling for subscription renewal
- Double-check pattern implementation for token operations
- Rate limiting for scheduled operations

The service integrates with OAuth manager to ensure thread-safe token refresh
operations and manages background tasks for webhook subscription maintenance.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, Set
from dataclasses import dataclass, field
from enum import Enum

import aiohttp

from src.models.webhook import SubscriptionAlert, SubscriptionStatus
from src.services.webhook_manager import WebhookManager
from src.services.error_handler import ErrorHandler, MCPErrors
from src.auth.oauth_manager import OAuthManager

# Configure logging
logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Types of scheduled tasks."""
    TOKEN_REFRESH = "token_refresh"
    SUBSCRIPTION_CHECK = "subscription_check"
    SUBSCRIPTION_RENEWAL = "subscription_renewal"
    ALERT_SEND = "alert_send"
    RATE_LIMIT_RESET = "rate_limit_reset"


class TaskStatus(Enum):
    """Status of a scheduled task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledTask:
    """
    Scheduled task for background operations.
    
    Attributes:
        task_id: Unique identifier for the task
        task_type: Type of scheduled task
        user_id: User associated with the task
        provider: Provider name (google, outlook)
        status: Current task status
        scheduled_at: When the task was scheduled
        started_at: When the task started
        completed_at: When the task completed
        error_message: Error message if task failed
        retry_count: Number of retry attempts
        max_retries: Maximum retry attempts allowed
        callback: Callback function to execute
        args: Arguments for the callback
    """
    task_id: str
    task_type: TaskType
    user_id: str
    provider: str
    status: TaskStatus = TaskStatus.PENDING
    scheduled_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    callback: Optional[Callable[..., Any]] = None
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RefreshLock:
    """
    Lock for token refresh operations.
    
    Attributes:
        key: Lock key (user_id:provider)
        lock: Asyncio lock instance
        acquired: Whether lock is currently acquired
        acquired_at: When lock was acquired
    """
    key: str
    lock: asyncio.Lock
    acquired: bool = False
    acquired_at: Optional[datetime] = None


@dataclass
class RefreshLockManager:
    """
    Manager for token refresh locks.
    
    This class manages refresh locks for different user/provider combinations
    to prevent concurrent token refresh storms.
    
    Attributes:
        locks: Dictionary of refresh locks
    """
    locks: Dict[str, RefreshLock] = field(default_factory=dict)
    
    async def acquire(
        self,
        user_id: str,
        provider: str,
    ) -> bool:
        """
        Acquire a refresh lock for a user/provider combination.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            True if lock acquired, False if already held
        """
        key = f"{user_id}:{provider}"
        
        if key not in self.locks:
            self.locks[key] = RefreshLock(
                key=key,
                lock=asyncio.Lock(),
            )
        
        lock = self.locks[key]
        
        # Double-check pattern: check if already acquired after acquiring lock
        async with lock.lock:
            if lock.acquired:
                return False
            
            lock.acquired = True
            lock.acquired_at = datetime.utcnow()
            return True
    
    async def release(
        self,
        user_id: str,
        provider: str,
    ) -> None:
        """
        Release a refresh lock.
        
        Args:
            user_id: User identifier
            provider: Provider name
        """
        key = f"{user_id}:{provider}"
        
        if key in self.locks:
            lock = self.locks[key]
            async with lock.lock:
                lock.acquired = False
                lock.acquired_at = None
    
    async def is_acquired(
        self,
        user_id: str,
        provider: str,
    ) -> bool:
        """
        Check if a lock is currently acquired.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            True if lock is acquired
        """
        key = f"{user_id}:{provider}"
        
        if key not in self.locks:
            return False
        
        lock = self.locks[key]
        async with lock.lock:
            return lock.acquired
    
    def get_lock(
        self,
        user_id: str,
        provider: str,
    ) -> Optional[RefreshLock]:
        """
        Get a refresh lock for a user/provider combination.
        
        Args:
            user_id: User identifier
            provider: Provider name
            
        Returns:
            RefreshLock or None if not found
        """
        return self.locks.get(f"{user_id}:{provider}")


class SchedulingService:
    """
    Service for scheduling and managing background tasks.
    
    This service handles:
    - Token refresh scheduling with locking
    - Subscription renewal scheduling
    - Alert sending scheduling
    - Rate limit reset scheduling
    - Task status tracking
    
    Attributes:
        webhook_manager: Webhook manager for subscription operations
        error_handler: Error handler for MCP error mapping
        oauth_manager: OAuth manager for token operations
        refresh_lock_manager: Manager for refresh locks
        tasks: Dictionary of scheduled tasks
        task_lock: Lock for task operations
    """
    
    def __init__(
        self,
        webhook_manager: WebhookManager,
        error_handler: ErrorHandler,
        oauth_manager: OAuthManager,
    ):
        """
        Initialize the scheduling service.
        
        Args:
            webhook_manager: Webhook manager for subscription operations
            error_handler: Error handler for MCP error mapping
            oauth_manager: OAuth manager for token operations
        """
        self.webhook_manager = webhook_manager
        self.error_handler = error_handler
        self.oauth_manager = oauth_manager
        
        # Refresh lock manager
        self.refresh_lock_manager = RefreshLockManager()
        
        # Scheduled tasks
        self._tasks: Dict[str, ScheduledTask] = {}
        
        # Task lock for thread safety
        self._task_lock = asyncio.Lock()
        
        # Running tasks
        self._running_tasks: Set[str] = set()
        
        # Task completion callbacks
        self._completion_callbacks: Dict[str, Callable[..., Any]] = {}
    
    async def schedule_token_refresh(
        self,
        user_id: str,
        provider: str,
        callback: Optional[Callable[..., Any]] = None,
    ) -> ScheduledTask:
        """
        Schedule a token refresh operation with locking.
        
        Args:
            user_id: User identifier
            provider: Provider name
            callback: Optional callback to execute on completion
            
        Returns:
            ScheduledTask object
        """
        task_id = self._generate_task_id(
            TaskType.TOKEN_REFRESH, user_id, provider
        )
        
        # Acquire refresh lock
        lock_acquired = await self.refresh_lock_manager.acquire(
            user_id=user_id,
            provider=provider,
        )
        
        if not lock_acquired:
            logger.warning(
                f"Token refresh already in progress for {user_id}:{provider}"
            )
            return ScheduledTask(
                task_id=task_id,
                task_type=TaskType.TOKEN_REFRESH,
                user_id=user_id,
                provider=provider,
                status=TaskStatus.FAILED,
                error_message="Refresh lock already held",
            )
        
        # Create task
        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.TOKEN_REFRESH,
            user_id=user_id,
            provider=provider,
            callback=callback,
        )
        
        # Store task
        async with self._task_lock:
            self._tasks[task_id] = task
        
        logger.info(
            f"Scheduled token refresh for {user_id}:{provider} "
            f"task {task_id}"
        )
        
        return task
    
    async def execute_token_refresh(
        self,
        task: ScheduledTask,
    ) -> bool:
        """
        Execute a token refresh operation.
        
        Args:
            task: ScheduledTask to execute
            
        Returns:
            True if refresh succeeded
        """
        task.started_at = datetime.utcnow()
        task.status = TaskStatus.RUNNING
        
        try:
            # Perform token refresh
            token = await self.oauth_manager.refresh_token(
                user_id=task.user_id,
                provider=task.provider,
            )
            
            if token:
                logger.info(
                    f"Token refresh succeeded for {task.user_id}:{task.provider} "
                    f"task {task.task_id}"
                )
                
                task.completed_at = datetime.utcnow()
                task.status = TaskStatus.COMPLETED
                
                # Execute callback if provided
                if task.callback:
                    await task.callback(task)
                
                return True
            else:
                logger.error(
                    f"Token refresh returned None for {task.user_id}:{task.provider} "
                    f"task {task.task_id}"
                )
                
                task.error_message = "Token refresh returned None"
                task.status = TaskStatus.FAILED
                return False
                
        except Exception as e:
            logger.error(
                f"Token refresh failed for {task.user_id}:{task.provider} "
                f"task {task.task_id}: {e}"
            )
            
            task.error_message = str(e)
            task.status = TaskStatus.FAILED
            task.retry_count += 1
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                # Schedule retry
                delay = 1.0 * (2 ** task.retry_count)
                logger.info(
                    f"Scheduling retry for token refresh task {task.task_id} "
                    f"in {delay:.0f}s"
                )
                await asyncio.sleep(delay)
                return await self.execute_token_refresh(task)
            else:
                logger.error(
                    f"Max retries exceeded for token refresh task {task.task_id}"
                )
                return False
    
    async def schedule_subscription_check(
        self,
        hours: int = 48,
        callback: Optional[Callable[..., Any]] = None,
    ) -> ScheduledTask:
        """
        Schedule a subscription check for expiring subscriptions.
        
        Args:
            hours: Hours before expiration to check
            callback: Optional callback to execute on completion
            
        Returns:
            ScheduledTask object
        """
        task_id = self._generate_task_id(
            TaskType.SUBSCRIPTION_CHECK, "system", "all"
        )
        
        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.SUBSCRIPTION_CHECK,
            user_id="system",
            provider="all",
            callback=callback,
        )
        
        # Store task
        async with self._task_lock:
            self._tasks[task_id] = task
        
        logger.info(
            f"Scheduled subscription check for subscriptions expiring in {hours} hours "
            f"task {task_id}"
        )
        
        return task
    
    async def execute_subscription_check(
        self,
        task: ScheduledTask,
    ) -> bool:
        """
        Execute a subscription check.
        
        Args:
            task: ScheduledTask to execute
            
        Returns:
            True if check succeeded
        """
        task.started_at = datetime.utcnow()
        task.status = TaskStatus.RUNNING
        
        try:
            # Check for expiring subscriptions
            alerts = await self.webhook_manager.check_expiring_subscriptions(
                hours=task.args.get('hours', 48)
            )
            
            # Send alerts
            for alert in alerts:
                await self.webhook_manager.send_alert(alert)
            
            logger.info(
                f"Subscription check completed, sent {len(alerts)} alerts "
                f"task {task.task_id}"
            )
            
            task.completed_at = datetime.utcnow()
            task.status = TaskStatus.COMPLETED
            
            # Execute callback if provided
            if task.callback:
                await task.callback(task)
            
            return True
            
        except Exception as e:
            logger.error(
                f"Subscription check failed for task {task.task_id}: {e}"
            )
            
            task.error_message = str(e)
            task.status = TaskStatus.FAILED
            task.retry_count += 1
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                delay = 1.0 * (2 ** task.retry_count)
                logger.info(
                    f"Scheduling retry for subscription check task {task.task_id} "
                    f"in {delay:.0f}s"
                )
                await asyncio.sleep(delay)
                return await self.execute_subscription_check(task)
            else:
                logger.error(
                    f"Max retries exceeded for subscription check task {task.task_id}"
                )
                return False
    
    async def schedule_subscription_renewal(
        self,
        subscription_id: str,
        new_expires_in_days: int = 365,
        callback: Optional[Callable[..., Any]] = None,
    ) -> ScheduledTask:
        """
        Schedule a subscription renewal.
        
        Args:
            subscription_id: Subscription identifier
            new_expires_in_days: New subscription lifetime in days
            callback: Optional callback to execute on completion
            
        Returns:
            ScheduledTask object
        """
        task_id = self._generate_task_id(
            TaskType.SUBSCRIPTION_RENEWAL, "system", "all"
        )
        
        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.SUBSCRIPTION_RENEWAL,
            user_id="system",
            provider="all",
            args=(subscription_id, new_expires_in_days),
            callback=callback,
        )
        
        # Store task
        async with self._task_lock:
            self._tasks[task_id] = task
        
        logger.info(
            f"Scheduled subscription renewal for {subscription_id} "
            f"task {task_id}"
        )
        
        return task
    
    async def execute_subscription_renewal(
        self,
        task: ScheduledTask,
    ) -> bool:
        """
        Execute a subscription renewal.
        
        Args:
            task: ScheduledTask to execute
            
        Returns:
            True if renewal succeeded
        """
        subscription_id, new_expires_in_days = task.args
        
        task.started_at = datetime.utcnow()
        task.status = TaskStatus.RUNNING
        
        try:
            # Renew subscription
            result = await self.webhook_manager.renew_subscription(
                subscription_id=subscription_id,
                new_expires_in_days=new_expires_in_days,
            )
            
            if result.success:
                logger.info(
                    f"Subscription renewal succeeded for {subscription_id} "
                    f"task {task.task_id}"
                )
                
                task.completed_at = datetime.utcnow()
                task.status = TaskStatus.COMPLETED
                
                # Execute callback if provided
                if task.callback:
                    await task.callback(task)
                
                return True
            else:
                logger.error(
                    f"Subscription renewal failed for {subscription_id}: "
                    f"{result.error_message} task {task.task_id}"
                )
                
                task.error_message = result.error_message
                task.status = TaskStatus.FAILED
                task.retry_count += 1
                
                # Check if we should retry
                if task.retry_count < task.max_retries:
                    delay = 1.0 * (2 ** task.retry_count)
                    logger.info(
                        f"Scheduling retry for subscription renewal task {task.task_id} "
                        f"in {delay:.0f}s"
                    )
                    await asyncio.sleep(delay)
                    return await self.execute_subscription_renewal(task)
                else:
                    logger.error(
                        f"Max retries exceeded for subscription renewal task {task.task_id}"
                    )
                    return False
                    
        except Exception as e:
            logger.error(
                f"Subscription renewal failed for {subscription_id}: {e} task {task.task_id}"
            )
            
            task.error_message = str(e)
            task.status = TaskStatus.FAILED
            task.retry_count += 1
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                delay = 1.0 * (2 ** task.retry_count)
                logger.info(
                    f"Scheduling retry for subscription renewal task {task.task_id} "
                    f"in {delay:.0f}s"
                )
                await asyncio.sleep(delay)
                return await self.execute_subscription_renewal(task)
            else:
                logger.error(
                    f"Max retries exceeded for subscription renewal task {task.task_id}"
                )
                return False
    
    async def schedule_alert_send(
        self,
        alert: SubscriptionAlert,
        callback: Optional[Callable[..., Any]] = None,
    ) -> ScheduledTask:
        """
        Schedule an alert send operation.
        
        Args:
            alert: SubscriptionAlert to send
            callback: Optional callback to execute on completion
            
        Returns:
            ScheduledTask object
        """
        task_id = self._generate_task_id(
            TaskType.ALERT_SEND, "system", "all"
        )
        
        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.ALERT_SEND,
            user_id="system",
            provider="all",
            callback=callback,
        )
        
        # Store task
        async with self._task_lock:
            self._tasks[task_id] = task
        
        logger.info(
            f"Scheduled alert send for {alert.alert_id} task {task_id}"
        )
        
        return task
    
    async def execute_alert_send(
        self,
        task: ScheduledTask,
    ) -> bool:
        """
        Execute an alert send operation.
        
        Args:
            task: ScheduledTask to execute
            
        Returns:
            True if alert sent successfully
        """
        task.started_at = datetime.utcnow()
        task.status = TaskStatus.RUNNING
        
        try:
            # Send alert
            await self.webhook_manager.send_alert(task.args[0])
            
            logger.info(
                f"Alert sent for {task.args[0].alert_id} task {task.task_id}"
            )
            
            task.completed_at = datetime.utcnow()
            task.status = TaskStatus.COMPLETED
            
            # Execute callback if provided
            if task.callback:
                await task.callback(task)
            
            return True
            
        except Exception as e:
            logger.error(
                f"Alert send failed for {task.args[0].alert_id}: {e} task {task.task_id}"
            )
            
            task.error_message = str(e)
            task.status = TaskStatus.FAILED
            task.retry_count += 1
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                delay = 1.0 * (2 ** task.retry_count)
                logger.info(
                    f"Scheduling retry for alert send task {task.task_id} "
                    f"in {delay:.0f}s"
                )
                await asyncio.sleep(delay)
                return await self.execute_alert_send(task)
            else:
                logger.error(
                    f"Max retries exceeded for alert send task {task.task_id}"
                )
                return False
    
    async def schedule_rate_limit_reset(
        self,
        provider: str,
        callback: Optional[Callable[..., Any]] = None,
    ) -> ScheduledTask:
        """
        Schedule a rate limit reset check.
        
        Args:
            provider: Provider name
            callback: Optional callback to execute on completion
            
        Returns:
            ScheduledTask object
        """
        task_id = self._generate_task_id(
            TaskType.RATE_LIMIT_RESET, "system", provider
        )
        
        task = ScheduledTask(
            task_id=task_id,
            task_type=TaskType.RATE_LIMIT_RESET,
            user_id="system",
            provider=provider,
            callback=callback,
        )
        
        # Store task
        async with self._task_lock:
            self._tasks[task_id] = task
        
        logger.info(
            f"Scheduled rate limit reset check for {provider} task {task_id}"
        )
        
        return task
    
    async def execute_rate_limit_reset(
        self,
        task: ScheduledTask,
    ) -> bool:
        """
        Execute a rate limit reset check.
        
        Args:
            task: ScheduledTask to execute
            
        Returns:
            True if check succeeded
        """
        task.started_at = datetime.utcnow()
        task.status = TaskStatus.RUNNING
        
        try:
            # Check rate limit status
            # In a real implementation, this would check provider rate limit status
            # For now, we just log
            logger.info(
                f"Rate limit reset check for {task.provider} task {task.task_id}"
            )
            
            task.completed_at = datetime.utcnow()
            task.status = TaskStatus.COMPLETED
            
            # Execute callback if provided
            if task.callback:
                await task.callback(task)
            
            return True
            
        except Exception as e:
            logger.error(
                f"Rate limit reset check failed for {task.provider}: {e} task {task.task_id}"
            )
            
            task.error_message = str(e)
            task.status = TaskStatus.FAILED
            task.retry_count += 1
            
            # Check if we should retry
            if task.retry_count < task.max_retries:
                delay = 1.0 * (2 ** task.retry_count)
                logger.info(
                    f"Scheduling retry for rate limit reset task {task.task_id} "
                    f"in {delay:.0f}s"
                )
                await asyncio.sleep(delay)
                return await self.execute_rate_limit_reset(task)
            else:
                logger.error(
                    f"Max retries exceeded for rate limit reset task {task.task_id}"
                )
                return False
    
    async def get_task(
        self,
        task_id: str,
    ) -> Optional[ScheduledTask]:
        """
        Get a scheduled task by ID.
        
        Args:
            task_id: Task identifier
            
        Returns:
            ScheduledTask or None if not found
        """
        return self._tasks.get(task_id)
    
    async def get_all_tasks(
        self,
        task_type: Optional[TaskType] = None,
        status: Optional[TaskStatus] = None,
    ) -> List[ScheduledTask]:
        """
        Get all scheduled tasks, optionally filtered.
        
        Args:
            task_type: Filter by task type
            status: Filter by status
            
        Returns:
            List of ScheduledTask objects
        """
        tasks = list(self._tasks.values())
        
        if task_type:
            tasks = [t for t in tasks if t.task_type == task_type]
        
        if status:
            tasks = [t for t in tasks if t.status == status]
        
        return tasks
    
    async def cancel_task(
        self,
        task_id: str,
    ) -> bool:
        """
        Cancel a scheduled task.
        
        Args:
            task_id: Task identifier
            
        Returns:
            True if task cancelled
        """
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        
        logger.info(f"Cancelled task {task_id}")
        
        return True
    
    async def get_task_stats(
        self,
    ) -> Dict[str, Any]:
        """
        Get statistics about scheduled tasks.
        
        Returns:
            Dictionary with task statistics
        """
        stats = {
            "total_tasks": len(self._tasks),
            "pending_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING),
            "running_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING),
            "completed_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED),
            "failed_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED),
            "cancelled_tasks": sum(1 for t in self._tasks.values() if t.status == TaskStatus.CANCELLED),
        }
        
        return stats
    
    def _generate_task_id(
        self,
        task_type: TaskType,
        user_id: str,
        provider: str,
    ) -> str:
        """
        Generate a unique task ID.
        
        Args:
            task_type: Task type
            user_id: User identifier
            provider: Provider name
            
        Returns:
            Unique task ID
        """
        timestamp = datetime.utcnow().isoformat()
        counter_str = str(len(self._tasks) + 1)
        hash_input = f"{timestamp}:{counter_str}:{task_type.value}:{user_id}:{provider}"
        hash_value = hashlib.sha256(hash_input.encode()).hexdigest()[:16]
        return f"task_{hash_value}"
    
    async def cleanup_completed_tasks(
        self,
        retention_hours: int = 24,
    ) -> int:
        """
        Clean up completed tasks beyond retention period.
        
        Args:
            retention_hours: Hours to retain completed tasks
            
        Returns:
            Number of tasks cleaned up
        """
        cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
        cleaned = 0
        
        for task_id, task in list(self._tasks.items()):
            if task.completed_at and task.completed_at < cutoff:
                del self._tasks[task_id]
                cleaned += 1
                logger.info(
                    f"Cleaned up completed task {task_id} "
                    f"completed at {task.completed_at.isoformat()}"
                )
        
        return cleaned


# Import hashlib for task ID generation
import hashlib