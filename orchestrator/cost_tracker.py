"""Cost tracking for OpenRouter API calls.

Wraps the OpenRouter client to log every completion call with model,
tokens, cost, and pipeline stage. Stores as JSONL for the dashboard.
"""

import json
import os
import threading
from datetime import datetime, timezone

COST_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cost_logs")
os.makedirs(COST_LOG_DIR, exist_ok=True)

_lock = threading.Lock()


def _log_path() -> str:
    """Daily log file path."""
    return os.path.join(COST_LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.jsonl")


def log_call(response, stage: str = "unknown", model_requested: str = ""):
    """Log an OpenRouter completion response to the daily JSONL file.

    Args:
        response: The OpenAI ChatCompletion response object
        stage: Pipeline stage (e.g., "cassie_raw", "lawwama_critic", "director")
        model_requested: The model slug we requested
    """
    try:
        usage = response.usage
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "model_requested": model_requested,
            "model_actual": getattr(response, "model", ""),
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
            "cost": getattr(usage, "cost", 0) or 0,
        }
        with _lock:
            with open(_log_path(), "a") as f:
                f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[cost] Failed to log: {e}")


def get_daily_summary(date_str: str = None) -> dict:
    """Get cost summary for a given date (YYYY-MM-DD). Defaults to today."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(COST_LOG_DIR, f"{date_str}.jsonl")
    if not os.path.isfile(path):
        return {"date": date_str, "total_cost": 0, "total_calls": 0, "by_stage": {}, "by_model": {}}

    total_cost = 0
    total_calls = 0
    by_stage = {}
    by_model = {}
    entries = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
                cost = entry.get("cost", 0)
                stage = entry.get("stage", "unknown")
                model = entry.get("model_requested", "unknown")

                total_cost += cost
                total_calls += 1

                if stage not in by_stage:
                    by_stage[stage] = {"cost": 0, "calls": 0, "tokens": 0}
                by_stage[stage]["cost"] += cost
                by_stage[stage]["calls"] += 1
                by_stage[stage]["tokens"] += entry.get("total_tokens", 0)

                if model not in by_model:
                    by_model[model] = {"cost": 0, "calls": 0, "tokens": 0}
                by_model[model]["cost"] += cost
                by_model[model]["calls"] += 1
                by_model[model]["tokens"] += entry.get("total_tokens", 0)
            except json.JSONDecodeError:
                continue

    return {
        "date": date_str,
        "total_cost": round(total_cost, 6),
        "total_calls": total_calls,
        "by_stage": {k: {**v, "cost": round(v["cost"], 6)} for k, v in sorted(by_stage.items(), key=lambda x: -x[1]["cost"])},
        "by_model": {k: {**v, "cost": round(v["cost"], 6)} for k, v in sorted(by_model.items(), key=lambda x: -x[1]["cost"])},
    }


def get_range_summary(days: int = 30) -> dict:
    """Get cost summary for the last N days."""
    from datetime import timedelta
    today = datetime.now()
    daily = []
    total_cost = 0
    total_calls = 0

    for i in range(days):
        date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        summary = get_daily_summary(date_str)
        if summary["total_calls"] > 0:
            daily.append(summary)
            total_cost += summary["total_cost"]
            total_calls += summary["total_calls"]

    return {
        "days": days,
        "total_cost": round(total_cost, 6),
        "total_calls": total_calls,
        "daily": daily,
    }
