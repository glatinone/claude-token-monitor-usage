import json
import os
from datetime import datetime
import threading

# File path to store data
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usage_data.json")

# Model pricing per 1 million tokens (USD)
# Claude 3.5 Sonnet: Input $3.00, Output $15.00, Cache Creation $3.75, Cache Read $0.30
MODEL_PRICING = {
    "claude-3-5-sonnet": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation": 3.75,
        "cache_read": 0.30
    },
    "claude-sonnet-4-6": { # Claude Code internal name for Sonnet 3.5
        "input": 3.00,
        "output": 15.00,
        "cache_creation": 3.75,
        "cache_read": 0.30
    },
    "default": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation": 3.75,
        "cache_read": 0.30
    }
}

class StorageManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = self._load_data()

    def _load_data(self):
        with self.lock:
            if os.path.exists(DATA_FILE):
                try:
                    with open(DATA_FILE, "r") as f:
                        return json.load(f)
                except Exception as e:
                    print(f"[Storage] Error loading data: {e}")
            
            # Default structure if file doesn't exist or is corrupted
            return {
                "claude_code": {}, # date string: {input, output, cache_read, cache_creation, cost}
                "claude_web": {
                    "remaining": 100.0,
                    "limit": 100.0,
                    "percentage": 100.0,
                    "reset_at": "",
                    "last_updated": ""
                },
                "history": [] # raw event log for debugging/graphing
            }

    def _save_data(self):
        with self.lock:
            try:
                with open(DATA_FILE, "w") as f:
                    json.dump(self.data, f, indent=4)
            except Exception as e:
                print(f"[Storage] Error saving data: {e}")

    def add_cli_usage(self, model_name, input_tokens, output_tokens, cache_read, cache_creation, session_id, log_date=None):
        # Calculate cost
        pricing = MODEL_PRICING.get(model_name, MODEL_PRICING["default"])
        
        cost = (
            (input_tokens * pricing["input"]) +
            (output_tokens * pricing["output"]) +
            (cache_read * pricing["cache_read"]) +
            (cache_creation * pricing["cache_creation"])
        ) / 1_000_000.0

        if not log_date:
            log_date = datetime.now().strftime("%Y-%m-%d")
        
        # Check if this session event is already processed to avoid double counting
        # We store processed session update timestamps in the history
        history_key = f"cli_{session_id}_{input_tokens}_{output_tokens}_{cache_read}_{cache_creation}"
        if history_key in self.data.get("history", []):
            return log_date, self.data["claude_code"].get(log_date, {})

        if log_date not in self.data["claude_code"]:
            self.data["claude_code"][log_date] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_creation_tokens": 0,
                "cost": 0.0
            }

        # Update stats
        day_stats = self.data["claude_code"][log_date]
        day_stats["input_tokens"] += input_tokens
        day_stats["output_tokens"] += output_tokens
        day_stats["cache_read_tokens"] += cache_read
        day_stats["cache_creation_tokens"] += cache_creation
        day_stats["cost"] += cost

        # Keep history capped to last 500 events
        if "history" not in self.data:
            self.data["history"] = []
        self.data["history"].append(history_key)
        if len(self.data["history"]) > 500:
            self.data["history"] = self.data["history"][-500:]

        self._save_data()
        return log_date, day_stats

    def update_web_usage(self, remaining, limit, percentage, reset_at):
        self.data["claude_web"] = {
            "remaining": remaining,
            "limit": limit,
            "percentage": percentage,
            "reset_at": reset_at,
            "last_updated": datetime.now().isoformat()
        }
        self._save_data()
        return self.data["claude_web"]

    def get_today_cli_stats(self):
        today = datetime.now().strftime("%Y-%m-%d")
        return self.data["claude_code"].get(today, {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost": 0.0
        })

    def get_web_stats(self):
        return self.data["claude_web"]
