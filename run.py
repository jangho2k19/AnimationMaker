import os
import sys
import socket
import uvicorn
import webbrowser
from threading import Timer

# Reconfigure console streams to UTF-8 on Windows to eliminate UnicodeEncodeError with non-ASCII text
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a given port is already occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def find_available_port(preferred_port: int = 8088, max_attempts: int = 50) -> int:
    """Find the preferred port or the next available port."""
    for p in range(preferred_port, preferred_port + max_attempts):
        if not is_port_in_use(p):
            return p
    return preferred_port

def open_browser(port: int):
    webbrowser.open(f"http://localhost:{port}")

if __name__ == "__main__":
    # Check CLI arguments or environment variable for custom port
    custom_port = None
    for idx, arg in enumerate(sys.argv[1:]):
        if arg in ("--port", "-p") and idx + 1 < len(sys.argv) - 1:
            try:
                custom_port = int(sys.argv[idx + 2])
            except ValueError:
                pass
        elif arg.isdigit():
            custom_port = int(arg)

    if not custom_port:
        custom_port = int(os.environ.get("PORT", 8088))

    port = find_available_port(preferred_port=custom_port)

    print("\n" + "="*65)
    print("🎬 AniStory AI — Autonomous Animation Studio Agent")
    print("="*65)
    print(f"👉 Studio Web App URL : http://localhost:{port}")
    if port != custom_port:
        print(f"ℹ️ (Port {custom_port} was occupied, automatically switched to {port})")
    print("="*65 + "\n")

    # Open browser automatically after server boots
    Timer(1.2, open_browser, args=[port]).start()

    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=True)
