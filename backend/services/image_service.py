import os
import random
import re
import io
import urllib.parse
from pathlib import Path
import httpx
from PIL import Image, ImageDraw, ImageFont
from backend.config import ART_STYLES

class ImageService:
    def __init__(self, default_style: str = "ghibli", api_key: str = None, provider: str = "gemini"):
        self.default_style = default_style
        self.provider = (provider or "gemini").lower()
        self.api_key = api_key or os.environ.get(f"{self.provider.upper()}_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")

    @staticmethod
    def sanitize_visual_prompt(prompt: str) -> str:
        """
        Strips quotes, spoken dialogue, and speech bubble indicators from prompt
        to prevent image models from drawing speech bubbles with garbled text.
        """
        if not prompt:
            return ""
        p = prompt.strip()
        # Remove quoted dialogue like "..." or “...” or '...'
        p = re.sub(r'["“][^"”]{2,}["”]', '', p)
        p = re.sub(r"['‘][^'’]{2,}['’]", '', p)
        # Remove dialogue markers and speech bubble requests
        p = re.sub(r'(?i)\b(?:speech bubble|dialogue bubble|thought bubble|speech balloon|comic bubble|text bubble)\b', '', p)
        p = re.sub(r'(?i)\b(?:nói rằng|cất tiếng nói|nói với|bảo rằng|lời nói|says|saying)\b[:\s]*', '', p)
        # If a massive story paragraph was mistakenly passed in, keep only the visual description parts
        if len(p) > 500:
            # Keep first 250 characters and strip trailing half-words
            p = p[:250].rsplit(' ', 1)[0]
        # Collapse multiple spaces and commas
        p = re.sub(r'\s*,\s*', ', ', p)
        p = re.sub(r',\s*,+', ', ', p)
        p = re.sub(r'\s+', ' ', p).strip()
        p = p.strip(',').strip()
        return p

    def craft_full_prompt(self, base_prompt: str, style_key: str = None) -> str:
        """Combine base scene prompt with tuned artistic style keywords and anti-text constraints."""
        style_info = ART_STYLES.get(style_key or self.default_style, ART_STYLES["ghibli"])
        suffix = style_info.get("prompt_suffix", "")
        clean_base = self.sanitize_visual_prompt(base_prompt)
        anti_text = ", clean textless illustration, no speech bubbles, no dialogue bubbles, no words, no letters, no subtitles, no watermark"
        return f"{clean_base}{suffix}{anti_text}"

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
        image_mode: str = "server"
    ) -> str:
        """
        Multi-tier robust scene visual pipeline:
        1. Google Gemini / Imagen 3 (if image_mode is gemini or provider is gemini)
        2. OpenAI DALL-E 3 (if provider is OpenAI)
        3. Free Neural AI Generator (Pollinations Flux / SDXL)
        4. Open Thematic Asset Engines (Openverse & Wikimedia Commons matching scene keywords)
        5. Scene-specific procedural artwork generator (guarantees every scene looks distinct)
        """
        output_path = str(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        full_prompt = self.craft_full_prompt(prompt, style_key)

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
        # 2. GOOGLE GEMINI / IMAGEN 3 MODE
        # ============================================================
        if image_mode == "gemini" or (image_mode != "server" and self.provider in ("gemini", "gemini_cookie")):
            gemini_error = None
            # 2a. Try official Gemini API Key with Image models
            if self.api_key and "__Secure-1PSID" not in self.api_key and self.provider != "gemini_cookie":
                try:
                    from google import genai
                    client = genai.Client(api_key=self.api_key)
                    for img_model in ["gemini-2.5-flash-image", "gemini-3-pro-image-preview", "gemini-3.1-flash-image"]:
                        try:
                            resp = client.models.generate_content(
                                model=img_model,
                                contents=f"Generate a high quality illustration: {full_prompt[:1000]}. STRICT: No speech bubbles, no dialogue, no text in the artwork."
                            )
                            if resp.candidates:
                                for cand in resp.candidates:
                                    if cand.content and cand.content.parts:
                                        for part in cand.content.parts:
                                            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                                                raw_data = part.inline_data.data
                                                if isinstance(raw_data, str):
                                                    import base64
                                                    raw_data = base64.b64decode(raw_data)
                                                img = Image.open(io.BytesIO(raw_data))
                                                fitted = self.fit_image_to_aspect_ratio(img, width, height)
                                                fitted.save(output_path, "JPEG", quality=93)
                                                print(f"Generated scene {scene_idx + 1} using Google Gemini Image Model ({img_model})!")
                                                return output_path
                        except Exception as e_gen:
                            gemini_error = str(e_gen)
                except Exception as e:
                    gemini_error = str(e)

            # 2b. Try Gemini Pro Web Session Cookie
            from backend.config import get_server_credentials
            s_creds = get_server_credentials()
            saved_psid = s_creds.get("gemini_cookie_psid")
            saved_psidts = s_creds.get("gemini_cookie_psidts")
            cookie_input = self.api_key if ("__Secure-1PSID" in (self.api_key or "")) else (f"{saved_psid}|{saved_psidts}" if saved_psidts else saved_psid)
            psid, psidts = self._parse_gemini_cookie_pair(cookie_input)

            if psid:
                try:
                    from backend.services.gemini_wrapper import GeminiWebWrapper
                    wrapper = GeminiWebWrapper.get_instance()
                    resp = await wrapper.generate_content(
                        f"Generate an image of: {full_prompt[:800]}. Clean illustration without text, no speech bubbles, no words.",
                        cookie_override=cookie_input
                    )
                    saved_img = None
                    if resp.has_images:
                        temp_dir = Path(output_path).parent / "temp_gemini"
                        os.makedirs(temp_dir, exist_ok=True)
                        saved_img = await resp.images[0].save(path=str(temp_dir))

                    if saved_img and os.path.exists(saved_img):
                        img = Image.open(saved_img)
                        fitted = self.fit_image_to_aspect_ratio(img, width, height)
                        fitted.save(output_path, "JPEG", quality=93)
                        try:
                            os.remove(saved_img)
                        except Exception:
                            pass
                        print(f"Generated scene {scene_idx + 1} using Gemini Pro Web Session Imagen 3!")
                        return output_path
                except RuntimeError:
                    raise
                except Exception as e:
                    gemini_error = str(e)

            # Strict: No procedural or silent fallback!
            err_msg = gemini_error or "Google Gemini Imagen 3 generation failed. Please verify your Gemini API key or ensure __Secure-1PSID and __Secure-1PSIDTS cookies are valid."
            raise RuntimeError(f"Gemini Imagen 3 Error: {err_msg}")

        # ============================================================
        # 3. PUTER.JS IN-BROWSER MODE
        # ============================================================
        if image_mode == "puter":
            raise RuntimeError("In-Browser Puter image generation runs directly in the browser client. Please use the 'Repaint with Puter' button in the Storyboard.")

        # ============================================================
        # 4. OPENAI DALL-E 3 MODE
        # ============================================================
        if self.provider == "openai" and self.api_key:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/images/generations",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "dall-e-3",
                            "prompt": full_prompt[:950],
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
        # 5. FREE NEURAL AI GENERATOR (Pollinations Flux / SDXL)
        # ============================================================
        last_poll_error = None
        for model_name in ["flux", "turbo"]:
            try:
                safe_prompt = urllib.parse.quote(full_prompt[:350])
                poll_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?model={model_name}&width={width}&height={height}&nologo=true"
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                    poll_resp = await client.get(poll_url)
                    if poll_resp.status_code == 200 and len(poll_resp.content) > 10000:
                        img = Image.open(io.BytesIO(poll_resp.content))
                        fitted = self.fit_image_to_aspect_ratio(img, width, height)
                        fitted.save(output_path, "JPEG", quality=92)
                        print(f"Generated scene {scene_idx + 1} using Free Neural AI Engine ({model_name.upper()})!")
                        return output_path
                    else:
                        last_poll_error = f"HTTP {poll_resp.status_code}"
            except Exception as e_poll:
                last_poll_error = str(e_poll)
                continue

        # Strictly raise error — NO procedural / vector placeholder fallback!
        raise RuntimeError(f"Image generation failed on chosen engine ({image_mode}): {last_poll_error or 'Connection timed out'}. No placeholder fallback used. Please switch to In-Browser Puter.js ('🖌️') or Gemini Imagen 3 in Settings.")

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
