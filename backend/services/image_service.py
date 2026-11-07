import os
import random
import re
import io
import urllib.parse
from pathlib import Path
import httpx
from PIL import Image, ImageDraw, ImageFont
from backend.config import ART_STYLES, SPEAKER_FOCUS_PROMPT_SUFFIX

class ImageService:
    def __init__(self, default_style: str = "ghibli", api_key: str = None, provider: str = "gemini"):
        self.default_style = default_style
        self.provider = (provider or "gemini").lower()
        self.api_key = api_key or os.environ.get(f"{self.provider.upper()}_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")

    @staticmethod
    def sanitize_visual_prompt(prompt: str) -> str:
        """
        Strips quotes, spoken dialogue, speech bubble indicators, video timestamps,
        camera moves, and negative prompts from prompt to prevent image models
        from rendering speech bubbles, text overlays, or getting confused by video directives.
        """
        if not prompt:
            return ""
        p = prompt.strip()
        # Remove video timing markers like 0-3s:, 3-6s:, 6-8s:
        p = re.sub(r'(?i)\b\d+-\d+s\s*:\s*', '', p)
        # Remove video camera and negative markers
        p = re.sub(r'(?i)\bCamera\s*:[^.]*\.?', '', p)
        p = re.sub(r'(?i)\bLighting\s*:[^.]*\.?', '', p)
        p = re.sub(r'(?i)\bNegative\s*:[^.]*\.?', '', p)
        # Remove quoted dialogue like "..." or “...” or '...'
        p = re.sub(r'["“][^"”]{2,}["”]', '', p)
        p = re.sub(r"['‘][^'’]{2,}['’]", '', p)
        # Remove dialogue markers and speech bubble requests
        p = re.sub(r'(?i)\b(?:speech bubble|dialogue bubble|thought bubble|speech balloon|comic bubble|text bubble)\b', '', p)
        p = re.sub(r'(?i)\b(?:nói rằng|cất tiếng nói|nói với|bảo rằng|lời nói|says|saying)\b[:\s]*', '', p)
        # Preserve full detailed visual prompts (up to 2000 chars) so character actions, animals (e.g. golden-brown cow),
        # and key props (e.g. bamboo sleeping cot) are never cut off mid-sentence!
        if len(p) > 2000:
            p = p[:2000].rsplit(' ', 1)[0]
        # Collapse multiple spaces and commas
        p = re.sub(r'\s*,\s*', ', ', p)
        p = re.sub(r',\s*,+', ', ', p)
        p = re.sub(r'\s+', ' ', p).strip()
        p = p.strip(',').strip()
        return p

    def craft_full_prompt(
        self,
        base_prompt: str,
        style_key: str = None,
        character_desc: str = None,
        camera_on_speaker: bool = False
    ) -> str:
        """Combine base scene prompt with character consistency anchors, subject/prop disambiguation, artistic style keywords, optional speaker-focus framing, and anti-text constraints."""
        clean_base = self.sanitize_visual_prompt(base_prompt)
        lower_base = clean_base.lower()

        # Legacy fallback if style_key was saved as "dialogue_cinema"
        effective_style = style_key or self.default_style or "ghibli"
        if effective_style == "dialogue_cinema":
            effective_style = "ghibli"
            camera_on_speaker = True

        # Auto-harmonize style if the visual prompt explicitly specifies 3D Pixar, Ghibli, Realistic, or Stick Figure
        if any(k in lower_base for k in ("pixar", "3d animated", "3d animation", "disney 3d")):
            effective_style = "pixar"
        elif any(k in lower_base for k in ("studio ghibli", "ghibli", "2d hand-drawn", "cel-shaded anime")):
            effective_style = "ghibli"
        elif any(k in lower_base for k in ("raw photograph", "photorealistic", "live-action")):
            effective_style = "realistic"
        elif any(k in lower_base for k in ("stick figure", "stickman", "stick figures", "stick-figure", "người que")):
            effective_style = "stick_figure"

        style_info = ART_STYLES.get(effective_style, ART_STYLES["ghibli"])
        suffix = style_info.get("prompt_suffix", "")
        # Avoid duplicating style suffix if base prompt already describes the style thoroughly
        if effective_style == "pixar" and "pixar" in lower_base:
            suffix = ", consistent 3D Pixar-inspired character proportions, warm subsurface scattering, cinematic lighting"
        elif effective_style == "stick_figure" and any(k in lower_base for k in ("stick figure", "stickman")):
            suffix = ", clean bold line-drawn stickman silhouette, Alan Becker aesthetic, smooth 2D vector animation style"

        has_speaker_cue = any(k in lower_base for k in (
            "camera focused directly on",
            "góc máy cận cảnh tập trung",
            "speaking, ",
            "đang nói chuyện",
            "expressive speaking pose"
        ))
        speaker_addon = SPEAKER_FOCUS_PROMPT_SUFFIX if (camera_on_speaker or has_speaker_cue) else ""

        char_addon = ""
        clean_char = ""
        if character_desc and str(character_desc).strip():
            clean_char = self.sanitize_visual_prompt(str(character_desc))
            # Append character sheet anchor (up to 500 chars so supporting characters & animals like Bò Vàng / Quan Huyện are preserved)
            char_tokens = [w for w in re.findall(r'\b\w{4,}\b', clean_char.lower()) if w not in ("character", "protagonist", "appearance", "visual", "consistency", "companion", "supporting")]
            matching_tokens = sum(1 for tok in char_tokens if tok in lower_base)
            if not char_tokens or matching_tokens < len(char_tokens) * 0.65:
                short_char = clean_char[:500].rsplit(' ', 1)[0] if len(clean_char) > 500 else clean_char
                char_addon = f", character & cast visual consistency ({short_char}), maintain exact same character appearance, faces, and outfits across all scenes"

        # Subject & Prop Disambiguation Anchors to prevent common visual hallucinations in Vietnamese rural stories
        disambiguation_parts = []
        combined_lower = f"{lower_base} {clean_char.lower()}"
        has_cow_in_scene = any(k in lower_base for k in ("cow", "bò vàng", "con bò", "cattle", "calf", "golden-brown cow"))
        has_buffalo = any(k in lower_base for k in ("buffalo", "con trâu", "water buffalo"))
        if has_cow_in_scene and not has_buffalo:
            disambiguation_parts.append(
                "IMPORTANT ANIMAL ACCURACY: The animal in this scene is strictly a warm golden-yellow/brown domestic cow (bò vàng) with sleek golden-tan fur and short small curved horns — NOT a dark gray or black water buffalo (con trâu) and NOT wide water buffalo horns"
            )

        has_cot_in_scene = any(k in lower_base for k in ("sleeping cot", "bamboo cot", "cot", "chõng", "giường", "bamboo bed"))
        has_lifting_in_scene = any(k in lower_base for k in ("lift", "lifting", "carry", "carrying", "move", "khiêng", "nhấc", "two masked thieves", "thieves"))
        if has_cot_in_scene and has_lifting_in_scene and any(k in lower_base for k in ("lift", "lifting", "carry", "carrying", "khiêng", "nhấc")):
            disambiguation_parts.append(
                "IMPORTANT PROP ACCURACY: The two thieves are lifting a flat, open rectangular four-legged woven bamboo bed/cot (chiếc chõng tre) by its wooden legs with the sleeping young man lying flat and fully visible on top of the open bed surface — strictly an open flat bamboo bed/cot, NOT carrying a sack, NOT a bag, NOT a wrapped bundle"
            )

        disambiguation_addon = (". " + ". ".join(disambiguation_parts)) if disambiguation_parts else ""

        if effective_style == "realistic":
            anti_text = ", textless RAW photograph, no speech bubbles, no dialogue bubbles, no words, no letters, no subtitles, no watermark, not cartoon, not 3D render, not illustration, not painting"
        elif effective_style == "stick_figure":
            anti_text = ", clean textless stickman illustration, no speech bubbles, no dialogue bubbles, no words, no letters, no subtitles, no watermark, not photorealistic, no realistic human faces, no detailed skin, no 3D rendering"
        else:
            anti_text = ", clean textless illustration, no speech bubbles, no dialogue bubbles, no words, no letters, no subtitles, no watermark"
        return f"{clean_base}{disambiguation_addon}{char_addon}{suffix}{speaker_addon}{anti_text}"

    def extract_keywords(self, prompt: str, title: str = "") -> list:
        """Extract clean, meaningful visual keywords for thematic asset discovery."""
        stop_words = {
            "a", "an", "the", "in", "on", "at", "of", "for", "with", "and", "or", "to", "is",
            "shot", "wide", "cinematic", "detailed", "4k", "style", "view", "angle", "camera",
            "looking", "stands", "across", "into", "from", "this", "that", "medium", "close",
            "low", "high", "extreme", "background", "foreground", "frame", "visual", "prompt"
        }
        words = re.findall(r"[a-zA-Z]+", f"{title} {prompt}".lower())
        clean = [w for w in words if len(w) >= 4 and w not in stop_words]
        return clean

    def fit_image_to_aspect_ratio(self, img: Image.Image, target_w: int = 1280, target_h: int = 720) -> Image.Image:
        """Crop and scale image to exact aspect ratio and dimensions without distortion."""
        img = img.convert("RGB")
        target_ratio = target_w / float(target_h)
        w, h = img.size
        curr_ratio = w / float(h)

        if curr_ratio > target_ratio:
            new_w = int(h * target_ratio)
            offset = (w - new_w) // 2
            img = img.crop((offset, 0, offset + new_w, h))
        else:
            new_h = int(w / target_ratio)
            offset = (h - new_h) // 2
            img = img.crop((0, offset, w, offset + new_h))

        return img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    def fit_image_to_16_9(self, img: Image.Image, target_w: int = 1280, target_h: int = 720) -> Image.Image:
        """Backward compatibility alias for 16:9 fitting."""
        return self.fit_image_to_aspect_ratio(img, target_w, target_h)

    async def generate_scene_image(
        self,
        prompt: str,
        output_path: str,
        style_key: str = "ghibli",
        seed: int = None,
        width: int = 1280,
        height: int = 720,
        scene_idx: int = 0,
        title: str = "",
        image_mode: str = "gemini",
        character_desc: str = None,
        reference_image_path: str = None,
        api_key: str = None,
        provider: str = None,
        camera_on_speaker: bool = False
    ) -> str:
        """
        Scene visual generation pipeline:
        1. Google Gemini / Imagen 3 (Default — official API key or web session cookie)
        2. Neural.love AI Art Engine (if image_mode is neural_love)
        3. OpenAI DALL-E 3 (if image_mode or provider is OpenAI)
        4. Storyboard-Only Canvas (if image_mode is manual)
        """
        eff_api_key = api_key or self.api_key
        eff_provider = provider or self.provider
        output_path = str(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        full_prompt = self.craft_full_prompt(
            prompt,
            style_key=style_key,
            character_desc=character_desc,
            camera_on_speaker=camera_on_speaker
        )

        # Determine best aspect ratios
        curr_ratio = width / float(height)
        if curr_ratio > 1.6:
            imagen_ratio = "16:9"
            dalle_size = "1792x1024"
        elif curr_ratio < 0.65:
            imagen_ratio = "9:16"
            dalle_size = "1024x1792"
        elif curr_ratio > 1.2:
            imagen_ratio = "4:3"
            dalle_size = "1024x1024"
        elif curr_ratio < 0.85:
            imagen_ratio = "3:4"
            dalle_size = "1024x1024"
        else:
            imagen_ratio = "1:1"
            dalle_size = "1024x1024"

        # ============================================================
        # 0. STORYBOARD ONLY / MANUAL MODE (Zero AI Tokens)
        # ============================================================
        if image_mode in ("manual", "storyboard_only", "placeholder"):
            self.generate_procedural_fallback(title=title, prompt=prompt, output_path=output_path, style_key=style_key, scene_idx=scene_idx, width=width, height=height)
            print(f"Scene {scene_idx + 1} visual rendered using Storyboard-Only canvas (zero AI calls).")
            return output_path

        # ============================================================
        # 1. NEURAL.LOVE AI ART MODE
        # ============================================================
        if image_mode == "neural_love":
            nl_success = await self._generate_with_neural_love(
                prompt=full_prompt,
                output_path=output_path,
                width=width,
                height=height,
                style_key=style_key
            )
            if nl_success:
                print(f"Generated scene {scene_idx + 1} using Neural.love AI Art Engine!")
                return output_path
            raise RuntimeError("Neural.love image generation failed. Please check your API key and credit balance.")

        # ============================================================
        # 2. OPENAI DALL-E 3 MODE
        # ============================================================
        if image_mode == "openai" or (eff_provider == "openai" and eff_api_key):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/images/generations",
                        headers={
                            "Authorization": f"Bearer {eff_api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "dall-e-3",
                            "prompt": full_prompt[:1800],
                            "size": dalle_size,
                            "quality": "standard",
                            "n": 1
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        dalle_url = data["data"][0]["url"]
                        img_resp = await client.get(dalle_url)
                        if img_resp.status_code == 200:
                            img = Image.open(io.BytesIO(img_resp.content))
                            fitted = self.fit_image_to_aspect_ratio(img, width, height)
                            fitted.save(output_path, "JPEG", quality=92)
                            print(f"Generated scene using OpenAI DALL-E 3 ({dalle_size})!")
                            return output_path
                    else:
                        raise RuntimeError(f"OpenAI DALL-E error {resp.status_code}: {resp.text}")
            except Exception as e:
                raise RuntimeError(f"OpenAI DALL-E 3 generation failed: {e}")

        # ============================================================
        # 3. PUTER.JS IN-BROWSER MODE
        # ============================================================
        if image_mode == "puter":
            raise RuntimeError("In-Browser Puter image generation runs directly in the browser client. Please use the 'Repaint with Puter' button in the Storyboard.")

        # ============================================================
        # 4. GOOGLE GEMINI / IMAGEN 3 MODE (Default)
        # ============================================================
        if image_mode in ("gemini", "server"):
            gemini_error = None

            # 4a. Official Google AI Studio API Key (starts with AIzaSy... or standard API key)
            is_cookie_key = bool(
                eff_api_key and (
                    eff_api_key.startswith("g.a")
                    or "__Secure-1PSID" in eff_api_key
                    or eff_provider == "gemini_cookie"
                )
            )

            if eff_api_key and not is_cookie_key:
                try:
                    from google import genai
                    from google.genai import types
                    client = genai.Client(api_key=eff_api_key)
                    for img_model in ["imagen-3.0-generate-002", "imagen-3.0-fast-generate-001"]:
                        try:
                            resp = client.models.generate_images(
                                model=img_model,
                                prompt=full_prompt[:2800],
                                config=types.GenerateImagesConfig(
                                    number_of_images=1,
                                    aspect_ratio=imagen_ratio,
                                    output_mime_type="image/jpeg",
                                    person_generation="ALLOW_ADULT"
                                )
                            )
                            if resp.generated_images:
                                raw_bytes = resp.generated_images[0].image.image_bytes
                                img = Image.open(io.BytesIO(raw_bytes))
                                fitted = self.fit_image_to_aspect_ratio(img, width, height)
                                fitted.save(output_path, "JPEG", quality=95)
                                print(f"Generated scene {scene_idx + 1} using Google Gemini Imagen 3 API ({img_model})!")
                                return output_path
                        except Exception as e_model:
                            gemini_error = str(e_model)
                except Exception as e:
                    gemini_error = str(e)

            # 4b. Google Gemini Web Session Cookie (__Secure-1PSID)
            from backend.config import get_server_credentials
            s_creds = get_server_credentials()
            saved_psid = s_creds.get("gemini_cookie_psid")
            saved_psidts = s_creds.get("gemini_cookie_psidts")
            cookie_input = eff_api_key if is_cookie_key else (f"{saved_psid}|{saved_psidts}" if saved_psidts else saved_psid)
            psid, psidts = self._parse_gemini_cookie_pair(cookie_input)
            if not psid:
                psid = saved_psid
            if not psidts:
                psidts = saved_psidts or psidts

            if psid:
                combined_cookie = f"{psid}|{psidts}" if psidts else psid
                try:
                    from backend.services.gemini_wrapper import GeminiWebWrapper
                    wrapper = GeminiWebWrapper.get_instance()
                    req_files = [reference_image_path] if (reference_image_path and os.path.exists(reference_image_path)) else None
                    if req_files:
                        gemini_prompt = (
                            f"Generate a brand-new scene illustration strictly depicting this exact scene action, props, and setting: {full_prompt[:2800]}. "
                            f"Use the attached reference image ONLY to keep the main character's face, hairstyle, and clothing consistent — do NOT copy the pose or background from the reference image, and accurately depict all new actions, props, and characters described above. "
                            f"Clean illustration without text, no speech bubbles, no words."
                        )
                    else:
                        gemini_prompt = f"Generate an image of: {full_prompt[:2800]}. Clean illustration without text, no speech bubbles, no words."

                    resp = await wrapper.generate_content(
                        gemini_prompt,
                        files=req_files,
                        cookie_override=combined_cookie
                    )
                    saved_img = None
                    if resp.has_images:
                        temp_dir = Path(output_path).parent / "temp_gemini"
                        os.makedirs(temp_dir, exist_ok=True)
                        saved_img = await resp.images[0].save(path=str(temp_dir))

                    if saved_img and os.path.exists(saved_img):
                        img = Image.open(saved_img)
                        fitted = self.fit_image_to_aspect_ratio(img, width, height)
                        fitted.save(output_path, "JPEG", quality=95)
                        try:
                            os.remove(saved_img)
                        except Exception:
                            pass
                        print(f"Generated scene {scene_idx + 1} using Gemini Pro Web Session Imagen 3 with character consistency!")
                        return output_path
                    else:
                        gemini_error = "Gemini returned response without image content. Try again or verify session cookies."
                except Exception as e:
                    gemini_error = str(e)

            err_msg = gemini_error or "Google Gemini Imagen 3 generation failed. Please verify your Gemini API key or ensure cookies are valid."
            raise RuntimeError(f"Google Gemini Imagen 3 generation failed: {err_msg}")

        raise RuntimeError(f"Unsupported image generation mode '{image_mode}'. Free Neural AI Engine has been removed.")

    async def _fetch_thematic_image(self, keywords: list, width: int = 1280, height: int = 720) -> Image.Image:
        """Search and fetch high-res thematic visuals from open creative repositories."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # Query candidates from pairs of keywords
        query_candidates = []
        for i in range(min(5, len(keywords) - 1)):
            query_candidates.append(f"{keywords[i]} {keywords[i+1]}")
        if len(keywords) >= 1:
            query_candidates.append(keywords[0])

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            # 2a. Try Openverse
            for q in query_candidates:
                try:
                    url = f"https://api.openverse.org/v1/images/?q={urllib.parse.quote(q)}&page_size=5"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        results = data.get("results", [])
                        for item in results:
                            img_url = item.get("url")
                            if img_url:
                                img_resp = await client.get(img_url, headers=headers)
                                if img_resp.status_code == 200 and len(img_resp.content) > 10000:
                                    try:
                                        img = Image.open(io.BytesIO(img_resp.content))
                                        return self.fit_image_to_aspect_ratio(img, width, height)
                                    except Exception:
                                        continue
                except Exception:
                    continue

            # 2b. Try Wikimedia Commons
            for q in query_candidates:
                try:
                    url = f"https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6&gsrsearch={urllib.parse.quote(q)}&gsrlimit=3&prop=imageinfo&iiprop=url|mime&format=json"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        pages = data.get("query", {}).get("pages", {})
                        for p in pages.values():
                            info = p.get("imageinfo", [{}])[0]
                            img_url = info.get("url")
                            if img_url:
                                img_resp = await client.get(img_url, headers=headers)
                                if img_resp.status_code == 200 and len(img_resp.content) > 10000:
                                    try:
                                        img = Image.open(io.BytesIO(img_resp.content))
                                        return self.fit_image_to_aspect_ratio(img, width, height)
                                    except Exception:
                                        continue
                except Exception:
                    continue

        return None

    def generate_procedural_fallback(
        self,
        title: str,
        prompt: str,
        output_path: str,
        style_key: str = "ghibli",
        scene_idx: int = 0,
        width: int = 1280,
        height: int = 720
    ):
        """
        Generates a rich, unique stylized storyboard illustration:
        - Distinct color palette per scene (Dawn, Emerald, Crimson Sunset, Midnight Indigo)
        - Thematic silhouettes tailored to prompt (Skyscraper skyline, Alleyway/Interior, Horizon, Mountains)
        - Atmospheric particle effects and stylized scene header banner
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)

        # Diverse palettes based on scene index + style
        palettes = [
            # Scene 1: Deep Twilight / Blue Horizon
            ((15, 25, 55), (180, 70, 90), (255, 220, 140)),
            # Scene 2: Emerald Neon / Cyber Alley
            ((10, 35, 40), (20, 140, 160), (0, 255, 200)),
            # Scene 3: Sunset Crimson / Violet
            ((35, 10, 45), (200, 60, 80), (255, 180, 100)),
            # Scene 4: Midnight Indigo / Amber Flare
            ((10, 10, 30), (70, 40, 110), (255, 240, 160)),
        ]
        top_color, bot_color, accent_color = palettes[scene_idx % len(palettes)]

        # Smooth vertical gradient
        for y in range(height):
            ratio = y / float(height)
            r = int(top_color[0] * (1 - ratio) + bot_color[0] * ratio)
            g = int(top_color[1] * (1 - ratio) + bot_color[1] * ratio)
            b = int(top_color[2] * (1 - ratio) + bot_color[2] * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        rng = random.Random((hash(title + prompt) + scene_idx * 1337) & 0xffffffff)

        # Celestial body (sun / moon / digital orb)
        orb_x = int(width * (0.25 if scene_idx % 2 == 1 else 0.75))
        orb_y = int(height * (0.28 + (scene_idx % 3) * 0.05))
        orb_r = 75
        draw.ellipse([orb_x - orb_r, orb_y - orb_r, orb_x + orb_r, orb_y + orb_r], fill=accent_color)

        # Atmospheric stars / digital motes
        for _ in range(60):
            sx = rng.randint(0, width)
            sy = rng.randint(0, int(height * 0.65))
            sr = rng.randint(1, 3)
            opacity = rng.randint(120, 255)
            draw.ellipse([sx, sy, sx + sr, sy + sr], fill=(opacity, opacity, opacity))

        prompt_lower = (prompt + " " + title).lower()
        is_city = any(w in prompt_lower for w in ["city", "cyberpunk", "skyscraper", "rooftop", "street", "alley", "detective", "building"])

        if is_city:
            # Draw layered city skyline with illuminated windows
            # Far skyline
            num_bldgs = 14
            for i in range(num_bldgs):
                bx = int(i * (width / num_bldgs) - 20)
                bw = int((width / num_bldgs) + 30)
                bh = rng.randint(180, 340)
                by = height - bh
                draw.rectangle([bx, by, bx + bw, height], fill=(12, 16, 28))
                # Far windows
                for wy in range(by + 15, height - 40, 25):
                    for wx in range(bx + 10, bx + bw - 10, 20):
                        if rng.random() > 0.45:
                            draw.rectangle([wx, wy, wx + 6, wy + 10], fill=accent_color)

            # Foreground skyline silhouettes
            for i in range(8):
                bx = int(i * (width / 8) - 10)
                bw = int((width / 8) + 20)
                bh = rng.randint(100, 220)
                by = height - bh
                draw.rectangle([bx, by, bx + bw, height], fill=(6, 8, 16))
                for wy in range(by + 10, height - 20, 20):
                    for wx in range(bx + 12, bx + bw - 12, 16):
                        if rng.random() > 0.5:
                            draw.rectangle([wx, wy, wx + 5, wy + 8], fill=(240, 240, 240))
        else:
            # Layered rolling landscape silhouettes
            for layer_idx, base_y in enumerate([int(height * 0.70), int(height * 0.82)]):
                points = [(0, height)]
                h_color = (12 - layer_idx * 5, 18 - layer_idx * 5, 30 - layer_idx * 5)
                num_steps = 18
                for step in range(num_steps + 1):
                    px = int(step * (width / num_steps))
                    py = base_y + int(rng.randint(-35, 35))
                    points.append((px, py))
                points.append((width, height))
                draw.polygon(points, fill=h_color)

        # Cinematic top & bottom letterbox bars
        letterbox_h = 24
        draw.rectangle([0, 0, width, letterbox_h], fill=(5, 5, 10))
        draw.rectangle([0, height - letterbox_h, width, height], fill=(5, 5, 10))

        # Stylized Scene Title Badge
        badge_text = f"SCENE {scene_idx + 1}: {title.upper() if title else 'STORYBOARD'}"
        badge_w = min(width - 80, len(badge_text) * 11 + 40)
        badge_box = [(width - badge_w) // 2, 12, (width + badge_w) // 2, 42]
        draw.rectangle(badge_box, fill=(15, 20, 35), outline=accent_color, width=1)
        draw.text(((width - badge_w) // 2 + 15, 18), badge_text, fill=(245, 245, 255))

        img.save(output_path, "JPEG", quality=92)

    @staticmethod
    def _parse_gemini_cookie_pair(cookie_input: str) -> tuple:
        s = (cookie_input or "").strip()
        psid, psidts = None, None
        if s.startswith("{"):
            try:
                import json
                d = json.loads(s)
                psid = d.get("__Secure-1PSID") or d.get("secure_1psid") or d.get("psid")
                psidts = d.get("__Secure-1PSIDTS") or d.get("secure_1psidts") or d.get("psidts")
            except Exception:
                pass

        if not psid:
            m1 = re.search(r"__Secure-1PSID=([^;\s\r\n]+)", s)
            if m1:
                psid = m1.group(1).strip()
            m2 = re.search(r"__Secure-1PSIDTS=([^;\s\r\n]+)", s)
            if m2:
                psidts = m2.group(1).strip()

        if not psid:
            if "|" in s:
                p = s.split("|", 1)
                psid, psidts = p[0].strip(), p[1].strip()
            elif "\n" in s:
                p = s.split("\n", 1)
                psid, psidts = p[0].strip(), p[1].strip()
            else:
                psid = s
        return psid, psidts

    async def _generate_with_neural_love(
        self,
        prompt: str,
        output_path: str,
        width: int = 1280,
        height: int = 720,
        style_key: str = "ghibli"
    ) -> bool:
        """Generate high fidelity artistic images using Neural.love AI Art API."""
        from backend.config import get_server_credentials
        s_creds = get_server_credentials()
        key = s_creds.get("neural_love_key") or os.environ.get("NEURAL_LOVE_API_KEY", "")
        if not key:
            return False

        style = "anime" if ("anime" in (style_key or "") or style_key in ("ghibli", "comic")) else "anything"
        layout = "horizontal" if width >= height else "vertical"
        if abs(width - height) < 50:
            layout = "square"

        payload = {
            "prompt": prompt[:800],
            "style": style,
            "layout": layout,
            "amount": 1,
            "isHd": False
        }

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post("https://api.neural.love/v1/ai-art/generate", json=payload, headers=headers)
            if resp.status_code == 439:
                err_detail = resp.json().get("detail", "Free generation limit reached for today.")
                raise RuntimeError(f"Neural.love quota notice: {err_detail}")
            elif resp.status_code == 402:
                err_detail = resp.json().get("detail", "Payment required / 0 credits remaining.")
                raise RuntimeError(f"Neural.love credits notice: {err_detail}")
            elif resp.status_code not in (200, 201, 202):
                print(f"Neural.love API error: {resp.status_code} {resp.text}")
                return False

            data = resp.json()
            order_id = data.get("orderId") or data.get("id")
            if not order_id:
                return False

            import asyncio
            for _ in range(30):
                await asyncio.sleep(2.5)
                poll_resp = await client.get(f"https://api.neural.love/v1/ai-art/orders/{order_id}", headers=headers)
                if poll_resp.status_code == 200:
                    p_data = poll_resp.json()
                    status = (p_data.get("status") or "").lower()
                    if status in ("done", "ready", "finished", "success"):
                        images = p_data.get("output") or p_data.get("images") or []
                        img_url = None
                        if isinstance(images, list) and images:
                            img_item = images[0]
                            img_url = img_item.get("url") if isinstance(img_item, dict) else img_item
                        elif isinstance(images, str):
                            img_url = images

                        if img_url:
                            img_get = await client.get(img_url)
                            if img_get.status_code == 200 and len(img_get.content) > 1000:
                                img = Image.open(io.BytesIO(img_get.content))
                                fitted = self.fit_image_to_aspect_ratio(img, width, height)
                                fitted.save(output_path, "JPEG", quality=93)
                                return True
                    elif status in ("failed", "error"):
                        print(f"Neural.love order failed: {p_data}")
                        return False
        return False
