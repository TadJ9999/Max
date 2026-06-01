from .web_search import WebSearchCapability, ddg_search
from .reports import ReportCapability, ReportService
from .files import FilesCapability, FilesService
from .spotify import SpotifyCapability, SpotifyService
from .calendar_skill import CalendarCapability, CalendarService

__all__ = [
    "WebSearchCapability", "ddg_search",
    "ReportCapability", "ReportService",
    "FilesCapability", "FilesService",
    "SpotifyCapability", "SpotifyService",
    "CalendarCapability", "CalendarService",
]
