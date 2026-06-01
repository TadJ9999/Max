"""Code editing module — file management and multi-file AI edit planning."""

from .file_manager import FileEntry, FileManager
from .planner import EditPlan, FilePatch

__all__ = ["FileEntry", "FileManager", "EditPlan", "FilePatch"]
