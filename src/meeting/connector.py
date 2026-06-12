"""Browser-based meeting connector using Playwright."""
import asyncio
import logging
import time
from playwright.async_api import async_playwright, Browser, Page

from src.errors import BrowserError, chromium_not_found

logger = logging.getLogger(__name__)


class MeetingConnector:
    """Connects to online meetings via browser automation."""

    def __init__(self):
        self._playwright = None
        self.browser: Browser | None = None
        self.page: Page | None = None

    async def start(self):
        """Launch browser with anti-detection measures."""
        from playwright_stealth import Stealth

        try:
            self._playwright = await async_playwright().start()
            self.browser = await self._playwright.chromium.launch(
                headless=False,
                args=[
                    "--use-fake-device-for-media-stream",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                ],
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "executable doesn't exist" in err_msg or "browsertype.launch" in err_msg:
                raise chromium_not_found() from e
            raise BrowserError(f"Failed to launch browser: {e}") from e
        context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        )
        self.page = await context.new_page()
        await Stealth().apply_stealth_async(self.page)

    async def join_google_meet(self, meeting_url: str, bot_name: str = "Meeting Notes Bot"):
        """Join a Google Meet meeting."""
        await self.page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)  # let SPA hydrate
        try:
            await self.page.wait_for_selector('input[aria-label="Your name"]', timeout=15000)
            await self.page.fill('input[aria-label="Your name"]', bot_name)
            await self.page.click('button[aria-label="Turn off camera"]')
            await self.page.click('button[aria-label="Turn off microphone"]')
            await self.page.click('button:has-text("Ask to join")')
        except Exception as e:
            logger.warning("Google Meet join flow failed: %s", e)
            try:
                await self.page.wait_for_selector('input[aria-label*="Your name"], input[placeholder*="name"]', timeout=10000)
                await self.page.fill('input[aria-label*="Your name"], input[placeholder*="name"]', bot_name)
                await self.page.click('button:has-text("Ask to join"), button:has-text("Join")')
            except Exception as e2:
                logger.error("Google Meet join fallback also failed: %s", e2)

    async def join_zoom(self, meeting_url: str, bot_name: str = "Meeting Notes Bot"):
        """Join a Zoom meeting via web client."""
        await self.page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        try:
            await self.page.wait_for_selector('#input_for_name', timeout=10000)
            await self.page.fill('#input_for_name', bot_name)
            await self.page.click('#joinBtn')
        except Exception as e:
            logger.warning("Zoom join flow failed: %s", e)

    async def join_teams(self, meeting_url: str, bot_name: str = "Meeting Notes Bot"):
        """Join a Microsoft Teams meeting via web."""
        await self.page.goto(meeting_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        try:
            await self.page.wait_for_selector('input[placeholder="Type your name"]', timeout=10000)
            await self.page.fill('input[placeholder="Type your name"]', bot_name)
            await self.page.click('button:has-text("Join now")')
        except Exception as e:
            logger.warning("Teams join flow failed: %s", e)

    async def join_meeting(self, platform: str, url: str, bot_name: str = "Meeting Notes Bot"):
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

    async def wait_for_meeting_end(self, timeout_minutes: int = 120):
        """Wait until meeting ends or timeout."""
        start = time.time()
        while time.time() - start < timeout_minutes * 60:
            try:
                await self.page.wait_for_selector(
                    'button[aria-label*="Leave"], button:has-text("Leave")',
                    timeout=5000,
                )
            except Exception:
                break
            await asyncio.sleep(5)

    async def leave(self):
        """Leave the meeting."""
        try:
            await self.page.click('button[aria-label*="Leave"]')
        except Exception:
            pass

    async def stop(self):
        """Close browser and playwright instance."""
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()
