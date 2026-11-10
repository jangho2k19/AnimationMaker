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
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[config] Warning: could not read {CREDENTIALS_FILE.name}: {e}")
    return {}

def save_server_credentials(creds: dict):
    """Merges and atomically persists credentials. Raises on failure so callers can report it."""
    existing = get_server_credentials()
    existing.update(creds)
    tmp_file = CREDENTIALS_FILE.with_suffix(".json.tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    os.replace(tmp_file, CREDENTIALS_FILE)

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
    },
    "stick_figure": {
        "name": "Stick Figure Animation",
        "description": "Minimalist stickman figures, clean line art, dynamic action choreography (Alan Becker / Xiao Xiao style)",
        "prompt_suffix": ", minimalist stick figure animation style, iconic stickman character design, simple circular head, clean bold line-drawn limbs and torso, expressive stick figure posing and energetic action choreography, Alan Becker Animation vs Animator aesthetic, clean high-contrast minimalist background, crisp 2D vector lineart, action silhouette, textless, no photorealistic human faces, no detailed human skin, no complex rendered clothing, classic stickman animation masterpiece",
        "icon": "🏃"
    },
    "realistic": {
        "name": "Realistic / Live-Action Cinema",
        "description": "Hyper-realistic cinema, 35mm photography, natural lighting & lifelike textures",
        "prompt_suffix": ", photorealistic RAW photograph, cinematic live-action film still, shot on 35mm lens, 8k resolution, ultra-detailed textures, natural dramatic lighting, shallow depth of field, sharp focus, masterpiece photography, lifelike realism",
        "icon": "📸"
    }
}

# Combinable Camera-on-Speaker (Dialogue Film) suffix that works with ANY Visual Animation Style
SPEAKER_FOCUS_PROMPT_SUFFIX = (
    ", cinematic dialogue shot, camera focused directly on the speaking character, "
    "medium close-up and over-the-shoulder shot-reverse-shot conversation framing, "
    "expressive facial acting and natural lip-sync mouth articulation while speaking, "
    "warm key light on the active speaker's face, shallow 50mm f/1.8 depth of field with soft background bokeh"
)

# Voices available (Vietnamese Dedicated Neural Personas, Google Gemini Multimodal Voices & International)
VOICES = [
    # 1. Vietnamese Dedicated Neural Voices & Character Personas (Microsoft Edge Neural — 100% Free & Consistent)
    {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My (Việt Nam - Nữ chuẩn dịu dàng, tự nhiên)", "lang": "vi", "gender": "Female", "group": "vn_neural"},
    {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh (Việt Nam - Nam chuẩn truyền cảm, ấm áp)", "lang": "vi", "gender": "Male", "group": "vn_neural"},
    {"id": "vi-VN-HoaiMyNeural-story", "name": "Thanh Hà Kể Chuyện (Việt Nam - Nữ êm đềm, sâu lắng, cổ tích)", "lang": "vi", "gender": "Female", "group": "vn_neural"},
    {"id": "vi-VN-NamMinhNeural-story", "name": "Bác Ba Kể Chuyện (Việt Nam - Nam trầm ấm, dân gian & hồi ức)", "lang": "vi", "gender": "Male", "group": "vn_neural"},
    {"id": "vi-VN-HoaiMyNeural-energetic", "name": "Linh Đan Hoạt Bát (Việt Nam - Nữ vui tươi, nhí nhảnh, thiếu nhi)", "lang": "vi", "gender": "Female", "group": "vn_neural"},
    {"id": "vi-VN-NamMinhNeural-energetic", "name": "Tí Hon / Minh Khôi (Việt Nam - Nam hài hước, lém lỉnh, truyện cười)", "lang": "vi", "gender": "Male", "group": "vn_neural"},
    {"id": "vi-VN-NamMinhNeural-heroic", "name": "Quan Đại Nhân / Hùng Dũng (Việt Nam - Nam uy nghiêm, cổ trang & sử thi)", "lang": "vi", "gender": "Male", "group": "vn_neural"},
    {"id": "vi-VN-HoaiMyNeural-sweet", "name": "Ngọc Lan Ngọt Ngào (Việt Nam - Nữ trong trẻo, thơ mộng & cảm xúc)", "lang": "vi", "gender": "Female", "group": "vn_neural"},
    {"id": "vi-VN-HoaiMyNeural-drama", "name": "Mai Phương Điện Ảnh (Việt Nam - Nữ kịch tính, sâu sắc & tâm lý)", "lang": "vi", "gender": "Female", "group": "vn_neural"},
    {"id": "vi-VN-NamMinhNeural-documentary", "name": "Hoàng Quân Thuyết Minh (Việt Nam - Nam điềm đạm, chững chạc, tài liệu)", "lang": "vi", "gender": "Male", "group": "vn_neural"},
    {"id": "vi-VN-HoaiMyNeural-commercial", "name": "Minh Anh Review (Việt Nam - Nữ năng động, sắc nét, Quảng cáo & Reels)", "lang": "vi", "gender": "Female", "group": "vn_neural"},
    {"id": "vi-VN-NamMinhNeural-commercial", "name": "Quốc Khánh Review (Việt Nam - Nam hiện đại, cuốn hút, Quảng cáo & TikTok)", "lang": "vi", "gender": "Male", "group": "vn_neural"},
    {"id": "vi-VN-HoaiMyNeural-elder", "name": "Bà Tiên / Bà Ngoại (Việt Nam - Nữ hiền từ, chậm rãi, cổ tích)", "lang": "vi", "gender": "Female", "group": "vn_neural"},
    {"id": "vi-VN-NamMinhNeural-elder", "name": "Ông Bụt / Cụ Già Làng (Việt Nam - Nam trầm khàn, thông thái, dân gian)", "lang": "vi", "gender": "Male", "group": "vn_neural"},

    # 2. Google Gemini Native Multimodal Voices (Fluent in Vietnamese & English)
    {"id": "gemini-Aoede", "name": "✨ Gemini Aoede (Nữ truyền cảm - VN / Global)", "lang": "vi", "gender": "Female", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Kore", "name": "✨ Gemini Kore (Nữ nhẹ nhàng kể chuyện - VN / Global)", "lang": "vi", "gender": "Female", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Leda", "name": "✨ Gemini Leda (Nữ trẻ trung, trong sáng - VN / Global)", "lang": "vi", "gender": "Female", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Zephyr", "name": "✨ Gemini Zephyr (Nữ tươi sáng, năng động - VN / Global)", "lang": "vi", "gender": "Female", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Callirrhoe", "name": "✨ Gemini Callirrhoe (Nữ dịu dàng, sâu lắng - VN / Global)", "lang": "vi", "gender": "Female", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Puck", "name": "✨ Gemini Puck (Nam hoạt bát, hài hước - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Charon", "name": "✨ Gemini Charon (Nam trầm ấm điện ảnh - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Fenrir", "name": "✨ Gemini Fenrir (Nam hào hùng, uy lực - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Orus", "name": "✨ Gemini Orus (Nam điềm đạm, chững chạc - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini", "group": "vn_gemini"},
    {"id": "gemini-Enceladus", "name": "✨ Gemini Enceladus (Nam truyền cảm, sâu sắc - VN / Global)", "lang": "vi", "gender": "Male", "provider": "gemini", "group": "vn_gemini"},

    # 3. Google Translate TTS Vietnamese Voices
    {"id": "gtts-vi", "name": "Google Voice VN (Việt Nam - Nữ chuẩn Google TTS)", "lang": "vi", "gender": "Female", "group": "vn_gtts"},
    {"id": "gtts-vi-fast", "name": "Google Voice VN Nhanh (Việt Nam - Nữ đọc nhanh Review / Shorts)", "lang": "vi", "gender": "Female", "group": "vn_gtts"},

    # 4. International Voices (English, Japanese, French, Spanish)
    {"id": "en-US-ChristopherNeural", "name": "Christopher (US - Storyteller Male)", "lang": "en", "gender": "Male", "group": "intl"},
    {"id": "en-US-JennyNeural", "name": "Jenny (US - Warm Expressive Female)", "lang": "en", "gender": "Female", "group": "intl"},
    {"id": "en-US-GuyNeural", "name": "Guy (US - Casual Friendly Male)", "lang": "en", "gender": "Male", "group": "intl"},
    {"id": "en-US-AriaNeural", "name": "Aria (US - Clear Narrator Female)", "lang": "en", "gender": "Female", "group": "intl"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia (British - Elegant Female)", "lang": "en", "gender": "Female", "group": "intl"},
    {"id": "en-GB-RyanNeural", "name": "Ryan (British - Documentary Male)", "lang": "en", "gender": "Male", "group": "intl"},
    {"id": "ja-JP-NanamiNeural", "name": "Nanami (Japanese - Female)", "lang": "ja", "gender": "Female", "group": "intl"},
    {"id": "ja-JP-KeitaNeural", "name": "Keita (Japanese - Male)", "lang": "ja", "gender": "Male", "group": "intl"},
    {"id": "fr-FR-DeniseNeural", "name": "Denise (French - Female)", "lang": "fr", "gender": "Female", "group": "intl"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira (Spanish - Female)", "lang": "es", "gender": "Female", "group": "intl"},
]

# Camera Motion presets for Ken Burns effect
CAMERA_MOTIONS = [
    {"id": "speaker_focus", "name": "Speaker Close-Up Focus", "description": "Smoothly pushes in on the speaking character's face & expression"},
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
    },
    "manual": {
        "id": "manual",
        "name": "Storyboard Only (No AI Painting)",
        "description": "Zero image AI tokens consumed — uses clean SVG storyboard placeholders and manual user image uploads",
        "icon": "📝"
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


