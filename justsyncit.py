#!/usr/bin/env python3
"""Download the latest rclone binary next to this script on Windows, macOS, or Linux."""

import os
import platform
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from tkinter import ttk


sys.dont_write_bytecode = True


DOWNLOAD_BASE = "https://downloads.rclone.org"


def release_target():
    """Return the rclone archive name and downloaded binary name for this host."""
    system = platform.system()
    machine = platform.machine().lower()

    if system == "Windows":
        if machine in {"arm64", "aarch64"}:
            return "windows-arm64", "rclone.exe"
        if machine in {"x86", "i386", "i686"}:
            return "windows-386", "rclone.exe"
        return "windows-amd64", "rclone.exe"

    if system == "Darwin":
        if machine in {"arm64", "aarch64"}:
            return "osx-arm64", "rclone"
        return "osx-amd64", "rclone"

    if system == "Linux":
        if machine in {"arm64", "aarch64"}:
            return "linux-arm64", "rclone"
        if machine in {"x86", "i386", "i686"}:
            return "linux-386", "rclone"
        return "linux-amd64", "rclone"

    raise RuntimeError("This script supports Windows, macOS, and Linux only.")


def download_rclone(report_progress):
    report_progress("Checking your system...", 0)
    target, binary_name = release_target()
    script_dir = Path(__file__).resolve().parent
    destination = script_dir / binary_name
    config_path = script_dir / "rclone.conf"
    url = f"{DOWNLOAD_BASE}/rclone-current-{target}.zip"

    report_progress(f"Downloading latest rclone for {target}...", 5)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "justsyncit"})
        with urllib.request.urlopen(request, timeout=60) as response:
            total_bytes = int(response.headers.get("Content-Length", 0))
            downloaded_bytes = 0
            last_update = 0.0
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".zip", dir=script_dir, delete=False
            ) as archive_file:
                while chunk := response.read(128 * 1024):
                    archive_file.write(chunk)
                    downloaded_bytes += len(chunk)
                    now = time.monotonic()
                    if now - last_update >= 0.05:
                        if total_bytes:
                            percent = 5 + int(downloaded_bytes / total_bytes * 75)
                        else:
                            percent = min(79, 5 + downloaded_bytes // (512 * 1024))
                        megabytes = downloaded_bytes / (1024 * 1024)
                        report_progress(f"Downloading rclone... {megabytes:.1f} MB", percent)
                        last_update = now
                archive_path = Path(archive_file.name)
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not download rclone: {error.reason}") from error

    report_progress("Download complete. Extracting rclone...", 80)
    temporary_binary = None
    try:
        with zipfile.ZipFile(archive_path) as archive:
            member = next(
                (entry for entry in archive.namelist() if Path(entry).name == binary_name),
                None,
            )
            if member is None:
                raise RuntimeError(f"The downloaded archive does not contain {binary_name}.")

            with archive.open(member) as source:
                with tempfile.NamedTemporaryFile(
                    mode="wb", dir=script_dir, delete=False
                ) as binary_file:
                    while chunk := source.read(128 * 1024):
                        binary_file.write(chunk)
                    temporary_binary = Path(binary_file.name)

        if platform.system() != "Windows":
            report_progress("Setting executable permissions...", 90)
            temporary_binary.chmod(temporary_binary.stat().st_mode | 0o111)
        report_progress("Saving rclone beside this script...", 95)
        os.replace(temporary_binary, destination)
    finally:
        archive_path.unlink(missing_ok=True)
        if temporary_binary is not None:
            temporary_binary.unlink(missing_ok=True)

    report_progress("Creating rclone.conf...", 98)
    config_path.touch(exist_ok=True)
    report_progress("rclone is ready.", 100)
    return destination


class RcloneDownloader(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("JustSyncIt")
        self.resizable(False, False)
        self.events = queue.Queue()

        frame = ttk.Frame(self, padding=24)
        frame.grid()
        ttk.Label(frame, text="Download latest rclone", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(frame, text="The rclone binary will be saved next to this script.").grid(
            row=1, column=0, pady=(6, 18), sticky="w"
        )

        self.status = tk.StringVar(value="Preparing download...")
        ttk.Label(frame, textvariable=self.status).grid(row=2, column=0, sticky="w")
        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100, length=360)
        self.progress.grid(row=3, column=0, pady=(8, 6), sticky="ew")
        self.percent = tk.StringVar(value="0%")
        ttk.Label(frame, textvariable=self.percent).grid(row=4, column=0, sticky="e")
        self.download_button = ttk.Button(frame, text="Download again", command=self.start_download)
        self.download_button.grid(row=5, column=0, pady=(16, 0), sticky="e")

        self.after(100, self.start_download)
        self.after(50, self.process_events)

    def start_download(self):
        if self.download_button.instate(("disabled",)):
            return
        self.progress["value"] = 0
        self.percent.set("0%")
        self.status.set("Preparing download...")
        self.download_button.state(("disabled",))
        threading.Thread(target=self.download, daemon=True).start()

    def download(self):
        try:
            destination = download_rclone(self.queue_progress)
        except (RuntimeError, OSError, ValueError, zipfile.BadZipFile) as error:
            self.events.put(("error", str(error)))
        else:
            self.events.put(("complete", str(destination)))

    def queue_progress(self, message, percent):
        self.events.put(("progress", message, min(percent, 100)))

    def process_events(self):
        # Tkinter widgets may only be updated from the main thread.
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    _, message, percent = event
                    self.status.set(message)
                    self.progress["value"] = percent
                    self.percent.set(f"{percent}%")
                elif event[0] == "complete":
                    self.status.set(f"Downloaded: {event[1]}")
                    self.download_button.state(("!disabled",))
                else:
                    self.status.set(f"Error: {event[1]}")
                    self.download_button.state(("!disabled",))
        except queue.Empty:
            pass
        self.after(50, self.process_events)


if __name__ == "__main__":
    RcloneDownloader().mainloop()
