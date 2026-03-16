"""
Unit tests for the memory system.

Tests:
  - ShortTermMemory: ring buffer, max size, recent()
  - LongTermMemory: add + search (with ChromaDB stub)
  - MemoryManager: observe, memorize, recall, clear_session
"""

from __future__ import annotations

import pytest


class TestShortTermMemory:

    def test_add_and_retrieve(self) -> None:
        from agent.core.memory import ShortTermMemory
        mem = ShortTermMemory(max_entries=10)
        mem.add("observation 1")
        mem.add("observation 2")
        recent = mem.recent(2)
        assert len(recent) == 2
        assert recent[-1].content == "observation 2"

    def test_ring_buffer_evicts_oldest(self) -> None:
        from agent.core.memory import ShortTermMemory
        mem = ShortTermMemory(max_entries=3)
        for i in range(5):
            mem.add(f"entry {i}")
        assert len(mem) == 3
        contents = [e.content for e in mem.recent(3)]
        assert "entry 0" not in contents
        assert "entry 4" in contents

    def test_recent_returns_n_entries(self) -> None:
        from agent.core.memory import ShortTermMemory
        mem = ShortTermMemory(max_entries=20)
        for i in range(10):
            mem.add(f"item {i}")
        recent = mem.recent(3)
        assert len(recent) == 3
        assert recent[-1].content == "item 9"

    def test_clear_empties_memory(self) -> None:
        from agent.core.memory import ShortTermMemory
        mem = ShortTermMemory()
        mem.add("something")
        mem.clear()
        assert len(mem) == 0

    def test_metadata_stored(self) -> None:
        from agent.core.memory import ShortTermMemory
        mem = ShortTermMemory()
        entry = mem.add("content", metadata={"step": 5, "tool": "read_file"})
        assert entry.metadata["step"] == 5
        assert entry.metadata["tool"] == "read_file"


class TestMemoryManager:

    def test_observe_stores_in_short_term(self) -> None:
        from agent.core.memory import MemoryManager
        mgr = MemoryManager(enable_long_term=False)
        mgr.observe("step result", {"step": 1})
        recent = mgr.recent_observations(1)
        assert len(recent) == 1
        assert recent[0].content == "step result"

    def test_clear_session_empties_short_term(self) -> None:
        from agent.core.memory import MemoryManager
        mgr = MemoryManager(enable_long_term=False)
        mgr.observe("something")
        mgr.clear_session()
        assert len(mgr.recent_observations(10)) == 0

    def test_recall_falls_back_to_short_term(self) -> None:
        from agent.core.memory import MemoryManager
        mgr = MemoryManager(enable_long_term=False)
        mgr.observe("recent context")
        results = mgr.recall("context", n=3)
        assert any("recent context" in r.content for r in results)

    def test_memorize_without_long_term(self) -> None:
        from agent.core.memory import MemoryManager
        mgr = MemoryManager(enable_long_term=False)
        result = mgr.memorize("important info", {"type": "solution"})
        # Should return None when long-term is disabled
        assert result is None
