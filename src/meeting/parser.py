"""Parse meeting URLs to detect platform."""
import re
from enum import Enum
from dataclasses import dataclass


class Platform(Enum):
    GOOGLE_MEET = "google_meet"
    ZOOM = "zoom"
    TEAMS = "teams"
    WEBEX = "webex"
    UNKNOWN = "unknown"


@dataclass
class MeetingInfo:
    platform: Platform
    meeting_id: str
    url: str
    title: str = ""


def parse_meeting_url(url: str) -> MeetingInfo:
    """Detect meeting platform from URL."""
    url_lower = url.lower()

    if "meet.google.com" in url_lower:
        match = re.search(r'meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})', url_lower)
        meeting_id = match.group(1) if match else "unknown"
        return MeetingInfo(Platform.GOOGLE_MEET, meeting_id, url)

    elif "zoom.us" in url_lower:
        match = re.search(r'zoom\.us/j/(\d+)', url_lower)
        meeting_id = match.group(1) if match else "unknown"
        return MeetingInfo(Platform.ZOOM, meeting_id, url)

    elif "teams.microsoft.com" in url_lower or "teams.live.com" in url_lower:
        return MeetingInfo(Platform.TEAMS, "teams", url)

    elif "webex.com" in url_lower:
        return MeetingInfo(Platform.WEBEX, "webex", url)

    return MeetingInfo(Platform.UNKNOWN, "unknown", url)
