"""
Compatibility module: re-exports GeminiWebWrapper as GeminiWebSessionManager.
"""
from backend.services.gemini_wrapper import (
    GeminiWebWrapper,
    GeminiWebSessionManager,
    GeminiResponse,
    GeminiImage,
    GeminiChatSession
)

__all__ = [
    "GeminiWebWrapper",
    "GeminiWebSessionManager",
    "GeminiResponse",
    "GeminiImage",
    "GeminiChatSession"
]
