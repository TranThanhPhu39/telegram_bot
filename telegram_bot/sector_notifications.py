"""Thread-safe Telegram notifications for background sector-history sync.

Registration, the single INCOMPLETE notice, the eventual READY notice and any
queued-but-undelivered message are held in a pluggable store.  With the default
in-memory store the behaviour is identical to the previous implementation; with
``SQLiteNotificationStore`` the same state survives a bot restart.

Delivery is at-least-once: a message is sent first and only marked delivered
afterwards, so a crash between the two can repeat a notification but can never
silently drop one.  One failing chat never blocks the rest of the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import threading
import time
from typing import Callable

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot.sector_notification_store import (
    InMemoryNotificationStore,
    PENDING_READY,
    RetainedResult,
    WatcherState,
    canonical_chat_id,
    cleared,
    decode_chat_id,
    format_sector_sync_text,
    normalize_symbol,
    pending_kind_for,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_DELIVERY_ATTEMPTS = 5
DEFAULT_REGISTRATION_TTL_SECONDS = 86_400.0
DEFAULT_PURGE_INTERVAL_SECONDS = 300.0


@dataclass(frozen=True, slots=True)
class SectorSyncNotification:
    chat_id: int | str
    symbol: str
    text: str
    ready: bool


class SectorSyncNotificationBroker:
    """Bridge a worker thread to the Telegram asyncio application."""

    def __init__(
        self,
        store=None,
        *,
        max_delivery_attempts: int = DEFAULT_MAX_DELIVERY_ATTEMPTS,
        registration_ttl_seconds: float = DEFAULT_REGISTRATION_TTL_SECONDS,
        purge_interval_seconds: float = DEFAULT_PURGE_INTERVAL_SECONDS,
        now: Callable[[], float] = time.time,
    ) -> None:
        if max_delivery_attempts < 1:
            raise ValueError("max_delivery_attempts must be positive")
        if registration_ttl_seconds <= 0 or purge_interval_seconds <= 0:
            raise ValueError("notification TTL and purge interval must be positive")
        self._store = store if store is not None else InMemoryNotificationStore()
        self._max_delivery_attempts = max_delivery_attempts
        self._registration_ttl_seconds = registration_ttl_seconds
        self._purge_interval_seconds = purge_interval_seconds
        self._now = now
        self._lock = threading.RLock()
        # Claimed keys are process-local on purpose: after a restart every
        # persisted pending row becomes deliverable again.
        self._claimed: set[tuple[str, str]] = set()
        self._last_purge = 0.0

    @property
    def persistent(self) -> bool:
        return bool(getattr(self._store, "persistent", False))

    # ------------------------------------------------------------ watching
    def watch(self, chat_id: int | str, symbol: str) -> None:
        """Register a chat before any sector synchronization is requested."""
        key_chat = canonical_chat_id(chat_id)
        key_symbol = normalize_symbol(symbol)
        stamp = int(self._now())
        with self._lock:
            existing = self._store.load_watcher(key_chat, key_symbol)
            if existing is None:
                watcher = WatcherState(
                    chat_id=key_chat, symbol=key_symbol,
                    created_at=stamp, updated_at=stamp,
                )
            elif existing.closed:
                # A completed subscription is reopened as a fresh cycle.
                watcher = replace(
                    existing, closed=False, incomplete_sent=False,
                    updated_at=stamp,
                )
            else:
                watcher = replace(existing, updated_at=stamp)
            retained = self._store.load_result(key_symbol)
            if retained is not None:
                result = retained[0]
                if (
                    result.sector_code is not None
                    and not result.ready
                    and not watcher.incomplete_sent
                ):
                    watcher = replace(
                        watcher, incomplete_sent=True,
                        pending_kind=pending_kind_for(result),
                        pending_text=format_sector_sync_text(result),
                        pending_attempts=0, updated_at=stamp,
                    )
            self._store.save_watcher(watcher)

    def unwatch(self, chat_id: int | str, symbol: str) -> None:
        """Drop a registration; an already queued message is still delivered."""
        key_chat = canonical_chat_id(chat_id)
        key_symbol = str(symbol).strip().upper()
        stamp = int(self._now())
        with self._lock:
            watcher = self._store.load_watcher(key_chat, key_symbol)
            if watcher is None:
                return
            if watcher.pending_kind is None:
                self._store.delete_watcher(key_chat, key_symbol)
                return
            self._store.save_watcher(
                replace(watcher, closed=True, updated_at=stamp)
            )

    def is_watching(self, chat_id: int | str, symbol: str) -> bool:
        key_chat = canonical_chat_id(chat_id)
        key_symbol = str(symbol).strip().upper()
        with self._lock:
            watcher = self._store.load_watcher(key_chat, key_symbol)
            return watcher is not None and not watcher.closed

    # ----------------------------------------------------------- publishing
    def publish(self, result) -> int:
        """Queue at most one incomplete notice and one eventual ready notice."""
        retained = RetainedResult.from_sync_result(result)
        stamp = int(self._now())
        with self._lock:
            previous = self._store.load_result(retained.requested_symbol)
            self._store.save_result(retained, stamp)
            if previous is not None and previous[1] == retained.fingerprint:
                return 0  # identical worker pass republished
            queued = 0
            kind = pending_kind_for(retained)
            text = format_sector_sync_text(retained)
            for watcher in self._store.open_watchers(retained.requested_symbol):
                if not retained.terminal and watcher.incomplete_sent:
                    continue
                self._store.save_watcher(replace(
                    watcher,
                    incomplete_sent=watcher.incomplete_sent or not retained.terminal,
                    closed=retained.terminal,
                    pending_kind=kind, pending_text=text,
                    pending_attempts=0, updated_at=stamp,
                ))
                queued += 1
            return queued

    # ------------------------------------------------------------ delivery
    def drain(self) -> tuple[SectorSyncNotification, ...]:
        """Claim every deliverable notification exactly once per process run."""
        with self._lock:
            claimed: list[SectorSyncNotification] = []
            for watcher in self._store.pending_watchers():
                key = (watcher.chat_id, watcher.symbol)
                if key in self._claimed:
                    continue
                self._claimed.add(key)
                claimed.append(SectorSyncNotification(
                    chat_id=decode_chat_id(watcher.chat_id),
                    symbol=watcher.symbol,
                    text=watcher.pending_text or "",
                    ready=watcher.pending_kind == PENDING_READY,
                ))
            return tuple(claimed)

    def pending_count(self) -> int:
        """Return undelivered notifications, including ones already claimed."""
        with self._lock:
            return len(self._store.pending_watchers())

    def mark_delivered(self, notification: SectorSyncNotification) -> None:
        key_chat = canonical_chat_id(notification.chat_id)
        stamp = int(self._now())
        with self._lock:
            self._claimed.discard((key_chat, notification.symbol))
            watcher = self._store.load_watcher(key_chat, notification.symbol)
            if watcher is None:
                return
            if watcher.closed:
                self._store.delete_watcher(key_chat, notification.symbol)
                return
            self._store.save_watcher(cleared(watcher, stamp))

    def requeue(self, notification: SectorSyncNotification) -> None:
        """Return a failed send to the queue until the attempt budget runs out."""
        key_chat = canonical_chat_id(notification.chat_id)
        stamp = int(self._now())
        with self._lock:
            self._claimed.discard((key_chat, notification.symbol))
            watcher = self._store.load_watcher(key_chat, notification.symbol)
            if watcher is None:
                return
            attempts = watcher.pending_attempts + 1
            if attempts >= self._max_delivery_attempts:
                LOGGER.warning(
                    "Dropping sector notification after repeated send failures",
                    extra={"symbol": watcher.symbol, "attempts": attempts},
                )
                if watcher.closed:
                    self._store.delete_watcher(key_chat, notification.symbol)
                else:
                    self._store.save_watcher(cleared(watcher, stamp))
                return
            self._store.save_watcher(
                replace(watcher, pending_attempts=attempts, updated_at=stamp)
            )

    # ------------------------------------------------------------- cleanup
    def purge_stale(self) -> int:
        """Delete idle registrations and retained results older than the TTL."""
        stamp = self._now()
        with self._lock:
            self._last_purge = stamp
            return self._store.purge(int(stamp - self._registration_ttl_seconds))

    def maintain(self) -> None:
        """Run the throttled cleanup from the delivery loop."""
        stamp = self._now()
        with self._lock:
            due = stamp - self._last_purge >= self._purge_interval_seconds
            if not due:
                return
        self.purge_stale()


def sector_notification_keyboard(symbol: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎯 Xem lại ASMF", callback_data=f"soi:asmf:{symbol.strip().upper()}"
        )
    ]])


async def deliver_sector_notifications(
    bot: Bot, broker: SectorSyncNotificationBroker
) -> int:
    """Deliver one broker snapshot and retain failed sends for retry."""
    sent = 0
    first_error: BaseException | None = None
    for notification in broker.drain():
        try:
            await bot.send_message(
                chat_id=notification.chat_id,
                text=notification.text,
                reply_markup=sector_notification_keyboard(notification.symbol),
            )
        except Exception as error:  # one bad chat must not stall the queue
            broker.requeue(notification)
            if first_error is None:
                first_error = error
            continue
        broker.mark_delivered(notification)
        sent += 1
    broker.maintain()
    if first_error is not None:
        raise first_error
    return sent
