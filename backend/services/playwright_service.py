import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from backend.config import OUTPUT_DIR, get_server_credentials

logger = logging.getLogger("playwright_service")

BROWSER_PROFILE_DIR = OUTPUT_DIR / "browser_profile"
SCREENSHOTS_DIR = OUTPUT_DIR / "browser_screenshots"
BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

class PlaywrightService:
    """
    Automates Chromium browser sessions via Playwright with persistent authentication.
    Uses sync_playwright executed via asyncio.to_thread to eliminate Windows asyncio event loop conflicts.
    Supports:
    - Injecting Google session cookies from credentials.json
    - Persistent user profile directory (preserves Google login across sessions)
    - Headed interactive login window for Google Flow (flow.google.com)
    - Automated page inspection, screenshotting, and video generation
    """

    _instance: Optional["PlaywrightService"] = None

    def __init__(self, headless: bool = True):
        self.headless = headless

    @classmethod
    def get_instance(cls, headless: bool = True) -> "PlaywrightService":
        if cls._instance is None:
            cls._instance = cls(headless=headless)
        return cls._instance

    @staticmethod
    def _get_google_cookies_for_playwright() -> List[Dict[str, Any]]:
        """Constructs cookie dictionaries from saved credentials for Playwright."""
        creds = get_server_credentials()
        cookies = []
        psid = creds.get("gemini_cookie_psid", "")
        psidts = creds.get("gemini_cookie_psidts", "")

        if psid:
            cookies.append({
                "name": "__Secure-1PSID",
                "value": psid,
                "domain": ".google.com",
                "path": "/",
                "secure": True,
                "httpOnly": True
            })
        if psidts:
            cookies.append({
                "name": "__Secure-1PSIDTS",
                "value": psidts,
                "domain": ".google.com",
                "path": "/",
                "secure": True,
                "httpOnly": True
            })
        return cookies

    def _sync_check_flow_status(self) -> Dict[str, Any]:
        """Internal synchronous check executed inside background worker thread."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_PROFILE_DIR),
                headless=True,
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )
            saved_cookies = self._get_google_cookies_for_playwright()
            if saved_cookies:
                try:
                    context.add_cookies(saved_cookies)
                except Exception as e:
                    logger.warning("Could not add initial cookies: %s", e)

            page = context.new_page()
            try:
                target_url = "https://flow.google.com"
                logger.info("Visiting %s via Playwright...", target_url)
                page.goto(target_url, wait_until="load", timeout=35000)
                page.wait_for_timeout(3000)

                current_url = page.url
                title = page.title()
                content = page.content()

                shot_file = SCREENSHOTS_DIR / "flow_status.png"
                page.screenshot(path=str(shot_file))

                is_login_page = ("accounts.google.com" in current_url) or ("Sign in" in title)
                is_flow_dashboard = ("flow.google.com" in current_url) and not is_login_page
                has_veo = "veo" in content.lower() or "video" in content.lower()

                return {
                    "status": "logged_in" if is_flow_dashboard else ("needs_login" if is_login_page else "accessible"),
                    "current_url": current_url,
                    "title": title,
                    "is_flow_dashboard": is_flow_dashboard,
                    "has_veo_features": has_veo,
                    "screenshot": str(shot_file.relative_to(OUTPUT_DIR)).replace("\\", "/")
                }
            finally:
                page.close()
                context.close()

    async def check_flow_status(self) -> Dict[str, Any]:
        """Async wrapper around the synchronous Playwright status check."""
        try:
            return await asyncio.to_thread(self._sync_check_flow_status)
        except Exception as e:
            logger.exception("Playwright check_flow_status failed")
            return {
                "status": "error",
                "error": f"{type(e).__name__}: {str(e)}",
                "is_flow_dashboard": False
            }

    def _sync_launch_headed_browser(self, target_url: str):
        """Launches a visible Chromium window in a separate process/thread."""
        import subprocess
        # Use playwright CLI or python script to open browser with persistent profile
        cmd = [
            sys.executable,
            "-c",
            f"from playwright.sync_api import sync_playwright; p=sync_playwright().start(); ctx=p.chromium.launch_persistent_context(r'{BROWSER_PROFILE_DIR}', headless=False, args=['--disable-blink-features=AutomationControlled']); page=ctx.new_page(); page.goto(r'{target_url}'); input('Browser open. Press Enter when done...'); ctx.close(); p.stop()"
        ]
        proc = subprocess.Popen(cmd)
        return proc.pid

    async def launch_headed_browser(self, target_url: str = "https://flow.google.com") -> Dict[str, Any]:
        """Launches an interactive Chromium window with the persistent profile."""
        pid = await asyncio.to_thread(self._sync_launch_headed_browser, target_url)
        return {
            "status": "opened",
            "url": target_url,
            "pid": pid,
            "profile_dir": str(BROWSER_PROFILE_DIR)
        }

    async def close(self):
        """No-op or cleanup for persistent resources."""
        pass
