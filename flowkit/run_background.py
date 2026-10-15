"""Background runner for FlowKit — runs silently with pythonw.exe and logs to flowkit_agent.log."""
import sys
import os
from pathlib import Path

flowkit_dir = Path(__file__).resolve().parent
os.chdir(flowkit_dir)
if str(flowkit_dir) not in sys.path:
    sys.path.insert(0, str(flowkit_dir))

# Redirect stdout and stderr to log file for silent pythonw execution
log_path = flowkit_dir / "flowkit_agent.log"
try:
    log_file = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
except Exception:
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")

import uvicorn
from agent.config import API_HOST, API_PORT

if __name__ == "__main__":
    uvicorn.run(
        "agent.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
    )
