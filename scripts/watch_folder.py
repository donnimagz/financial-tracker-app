#!/usr/bin/env python3
"""
watch_folder.py - Local macOS Folder Watcher for Pennyworth CSV Exports.

Monitors a directory (default: ~/Downloads or iCloud Drive) for newly downloaded,
AirDropped, or exported Pennyworth CSV files. Automatically runs sync_engine.py,
reconciles transactions, and optionally commits & pushes to GitHub.

Usage:
  python3 scripts/watch_folder.py [--dir ~/Downloads] [--git-push] [--once]
"""

import os
import sys
import time
import glob
import shutil
import argparse
from datetime import datetime

# Add project root to sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import sync_engine

def find_candidate_csvs(watch_dir):
    """Find CSV files that look like Pennyworth or expense exports."""
    patterns = [
        os.path.join(watch_dir, "*pennyworth*.csv"),
        os.path.join(watch_dir, "*Pennyworth*.csv"),
        os.path.join(watch_dir, "export*.csv"),
        os.path.join(watch_dir, "*transactions*.csv"),
        os.path.join(watch_dir, "*expense*.csv")
    ]
    matches = []
    for pat in patterns:
        for f in glob.glob(pat):
            if not f.endswith(".processed") and os.path.isfile(f):
                matches.append(f)
    return sorted(list(set(matches)), key=os.path.getmtime)

def process_file(filepath, git_push=False):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Detected export file: {filepath}")
    try:
        res = sync_engine.sync_from_file(filepath, git_push=git_push)
        print(f"Result: {res.get('message', res)}")
        
        # Mark file as processed by renaming to .processed
        processed_path = filepath + ".processed"
        shutil.move(filepath, processed_path)
        print(f"Archived file to: {processed_path}")
        return True
    except Exception as e:
        print(f"Error processing file {filepath}: {e}", file=sys.stderr)
        return False

def watch_loop(watch_dir, git_push=False, interval=5):
    print(f"Watching directory: {watch_dir} (polling every {interval}s)")
    print("Drop or AirDrop a Pennyworth CSV export here to auto-sync.")
    print("Press Ctrl+C to stop.")
    
    while True:
        candidates = find_candidate_csvs(watch_dir)
        for c in candidates:
            # Ensure file is done writing (check file size stability)
            s1 = os.path.getsize(c)
            time.sleep(0.5)
            s2 = os.path.getsize(c)
            if s1 == s2 and s1 > 0:
                process_file(c, git_push=git_push)
        time.sleep(interval)

def main():
    default_watch = os.path.expanduser("~/Downloads")
    # Check iCloud drive Pennyworth folder if present
    icloud_dir = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/Pennyworth")
    if os.path.exists(icloud_dir):
        default_watch = icloud_dir

    parser = argparse.ArgumentParser(description="Financial Tracker Folder Watcher")
    parser.add_argument("--dir", default=default_watch, help=f"Directory to monitor (default: {default_watch})")
    parser.add_argument("--git-push", action="store_true", help="Commit and push changes to git automatically")
    parser.add_argument("--once", action="store_true", help="Process existing files and exit without looping")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    args = parser.parse_args()

    watch_dir = os.path.abspath(os.path.expanduser(args.dir))
    os.makedirs(watch_dir, exist_ok=True)

    if args.once:
        candidates = find_candidate_csvs(watch_dir)
        if not candidates:
            print(f"No new export files found in {watch_dir}.")
        for c in candidates:
            process_file(c, git_push=args.git_push)
    else:
        try:
            watch_loop(watch_dir, git_push=args.git_push, interval=args.interval)
        except KeyboardInterrupt:
            print("\nWatcher stopped.")

if __name__ == "__main__":
    main()
