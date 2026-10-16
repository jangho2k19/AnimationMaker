import os
from pathlib import Path
import imageio_ffmpeg

import json

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
PROJECTS_DIR = OUTPUT_DIR / "projects"
CACHE_DIR = OUTPUT_DIR / "cache"
CREDENTIALS_FILE = OUTPUT_DIR / "credentials.json"

os.makedirs(PROJECTS_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

def get_server_credentials() -> dict:
    if CREDENTIALS_FILE.exists():
        try:
            with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_server_credentials(creds: dict):
    try:
        existing = get_server_credentials()
        existing.update(creds)
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# Path to self-contained bundled FFmpeg binary
FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()

# Art Styles with tuned prompt modifiers
ART_STYLES = {
    "ghibli": {
        "name": "Studio Ghibli 2D",
        "description": "Lush watercolor backgrounds, hand-drawn anime aesthetic, warm magical lighting",
        "prompt_suffix": ", studio ghibli anime style, hayao miyazaki, lush watercolor backgrounds, soft whimsical lighting, highly detailed, vibrant colors, cinematic 2D animation masterpiece",
        "icon": "🍃"
    },
    "pixar": {
        "name": "3D Pixar / Disney Style",
        "description": "Charming 3D stylized characters, soft volumetric lighting, raytraced rendering",
        "prompt_suffix": ", 3D animated film render, pixar disney style, cute expressive character design, raytraced global illumination, rich textures, cinematic lighting, 8k render, unreal engine 5 octane render",
        "icon": "🧸"
    },
    "storybook": {
        "name": "Classic Storybook Fairy Tale",
        "description": "Delicate ink linework, gouache textures, vintage storybook illustration",
        "prompt_suffix": ", children storybook illustration, delicate ink line art, textured gouache painting, beatrix potter style, vintage fairy tale art, soft pastel color palette, whimsical and heartwarming",
        "icon": "📖"
    },
    "anime_cinematic": {
        "name": "Cinematic Shonen / Makoto Shinkai",
        "description": "Atmospheric skies, lens flares, dramatic hyper-detailed modern anime",
        "prompt_suffix": ", makoto shinkai style, breathtaking sky, dramatic lighting, detailed scenery, anime movie still, high quality 4k wallpaper, vibrant colors, emotional cinematic composition",
        "icon": "✨"
    },
    "cyberpunk": {
        "name": "Cyberpunk Neon Sci-Fi",
        "description": "Futuristic neon glows, rain-soaked reflections, high-tech anime",
        "prompt_suffix": ", cyberpunk anime art, glowing holographic neon lights, rainy futuristic cityscape, blade runner aesthetic, cinematic depth of field, detailed synthwave atmosphere",
        "icon": "🏙️"
    },
    "comic": {
        "name": "Graphic Novel / Comic Art",
        "description": "Bold ink contours, dynamic halftone shading, expressive comic panels",
        "prompt_suffix": ", modern graphic novel illustration, bold inked outlines, vibrant colors, dynamic cinematic framing, into the spiderverse comic book style, highly detailed",
        "icon": "💥"
    }
}

# Voices available (Google Gemini Native Neural Voices & Edge-TTS)
VOICES = [
    # Google Gemini Native Multimodal Voices (Fluent in Vietnamese & English)
    {"id": "gemini-Aoede", "name": "✨ Gemini Aoede (Nữ truyền cảm - VN / Global)", "lang": "vi", "gender": "Female", "provider": "gemini"},
    {"id": "gemini-Kore", "name": "✨ Gemini Kore (Nữ nhẹ nhàng kể chuyện - VN / Global)", "lang": "vi", "gender": "Female", "provider": "gemini"},
    {"id": "gemini-Puck", "name": "✨ Gemini Puck (Nam hoạt bát, sinh động - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini"},
    {"id": "gemini-Charon", "name": "✨ Gemini Charon (Nam trầm ấm điện ảnh - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini"},
    {"id": "gemini-Fenrir", "name": "✨ Gemini Fenrir (Nam hào hùng, lôi cuốn - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini"},

    # Vietnamese Dedicated Voices (Microsoft Edge Neural & Google)
    {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My (Việt Nam - Nữ dịu dàng miền Bắc)", "lang": "vi", "gender": "Female"},
    {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh (Việt Nam - Nam truyền cảm miền Bắc)", "lang": "vi", "gender": "Male"},
    {"id": "vi-VN-HoaiMyNeural-story", "name": "Hoài My Kể Chuyện (Việt Nam - Nữ êm đềm, chậm rãi)", "lang": "vi", "gender": "Female"},
    {"id": "vi-VN-NamMinhNeural-story", "name": "Nam Minh Thuyết Minh (Việt Nam - Nam sâu lắng, ấm áp)", "lang": "vi", "gender": "Male"},
    {"id": "vi-VN-HoaiMyNeural-energetic", "name": "Hoài My Hoạt Bát (Việt Nam - Nữ vui tươi, nhí nhảnh)", "lang": "vi", "gender": "Female"},
    {"id": "vi-VN-NamMinhNeural-heroic", "name": "Nam Minh Khí Thế (Việt Nam - Nam mạnh mẽ, dứt khoát)", "lang": "vi", "gender": "Male"},
    {"id": "gtts-vi", "name": "Google Voice VN (Việt Nam - Nữ chuẩn Google TTS)", "lang": "vi", "gender": "Female"},

    # English (Edge-TTS)
    {"id": "en-US-ChristopherNeural", "name": "Christopher (US - Storyteller Male)", "lang": "en", "gender": "Male"},
    {"id": "en-US-JennyNeural", "name": "Jenny (US - Warm Expressive Female)", "lang": "en", "gender": "Female"},
    {"id": "en-US-GuyNeural", "name": "Guy (US - Casual Friendly Male)", "lang": "en", "gender": "Male"},
    {"id": "en-US-AriaNeural", "name": "Aria (US - Clear Narrator Female)", "lang": "en", "gender": "Female"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (British - Elegant Female)", "lang": "en", "gender": "Female"},
    {"id": "en-GB-RyanNeural", "name": "Ryan (British - Documentary Male)", "lang": "en", "gender": "Male"},
    # Japanese
    {"id": "ja-JP-NanamiNeural", "name": "Nanami (Japanese - Female)", "lang": "ja", "gender": "Female"},
    {"id": "ja-JP-KeitaNeural", "name": "Keita (Japanese - Male)", "lang": "ja", "gender": "Male"},
    # French
    {"id": "fr-FR-DeniseNeural", "name": "Denise (French - Female)", "lang": "fr", "gender": "Female"},
    # Spanish
    {"id": "es-ES-ElviraNeural", "name": "Elvira (Spanish - Female)", "lang": "es", "gender": "Female"},
]

# Camera Motion presets for Ken Burns effect
CAMERA_MOTIONS = [
    {"id": "zoom_in", "name": "Smooth Zoom In", "description": "Slowly moves in toward the focal subject"},
    {"id": "zoom_out", "name": "Reveal Zoom Out", "description": "Starts close and widens to reveal the scene"},
    {"id": "pan_left", "name": "Cinematic Pan Left", "description": "Glides camera horizontally leftward"},
    {"id": "pan_right", "name": "Cinematic Pan Right", "description": "Glides camera horizontally rightward"},
    {"id": "subtle_drift", "name": "Subtle Drift", "description": "Gentle atmospheric ambient drift"}
]

# Supported LLM Providers
AI_PROVIDERS = {
    "gemini": {
        "name": "Google Gemini (Official API Key)",
        "default_model": "gemini-2.5-flash",
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
        "icon": "✨",
        "key_env": "GEMINI_API_KEY",
        "placeholder": "AIzaSy..."
    },
    "gemini_cookie": {
        "name": "Gemini Pro Web (Cookie / No API Quota)",
        "default_model": "default",
        "models": ["default", "gemini-2.5-pro", "gemini-2.0-flash"],
        "icon": "🍪",
        "key_env": "GEMINI_COOKIE",
        "placeholder": "Paste __Secure-1PSID or full Cookie string..."
    },
    "openai": {
        "name": "OpenAI",
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "icon": "🟢",
        "key_env": "OPENAI_API_KEY",
        "placeholder": "sk-proj-..."
    },
    "claude": {
        "name": "Anthropic Claude",
        "default_model": "claude-3-5-sonnet-20241022",
        "models": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
        "icon": "🟣",
        "key_env": "ANTHROPIC_API_KEY",
        "placeholder": "sk-ant-..."
    },
    "deepseek": {
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "icon": "🐋",
        "key_env": "DEEPSEEK_API_KEY",
        "placeholder": "sk-..."
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "default_model": "meta/llama-3.1-70b-instruct",
        "models": ["meta/llama-3.1-70b-instruct", "meta/llama-3.3-70b-instruct", "deepseek-ai/deepseek-r1", "nvidia/nemotron-4-340b-instruct"],
        "icon": "⚡",
        "key_env": "NVIDIA_API_KEY",
        "placeholder": "nvapi-..."
    }
}

# Image Painting Engine Modes
IMAGE_MODES = {
    "manual": {
        "id": "manual",
        "name": "Storyboard Only (No AI Painting)",
        "description": "Zero image AI tokens consumed — uses clean SVG storyboard placeholders and manual user image uploads",
        "icon": "📝"
    },
    "server": {
        "id": "server",
        "name": "Free Neural AI (Flux / SDXL)",
        "description": "Free unlimited neural generation with Flux & SDXL (Zero cost & no rate limits)",
        "icon": "🌐"
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini / Imagen 3",
        "description": "High-fidelity Google Imagen 3 visuals powered by your Gemini Key or Cookie",
        "icon": "✨"
    },
    "neural_love": {
        "id": "neural_love",
        "name": "Neural.love AI Art",
        "description": "High quality artistic illustrations via your Neural.love API key",
        "icon": "💖"
    },
    "puter": {
        "id": "puter",
        "name": "In-Browser Puter.js",
        "description": "Direct in-browser generation using Puter.js cloud balance",
        "icon": "🖌️"
    }
}

# Target Video Duration Presets
DURATION_PRESETS = [
    {"seconds": 30, "label": "30s — Social Short / Reels"},
    {"seconds": 60, "label": "60s — 1 Minute Standard"},
    {"seconds": 90, "label": "90s — 1.5 Minutes Spotlight"},
    {"seconds": 120, "label": "120s — 2 Minutes Mini Film"},
    {"seconds": 180, "label": "180s — 3 Minutes Storybook"},
    {"seconds": 300, "label": "300s — 5 Minutes Feature Short"}
]

# Video Dimensions & Aspect Ratio Presets
VIDEO_DIMENSIONS = {
    "16:9": {
        "id": "16:9",
        "name": "16:9 Widescreen (YouTube, TV, Desktop)",
        "width": 1280,
        "height": 720,
        "icon": "🖥️",
        "ratio_css": "16 / 9",
        "dalle_size": "1792x1024",
        "description": "Standard widescreen landscape HD (1280x720)"
    },
    "9:16": {
        "id": "9:16",
        "name": "9:16 Vertical (TikTok, Reels, Shorts)",
        "width": 720,
        "height": 1280,
        "icon": "📱",
        "ratio_css": "9 / 16",
        "dalle_size": "1024x1792",
        "description": "Full vertical portrait for mobile devices (720x1280)"
    },
    "1:1": {
        "id": "1:1",
        "name": "1:1 Square (Instagram & Social Feeds)",
        "width": 720,
        "height": 720,
        "icon": "🔲",
        "ratio_css": "1 / 1",
        "dalle_size": "1024x1024",
        "description": "Square feed format (720x720)"
    },
    "4:3": {
        "id": "4:3",
        "name": "4:3 Classic TV / Retro Presentation",
        "width": 960,
        "height": 720,
        "icon": "📺",
        "ratio_css": "4 / 3",
        "dalle_size": "1024x1024",
        "description": "Classic standard broadcast format (960x720)"
    },
    "3:4": {
        "id": "3:4",
        "name": "3:4 Tall Portrait (Pinterest, Story)",
        "width": 720,
        "height": 960,
        "icon": "📸",
        "ratio_css": "3 / 4",
        "dalle_size": "1024x1024",
        "description": "Tall vertical portrait format (720x960)"
    },
    "21:9": {
        "id": "21:9",
        "name": "21:9 Ultrawide Cinema (Movie Screen)",
        "width": 1680,
        "height": 720,
        "icon": "🎬",
        "ratio_css": "21 / 9",
        "dalle_size": "1792x1024",
        "description": "Anamorphic panoramic cinema format (1680x720)"
    }
}


