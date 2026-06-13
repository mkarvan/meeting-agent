"""Browser-based meeting connector using Playwright.

Detection-evasion strategy
--------------------------
Google Meet, Zoom, and Teams all run bot-detection JS that checks for:

  navigator.webdriver           → patched by playwright-stealth on the *context*
                                  (covers all pages, not just the first one)
  CDP Runtime.enable trace      → mitigated by headless=False + system Chrome
  Playwright Chromium build     → the bundled Chromium has known build IDs / WebGL
                                  renderer strings that Google fingerprints. Using
                                  channel="chrome" (system-installed Google Chrome)
                                  eliminates this entire vector.
  UA string / version mismatch  → when using a named channel the browser's real UA
                                  is left untouched; custom UA is only injected for
                                  the bundled Playwright Chromium where it matters.
  Fake media device enumeration → --use-fake-device-for-media-stream is NOT used;
                                  real virtual audio devices (PulseAudio / BlackHole)
                                  are used instead. --use-fake-ui-for-media-stream
                                  silences the permission dialog without touching devices.
  Missing persistent session    → chrome_user_data_dir lets the bot reuse a real
                                  Google account session across runs.

Chrome channel selection (chrome_channel config / --chrome-channel flag)
------------------------------------------------------------------------
  "auto"     → try system Chrome, then system Chromium, then Playwright bundled Chromium
  "chrome"   → system Google Chrome required (falls back to bundled on failure)
  "chromium" → system Chromium required (falls back to bundled on failure)
  ""         → always use Playwright's bundled Chromium (no system Chrome needed)

Linux headless
--------------
  Xvfb virtual display is started automatically when $DISPLAY is not set.
  Requires: sudo apt-get install xvfb && pip install 'meeting-agent[linux]'

Zoom web client
---------------
  The Zoom Meeting SDK is native C++/Obj-C with no Python bindings. The web
  client (zoom.us/wc/join/ID) is Zoom's own browser-based path. Standard /j/
  links are rewritten automatically.
"""
import asyncio
import logging
import platform
import re
import time
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from src.errors import BrowserError, chromium_not_found
from src.meeting.display import VirtualDisplay

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()


# ── URL helpers ───────────────────────────────────────────────────────────────

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


# ── Browser launch helpers ────────────────────────────────────────────────────

def _resolve_channels(pref: str) -> list[str | None]:
    """Return the ordered list of channels to try.

    None in the list means "Playwright's bundled Chromium" (always last resort).

      "auto"     → ["chrome", "chromium", None]
      "chrome"   → ["chrome", None]
      "chromium" → ["chromium", None]
      ""         → [None]
    """
    pref = (pref or "").strip().lower()
    if pref == "auto":
        return ["chrome", "chromium", None]
    if pref in ("chrome", "chromium", "msedge"):
        return [pref, None]
    return [None]


def _build_launch_args() -> list[str]:
    """Return Chromium launch flags appropriate for the current OS."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        # Auto-accept mic/camera permission dialog without faking the underlying
        # devices (distinct from --use-fake-device-for-media-stream).
        "--use-fake-ui-for-media-stream",
        # Suppress first-run UX and default-browser prompts that can block the page.
        "--no-first-run",
        "--no-default-browser-check",
        # Avoid keyring / secret-service dialogs on Linux desktop sessions.
        "--password-store=basic",
        # Set window size explicitly so viewport and window match.
        "--window-size=1280,720",
    ]
    if _SYSTEM == "Linux":
        # Required in containerised / low-resource environments.
        args += [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ]
    return args


def _user_agent() -> str:
    """Fallback UA used only when running Playwright's bundled Chromium."""
    ua_platform = (
        "Macintosh; Intel Mac OS X 10_15_7" if _SYSTEM == "Darwin"
        else "Windows NT 10.0; Win64; x64" if _SYSTEM == "Windows"
        else "X11; Linux x86_64"
    )
    return (
        f"Mozilla/5.0 ({ua_platform}) AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/125.0.0.0 Safari/537.36"
    )


async def _launch_browser(playwright, args: list[str], channels: list[str | None]) -> tuple[Browser, str | None]:
    """Try each channel in order; return (browser, channel_used).

    Named channels (system Chrome / Chromium) are tried first. If none are
    installed, falls back to Playwright's bundled Chromium (channel=None).
    Failure of the bundled fallback is always fatal.
    """
    for ch in channels:
        try:
            browser = await playwright.chromium.launch(
                headless=False,
                args=args,
                **({"channel": ch} if ch else {}),
            )
            logger.info(
                "Browser launched: %s",
                f"system Chrome (channel='{ch}')" if ch else "Playwright bundled Chromium",
            )
            return browser, ch
        except Exception as e:
            if ch is not None:
                logger.debug("Channel '%s' unavailable — trying next (%s)", ch, e)
            else:
                raise BrowserError(f"Failed to launch browser: {e}") from e
    raise BrowserError("No usable Chrome/Chromium browser found")


async def _launch_persistent(
    playwright,
    user_data_dir: str,
    args: list[str],
    channels: list[str | None],
) -> tuple[BrowserContext, str | None]:
    """Try each channel for a persistent-context launch; return (context, channel_used)."""
    for ch in channels:
        try:
            ctx = await playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                args=args,
                viewport={"width": 1280, "height": 720},
                **({"channel": ch} if ch else {}),
            )
            logger.info(
                "Persistent browser context launched: %s — profile: %s",
                f"system Chrome (channel='{ch}')" if ch else "Playwright bundled Chromium",
                user_data_dir,
            )
            return ctx, ch
        except Exception as e:
            if ch is not None:
                logger.debug(
                    "Channel '%s' unavailable for persistent context — trying next (%s)", ch, e
                )
            else:
                raise BrowserError(f"Failed to launch persistent browser context: {e}") from e
    raise BrowserError("No usable Chrome/Chromium browser found for persistent context")


# ── Connector ─────────────────────────────────────────────────────────────────

class MeetingConnector:
    """Connects to online meetings via browser automation."""

    def __init__(self):
        self._playwright = None
        self.browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None
        self._vdisplay: VirtualDisplay | None = None

    async def start(self, user_data_dir: str | None = None, channel: str = "auto"):
        """Launch browser with anti-detection measures.

        Parameters
        ----------
        user_data_dir:
            Path to a Chrome user data directory that already has a Google
            account signed in. When set, the browser reuses that session so
            Google Meet sees an authenticated user rather than a bot.
            Create one by running:
                chromium --user-data-dir=/path/to/dir
            Sign in to Google, close Chrome, then pass this path here.
        channel:
            Which browser binary to prefer. "auto" tries system Chrome, then
            system Chromium, then falls back to Playwright's bundled Chromium.
            Use "" to force the bundled Chromium (no system Chrome required).
        """
        # Start virtual display before the browser (no-op on macOS/Windows).
        self._vdisplay = VirtualDisplay()
        self._vdisplay.start()

        args = _build_launch_args()
        channels = _resolve_channels(channel)

        try:
            self._playwright = await async_playwright().start()

            if user_data_dir:
                self._context, ch_used = await _launch_persistent(
                    self._playwright, user_data_dir, args, channels
                )
                self.browser = None
            else:
                self.browser, ch_used = await _launch_browser(
                    self._playwright, args, channels
                )
                ctx_kwargs: dict = {"viewport": {"width": 1280, "height": 720}}
                if ch_used is None:
                    # Bundled Playwright Chromium: override UA so it matches a real Chrome.
                    # When using a named channel the browser reports its own real UA — we
                    # must NOT override it or the version strings become inconsistent.
                    ctx_kwargs["user_agent"] = _user_agent()
                self._context = await self.browser.new_context(**ctx_kwargs)

            # Apply stealth to the *context* so every page opened from it is patched —
            # including any popup, iframe, or redirect page Google Meet may open.
            await Stealth().apply_stealth_async(self._context)

            # Pre-grant mic/camera via the Web Permission API before any page loads.
            await self._context.grant_permissions(["microphone", "camera"])

            self.page = await self._context.new_page()

        except BrowserError:
            raise
        except Exception as e:
            err_msg = str(e).lower()
            if "executable doesn't exist" in err_msg or "browsertype.launch" in err_msg:
                raise chromium_not_found() from e
            raise BrowserError(f"Failed to launch browser: {e}") from e

    # ── Platform join methods ────────────────────────────────────────────

    async def join_google_meet(self, meeting_url: str, bot_name: str = "Meeting Notes Bot"):
        """Join a Google Meet meeting.

        For best results, pass a chrome_user_data_dir with a signed-in Google
        account when calling start(). Without a session, Meet may restrict the
        guest to observer-only or block the join entirely.
        """
        await self.page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(4)  # wait for SPA hydration and bot-detection JS to settle

        # Pre-join: disable camera and microphone if buttons are present.
        for label in ("Turn off camera", "Turn off microphone"):
            try:
                await self.page.click(f'button[aria-label="{label}"]', timeout=3000)
            except Exception:
                pass

        # Fill in guest name if the name input is shown (anonymous / pre-join screen).
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

        # Click the join / ask-to-join button.
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

        # Name input — Zoom web client uses several selector variants.
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

        # Dismiss "Open the Teams app?" banner if present.
        try:
            await self.page.click('button:has-text("Continue on this browser")', timeout=5000)
        except Exception:
            pass

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
            # Persistent context path — closing the context also closes the browser.
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
