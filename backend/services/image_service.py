import os
import random
import re
import io
import urllib.parse
from pathlib import Path
import httpx
from PIL import Image, ImageDraw, ImageFont
from backend.config import ART_STYLES, SPEAKER_FOCUS_PROMPT_SUFFIX, is_comic_style

class OrientationMismatchError(RuntimeError):
    """Raised when a generated image has opposite orientation (e.g. portrait for landscape) so it can be retried once."""


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
        p = re.sub(r'(?i)[,.]?\s*(?:Bong bóng thoại truyện tranh|Hộp dẫn truyện tranh \(Caption\)|Comic speech bubble|Comic narrator caption box)[^.]*\.?', '', p)
        p = re.sub(r'(?i),?\s*upper headroom for speech balloons?\b', '', p)
        p = re.sub(r'(?i)\b(?:speech|dialogue|thought|comic|text)\s+(?:bubbles?|balloons?)\b', '', p)
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
        elif is_comic_style(effective_style) or any(k in lower_base for k in ("comic book", "graphic novel panel")):
            effective_style = "comic"

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

    @staticmethod
    def get_base_image_path(output_path: str) -> str:
        """Returns the path for the un-bubbled base image corresponding to a scene image file."""
        p = Path(str(output_path))
        return str(p.with_name(f"{p.stem}_base{p.suffix}"))

    @staticmethod
    def _load_comic_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
        """
        Loads a TrueType font with 100% complete Vietnamese Unicode glyph coverage
        (including precomposed horn vowels ơ/ư and underdot vowels ạ/ộ/ệ/ợ/ự).
        Note: Windows `comicbd.ttf` / `comic.ttf` is intentionally excluded because it lacks
        Vietnamese horn/underdot glyphs and renders them as missing-glyph boxes (▯).
        """
        candidates = (
            [
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
                "C:/Windows/Fonts/tahomabd.ttf",
                "C:/Windows/Fonts/calibrib.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
            if bold
            else [
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/tahoma.ttf",
                "C:/Windows/Fonts/calibri.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )
        for fp in candidates:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    @staticmethod
    def _wrap_comic_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_px_w: int) -> list:
        """Wraps text into lines that fit within `max_px_w` pixels."""
        words = (text or "").strip().split()
        if not words:
            return []
        lines = []
        cur = []
        for w in words:
            test = " ".join(cur + [w])
            bbox = draw.textbbox((0, 0), test, font=font)
            tw = bbox[2] - bbox[0]
            if tw <= max_px_w or not cur:
                cur.append(w)
            else:
                lines.append(" ".join(cur))
                cur = [w]
        if cur:
            lines.append(" ".join(cur))
        return lines

    @staticmethod
    def _clean_ai_blank_top_balloon(base_img: Image.Image) -> Image.Image:
        """
        If an AI image generator accidentally drew an empty white speech balloon at the top edge
        of the base image, seamlessly inpaints it by stretching and feather-blending the natural
        background strip immediately below the balloon.
        """
        try:
            import numpy as np
            from PIL import ImageFilter
            rgb_img = base_img.convert("RGB")
            arr = np.array(rgb_img, dtype=np.uint8)
            h, w, _ = arr.shape
            top_h = int(h * 0.24)
            top_region = arr[:top_h, :, :]
            luma_top = 0.299 * top_region[:, :, 0] + 0.587 * top_region[:, :, 1] + 0.114 * top_region[:, :, 2]
            white_mask = (top_region[:, :, 0] > 240) & (top_region[:, :, 1] > 240) & (top_region[:, :, 2] > 240)
            if np.mean(white_mask[:int(h * 0.12), :]) < 0.50:
                return base_img

            # Verify it is genuinely an AI-drawn blank speech balloon (which has a dark ink border beneath the white fill),
            # NOT a natural white sky (like scene_4).
            non_w = luma_top < 240
            first_y = np.argmax(non_w, axis=0)
            cols = np.arange(w)
            fy_probe = np.clip(first_y + 1, 0, top_h - 1)
            is_ink_border = (first_y > int(h * 0.05)) & (first_y < int(h * 0.22)) & (luma_top[fy_probe, cols] < 75)
            if np.mean(is_ink_border) < 0.45:
                return base_img

            # Build an exact mask covering only the white balloon + its black outline per column (zero horizontal cutoff)
            yy = np.arange(top_h)[:, None]
            balloon_and_ink = (yy <= (first_y[None, :] + 10)) & (first_y[None, :] > int(h * 0.04))
            mask_pil = Image.fromarray((balloon_and_ink.astype(np.uint8) * 255), mode="L")
            mask_pil = mask_pil.filter(ImageFilter.MaxFilter(9))
            mask_pil = mask_pil.filter(ImageFilter.GaussianBlur(radius=5))
            alpha = (np.array(mask_pil, dtype=np.float32)[:, :, None] / 255.0).clip(0.0, 1.0)

            # Sample clean sky/background pixels just below the balloon border for each column
            sample_y = np.clip(first_y + 16, 0, h - 1)
            col_samples = arr[sample_y, cols, :].astype(np.float32)
            col_luma = 0.299 * col_samples[:, 0] + 0.587 * col_samples[:, 1] + 0.114 * col_samples[:, 2]
            valid_cols = col_luma > 150
            if np.any(valid_cols):
                median_sky = np.median(col_samples[valid_cols], axis=0)
                col_samples[~valid_cols] = median_sky
            else:
                col_samples[:] = np.array([224.0, 218.0, 208.0], dtype=np.float32)

            sky_row_img = Image.fromarray(col_samples[None, :, :].clip(0, 255).astype(np.uint8), mode="RGB")
            sky_strip = sky_row_img.resize((w, top_h), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(radius=16))
            sky_arr = np.array(sky_strip, dtype=np.float32)

            blended = (top_region.astype(np.float32) * (1.0 - alpha) + sky_arr * alpha).clip(0, 255).astype(np.uint8)
            arr[:top_h, :, :] = blended
            return Image.fromarray(arr, mode="RGB")
        except Exception:
            return base_img

    @staticmethod
    def _locate_character_heads(base_img: Image.Image) -> list:
        """
        Detects character face/head regions `(face_x, face_y, top_head_y)` in normalized `[0..1]`
        coordinates so speech bubbles can be placed right next to or above the speaking character
        WITHOUT covering any character's face.
        """
        try:
            import numpy as np
            small = base_img.convert("RGB").resize((96, 128), Image.Resampling.BILINEAR)
            arr = np.array(small, dtype=np.int16)
            r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

            # Warm skin-tone mask typical of comic/anime faces
            skin = (
                (r > 135) & (r < 248) &
                (g > 85) & (b > 55) &
                ((r - g) >= 10) & ((g - b) >= -5) &
                ((r - b) >= 28) & ((r - b) <= 130)
            )
            y0, y1 = int(128 * 0.14), int(128 * 0.56)
            x0, x1 = int(96 * 0.08), int(96 * 0.92)
            sub = skin[y0:y1, x0:x1]

            if np.sum(sub) < 12:
                return [(0.55, 0.28, 0.20), (0.35, 0.34, 0.25)]

            mid_x = (x1 - x0) // 2
            anchors = []
            for hx0, hx1 in [(0, mid_x), (mid_x, x1 - x0)]:
                h_sub = sub[:, hx0:hx1]
                cnt = int(np.sum(h_sub))
                if cnt >= 10:
                    ys, xs = np.where(h_sub)
                    # Top of forehead is ~8th percentile of skin y; hair extends ~0.05 above forehead
                    forehead_y = (y0 + float(np.percentile(ys, 8))) / 128.0
                    face_y = (y0 + float(np.percentile(ys, 22))) / 128.0
                    top_head_y = max(0.10, forehead_y - 0.055)
                    # Find x of the upper face rows (not arms/hands lower down)
                    upper_mask = ys <= np.percentile(ys, 35)
                    face_x = (x0 + hx0 + float(np.median(xs[upper_mask]))) / 96.0
                    anchors.append((cnt, face_x, face_y, top_head_y))

            if anchors:
                anchors.sort(key=lambda item: (item[2] - item[0] * 0.0004))
                return [(ax, ay, ty) for (_, ax, ay, ty) in anchors]
        except Exception:
            pass
        return [(0.55, 0.28, 0.20), (0.35, 0.34, 0.25)]

    def render_comic_overlay(
        self,
        img: Image.Image,
        dialogues: list = None,
        narration: str = "",
        prompt: str = "",
        title: str = "",
        scene_idx: int = 0,
        dialogue_only: bool = False,
        enable_image_captions: bool = True
    ) -> Image.Image:
        """
        Renders graphic-novel panel borders, an optional top comic narrator caption box
        (controlled by `enable_image_captions`), and large, legible comic-book speech balloons
        positioned right near the speaking character with directional pointer tails.
        """
        import unicodedata
        cleaned_rgb = self._clean_ai_blank_top_balloon(img)
        head_anchors = self._locate_character_heads(cleaned_rgb)
        base = cleaned_rgb.convert("RGBA")
        w, h = base.size

        def _norm_vn(s: str) -> str:
            return unicodedata.normalize("NFC", (s or "").strip())

        narrator_aliases = {"narrator", "người kể chuyện", "vo", "voiceover", "lời dẫn", "thuyết minh", "none", ""}

        # Extract character dialogues & narrator lines
        segs = []
        if dialogues and isinstance(dialogues, list):
            for d in dialogues:
                if isinstance(d, dict) and (d.get("text") or "").strip():
                    segs.append({
                        "speaker": _norm_vn(d.get("speaker") or "Narrator"),
                        "text": _norm_vn(d.get("text") or "")
                    })
        if not segs and narration:
            try:
                from backend.agents.script_agent import ScriptAgent
                segs = ScriptAgent.extract_scene_dialogue_segments(_norm_vn(narration))
            except Exception:
                segs = [{"speaker": "Narrator", "text": _norm_vn(narration)}]

        char_bubbles = []
        narr_lines = []
        for s in segs:
            spk = _norm_vn(s.get("speaker") or "Narrator")
            txt = _norm_vn(s.get("text") or "").strip('"“”')
            # If a narrator line actually starts with a dialogue dash (– or -), treat it as character dialogue
            if spk.lower() in narrator_aliases and re.match(r'^[–\-—]\s*\S', txt):
                txt = re.sub(r'^[–\-—]\s*', '', txt).strip()
                spk = "Character"
            if not txt:
                continue
            if spk.lower() in narrator_aliases:
                if txt not in narr_lines:
                    narr_lines.append(txt)
            else:
                char_bubbles.append((spk, txt))

        if not char_bubbles and prompt:
            for m in re.finditer(
                r'(?:Comic speech bubble from|Bong bóng thoại truyện tranh của)\s+([^:]+):\s*["“]([^"”]+)["”]',
                prompt,
                re.IGNORECASE
            ):
                cand_spk = _norm_vn(m.group(1))
                cand_txt = _norm_vn(m.group(2)).strip('"“”')
                if not cand_txt:
                    continue
                if cand_spk.lower() in narrator_aliases:
                    if cand_txt not in narr_lines:
                        narr_lines.append(cand_txt)
                else:
                    char_bubbles.append((cand_spk, cand_txt))

        # Infer actual character name from `prompt` or `title` when speaker is generic "Character"
        if char_bubbles and prompt:
            resolved_bubbles = []
            for spk, txt in char_bubbles:
                if spk.lower() in ("character", "nhân vật"):
                    m_focus = re.search(
                        r'(?:focus(?:ing|ed)?\s+(?:directly\s+)?on|Close-Up\s+Shot\s+of|Shot\s+of)\s+([A-ZÀ-Ỹ][A-Za-zÀ-ỹ]+(?:\s+[A-ZÀ-Ỹ][A-Za-zÀ-ỹ]+)?)',
                        prompt
                    )
                    if m_focus and m_focus.group(1).lower() not in ("the", "character", "medium", "wide", "extreme"):
                        spk = _norm_vn(m_focus.group(1))
                resolved_bubbles.append((spk, txt))
            char_bubbles = resolved_bubbles

        # 2x supersampled overlay canvas for anti-aliased comic ink lines and speech balloons
        scale = 2
        W, H = w * scale, h * scale
        is_portrait = H > W
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 1. Classic Comic Panel Outer Frame (white comic gutter + bold black ink border)
        gutter = max(8, int(min(W, H) * 0.008))
        ink_w = max(4, int(min(W, H) * 0.004))
        draw.rectangle([0, 0, W - 1, H - 1], outline=(255, 255, 255, 255), width=gutter)
        draw.rectangle(
            [gutter, gutter, W - 1 - gutter, H - 1 - gutter],
            outline=(15, 23, 42, 255),
            width=ink_w
        )

        margin_x = gutter + ink_w + int(W * (0.035 if is_portrait else 0.030))
        margin_y = gutter + ink_w + int(H * (0.018 if is_portrait else 0.024))
        usable_w = max(200, W - margin_x * 2)
        cursor_top_y = margin_y

        # 2. Optional Top Golden Comic Narrative Caption Box (controlled by `enable_image_captions`)
        show_caption = bool(enable_image_captions) and (not dialogue_only) and bool(narr_lines) and (len(char_bubbles) == 0 or len(char_bubbles) == 1)
        if show_caption:
            cap_text = _norm_vn(" ".join(narr_lines))
            cap_words = cap_text.split()
            max_cap_words = 50 if len(char_bubbles) == 0 else 18
            if len(cap_words) > max_cap_words:
                candidate_cut = " ".join(cap_words[:max_cap_words])
                m_punct = re.search(r'^(.+[.!?;,])\s+\S+$', candidate_cut)
                if m_punct and len(m_punct.group(1).split()) >= int(max_cap_words * 0.6):
                    cap_text = m_punct.group(1).rstrip(" ,;:-") + ("..." if not m_punct.group(1).endswith((".", "!", "?")) else "")
                else:
                    cap_text = candidate_cut.rstrip(" ,;:-") + "..."
            cap_font_size = max(24, int(min(W, H) * (0.027 if len(char_bubbles) == 0 else 0.024)))
            cap_font = self._load_comic_font(cap_font_size, bold=True)
            max_cap_box_w = min(usable_w, int(W * (0.90 if is_portrait else (0.78 if len(char_bubbles) == 0 else 0.58))))
            pad_x = int(cap_font_size * 0.72)
            pad_y = int(cap_font_size * 0.50)
            cap_lines = self._wrap_comic_text(draw, cap_text, cap_font, max_cap_box_w - pad_x * 2)
            if cap_lines:
                line_h = int(cap_font_size * 1.34)
                measured_w = max(
                    (draw.textbbox((0, 0), ln, font=cap_font)[2] - draw.textbbox((0, 0), ln, font=cap_font)[0])
                    for ln in cap_lines
                )
                box_w = min(max_cap_box_w, measured_w + pad_x * 2)
                box_h = len(cap_lines) * line_h + pad_y * 2
                bx0 = (W - box_w) // 2 if (is_portrait or len(char_bubbles) == 0) else margin_x
                by0 = cursor_top_y
                bx1, by1 = bx0 + box_w, by0 + box_h
                sh_off = max(6, int(ink_w * 1.4))

                # Hard comic drop shadow
                draw.rectangle([bx0 + sh_off, by0 + sh_off, bx1 + sh_off, by1 + sh_off], fill=(15, 23, 42, 195))
                # Classic golden-yellow comic caption box with bold black ink frame
                draw.rectangle([bx0, by0, bx1, by1], fill=(254, 240, 138, 246), outline=(15, 23, 42, 255), width=ink_w)
                draw.rectangle([bx0 + ink_w + 2, by0 + ink_w + 2, bx1 - ink_w - 2, by1 - ink_w - 2], outline=(217, 119, 6, 120), width=2)

                ty = by0 + pad_y
                for ln in cap_lines:
                    draw.text((bx0 + pad_x, ty), ln, font=cap_font, fill=(15, 23, 42, 255))
                    ty += line_h
                cursor_top_y = by1 + int(H * 0.020)

        # 3. Character Comic Speech Bubbles — Large Legible Dialogue Text Positioned Near the Speaking Character
        speaker_palette = [
            (220, 38, 38),   # Hero Red
            (37, 99, 235),   # Comic Blue
            (5, 150, 105),   # Emerald Green
            (124, 58, 237),  # Graphic Purple
            (217, 119, 6),   # Amber Gold
        ]
        speaker_color_map = {}

        bubbles_to_draw = char_bubbles[:3]
        num_b = len(bubbles_to_draw)
        prev_bubble_bottom = cursor_top_y

        for b_idx, (spk_raw, b_text) in enumerate(bubbles_to_draw):
            b_text = _norm_vn(b_text).lstrip("–-— ").strip()
            b_words = b_text.split()
            if len(b_words) > 30:
                b_text = " ".join(b_words[:30]).rstrip(" ,;:-") + "..."

            # Larger, bold comic dialogue typography
            if len(b_words) <= 6:
                f_ratio = 0.045
            elif len(b_words) <= 12:
                f_ratio = 0.040
            elif len(b_words) <= 20:
                f_ratio = 0.035
            else:
                f_ratio = 0.030
            if num_b >= 3:
                f_ratio *= 0.88

            font_size = max(32, int(min(W, H) * f_ratio))
            body_font = self._load_comic_font(font_size, bold=True)
            tag_font_size = max(22, int(font_size * 0.68))
            tag_font = self._load_comic_font(tag_font_size, bold=True)

            max_b_w = min(usable_w, int(W * (0.84 if is_portrait else (0.58 if num_b == 1 else 0.48))))
            pad_x = int(font_size * 0.78)
            pad_y = int(font_size * 0.62)
            lines = self._wrap_comic_text(draw, b_text, body_font, max_b_w - pad_x * 2)
            if not lines:
                continue

            line_h = int(font_size * 1.32)
            text_w = max(
                (draw.textbbox((0, 0), ln, font=body_font)[2] - draw.textbbox((0, 0), ln, font=body_font)[0])
                for ln in lines
            )
            spk_display = _norm_vn(spk_raw)
            show_spk_tag = spk_display.lower() not in ("", "character", "nhân vật", "narrator", "người kể chuyện")
            tag_w = 0
            tag_h = 0
            if show_spk_tag:
                spk_upper = spk_display.upper()
                tb = draw.textbbox((0, 0), spk_upper, font=tag_font)
                tag_w = (tb[2] - tb[0]) + int(tag_font_size * 1.25)
                tag_h = int(tag_font_size * 1.50)

            bubble_w = max(text_w + pad_x * 2, tag_w + pad_x * 2, int(W * 0.22))
            bubble_w = min(bubble_w, max_b_w)
            bubble_h = len(lines) * line_h + pad_y * 2 + (int(tag_h * 0.30) if show_spk_tag else 0)

            # Locate the speaking character's head `(head_px_x, face_px_y, top_head_px_y)` so the bubble sits right near the speaker WITHOUT covering their face
            anchor_rel_x, anchor_rel_y, top_head_rel_y = head_anchors[min(b_idx, len(head_anchors) - 1)]
            head_px_x = int(anchor_rel_x * W)
            face_px_y = int(anchor_rel_y * H)
            top_head_px_y = int(top_head_rel_y * H)
            tail_h = max(36, int(font_size * 1.15))
            tail_half_w = max(20, int(font_size * 0.58))

            if b_idx == 0:
                min_by0 = prev_bubble_bottom + (int(tag_h * 0.55) if show_spk_tag else 0)
                # Case A: Speaker is on the right side (e.g. x > 0.62) and open sky exists to the left of their head
                if anchor_rel_x > 0.62 and (head_px_x - int(W * 0.12) - bubble_w) >= margin_x:
                    bx0 = max(margin_x, head_px_x - int(W * 0.13) - bubble_w)
                    # Place vertically right beside the upper head/forehead (above any second lower character)
                    second_top_y = int(head_anchors[1][2] * H) if len(head_anchors) > 1 else int(H * 0.34)
                    ideal_by1 = min(face_px_y + int(H * 0.01), second_top_y - int(H * 0.02))
                    by0 = max(min_by0, min(ideal_by1 - bubble_h, int(H * 0.20)))
                    tail_dir = "side_right_toward_head"
                else:
                    # Case B: Place directly above the speaking character's head (`by1 <= top_head_px_y`)
                    ideal_by1 = top_head_px_y - tail_h - int(H * 0.008)
                    by0 = max(min_by0, min(ideal_by1 - bubble_h, int(H * 0.16)))
                    ideal_bx0 = head_px_x - int(bubble_w * 0.50)
                    bx0 = max(margin_x, min(W - margin_x - bubble_w, ideal_bx0))
                    tail_dir = "down_toward_head"
            elif b_idx == 1:
                bx0 = W - margin_x - bubble_w if anchor_rel_x >= 0.45 else margin_x
                by0 = max(prev_bubble_bottom + int(H * 0.022) + (int(tag_h * 0.55) if show_spk_tag else 0), int(H * 0.15))
                tail_dir = "down_toward_head"
            else:
                bx0 = margin_x
                by0 = H - margin_y - bubble_h - int(H * 0.045)
                tail_dir = "up_toward_head"

            bx1 = bx0 + bubble_w
            by1 = by0 + bubble_h
            radius = max(24, int(min(bubble_w, bubble_h) * 0.28))
            sh_off = max(7, int(ink_w * 1.5))

            # Build pointer tail aimed directly toward the speaking character's head/mouth
            if tail_dir == "side_right_toward_head":
                base_cy = max(by0 + radius + tail_half_w, min(by1 - radius - tail_half_w, int(by0 + bubble_h * 0.62)))
                tip_x = min(head_px_x - int(W * 0.05), bx1 + int(tail_h * 1.25))
                tip_y = max(by0 + int(bubble_h * 0.45), min(by1 + tail_h, face_px_y))
                tail_poly = [
                    (bx1 - ink_w, base_cy - tail_half_w),
                    (bx1 - ink_w, base_cy + tail_half_w),
                    (tip_x, tip_y)
                ]
            elif tail_dir == "down_toward_head":
                base_cx = max(bx0 + radius + tail_half_w, min(bx1 - radius - tail_half_w, int(bx0 + (head_px_x - bx0) * 0.65)))
                tip_x = max(bx0 + 10, min(bx1 + 45, base_cx + int((head_px_x - base_cx) * 0.50)))
                tip_y = by1 + tail_h
                tail_poly = [
                    (base_cx - tail_half_w, by1 - ink_w),
                    (base_cx + tail_half_w, by1 - ink_w),
                    (tip_x, tip_y)
                ]
            else:
                base_cx = bx0 + int(bubble_w * 0.35)
                tip_x = base_cx + int(tail_half_w * 1.1)
                tip_y = by0 - tail_h
                tail_poly = [
                    (base_cx - tail_half_w, by0 + ink_w),
                    (base_cx + tail_half_w, by0 + ink_w),
                    (tip_x, tip_y)
                ]

            shadow_tail = [(px + sh_off, py + sh_off) for (px, py) in tail_poly]

            # Layer A: Drop shadow (rounded balloon + tail)
            draw.rounded_rectangle(
                [bx0 + sh_off, by0 + sh_off, bx1 + sh_off, by1 + sh_off],
                radius=radius,
                fill=(15, 23, 42, 185)
            )
            draw.polygon(shadow_tail, fill=(15, 23, 42, 185))

            # Layer B: Bold black ink outer contour (balloon + tail)
            draw.polygon(tail_poly, fill=(255, 255, 255, 252), outline=(15, 23, 42, 255), width=ink_w)
            draw.rounded_rectangle(
                [bx0, by0, bx1, by1],
                radius=radius,
                fill=(255, 255, 255, 252),
                outline=(15, 23, 42, 255),
                width=ink_w
            )
            if tail_dir == "side_right_toward_head":
                inner_seam_poly = [
                    (tail_poly[0][0], tail_poly[0][1] + ink_w // 2),
                    (tail_poly[1][0], tail_poly[1][1] - ink_w // 2),
                    tail_poly[2]
                ]
            else:
                inner_seam_poly = [
                    (tail_poly[0][0] + ink_w // 2, tail_poly[0][1]),
                    (tail_poly[1][0] - ink_w // 2, tail_poly[1][1]),
                    tail_poly[2]
                ]
            draw.polygon(inner_seam_poly, fill=(255, 255, 255, 252))

            # Layer C: Speaker Name Pill Badge on top rim of speech balloon
            text_start_y = by0 + pad_y
            if show_spk_tag:
                spk_key = spk_display.lower()
                if spk_key not in speaker_color_map:
                    speaker_color_map[spk_key] = speaker_palette[len(speaker_color_map) % len(speaker_palette)]
                badge_rgb = speaker_color_map[spk_key]
                tx0 = bx0 + int(radius * 0.60)
                ty0 = by0 - int(tag_h * 0.52)
                tx1 = tx0 + tag_w
                ty1 = ty0 + tag_h
                tag_rad = max(12, tag_h // 2)
                draw.rounded_rectangle(
                    [tx0, ty0, tx1, ty1],
                    radius=tag_rad,
                    fill=(*badge_rgb, 255),
                    outline=(15, 23, 42, 255),
                    width=max(3, ink_w - 1)
                )
                spk_upper = spk_display.upper()
                tb = draw.textbbox((0, 0), spk_upper, font=tag_font)
                tw_s = tb[2] - tb[0]
                th_s = tb[3] - tb[1]
                draw.text(
                    (tx0 + (tag_w - tw_s) // 2, ty0 + (tag_h - th_s) // 2 - tb[1]),
                    spk_upper,
                    font=tag_font,
                    fill=(255, 255, 255, 255)
                )
                text_start_y += int(tag_h * 0.22)

            # Layer D: Large Bold Dialogue Text inside speech balloon
            curr_y = text_start_y
            for ln in lines:
                lb = draw.textbbox((0, 0), ln, font=body_font)
                lw = lb[2] - lb[0]
                lx = bx0 + (bubble_w - lw) // 2
                draw.text((lx, curr_y), ln, font=body_font, fill=(15, 23, 42, 255))
                curr_y += line_h

            prev_bubble_bottom = by1 + tail_h

        # Downscale 2x supersampled overlay onto base image with LANCZOS filter
        smooth_overlay = overlay.resize((w, h), Image.Resampling.LANCZOS)
        composited = Image.alpha_composite(base, smooth_overlay)
        return composited.convert("RGB")

    def apply_comic_overlay_to_file(
        self,
        image_path: str,
        dialogues: list = None,
        narration: str = "",
        prompt: str = "",
        title: str = "",
        scene_idx: int = 0,
        dialogue_only: bool = False,
        enable_image_captions: bool = True
    ) -> str:
        """
        Ensures a clean `_base.jpg` copy of `image_path` is preserved, then renders
        the comic panel border & dialogue speech bubbles onto `image_path`.
        """
        image_path = str(image_path)
        if not os.path.exists(image_path):
            return image_path
        base_path = self.get_base_image_path(image_path)
        import shutil
        if not os.path.exists(base_path):
            shutil.copy2(image_path, base_path)
        with Image.open(base_path) as raw_img:
            comic_img = self.render_comic_overlay(
                raw_img,
                dialogues=dialogues,
                narration=narration,
                prompt=prompt,
                title=title,
                scene_idx=scene_idx,
                dialogue_only=dialogue_only,
                enable_image_captions=enable_image_captions
            )
            comic_img.save(image_path, "JPEG", quality=95)
        return image_path

    def restore_base_image_file(self, image_path: str) -> bool:
        """Restores the un-bubbled `_base.jpg` image when switching away from Comic style."""
        image_path = str(image_path)
        base_path = self.get_base_image_path(image_path)
        if os.path.exists(base_path):
            import shutil
            shutil.copy2(base_path, image_path)
            return True
        return False

    def _collect_reference_files_and_instruction(
        self,
        full_prompt: str,
        character_references: list = None,
        reference_image_path: str = None,
        max_refs: int = 6,
        scene_only_prompt: str = None,
    ) -> tuple:
        """
        Builds a deduplicated ordered list of valid reference image paths (character portraits
        first, then optional scene continuity frame) and a strong identity-locking instruction
        binding each attached reference image to its character's exact face, headwear, outfit, and props.
        """
        req_files = []
        seen_paths = set()
        char_map_notes = []

        for ref in (character_references or []):
            if not isinstance(ref, dict):
                continue
            r_path = ref.get("path")
            if not r_path or not os.path.exists(r_path):
                continue
            ref_base = self.get_base_image_path(r_path)
            resolved = ref_base if os.path.exists(ref_base) else str(r_path)
            abs_p = str(Path(resolved).resolve())
            if abs_p in seen_paths:
                continue
            seen_paths.add(abs_p)
            req_files.append(resolved)
            c_name = (ref.get("name") or "").strip() or f"Character {len(req_files)}"
            c_desc = re.sub(r'\s+', ' ', str(ref.get("description") or "")).strip()
            note = (
                f"Reference Image {len(req_files)} = CHARACTER '{c_name}'"
                + (f" ({c_desc[:320]})" if c_desc else "")
                + f" — KEEP the exact face, headwear/crown/hat/headband, hairstyle, outfit/armor colors & details, and weapon shown in Reference Image {len(req_files)}."
            )
            char_map_notes.append(note)
            if len(req_files) >= max_refs:
                break

        has_scene_continuity_ref = False
        if reference_image_path and not char_map_notes and len(req_files) < max_refs:
            ref_base = self.get_base_image_path(reference_image_path)
            cand_scene_ref = ref_base if os.path.exists(ref_base) else str(reference_image_path)
            if os.path.exists(cand_scene_ref):
                abs_s = str(Path(cand_scene_ref).resolve())
                if abs_s not in seen_paths:
                    seen_paths.add(abs_s)
                    req_files.append(cand_scene_ref)
                    has_scene_continuity_ref = True

        if not req_files:
            instruction = f"Generate an image of: {full_prompt[:2800]}. Clean illustration without text, no speech bubbles, no words."
            return None, instruction

        parts = []
        if char_map_notes:
            parts.append("CHARACTER REFERENCE BINDINGS (DO NOT ALTER CHARACTER DESIGNS):\n- " + "\n- ".join(char_map_notes))
        if has_scene_continuity_ref:
            parts.append(
                f"Reference Image {len(req_files)} is a prior scene frame for art-style & lighting continuity ONLY (do NOT copy its pose or composition)."
            )
        target_scene_text = (scene_only_prompt or full_prompt)[:2400]
        parts.append(
            "MANDATORY VISUAL IDENTITY LOCK: For every character listed above, draw their EXACT face, headwear (keep hats, crowns, or headbands shown in their Reference Image — NEVER make a hatted character bareheaded), hairstyle, facial hair, armor/robe pattern & colors, and signature weapon from their attached Reference Image. Adapt ONLY pose, expression, camera framing, and environment.\n\n"
            f"NEW SCENE TO GENERATE:\n{target_scene_text}\n\n"
            "OUTPUT REQUIREMENT: Clean illustration without text, no speech bubbles, no words, no watermarks."
        )
        return req_files, "\n\n".join(parts)

    def _save_with_orientation_guard(
        self,
        img: Image.Image,
        output_path: str,
        width: int,
        height: int,
        quality: int = 95,
        enforce_orientation: bool = True,
    ) -> str:
        """Checks orientation against target canvas before fitting; raises OrientationMismatchError on first mismatch."""
        from backend.services.image_orientation import check_image_orientation
        if enforce_orientation:
            ok, reason = check_image_orientation(img, width, height)
            if not ok:
                raise OrientationMismatchError(reason)
        fitted = self.fit_image_to_aspect_ratio(img.convert("RGB"), width, height)
        fitted.save(output_path, "JPEG", quality=quality)
        return output_path

    async def _generate_raw_ai_image(
        self,
        full_prompt: str,
        output_path: str,
        style_key: str,
        width: int,
        height: int,
        image_mode: str = "gemini",
        req_files: list = None,
        multimodal_prompt: str = "",
        seed: int = None,
        api_key: str = None,
        provider: str = None,
        label: str = "image",
        _orientation_retry: bool = False,
    ) -> str:
        """
        Shared low-level image generation dispatcher with automatic 1-shot Orientation Guard retry
        (adapted from ViMax tools/image_orientation.py).
        """
        from backend.services.image_orientation import build_orientation_retry_hint
        try:
            return await self._generate_raw_ai_image_once(
                full_prompt=full_prompt,
                output_path=output_path,
                style_key=style_key,
                width=width,
                height=height,
                image_mode=image_mode,
                req_files=req_files,
                multimodal_prompt=multimodal_prompt,
                seed=seed,
                api_key=api_key,
                provider=provider,
                label=label,
                enforce_orientation=not _orientation_retry,
            )
        except OrientationMismatchError as e_orient:
            if _orientation_retry:
                raise RuntimeError(str(e_orient))
            hint = build_orientation_retry_hint(width, height)
            print(f"⚠️ Orientation guard triggered for {label}: {e_orient}. Retrying once with explicit orientation directive...")
            retry_prompt = f"{full_prompt}. {hint}"
            retry_mm = f"{multimodal_prompt}. {hint}" if multimodal_prompt else ""
            retry_seed = (seed + 7919) % 999999 if isinstance(seed, int) else None
            return await self._generate_raw_ai_image(
                full_prompt=retry_prompt,
                output_path=output_path,
                style_key=style_key,
                width=width,
                height=height,
                image_mode=image_mode,
                req_files=req_files,
                multimodal_prompt=retry_mm,
                seed=retry_seed,
                api_key=api_key,
                provider=provider,
                label=label,
                _orientation_retry=True,
            )

    async def _generate_raw_ai_image_once(
        self,
        full_prompt: str,
        output_path: str,
        style_key: str,
        width: int,
        height: int,
        image_mode: str = "gemini",
        req_files: list = None,
        multimodal_prompt: str = "",
        seed: int = None,
        api_key: str = None,
        provider: str = None,
        label: str = "image",
        enforce_orientation: bool = True,
    ) -> str:
        """
        Single-attempt image generation dispatcher across Antigravity CLI, FlowKit,
        OpenAI DALL-E 3, Pollinations, Google Gemini Official API, and Gemini Web Cookie.
        """
        import asyncio
        eff_api_key = api_key or self.api_key
        eff_provider = provider or self.provider
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        curr_ratio = width / float(height)
        if curr_ratio > 1.6:
            imagen_ratio = "16:9"
            flow_ratio = "IMAGE_ASPECT_RATIO_LANDSCAPE"
            dalle_size = "1792x1024"
        elif curr_ratio < 0.65:
            imagen_ratio = "9:16"
            flow_ratio = "IMAGE_ASPECT_RATIO_PORTRAIT"
            dalle_size = "1024x1792"
        elif curr_ratio > 1.2:
            imagen_ratio = "4:3"
            flow_ratio = "IMAGE_ASPECT_RATIO_LANDSCAPE"
            dalle_size = "1024x1024"
        elif curr_ratio < 0.85:
            imagen_ratio = "3:4"
            flow_ratio = "IMAGE_ASPECT_RATIO_PORTRAIT"
            dalle_size = "1024x1024"
        else:
            imagen_ratio = "1:1"
            flow_ratio = "IMAGE_ASPECT_RATIO_SQUARE"
            dalle_size = "1024x1024"

        # 0. Antigravity AI (Local CLI `agy` -> image-generator subagent)
        if image_mode == "antigravity":
            saved = await self._generate_with_antigravity(
                prompt=multimodal_prompt or full_prompt,
                output_path=output_path,
                width=width,
                height=height,
                aspect_ratio=imagen_ratio,
                req_files=req_files,
                enforce_orientation=enforce_orientation,
            )
            if saved and os.path.exists(output_path):
                print(f"Generated {label} using Antigravity AI (Local CLI)!")
                return output_path
            raise RuntimeError("Antigravity AI image generation failed to produce an image file.")

        # 1. Google Flow Bridge (FlowKit) with native character_media_ids
        if image_mode == "flowkit":
            from backend.services.flowkit_service import FlowKitService
            fk = FlowKitService.get_instance()
            tmp_out = f"{output_path}.flowtmp.jpg"
            await fk.generate_reference_image(
                prompt=multimodal_prompt or full_prompt,
                output_image_path=tmp_out,
                reference_image_paths=req_files,
                aspect_ratio=flow_ratio,
                seed=seed
            )
            img = Image.open(tmp_out)
            fitted = self.fit_image_to_aspect_ratio(img, width, height)
            fitted.save(output_path, "JPEG", quality=95)
            try:
                os.remove(tmp_out)
            except Exception:
                pass
            print(f"Generated {label} using Google Flow Bridge with {len(req_files or [])} reference(s)!")
            return output_path

        # 2. OpenAI DALL-E 3 Mode
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
                            self._save_with_orientation_guard(
                                img, output_path, width, height, quality=92, enforce_orientation=enforce_orientation
                            )
                            print(f"Generated {label} using OpenAI DALL-E 3 ({dalle_size})!")
                            return output_path
                    else:
                        raise RuntimeError(f"OpenAI DALL-E error {resp.status_code}: {resp.text}")
            except OrientationMismatchError:
                raise
            except Exception as e:
                raise RuntimeError(f"OpenAI DALL-E 3 generation failed: {e}")

        # 3b. Direct Cloud AI Art (Pollinations Flux / Sana) Mode
        if image_mode == "pollinations":
            import urllib.parse
            import random
            clean_p = re.sub(r'\s+', ' ', (full_prompt or "Animated illustration")).strip()[:950]
            encoded_p = urllib.parse.quote(clean_p)
            eff_seed = seed if seed is not None else random.randint(1000, 999999)
            req_w = min(1280, max(512, int(width)))
            req_h = min(1280, max(512, int(height)))
            poll_url = f"https://image.pollinations.ai/prompt/{encoded_p}?width={req_w}&height={req_h}&seed={eff_seed}&nologo=true"
            async with httpx.AsyncClient(timeout=35.0, follow_redirects=True) as client:
                p_resp = await client.get(poll_url)
                if p_resp.status_code == 200 and len(p_resp.content) > 2048:
                    img = Image.open(io.BytesIO(p_resp.content)).convert("RGB")
                    self._save_with_orientation_guard(
                        img, output_path, width, height, quality=95, enforce_orientation=enforce_orientation
                    )
                    print(f"Generated {label} using Cloud AI Art (Pollinations)!")
                    return output_path
            raise RuntimeError("Cloud AI Art (Pollinations) image generation failed.")

        # 4. Google Gemini / Imagen 3 Mode (Strict per selected method: gemini_api vs gemini_cookie)
        if image_mode in ("gemini", "server", "gemini_api", "gemini_cookie"):
            from backend.config import get_server_credentials
            s_creds = get_server_credentials()
            gemini_error = None

            use_cookie_strict = bool(
                image_mode == "gemini_cookie"
                or (
                    image_mode in ("gemini", "server")
                    and (
                        eff_provider == "gemini_cookie"
                        or (eff_api_key and (eff_api_key.startswith("g.a") or "__Secure-1PSID" in eff_api_key))
                    )
                )
            )
            use_api_strict = not use_cookie_strict

            # 4a. Strictly Official Google AI Studio API Key (when gemini_api or provider=gemini is selected)
            if use_api_strict:
                api_studio_key = (
                    eff_api_key
                    if (eff_api_key and not eff_api_key.startswith("g.a") and "__Secure-1PSID" not in eff_api_key)
                    else (s_creds.get("gemini_api_key") or "").strip()
                )
                if not api_studio_key or api_studio_key.startswith("g.a") or "__Secure-1PSID" in api_studio_key:
                    raise RuntimeError(
                        "Gemini API Image generation failed: No valid Google Gemini API key configured. "
                        "Please enter your Gemini API key or switch the task Paint Engine to Gemini Web Cookie / Cloud AI Art."
                    )
                try:
                    from google import genai
                    from google.genai import types
                    client = genai.Client(
                        api_key=api_studio_key,
                        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
                    )

                    ref_pil_imgs = []
                    for rf in (req_files or []):
                        try:
                            ref_pil_imgs.append(Image.open(rf).convert("RGB"))
                        except Exception:
                            pass
                    contents_payload = [*ref_pil_imgs, (multimodal_prompt or full_prompt)[:2600]] if ref_pil_imgs else (full_prompt[:2600])

                    for mm_model in ["gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-2.5-flash-image", "gemini-3-pro-image"]:
                        try:
                            mm_resp = await asyncio.to_thread(
                                lambda m=mm_model: client.models.generate_content(
                                    model=m,
                                    contents=contents_payload,
                                    config=types.GenerateContentConfig(
                                        response_modalities=["IMAGE"],
                                        image_config=types.ImageConfig(aspect_ratio=imagen_ratio)
                                    )
                                )
                            )
                            if mm_resp.candidates and mm_resp.candidates[0].content and mm_resp.candidates[0].content.parts:
                                for part in mm_resp.candidates[0].content.parts:
                                    inline = getattr(part, "inline_data", None)
                                    if inline and getattr(inline, "data", None):
                                        img = Image.open(io.BytesIO(inline.data))
                                        fitted = self.fit_image_to_aspect_ratio(img, width, height)
                                        fitted.save(output_path, "JPEG", quality=95)
                                        print(f"Generated {label} using Gemini Multimodal API ({mm_model})!")
                                        return output_path
                        except Exception as e_mm:
                            gemini_error = str(e_mm)
                except Exception as e:
                    gemini_error = str(e)
                raise RuntimeError(f"Gemini API Image generation failed: {gemini_error or 'No image returned by Gemini API.'}")

            # 4b. Strictly Google Gemini Web Session Cookie (__Secure-1PSID)
            saved_psid = (s_creds.get("gemini_cookie_psid") or "").strip()
            saved_psidts = (s_creds.get("gemini_cookie_psidts") or "").strip()
            eff_psid, eff_psidts = self._parse_gemini_cookie_pair(eff_api_key if use_cookie_strict else "")

            if saved_psid and saved_psid != eff_psid:
                psid = saved_psid
                psidts = saved_psidts
            else:
                psid = eff_psid or saved_psid
                psidts = eff_psidts or (saved_psidts if psid == saved_psid else "")

            if not psid:
                raise RuntimeError(
                    "Gemini Web Cookie Image generation failed: No __Secure-1PSID cookie configured in Settings ⚙️."
                )

            combined_cookie = f"{psid}|{psidts}" if psidts else psid
            try:
                from backend.services.gemini_wrapper import GeminiWebWrapper
                wrapper = GeminiWebWrapper.get_instance()
                resp = await wrapper.generate_content(
                    multimodal_prompt or f"Generate an image of: {full_prompt[:2800]}. Clean illustration without text, no speech bubbles, no words.",
                    files=req_files or None,
                    cookie_override=combined_cookie
                )
                saved_img = None
                if resp.has_images:
                    temp_dir = Path(output_path).parent / "temp_gemini"
                    os.makedirs(temp_dir, exist_ok=True)
                    saved_img = await resp.images[0].save(path=str(temp_dir))

                if saved_img and os.path.exists(saved_img):
                    img = Image.open(saved_img)
                    try:
                        self._save_with_orientation_guard(
                            img, output_path, width, height, quality=95, enforce_orientation=enforce_orientation
                        )
                    finally:
                        try:
                            os.remove(saved_img)
                        except Exception:
                            pass
                    print(f"Generated {label} using Gemini Pro Web Session with {len(req_files or [])} reference(s)!")
                    return output_path
                else:
                    acct_status = getattr(resp, "account_status", "UNKNOWN")
                    reply_hint = (resp.text or "").strip()[:180]
                    if acct_status == "UNAUTHENTICATED" or any(
                        phrase in (resp.text or "").lower()
                        for phrase in ["signed out", "can't create", "cannot generate", "search for images"]
                    ):
                        gemini_error = (
                            "Cookie session is in Guest Mode (UNAUTHENTICATED — Chrome/Brave rotated or invalidated __Secure-1PSIDTS). "
                            "Google Gemini Web blocks Imagen 3 image creation in Guest Mode (only Text AI works in Guest Mode). "
                            "Fix: Copy fresh __Secure-1PSID + __Secure-1PSIDTS from an Incognito window and close that tab immediately so Chrome does not rotate it, "
                            "OR switch the Task Paint Engine to '🌐 Cloud AI Art (Pollinations Flux)'."
                        )
                    else:
                        gemini_error = f"Gemini Web replied without a generated image ({reply_hint or 'no image returned'})."
            except OrientationMismatchError:
                raise
            except Exception as e:
                gemini_error = str(e).strip() or f"{type(e).__name__}: Gemini Web session request failed."

            raise RuntimeError(f"Gemini Web Cookie Image generation failed: {gemini_error}")

        raise RuntimeError(f"Unsupported image generation mode '{image_mode}'.")

    async def generate_character_portrait(
        self,
        name: str,
        description: str,
        output_path: str,
        style_key: str = "ghibli",
        width: int = 720,
        height: int = 960,
        image_mode: str = "gemini",
        reference_image_path: str = None,
        seed: int = None,
        api_key: str = None,
        provider: str = None
    ) -> str:
        """
        Generates a clean, consistent Character Reference Sheet portrait (3:4 vertical) matching
        the project's art style so it can be reused across all Scene Painting and AI Video steps.
        """
        output_path = str(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if image_mode in ("manual", "storyboard_only", "placeholder"):
            self.generate_procedural_fallback(
                title=name or "Character",
                prompt=description or name or "Character Portrait",
                output_path=output_path,
                style_key=style_key,
                scene_idx=0,
                width=width,
                height=height
            )
            return output_path

        clean_name = (name or "Character").strip()
        from backend.agents.script_agent import ScriptAgent
        static_traits, dynamic_traits = ScriptAgent.split_static_dynamic_features(description or "")
        if static_traits and dynamic_traits:
            clean_desc = (
                f"immutable identity ({self.sanitize_visual_prompt(static_traits)}), "
                f"wearing/carrying ({self.sanitize_visual_prompt(dynamic_traits)})"
            )
        else:
            clean_desc = self.sanitize_visual_prompt(static_traits or description or "") or f"expressive character named {clean_name}"
        effective_style = "ghibli" if style_key == "dialogue_cinema" else (style_key or self.default_style or "ghibli")
        style_info = ART_STYLES.get(effective_style, ART_STYLES["ghibli"])
        style_suffix = style_info.get("prompt_suffix", "")

        portrait_prompt = (
            f"Single character design reference sheet portrait of {clean_name}: {clean_desc}. "
            f"Medium three-quarter waist-up pose centered cleanly on a neutral soft studio backdrop, "
            f"clear front-facing / three-quarter face, unmistakable hairstyle, distinctive outfit colors and signature silhouette"
            f"{style_suffix}, clean illustration without text, no typography, no speech bubbles, no watermarks"
        )
        req_files = [reference_image_path] if (reference_image_path and os.path.exists(reference_image_path)) else None
        mm_prompt = (
            f"Using the attached photo/art as visual inspiration, draw a clean character reference portrait: {portrait_prompt}"
            if req_files else
            f"Generate a character reference portrait image: {portrait_prompt}"
        )
        return await self._generate_raw_ai_image(
            full_prompt=portrait_prompt,
            output_path=output_path,
            style_key=effective_style,
            width=width,
            height=height,
            image_mode=image_mode,
            req_files=req_files,
            multimodal_prompt=mm_prompt,
            seed=seed,
            api_key=api_key,
            provider=provider,
            label=f"character portrait '{clean_name}'"
        )

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
        character_references: list = None,
        api_key: str = None,
        provider: str = None,
        camera_on_speaker: bool = False,
        dialogues: list = None,
        narration: str = "",
        dialogue_only: bool = False,
        enable_image_captions: bool = True
    ) -> str:
        """
        Scene visual generation pipeline:
        1. Google Gemini / Imagen 3 (Default — official API key multimodal + Imagen 3, or web session cookie)
        2. Google Flow Bridge / FlowKit (if image_mode is flowkit)
        3. Neural.love AI Art Engine (if image_mode is neural_love)
        4. OpenAI DALL-E 3 (if image_mode or provider is OpenAI)
        5. Storyboard-Only Canvas (if image_mode is manual)
        Actively attaches matched character reference portraits (`character_references`) and prior
        scene continuity frame (`reference_image_path`) to keep characters visually consistent.
        """
        output_path = str(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        comic_mode = is_comic_style(style_key)

        # Remove stale base image before painting a brand-new illustration so `apply_comic_overlay_to_file` backs up the new art
        base_backup_path = self.get_base_image_path(output_path)
        if os.path.exists(base_backup_path):
            try:
                os.remove(base_backup_path)
            except Exception:
                pass

        def _finalize(saved_path: str) -> str:
            if comic_mode and os.path.exists(saved_path):
                self.apply_comic_overlay_to_file(
                    saved_path,
                    dialogues=dialogues,
                    narration=narration,
                    prompt=prompt,
                    title=title,
                    scene_idx=scene_idx,
                    dialogue_only=dialogue_only,
                    enable_image_captions=enable_image_captions
                )
            return saved_path

        # Merge character descriptions from matched character_references into character_desc if needed
        merged_char_desc = (character_desc or "").strip()
        if character_references:
            ref_descs = []
            for r in character_references:
                if isinstance(r, dict) and (r.get("name") or "").strip():
                    rn = r["name"].strip()
                    rd = (r.get("description") or "").strip()
                    if rn.lower() not in merged_char_desc.lower():
                        ref_descs.append(f"{rn}: {rd}" if rd else rn)
            if ref_descs:
                merged_char_desc = (merged_char_desc + " | " + " | ".join(ref_descs)).strip(" |")

        full_prompt = self.craft_full_prompt(
            prompt,
            style_key=style_key,
            character_desc=merged_char_desc,
            camera_on_speaker=camera_on_speaker
        )

        # ============================================================
        # 0. STORYBOARD ONLY / MANUAL MODE (Zero AI Tokens)
        # ============================================================
        if image_mode in ("manual", "storyboard_only", "placeholder"):
            # If no AI paint is used, composite the matched primary character portrait nicely if available
            first_char_path = next(
                (r.get("path") for r in (character_references or []) if isinstance(r, dict) and r.get("path") and os.path.exists(r["path"])),
                None
            )
            if first_char_path:
                try:
                    c_img = Image.open(first_char_path)
                    fitted = self.fit_image_to_aspect_ratio(c_img, width, height)
                    fitted.save(output_path, "JPEG", quality=92)
                    print(f"Scene {scene_idx + 1} visual composed from character portrait (Storyboard-Only mode).")
                    return _finalize(output_path)
                except Exception:
                    pass
            self.generate_procedural_fallback(title=title, prompt=prompt, output_path=output_path, style_key=style_key, scene_idx=scene_idx, width=width, height=height)
            print(f"Scene {scene_idx + 1} visual rendered using Storyboard-Only canvas (zero AI calls).")
            return _finalize(output_path)

        scene_only_prompt = self.craft_full_prompt(
            prompt,
            style_key=style_key,
            character_desc=None,
            camera_on_speaker=camera_on_speaker
        )
        req_files, mm_prompt = self._collect_reference_files_and_instruction(
            full_prompt=full_prompt,
            character_references=character_references,
            reference_image_path=reference_image_path,
            max_refs=6,
            scene_only_prompt=scene_only_prompt,
        )
        await self._generate_raw_ai_image(
            full_prompt=full_prompt,
            output_path=output_path,
            style_key=style_key,
            width=width,
            height=height,
            image_mode=image_mode,
            req_files=req_files,
            multimodal_prompt=mm_prompt,
            seed=seed,
            api_key=api_key,
            provider=provider,
            label=f"scene {scene_idx + 1}"
        )
        return _finalize(output_path)

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

        import hashlib
        _stable = int(hashlib.sha256((title + prompt).encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random((_stable + scene_idx * 1337) & 0xffffffff)

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

    @staticmethod
    def _find_antigravity_cli() -> Optional[str]:
        """Locates the installed Antigravity CLI executable (`agy` / `agy.exe`)."""
        import shutil
        env_path = (os.environ.get("AGY_CLI_PATH") or "").strip()
        if env_path and os.path.exists(env_path):
            return env_path
        found = shutil.which("agy") or shutil.which("agy.exe")
        if found:
            return found
        home = Path.home()
        for cand in [
            home / ".gemini" / "bin" / "agy.exe",
            home / ".gemini" / "bin" / "agy",
            Path(r"C:\Users\Po\.gemini\bin\agy.exe"),
        ]:
            if cand.exists():
                return str(cand)
        return None

    async def _generate_with_antigravity(
        self,
        prompt: str,
        output_path: str,
        width: int = 1280,
        height: int = 720,
        aspect_ratio: str = "16:9",
        req_files: Optional[list] = None,
        enforce_orientation: bool = True,
    ) -> bool:
        """
        Generates an image using the local Antigravity CLI (`agy --print`) and its
        built-in `image-generator` subagent, then fits and saves it to `output_path`.
        """
        import asyncio
        import subprocess
        import time

        agy_bin = self._find_antigravity_cli()
        if not agy_bin:
            raise RuntimeError(
                "Antigravity CLI (agy.exe) not found. Please install Antigravity CLI or set AGY_CLI_PATH."
            )

        clean_prompt = (prompt or "").strip()[:2400]
        ref_lines = ""
        valid_refs = [os.path.abspath(str(p)) for p in (req_files or []) if p and os.path.exists(str(p))]
        if valid_refs:
            ref_lines = (
                "\nReference character/continuity image files (keep character face, hair, and outfit visually consistent with these):\n"
                + "\n".join(f"- {rp}" for rp in valid_refs[:4])
                + "\n"
            )

        cli_prompt = (
            f"Use the image-generator subagent to generate a single high-quality image with aspect ratio {aspect_ratio} "
            f"(target {width}x{height}):\n"
            f"{clean_prompt}\n"
            f"{ref_lines}"
            f"Requirements: clean illustration, strictly NO text, NO watermark. "
            f"Reply with ONLY the absolute saved file path of the generated image."
        )

        started_ts = time.time()
        cmd = [
            agy_bin,
            "--print",
            cli_prompt,
            "--disable-slash-commands",
            "--output-format",
            "text",
            "--print-timeout",
            "150s",
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

        def _run_agy():
            return subprocess.run(
                cmd,
                capture_output=True,
                timeout=165,
                creationflags=creationflags,
            )

        try:
            proc_res = await asyncio.to_thread(_run_agy)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Antigravity CLI image generation timed out after 165s.")
        except Exception as sub_err:
            raise RuntimeError(f"Failed to launch Antigravity CLI ({agy_bin}): {sub_err or repr(sub_err)}") from sub_err

        stdout_txt = (proc_res.stdout or b"").decode("utf-8", errors="ignore").strip()
        stderr_txt = (proc_res.stderr or b"").decode("utf-8", errors="ignore").strip()

        if proc_res.returncode != 0:
            err_msg = (stderr_txt or stdout_txt or f"Exit code {proc_res.returncode}")[:300]
            raise RuntimeError(f"Antigravity CLI exited with error ({proc_res.returncode}): {err_msg}")

        # 1. Extract generated image path from stdout (supports Windows & POSIX paths)
        combined_out = f"{stdout_txt}\n{stderr_txt}"
        candidate_paths = []
        for pattern in [
            r'([A-Za-z]:[\\/][^\r\n"\'\`<>|]+?\.(?:jpg|jpeg|png|webp))',
            r'(/[^\r\n"\'\`<>|\s]+?\.(?:jpg|jpeg|png|webp))',
        ]:
            for m in re.findall(pattern, combined_out, flags=re.IGNORECASE):
                p_clean = m.strip().strip(".,;)")
                if os.path.exists(p_clean) and os.path.abspath(p_clean) not in valid_refs:
                    candidate_paths.append(p_clean)

        chosen_src = candidate_paths[-1] if candidate_paths else None

        # 2. Fallback: scan newest image created in ~/.gemini/antigravity-cli/brain/ since started_ts
        if not chosen_src:
            brain_dir = Path.home() / ".gemini" / "antigravity-cli" / "brain"
            if brain_dir.exists():
                recent = []
                for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                    for f in brain_dir.rglob(ext):
                        try:
                            mt = f.stat().st_mtime
                            if mt >= started_ts - 2.0:
                                recent.append((mt, str(f)))
                        except OSError:
                            pass
                if recent:
                    recent.sort(key=lambda x: x[0], reverse=True)
                    chosen_src = recent[0][1]

        if not chosen_src or not os.path.exists(chosen_src):
            snippet = stdout_txt[:220] if stdout_txt else stderr_txt[:220]
            raise RuntimeError(
                f"Antigravity CLI did not return a saved image path. Output: {snippet or '(empty)'}"
            )

        with Image.open(chosen_src) as pil_img:
            self._save_with_orientation_guard(
                pil_img, output_path, width, height, quality=95, enforce_orientation=enforce_orientation
            )
        return True
