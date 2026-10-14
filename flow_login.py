#!/usr/bin/env python3
"""
🎬 AniStory AI — Google Flow Playwright Session Manager
Launches a visible Chromium browser with persistent storage (output/browser_profile).
Allows you to sign in to Google Flow (flow.google.com) with your Google account.
Once signed in, the authentication state, tokens, and cookies remain saved permanently.
"""

import os
import sys
import asyncio

# Auto-switch to virtual environment Python if running outside a venv
if sys.prefix == sys.base_prefix:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_pythons = [
        os.path.join(script_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(script_dir, "venv", "Scripts", "python.exe"),
        os.path.join(script_dir, ".venv", "bin", "python"),
        os.path.join(script_dir, "venv", "bin", "python"),
    ]
    for venv_py in venv_pythons:
        if os.path.isfile(venv_py) and os.path.abspath(sys.executable) != os.path.abspath(venv_py):
            import subprocess
            try:
                sys.exit(subprocess.call([venv_py] + sys.argv))
            except Exception:
                pass

from backend.services.playwright_service import PlaywrightService, BROWSER_PROFILE_DIR

async def main():
    print("\n" + "=" * 65)
    print("🎬 AniStory AI — Google Flow (Playwright Login)")
    print("=" * 65)
    print(f"📁 Persistent Profile: {BROWSER_PROFILE_DIR}")
    print("🌐 Launching Chromium browser to: https://flow.google.com ...")
    print("👉 Please log in with your Google account in the opened browser.")
    print("=" * 65 + "\n")

    svc = PlaywrightService.get_instance(headless=False)
    res = await svc.launch_headed_browser("https://flow.google.com")
    print("✅ Browser opened! Once you have logged in and see Google Flow,")
    
    try:
        input("👉 Press [ENTER] in this console when you are done to save session & close browser: ")
    except EOFError:
        # If running in non-interactive environment, keep open for 60 seconds
        print("Waiting 60 seconds for login...")
        await asyncio.sleep(60)

    print("\nVerifying Google Flow login status...")
    status = await svc.check_flow_status()
    print("Result:", status.get("status"), "| Title:", status.get("title"))
    if status.get("is_flow_dashboard"):
        print("🎉 SUCCESS: You are signed into Google Flow! Session is saved.")
    else:
        print("ℹ️ Current status:", status.get("status"))

    await svc.close()
    print("Browser closed. Persistent profile ready for automation.\n")

if __name__ == "__main__":
    asyncio.run(main())
