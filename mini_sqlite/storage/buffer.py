from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

from mini_sqlite.errors import BufferPoolFullError, StorageError

PageLoader = Callable[[int], bytes]
EvictPredicate = Callable[["BufferFrame"], bool]
EvictCallback = Callable[["BufferFrame"], None]


@dataclass
class BufferFrame:
    """One in-memory database page.

    ``pin_count`` protects a frame while a caller is actively using its bytes.
    ``dirty`` says memory differs from the durable view selected by Pager.
    Replacement metadata is deliberately kept here rather than in Pager so the
    cache policy can evolve independently of durability.
    """

    page_id: int
    data: bytearray
    dirty: bool = False
    pin_count: int = 0
    last_touch: int = 0
    referenced: bool = True


class BufferManager:
    """A bounded page cache with explicit LRU or CLOCK replacement.

    The manager knows nothing about database files, rollback journals, or WAL.
    Pager supplies two policy hooks during eviction:

    * ``can_evict(frame)`` -- is this frame safe to remove now?
    * ``on_evict(frame)`` -- perform any required durable write-back first.

    This separation is the central v0.7 invariant: replacement chooses *which*
    frame to remove; Pager decides *whether/how* a dirty frame may leave memory.
    """

    def __init__(self, capacity: int = 64, policy: str = "clock"):
        if capacity < 1:
            raise StorageError("buffer capacity must be at least one page")
        normalized = policy.lower().strip()
        if normalized not in {"lru", "clock"}:
            raise StorageError(f"unsupported replacement policy {policy!r}")
        self.capacity = capacity
        self.policy = normalized
        self._frames: dict[int, BufferFrame] = {}
        self._tick = 0
        self._clock_order: list[int] = []
        self._clock_hand = 0

        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.dirty_evictions = 0

    def __len__(self) -> int:
        return len(self._frames)

    def __contains__(self, page_id: int) -> bool:
        return page_id in self._frames

    def page_ids(self) -> list[int]:
        return list(self._frames)

    def frames(self) -> Iterable[BufferFrame]:
        return self._frames.values()

    def frame(self, page_id: int) -> BufferFrame | None:
        return self._frames.get(page_id)

    def fetch(
        self,
        page_id: int,
        loader: PageLoader,
        *,
        pin: bool = False,
        can_evict: EvictPredicate,
        on_evict: EvictCallback,
    ) -> BufferFrame:
        frame = self._frames.get(page_id)
        if frame is not None:
            self.hits += 1
            self._touch(frame)
            if pin:
                frame.pin_count += 1
            return frame

        self.misses += 1
        self._ensure_room(can_evict=can_evict, on_evict=on_evict)
        raw = loader(page_id)
        frame = BufferFrame(page_id=page_id, data=bytearray(raw), pin_count=int(pin))
        self._insert(frame)
        return frame

    def install(
        self,
        page_id: int,
        data: bytes | bytearray,
        *,
        dirty: bool,
        pin: bool = False,
        can_evict: EvictPredicate,
        on_evict: EvictCallback,
    ) -> BufferFrame:
        frame = self._frames.get(page_id)
        if frame is None:
            self._ensure_room(can_evict=can_evict, on_evict=on_evict)
            frame = BufferFrame(
                page_id=page_id,
                data=bytearray(data),
                dirty=dirty,
                pin_count=int(pin),
            )
            self._insert(frame)
            return frame

        frame.data[:] = data
        frame.dirty = dirty
        if pin:
            frame.pin_count += 1
        self._touch(frame)
        return frame

    def remove(self, page_id: int) -> None:
        frame = self._frames.get(page_id)
        if frame is None:
            return
        if frame.pin_count:
            raise BufferPoolFullError(f"cannot remove pinned page {page_id}")
        del self._frames[page_id]
        self._remove_from_clock(page_id)

    def clear(self) -> None:
        pinned = [f.page_id for f in self._frames.values() if f.pin_count]
        if pinned:
            raise BufferPoolFullError(f"cannot clear buffer with pinned pages {pinned}")
        self._frames.clear()
        self._clock_order.clear()
        self._clock_hand = 0

    def pin(self, page_id: int) -> None:
        frame = self._require(page_id)
        frame.pin_count += 1
        self._touch(frame)

    def unpin(self, page_id: int) -> None:
        frame = self._require(page_id)
        if frame.pin_count <= 0:
            raise StorageError(f"page {page_id} is not pinned")
        frame.pin_count -= 1

    def mark_dirty(self, page_id: int) -> None:
        frame = self._require(page_id)
        frame.dirty = True
        self._touch(frame)

    def mark_clean(self, page_id: int) -> None:
        frame = self._frames.get(page_id)
        if frame is not None:
            frame.dirty = False

    def reset_counters(self) -> None:
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.dirty_evictions = 0

    def snapshot(self) -> list[dict[str, int | bool]]:
        return [
            {
                "page_id": frame.page_id,
                "dirty": frame.dirty,
                "pin_count": frame.pin_count,
                "last_touch": frame.last_touch,
                "referenced": frame.referenced,
            }
            for frame in sorted(self._frames.values(), key=lambda f: f.page_id)
        ]

    def stats(self) -> dict[str, int | str]:
        pinned = sum(1 for frame in self._frames.values() if frame.pin_count)
        dirty = sum(1 for frame in self._frames.values() if frame.dirty)
        accesses = self.hits + self.misses
        hit_rate_milli = int(self.hits * 1000 / accesses) if accesses else 0
        return {
            "capacity": self.capacity,
            "resident": len(self._frames),
            "dirty": dirty,
            "pinned": pinned,
            "policy": self.policy,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "dirty_evictions": self.dirty_evictions,
            "hit_rate_milli": hit_rate_milli,
        }

    def _require(self, page_id: int) -> BufferFrame:
        frame = self._frames.get(page_id)
        if frame is None:
            raise StorageError(f"page {page_id} is not resident in buffer")
        return frame

    def _insert(self, frame: BufferFrame) -> None:
        self._frames[frame.page_id] = frame
        self._clock_order.append(frame.page_id)
        self._touch(frame)

    def _touch(self, frame: BufferFrame) -> None:
        self._tick += 1
        frame.last_touch = self._tick
        frame.referenced = True

    def _ensure_room(
        self, *, can_evict: EvictPredicate, on_evict: EvictCallback
    ) -> None:
        if len(self._frames) < self.capacity:
            return
        victim = (
            self._choose_lru(can_evict)
            if self.policy == "lru"
            else self._choose_clock(can_evict)
        )
        if victim is None:
            pinned = [f.page_id for f in self._frames.values() if f.pin_count]
            blocked_dirty = [
                f.page_id
                for f in self._frames.values()
                if not f.pin_count and not can_evict(f)
            ]
            raise BufferPoolFullError(
                "buffer pool has no evictable frame "
                f"(capacity={self.capacity}, pinned={pinned}, blocked_dirty={blocked_dirty})"
            )

        was_dirty = victim.dirty
        on_evict(victim)
        # Pager's write-back callback must leave a dirty victim clean before it
        # can disappear. This catches durability bugs at the cache boundary.
        if victim.dirty:
            raise StorageError(
                f"eviction callback left dirty page {victim.page_id} unresolved"
            )
        del self._frames[victim.page_id]
        self._remove_from_clock(victim.page_id)
        self.evictions += 1
        if was_dirty:
            self.dirty_evictions += 1

    def _choose_lru(self, can_evict: EvictPredicate) -> BufferFrame | None:
        candidates = [
            frame
            for frame in self._frames.values()
            if frame.pin_count == 0 and can_evict(frame)
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda frame: (frame.last_touch, frame.page_id))

    def _choose_clock(self, can_evict: EvictPredicate) -> BufferFrame | None:
        if not self._clock_order:
            return None
        # Two full revolutions are enough: the first clears reference bits on
        # eligible frames, the second can choose one. Pinned/blocked frames keep
        # their state because they were not candidates in this decision.
        remaining = max(1, len(self._clock_order) * 2)
        while remaining:
            if not self._clock_order:
                return None
            self._clock_hand %= len(self._clock_order)
            page_id = self._clock_order[self._clock_hand]
            frame = self._frames[page_id]
            self._clock_hand = (self._clock_hand + 1) % len(self._clock_order)
            remaining -= 1

            if frame.pin_count or not can_evict(frame):
                continue
            if frame.referenced:
                frame.referenced = False
                continue
            return frame
        return None

    def _remove_from_clock(self, page_id: int) -> None:
        try:
            index = self._clock_order.index(page_id)
        except ValueError:
            return
        del self._clock_order[index]
        if not self._clock_order:
            self._clock_hand = 0
            return
        if index < self._clock_hand:
            self._clock_hand -= 1
        self._clock_hand %= len(self._clock_order)
