"""
Dashboard — optional Streamlit dashboard for live agent trace viewing.

Shows:
  - Real-time step-by-step agent progress
  - Token usage and cost per run
  - Error counts and recovery rates
  - Benchmark results over time

Run::

    pip install streamlit
    streamlit run observability/dashboard.py

Or launch from CLI::

    agent dashboard
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Streamlit app (only executed when run directly)
# ---------------------------------------------------------------------------


def _run_dashboard(log_dir: str = ".agent_logs") -> None:
    """Launch the Streamlit dashboard."""
    try:
        import streamlit as st  # type: ignore[import]
    except ImportError:
        print("Streamlit not installed. Run: pip install streamlit")
        sys.exit(1)

    st.set_page_config(
        page_title="Hams AI — Dashboard",
        page_icon="🤖",
        layout="wide",
    )

    st.title("🤖 Hams AI — Live Dashboard")

    log_path = Path(log_dir)
    if not log_path.exists():
        st.warning(f"Log directory not found: {log_dir}")
        st.info("Run an agent task first to populate the dashboard.")
        return

    # ── Sidebar: controls ──────────────────────────────────────────────
    with st.sidebar:
        st.header("Controls")
        refresh = st.button("🔄 Refresh")
        selected_log = st.selectbox(
            "Log file",
            options=sorted(log_path.glob("*_audit.jsonl"), reverse=True),
            format_func=lambda p: p.stem,
        )

    if not selected_log:
        st.info("No audit logs found.")
        return

    # ── Load events ────────────────────────────────────────────────────
    events: list[dict] = []
    for line in Path(selected_log).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    if not events:
        st.warning("No events in selected log.")
        return

    # ── Summary metrics ────────────────────────────────────────────────
    tool_calls  = [e for e in events if e.get("event_type") == "tool_call"]
    llm_calls   = [e for e in events if e.get("event_type") == "llm_call"]
    sec_events  = [e for e in events if e.get("event_type") == "security_event"]
    lifecycle   = [e for e in events if e.get("event_type") == "lifecycle"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tool Calls",      len(tool_calls))
    col2.metric("LLM Calls",       len(llm_calls))
    col3.metric("Security Events", len(sec_events))

    total_tokens = sum(e.get("total_tokens", 0) for e in llm_calls)
    col4.metric("Total Tokens", f"{total_tokens:,}")

    # ── Lifecycle ──────────────────────────────────────────────────────
    if lifecycle:
        st.subheader("Lifecycle")
        for ev in lifecycle:
            stage = ev.get("stage", "?")
            ts = ev.get("timestamp", "")[:19]
            st.write(f"`{ts}` — **{stage}**")

    # ── Tool call timeline ─────────────────────────────────────────────
    if tool_calls:
        st.subheader("Tool Call Timeline")
        import pandas as pd  # type: ignore[import]
        rows = []
        for ev in tool_calls:
            rows.append({
                "Step":    ev.get("step", 0),
                "Tool":    ev.get("tool_name", ""),
                "Elapsed (ms)": ev.get("elapsed_ms", 0),
                "Exit Code": ev.get("exit_code", 0),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    # ── Token usage ────────────────────────────────────────────────────
    if llm_calls:
        st.subheader("Token Usage per Step")
        import pandas as pd  # type: ignore[import]
        rows = [
            {
                "Step":   ev.get("step", 0),
                "Model":  ev.get("model", ""),
                "Input":  ev.get("input_tokens", 0),
                "Output": ev.get("output_tokens", 0),
                "Total":  ev.get("total_tokens", 0),
            }
            for ev in llm_calls
        ]
        df = pd.DataFrame(rows)
        st.bar_chart(df.set_index("Step")[["Input", "Output"]])

    # ── Security events ────────────────────────────────────────────────
    if sec_events:
        st.subheader("⚠️ Security Events")
        for ev in sec_events:
            severity = ev.get("severity", "medium")
            color = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
            st.write(
                f"{color} **{ev.get('event_name', '?')}** — {ev.get('detail', '')[:200]}"
            )


# ---------------------------------------------------------------------------
# Programmatic API (for use without Streamlit)
# ---------------------------------------------------------------------------


class DashboardData:
    """
    Loads and summarises audit log data without requiring Streamlit.
    Useful for generating reports or feeding data into external dashboards.
    """

    def __init__(self, log_dir: str = ".agent_logs") -> None:
        self.log_dir = Path(log_dir)

    def load_run(self, task_id: str) -> list[dict]:
        """Load all events for a specific task run."""
        path = self.log_dir / f"{task_id}_audit.jsonl"
        if not path.exists():
            return []
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events

    def run_summary(self, task_id: str) -> dict:
        """Return a summary dict for a task run."""
        events = self.load_run(task_id)
        tool_calls = [e for e in events if e.get("event_type") == "tool_call"]
        llm_calls  = [e for e in events if e.get("event_type") == "llm_call"]
        sec_events = [e for e in events if e.get("event_type") == "security_event"]
        lifecycle  = [e for e in events if e.get("event_type") == "lifecycle"]

        total_tokens = sum(e.get("total_tokens", 0) for e in llm_calls)
        blocked = sum(1 for e in sec_events if e.get("blocked"))

        stage = lifecycle[-1].get("stage", "unknown") if lifecycle else "unknown"

        return {
            "task_id": task_id,
            "final_stage": stage,
            "tool_calls": len(tool_calls),
            "llm_calls": len(llm_calls),
            "total_tokens": total_tokens,
            "security_events": len(sec_events),
            "blocked_actions": blocked,
        }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys
    log_dir = sys.argv[1] if len(sys.argv) > 1 else ".agent_logs"
    _run_dashboard(log_dir)
