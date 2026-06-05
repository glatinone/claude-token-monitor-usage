import json
import os
import glob
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime
import traceback

class ClaudeLogHandler(FileSystemEventHandler):
    def __init__(self, storage_manager, update_callback):
        self.storage_manager = storage_manager
        self.update_callback = update_callback
        self.file_offsets = {}  # file_path -> last_read_position
        user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        self.projects_dir = os.path.join(user_profile, ".claude", "projects")
        
        # Initialize and scan existing logs
        self.initial_scan()

    def initial_scan(self):
        """Scans existing jsonl log files to load today's CLI token usage"""
        print("[Watcher] Performing initial scan of Claude Code logs...")
        jsonl_files = glob.glob(os.path.join(self.projects_dir, "**", "*.jsonl"), recursive=True)
        
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for file_path in jsonl_files:
            try:
                # Set initial offset to file size so we only read new lines from now on
                file_size = os.path.getsize(file_path)
                self.file_offsets[file_path] = file_size
                
                # Scan files modified today to rebuild stats
                last_modified = datetime.fromtimestamp(os.path.getmtime(file_path))
                if last_modified.strftime("%Y-%m-%d") == today_str:
                    self._parse_file(file_path, parse_all=True)
            except Exception as e:
                print(f"[Watcher] Error scanning {file_path}: {e}")

    def _parse_file(self, file_path, parse_all=False):
        """Parses new lines in a jsonl log file"""
        if not os.path.exists(file_path):
            return

        current_size = os.path.getsize(file_path)
        start_offset = 0 if parse_all else self.file_offsets.get(file_path, 0)
        
        if current_size <= start_offset:
            self.file_offsets[file_path] = current_size
            return

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(start_offset)
            
            # Read line by line
            line = f.readline()
            while line:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "assistant":
                            message = entry.get("message", {})
                            model = message.get("model", "claude-3-5-sonnet")
                            usage = message.get("usage", {})
                            session_id = entry.get("sessionId", "unknown")
                            
                            # Parse token counts
                            input_tokens = int(usage.get("input_tokens", 0))
                            output_tokens = int(usage.get("output_tokens", 0))
                            cache_read = int(usage.get("cache_read_input_tokens", 0))
                            cache_creation = int(usage.get("cache_creation_input_tokens", 0))
                            
                            # Extract log date from timestamp
                            timestamp_str = entry.get("timestamp", "")
                            log_date = None
                            if timestamp_str:
                                try:
                                    log_date = timestamp_str.split("T")[0]
                                except Exception:
                                    pass
                            
                            # Log and update storage
                            actual_date, cli_stats = self.storage_manager.add_cli_usage(
                                model, input_tokens, output_tokens, cache_read, cache_creation, session_id, log_date=log_date
                            )
                            
                            # Trigger UI update only if this event is from today
                            today_str = datetime.now().strftime("%Y-%m-%d")
                            if actual_date == today_str and self.update_callback:
                                self.update_callback(cli_stats=cli_stats)
                    except json.JSONDecodeError:
                        # File might still be writing, roll back offset to start of this line
                        # and stop reading for now. We will try again on the next file modification.
                        offset_before_line = f.tell() - len(line) - 1
                        self.file_offsets[file_path] = max(0, offset_before_line)
                        return
                    except Exception as e:
                        print(f"[Watcher] Error parsing log line: {e}")
                
                # Move to next line
                line = f.readline()
                
            # Update offset to current position
            self.file_offsets[file_path] = f.tell()

    def on_modified(self, event):
        if event.is_directory or not event.src_path.endswith(".jsonl"):
            return
        self._parse_file(event.src_path)

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(".jsonl"):
            return
        # Initialize offset to 0 for new files
        self.file_offsets[event.src_path] = 0
        self._parse_file(event.src_path)


class ProjectLogWatcher:
    def __init__(self, storage_manager, update_callback):
        self.storage_manager = storage_manager
        self.update_callback = update_callback
        self.observer = Observer()
        self.handler = None
        user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        self.projects_dir = os.path.join(user_profile, ".claude", "projects")

    def start(self):
        # Ensure projects directory exists
        if not os.path.exists(self.projects_dir):
            try:
                os.makedirs(self.projects_dir)
            except Exception as e:
                print(f"[Watcher] Error creating projects directory: {e}")
                return

        self.handler = ClaudeLogHandler(self.storage_manager, self.update_callback)
        self.observer.schedule(self.handler, path=self.projects_dir, recursive=True)
        self.observer.start()
        print(f"[Watcher] Started watching: {self.projects_dir}")

    def stop(self):
        self.observer.stop()
        self.observer.join()
        print("[Watcher] Stopped watching")
