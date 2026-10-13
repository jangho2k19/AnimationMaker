import os
import asyncio
import logging
from typing import Optional, Tuple
from pathlib import Path

from backend.config import get_server_credentials, save_server_credentials

logger = logging.getLogger("gemini_web_session")

class GeminiWebSessionManager:
    """
    Persistent singleton manager for Google Gemini Web session.
    Maintains active background cookie rotation (auto-refresh) so that
    __Secure-1PSIDTS is automatically renewed with Google and does not expire.
    Guarantees event loop affinity to prevent 'Future attached to different loop' errors.
    """
    _instance: Optional["GeminiWebSessionManager"] = None

    def __init__(self):
        self.client = None
        self.psid: Optional[str] = None
        self.psidts: Optional[str] = None
        self._watcher_task: Optional[asyncio.Task] = None
        self._initialized = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock: Optional[asyncio.Lock] = None

    @classmethod
    def get_instance(cls) -> "GeminiWebSessionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_active_credentials(self) -> Tuple[Optional[str], Optional[str]]:
        creds = get_server_credentials()
        psid = creds.get("gemini_cookie_psid") or os.environ.get("GEMINI_COOKIE_PSID")
        psidts = creds.get("gemini_cookie_psidts") or os.environ.get("GEMINI_COOKIE_PSIDTS")
        
        # Also check combined GEMINI_COOKIE env
        if not psid:
            raw = os.environ.get("GEMINI_COOKIE", "")
            if "__Secure-1PSID" in raw:
                from backend.agents.script_agent import ScriptAgent
                psid, psidts = ScriptAgent._extract_gemini_cookies(None, raw)
        return psid, psidts

    def _ensure_lock(self, current_loop: asyncio.AbstractEventLoop) -> asyncio.Lock:
        if self._lock is None or self._loop != current_loop:
            self._lock = asyncio.Lock()
        return self._lock

    async def get_client(self, psid_override: Optional[str] = None, psidts_override: Optional[str] = None):
        """
        Get or initialize the persistent GeminiClient.
        Keeps background auto_refresh alive to rotate cookies continuously.
        """
        current_loop = asyncio.get_running_loop()
        lock = self._ensure_lock(current_loop)

        async with lock:
            active_psid = psid_override or self.psid
            active_psidts = psidts_override or self.psidts

            if not active_psid:
                active_psid, active_psidts = self._get_active_credentials()

            if not active_psid:
                raise ValueError("No valid __Secure-1PSID found. Please save cookies in Settings ⚙️.")

            # If client exists and event loop matches and credentials haven't changed
            if (
                self.client
                and self._initialized
                and self._loop == current_loop
                and self.psid == active_psid
            ):
                if getattr(self.client, "account_status", None) and self.client.account_status.name != "UNAUTHENTICATED":
                    return self.client

            # If switching loops or credentials, clean up previous client
            if self.client:
                try:
                    if self._watcher_task:
                        self._watcher_task.cancel()
                        self._watcher_task = None
                    if self._loop == current_loop:
                        await self.client.close()
                except Exception:
                    pass
                self.client = None
                self._initialized = False

            self._loop = current_loop
            self.psid = active_psid
            self.psidts = active_psidts

            from gemini_webapi import GeminiClient

            # Enable auto_refresh and disable auto_close so connection remains persistent
            self.client = GeminiClient(
                secure_1psid=self.psid,
                secure_1psidts=self.psidts,
                auto_refresh=True,
                refresh_interval=300
            )

            await self.client.init(
                timeout=60,
                auto_close=False,
                auto_refresh=True,
                refresh_interval=300
            )

            if self.client.account_status.name == "UNAUTHENTICATED":
                self._initialized = False
                raise RuntimeError(
                    "Google Gemini Session is UNAUTHENTICATED or cookies have expired. "
                    "Please copy fresh __Secure-1PSID and __Secure-1PSIDTS from gemini.google.com and save in Settings ⚙️."
                )

            self._initialized = True

            # Start watcher to persist rotated cookies to credentials.json
            self._watcher_task = asyncio.create_task(self._cookie_sync_loop())

            return self.client

    async def _cookie_sync_loop(self):
        """Monitors client cookies for new rotated __Secure-1PSIDTS and saves to disk."""
        while self.client and self._initialized:
            try:
                await asyncio.sleep(60)
                if not self.client or not self._initialized:
                    break
                
                current_ts = None
                if hasattr(self.client, "cookies") and self.client.cookies:
                    current_ts = self.client.cookies.get("__Secure-1PSIDTS")
                
                if current_ts and current_ts != self.psidts:
                    self.psidts = current_ts
                    save_server_credentials({"gemini_cookie_psidts": current_ts})
                    logger.info("Successfully synced newly rotated __Secure-1PSIDTS to disk!")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Cookie sync notice: {e}")

    async def invalidate(self):
        """Invalidate and reset the session."""
        try:
            current_loop = asyncio.get_running_loop()
            lock = self._ensure_lock(current_loop)
            async with lock:
                self._initialized = False
                if self._watcher_task:
                    self._watcher_task.cancel()
                    self._watcher_task = None
                if self.client:
                    try:
                        await self.client.close()
                    except Exception:
                        pass
                    self.client = None
        except Exception:
            self._initialized = False
            self.client = None
