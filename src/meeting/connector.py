"""Browser-based meeting connector using Playwright.

Detection-evasion strategy
--------------------------
Google Meet, Zoom, and Teams all run bot-detection JS that checks for:
  - navigator.webdriver flag           → patched by playwright-stealth
  - Chrome DevTools Protocol traces    → mitigated by headless=False
  - Fake media device enumeration      → we do NOT pass --use-fake-device-for-media-stream;
                                          real virtual audio devices are used instead
                                          (PulseAudio null-sink on Linux, BlackHole on macOS)
  - Missing persistent browser state   → use chrome_user_data_dir for Google sessions

Cross-platform virtual display
-------------------------------
- Linux headless (CI, Docker, SSH): Xvfb via VirtualDisplay so Chrome sees a real X server
- macOS / Windows: native display session is always available; VirtualDisplay is a no-op

Zoom web client vs Meeting SDK
-------------------------------
The Zoom Meeting SDK is a native C++/Objective-C SDK with no Python bindings. For Python,
the correct approach is Zoom's web client (zoom.us/wc/join/MEETING_ID), which is Zoom's
own browser-based joining path — identical to what human guests use. We rewrite standard
/j/ join links to /wc/join/ to skip the "Open Zoom?" native-app redirect page.
"""
import asyncio
import logging
import platform
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from src.errors import BrowserError, chromium_not_found
from src.meeting.display import VirtualDisplay

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()


def _zoom_web_client_url(url: str) -> str:
    """Rewrite a standard Zoom join URL to the web client path.

    zoom.us/j/12345?pwd=X  →  zoom.us/wc/join/12345?pwd=X

    The /j/ path shows an interstitial that tries to open the native app.
    /wc/join/ goes directly to the in-browser client.
    """
    parsed = urlparse(url)
    if "zoom.us" not in parsed.netloc:
        return url
    if parsed.path.startswith("/wc/"):
        return url
    match = re.search(r"/j/(\d+)", parsed.path)
    if match:
        meeting_id = match.group(1)
        query = f"?{parsed.query}" if parsed.query else ""
        return f"https://zoom.us/wc/join/{meeting_id}{query}"
    return url


def _build_launch_args() -> list[str]:
    """Return Chromium launch flags appropriate for the current OS."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
    ]
    if _SYSTEM == "Linux":
        # Required in containerised / low-resource environments
        args += [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
    return args


def _user_agent() -> str:
    ua_platform = (
        "Macintosh; Intel Mac OS X 10_15_7" if _SYSTEM == "Darwin"
        else "Windows NT 10.0; Win64; x64" if _SYSTEM == "Windows"
        else "X11; Linux x86_64"
    )
    return (
        f"Mozilla/5.0 ({ua_platform}) AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/125.0.0.0 Safari/537.36"
    )


class MeetingConnector:
    """Connects to online meetings via browser automation."""

    def __init__(self):
        self._playwright = None
        self.browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self._vdisplay: VirtualDisplay | None = None

    async def start(self, user_data_dir: str | None = None):
        """Launch browser with anti-detection measures.

        Parameters
        ----------
        user_data_dir:
            Path to a Chrome user data directory that already has a Google
            account signed in. When set, the browser reuses that session so
            Google Meet sees an authenticated user rather than a bot.
            Create one by running Chrome once with:
                chromium --user-data-dir=/path/to/dir
            and signing in to Google, then point this setting at that path.
            Leave as None for anonymous / guest joining (works for Zoom/Teams;
            may be limited on Google Meet).
        """
        from playwright_stealth import Stealth

        # Start virtual display before the browser (no-op on macOS/Windows)
        self._vdisplay = VirtualDisplay()
        self._vdisplay.start()

        args = _build_launch_args()
        ua = _user_agent()

        try:
            self._playwright = await async_playwright().start()

            if user_data_dir:
                # Persistent context — reuses cookies/session from an existing Chrome profile
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=False,
                    args=args,
                    user_agent=ua,
                    viewport={"width": 1280, "height": 720},
                )
                self.browser = None
                self.page = await self._context.new_page()
                logger.info("Browser launched with persistent profile: %s", user_data_dir)
            else:
                self.browser = await self._playwright.chromium.launch(
                    headless=False,
                    args=args,
                )
                self._context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=ua,
                )
                self.page = await self._context.new_page()
                logger.info("Browser launched (anonymous session)")

        except Exception as e:
            err_msg = str(e).lower()
            if "executable doesn't exist" in err_msg or "browsertype.launch" in err_msg:
                raise chromium_not_found() from e
            raise BrowserError(f"Failed to launch browser: {e}") from e

        await Stealth().apply_stealth_async(self.page)

    # ── Platform join methods ────────────────────────────────────────────

    async def join_google_meet(self, meeting_url: str, bot_name: str = "Meeting Notes Bot"):
        """Join a Google Meet meeting.

        For best results, pass a chrome_user_data_dir with a signed-in Google
        account when calling start(). Without a session, Meet may restrict the
        guest to observer-only or block the join entirely.
        """
        await self.page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(4)  # wait for SPA hydration and bot-detection JS to settle

        # Pre-join: disable camera and microphone if buttons are present
        for label in ("Turn off camera", "Turn off microphone"):
            try:
                await self.page.click(f'button[aria-label="{label}"]', timeout=3000)
            except Exception:
                pass

        # Fill in guest name if the name input is shown (anonymous / pre-join screen)
        name_selectors = [
            'input[aria-label="Your name"]',
            'input[placeholder*="name" i]',
            'input[data-testid*="name" i]',
        ]
        for sel in name_selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=5000)
                await self.page.fill(sel, bot_name)
                logger.debug("Filled name field with '%s'", bot_name)
                break
            except Exception:
                continue

        # Click the join / ask-to-join button
        join_selectors = [
            'button:has-text("Ask to join")',
            'button:has-text("Join now")',
            'button:has-text("Join")',
        ]
        joined = False
        for sel in join_selectors:
            try:
                await self.page.click(sel, timeout=5000)
                logger.info("Google Meet: clicked join button (%s)", sel)
                joined = True
                break
            except Exception:
                continue

        if not joined:
            logger.warning(
                "Google Meet: could not find a join button. "
                "The meeting may require a signed-in Google account. "
                "Set chrome_user_data_dir in config to a pre-authenticated Chrome profile."
            )

    async def join_zoom(self, meeting_url: str, bot_name: str = "Meeting Notes Bot"):
        """Join a Zoom meeting via the Zoom web client.

        Standard zoom.us/j/ URLs are rewritten to zoom.us/wc/join/ to skip
        the native-app redirect interstitial. The web client is Zoom's official
        browser-based join path and requires no Zoom account.
        """
        web_url = _zoom_web_client_url(meeting_url)
        if web_url != meeting_url:
            logger.debug("Zoom URL rewritten: %s → %s", meeting_url, web_url)

        await self.page.goto(web_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Name input — Zoom web client uses several selector variants
        name_selectors = [
            '#input-for-name',
            '#inputname',
            'input[placeholder*="name" i]',
        ]
        for sel in name_selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=8000)
                await self.page.fill(sel, bot_name)
                logger.debug("Zoom: filled name field")
                break
            except Exception:
                continue

        # Join button
        join_selectors = [
            '#joinBtn',
            'button:has-text("Join")',
            'button[type="submit"]',
        ]
        for sel in join_selectors:
            try:
                await self.page.click(sel, timeout=5000)
                logger.info("Zoom: clicked join button")
                break
            except Exception:
                continue
        else:
            logger.warning("Zoom: could not find the join button")

    async def join_teams(self, meeting_url: str, bot_name: str = "Meeting Notes Bot"):
        """Join a Microsoft Teams meeting via the web client.

        Teams allows anonymous guest joining without a Microsoft account,
        making it the most bot-friendly of the three major platforms.
        """
        await self.page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Dismiss "Open the Teams app?" banner if present
        try:
            await self.page.click('button:has-text("Continue on this browser")', timeout=5000)
        except Exception:
            pass

        # Guest name input
        name_selectors = [
            'input[placeholder="Type your name"]',
            'input[placeholder*="name" i]',
            'input[data-tid="prejoin-display-name-input"]',
        ]
        for sel in name_selectors:
            try:
                await self.page.wait_for_selector(sel, timeout=10000)
                await self.page.fill(sel, bot_name)
                logger.debug("Teams: filled name field")
                break
            except Exception:
                continue

        # Join button
        join_selectors = [
            'button:has-text("Join now")',
            'button:has-text("Join")',
            'button[data-tid="prejoin-join-button"]',
        ]
        for sel in join_selectors:
            try:
                await self.page.click(sel, timeout=5000)
                logger.info("Teams: clicked join button")
                break
            except Exception:
                continue
        else:
            logger.warning("Teams: could not find the join button")

    # ── Dispatcher ──────────────────────────────────────────────────────

    async def join_meeting(
        self,
        platform: str,
        url: str,
        bot_name: str = "Meeting Notes Bot",
        user_data_dir: str | None = None,
    ):
        """Join a meeting on any supported platform."""
        join_methods = {
            "google_meet": self.join_google_meet,
            "zoom": self.join_zoom,
            "teams": self.join_teams,
        }
        method = join_methods.get(platform)
        if method:
            await method(url, bot_name)
        elif platform == "webex":
            raise BrowserError(
                "Webex meetings are not yet supported for auto-join. "
                "Use 'meeting-agent listen' instead and join manually."
            )
        else:
            raise BrowserError(f"Unsupported meeting platform: {platform}")

    # ── Meeting lifecycle ────────────────────────────────────────────────

    async def wait_for_meeting_end(self, timeout_minutes: int = 120):
        """Poll until the meeting ends or the timeout expires."""
        start = time.time()
        while time.time() - start < timeout_minutes * 60:
            try:
                await self.page.wait_for_selector(
                    'button[aria-label*="Leave"], button:has-text("Leave"), '
                    'button:has-text("End call")',
                    timeout=5000,
                )
            except Exception:
                # Selector gone → meeting has ended
                break
            await asyncio.sleep(5)

    async def leave(self):
        """Click the Leave / End call button."""
        for sel in (
            'button[aria-label*="Leave"]',
            'button:has-text("Leave")',
            'button:has-text("End call")',
        ):
            try:
                await self.page.click(sel, timeout=3000)
                return
            except Exception:
                continue

    async def stop(self):
        """Close browser, playwright instance, and virtual display."""
        if self.page:
            try:
                await self.page.close()
            except Exception:
                pass
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
        elif self._context:
            # persistent context path — closing the context also closes the browser
            try:
                await self._context.close()
            except Exception:
                pass
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        if self._vdisplay:
            self._vdisplay.stop()
