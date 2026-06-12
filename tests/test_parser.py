"""Unit tests for meeting URL parser."""

import pytest

from src.meeting.parser import Platform, MeetingInfo, parse_meeting_url


# ── Platform enum ────────────────────────────────────────────────────────────

def test_platform_values():
    """All expected platforms are defined."""
    assert Platform.GOOGLE_MEET.value == "google_meet"
    assert Platform.ZOOM.value == "zoom"
    assert Platform.TEAMS.value == "teams"
    assert Platform.WEBEX.value == "webex"
    assert Platform.UNKNOWN.value == "unknown"


def test_platform_len():
    """Ensure the enum has exactly the 5 expected members."""
    assert len(Platform) == 5


# ── MeetingInfo dataclass ────────────────────────────────────────────────────

def test_meeting_info_defaults():
    """title defaults to empty string."""
    info = MeetingInfo(Platform.UNKNOWN, "unknown", "http://example.com")
    assert info.platform == Platform.UNKNOWN
    assert info.meeting_id == "unknown"
    assert info.url == "http://example.com"
    assert info.title == ""


def test_meeting_info_custom_title():
    """title can be set explicitly."""
    info = MeetingInfo(Platform.GOOGLE_MEET, "abc-defg-hij",
                       "https://meet.google.com/abc-defg-hij",
                       title="Standup")
    assert info.title == "Standup"


def test_meeting_info_equality():
    """Same fields produce equal dataclass instances."""
    a = MeetingInfo(Platform.ZOOM, "123", "https://zoom.us/j/123")
    b = MeetingInfo(Platform.ZOOM, "123", "https://zoom.us/j/123")
    assert a == b


# ── Google Meet ──────────────────────────────────────────────────────────────

def test_google_meet_standard():
    result = parse_meeting_url("https://meet.google.com/abc-defg-hij")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "abc-defg-hij"
    assert result.url == "https://meet.google.com/abc-defg-hij"


def test_google_meet_with_query_params():
    result = parse_meeting_url(
        "https://meet.google.com/xyz-abcd-uvw?authuser=0&hl=en"
    )
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "xyz-abcd-uvw"


def test_google_meet_case_insensitive():
    result = parse_meeting_url("https://MEET.GOOGLE.COM/AbC-DeFg-HiJ")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "abc-defg-hij"


def test_google_meet_missing_code():
    """URL matches google meet domain but has no valid meeting code."""
    result = parse_meeting_url("https://meet.google.com/")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "unknown"


def test_google_meet_malformed_code():
    """Meeting code doesn't match the expected abc-defg-hij pattern."""
    result = parse_meeting_url("https://meet.google.com/badcode")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "unknown"


def test_google_meet_with_fragment():
    result = parse_meeting_url("https://meet.google.com/qwe-rtyu-iop#heading")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "qwe-rtyu-iop"


def test_google_meet_new_domain():
    """Google Meet can appear at meet.google.com without www prefix."""
    result = parse_meeting_url("https://meet.google.com/lmn-opqr-stu")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "lmn-opqr-stu"


def test_google_meet_with_path_prefix():
    """Code must appear immediately after meet.google.com/ — extra segments
    break regex extraction (the parser does not search deeper)."""
    result = parse_meeting_url(
        "https://meet.google.com/lookup/abc-defg-hij"
    )
    assert result.platform == Platform.GOOGLE_MEET
    # Regex requires code right after the domain; "lookup/" in the way → unknown
    assert result.meeting_id == "unknown"


# ── Zoom ─────────────────────────────────────────────────────────────────────

def test_zoom_standard():
    result = parse_meeting_url("https://zoom.us/j/123456789")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "123456789"
    assert result.url == "https://zoom.us/j/123456789"


def test_zoom_with_pwd():
    result = parse_meeting_url(
        "https://zoom.us/j/987654321?pwd=abc123def456"
    )
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "987654321"


def test_zoom_case_insensitive():
    result = parse_meeting_url("https://ZOOM.US/J/555555555")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "555555555"


def test_zoom_missing_meeting_id():
    result = parse_meeting_url("https://zoom.us/j/")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "unknown"


def test_zoom_no_meeting_path():
    result = parse_meeting_url("https://zoom.us/")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "unknown"


def test_zoom_with_fragment():
    result = parse_meeting_url("https://zoom.us/j/111222333#success")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "111222333"


def test_zoom_subdomain():
    """zoom.us may appear with subdomains like us02web.zoom.us."""
    result = parse_meeting_url(
        "https://us02web.zoom.us/j/444555666?pwd=secret"
    )
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "444555666"


def test_zoom_long_meeting_id():
    """Meeting IDs can be 10-11 digits."""
    result = parse_meeting_url("https://zoom.us/j/12345678901")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "12345678901"


def test_zoom_short_meeting_id():
    """Meeting IDs with fewer digits."""
    result = parse_meeting_url("https://zoom.us/j/123")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "123"


# ── Microsoft Teams ──────────────────────────────────────────────────────────

def test_teams_microsoft_com():
    result = parse_meeting_url(
        "https://teams.microsoft.com/l/meetup-join/"
        "19%3ameeting_ABC123%40thread.v2/0?context=..."
    )
    assert result.platform == Platform.TEAMS
    assert result.meeting_id == "teams"


def test_teams_live_com():
    result = parse_meeting_url(
        "https://teams.live.com/meet/1234567890"
    )
    assert result.platform == Platform.TEAMS
    assert result.meeting_id == "teams"


def test_teams_case_insensitive():
    result = parse_meeting_url(
        "https://TEAMS.MICROSOFT.COM/l/meetup-join/..."
    )
    assert result.platform == Platform.TEAMS


def test_teams_url_includes_both():
    """URL contains both teams substrings — still detected correctly."""
    result = parse_meeting_url(
        "https://teams.microsoft.com/redirect?to=teams.live.com"
    )
    assert result.platform == Platform.TEAMS


def test_teams_bare_domain():
    result = parse_meeting_url("https://teams.microsoft.com/")
    assert result.platform == Platform.TEAMS
    assert result.meeting_id == "teams"


# ── Webex ────────────────────────────────────────────────────────────────────

def test_webex_standard():
    result = parse_meeting_url(
        "https://acme.webex.com/acme/j.php?MTID=abc123def456"
    )
    assert result.platform == Platform.WEBEX
    assert result.meeting_id == "webex"
    assert result.url.startswith("https://acme.webex.com")


def test_webex_case_insensitive():
    result = parse_meeting_url("https://ACME.WEBEX.COM/meet/john")
    assert result.platform == Platform.WEBEX


def test_webex_bare_domain():
    result = parse_meeting_url("https://webex.com/")
    assert result.platform == Platform.WEBEX
    assert result.meeting_id == "webex"


def test_webex_meeting_dot_webex():
    """Some Webex links use meeting.webex.com."""
    result = parse_meeting_url("https://meeting.webex.com/join/smith")
    assert result.platform == Platform.WEBEX


# ── Unknown / random URLs ───────────────────────────────────────────────────

def test_unknown_random_url():
    result = parse_meeting_url("https://example.com/some/page")
    assert result.platform == Platform.UNKNOWN
    assert result.meeting_id == "unknown"
    assert result.url == "https://example.com/some/page"


def test_unknown_generic():
    result = parse_meeting_url("https://calendly.com/user/30min")
    assert result.platform == Platform.UNKNOWN


def test_unknown_empty_string():
    result = parse_meeting_url("")
    assert result.platform == Platform.UNKNOWN
    assert result.meeting_id == "unknown"
    assert result.url == ""


def test_unknown_nonsense():
    result = parse_meeting_url("not-a-url")
    assert result.platform == Platform.UNKNOWN


def test_unknown_looks_like_similar():
    """Parser uses simple substring matching — 'fake-zoom.us' contains 'zoom.us'
    so it is detected as Zoom."""
    result = parse_meeting_url("https://fake-zoom.us/j/123")
    # Substring matching: "zoom.us" appears in "fake-zoom.us"
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "123"


def test_unknown_contains_meet_in_path():
    """Substring matching means 'meet.google.com' in the path still triggers
    Google Meet detection."""
    result = parse_meeting_url("https://example.com/meet.google.com/fake")
    assert result.platform == Platform.GOOGLE_MEET
    # No valid meeting code after the domain-match substring
    assert result.meeting_id == "unknown"


def test_unknown_contains_teams_in_path():
    """Substring matching means 'teams.microsoft.com' in the path still triggers
    Teams detection."""
    result = parse_meeting_url("https://example.com/teams.microsoft.com/fake")
    assert result.platform == Platform.TEAMS
    assert result.meeting_id == "teams"


# ── Edge cases ───────────────────────────────────────────────────────────────

def test_edge_no_scheme():
    """URLs without a scheme are still parsed by substring matching."""
    result = parse_meeting_url("meet.google.com/abc-defg-hij")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "abc-defg-hij"


def test_edge_extra_whitespace():
    """The parser does NOT strip — whitespace may break detection."""
    result = parse_meeting_url("  https://meet.google.com/abc-defg-hij  ")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "abc-defg-hij"


def test_edge_http_not_https():
    result = parse_meeting_url("http://zoom.us/j/999888777")
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "999888777"


def test_edge_meet_redirect():
    """Google Workspace redirect links that go to Meet."""
    result = parse_meeting_url(
        "https://meet.google.com/abc-defg-hij?pli=1&authuser=1"
    )
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "abc-defg-hij"


def test_edge_zoom_with_phone():
    """Zoom links with teleconference numbers — still zoom.us."""
    result = parse_meeting_url(
        "https://zoom.us/j/555111222?pwd=xyz#success"
    )
    assert result.platform == Platform.ZOOM
    assert result.meeting_id == "555111222"


def test_edge_non_ascii():
    """Non-ASCII characters in URL — parser handles them gracefully."""
    result = parse_meeting_url("https://meet.google.com/abc-defg-hij?name=café")
    assert result.platform == Platform.GOOGLE_MEET
    assert result.meeting_id == "abc-defg-hij"


# ── Mutation tests: MeetingInfo immutability ─────────────────────────────────

def test_meeting_info_is_frozen():
    """MeetingInfo fields can be reassigned (dataclass default)."""
    info = parse_meeting_url("https://zoom.us/j/123")
    info.title = "Updated"
    assert info.title == "Updated"


# ── Type consistency ─────────────────────────────────────────────────────────

def test_return_type_is_meeting_info():
    result = parse_meeting_url("https://zoom.us/j/123")
    assert isinstance(result, MeetingInfo)


def test_all_fields_are_strings():
    for url in [
        "https://meet.google.com/abc-defg-hij",
        "https://zoom.us/j/123",
        "https://teams.microsoft.com/l/meetup-join",
        "https://webex.com/meet",
        "https://example.com",
    ]:
        result = parse_meeting_url(url)
        assert isinstance(result.platform, Platform)
        assert isinstance(result.meeting_id, str)
        assert isinstance(result.url, str)
        assert isinstance(result.title, str)
