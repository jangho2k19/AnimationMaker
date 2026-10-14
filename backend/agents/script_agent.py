import os
import re
import json
import random
import httpx
from typing import Dict, Any, List

class ScriptAgent:
    def __init__(self, api_key: str = None, provider: str = "gemini", model: str = None):
        self.provider = (provider or "gemini").lower()
        self.api_key = api_key or os.environ.get(f"{self.provider.upper()}_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        self.model = model

    async def generate_storyboard(
        self,
        idea: str,
        num_scenes: int = 4,
        target_duration: int = None,
        art_style: str = "ghibli",
        language: str = "en",
        audience: str = "general",
        title: str = None
    ) -> Dict[str, Any]:
        """
        Brainstorms and structures an animated short film from a user idea.
        Supports:
        - Google Gemini (gemini-2.5-flash, gemini-2.0-flash, gemini-1.5-pro)
        - OpenAI (gpt-4o, gpt-4o-mini, gpt-4-turbo)
        - Anthropic Claude (claude-3-5-sonnet, claude-3-5-haiku, claude-3-opus)
        - DeepSeek (deepseek-chat, deepseek-reasoner)
        - NVIDIA NIM (meta/llama-3.1-70b-instruct, deepseek-r1, etc.)
        - Built-in Genre-Aware Creative Story Architect (offline/zero-key fallback)
        """
        prompt = self._build_story_prompt(idea, num_scenes, target_duration, art_style, language, audience, title=title)

        if self.api_key:
            try:
                is_cookie = (
                    self.provider in ("gemini_cookie", "gemini_web") or
                    ("__Secure-1PSID" in self.api_key) or
                    (self.provider == "gemini" and len(self.api_key) > 70 and not self.api_key.startswith("AIzaSy"))
                )

                if is_cookie:
                    story = await self._generate_with_gemini_cookie(prompt, self.api_key)
                    print("Generated screenplay using Google Gemini Web Session (Cookies)!")
                    return story

                elif self.provider == "gemini":
                    story = self._generate_with_gemini(prompt, self.model or "gemini-2.0-flash")
                    print(f"Generated screenplay using Google Gemini ({self.model or 'gemini-2.0-flash'})!")
                    return story

                elif self.provider == "openai":
                    story = self._generate_with_openai_compatible(
                        endpoint="https://api.openai.com/v1",
                        api_key=self.api_key,
                        model=self.model or "gpt-4o",
                        prompt=prompt
                    )
                    print(f"Generated screenplay using OpenAI ({self.model or 'gpt-4o'})!")
                    return story

                elif self.provider in ("claude", "anthropic"):
                    story = self._generate_with_anthropic(
                        api_key=self.api_key,
                        model=self.model or "claude-3-5-sonnet-20241022",
                        prompt=prompt
                    )
                    print(f"Generated screenplay using Anthropic Claude ({self.model or 'claude-3-5-sonnet'})!")
                    return story

                elif self.provider == "deepseek":
                    story = self._generate_with_openai_compatible(
                        endpoint="https://api.deepseek.com/v1",
                        api_key=self.api_key,
                        model=self.model or "deepseek-chat",
                        prompt=prompt
                    )
                    print(f"Generated screenplay using DeepSeek ({self.model or 'deepseek-chat'})!")
                    return story

                elif self.provider == "nvidia":
                    story = self._generate_with_openai_compatible(
                        endpoint="https://integrate.api.nvidia.com/v1",
                        api_key=self.api_key,
                        model=self.model or "meta/llama-3.1-70b-instruct",
                        prompt=prompt
                    )
                    print(f"Generated screenplay using NVIDIA NIM ({self.model or 'meta/llama-3.1-70b-instruct'})!")
                    return story

            except Exception as e:
                print(f"{self.provider.upper()} LLM notice ({e}), falling back to Genre-Aware Story Architect.")

        return self._generate_with_story_architect(idea, num_scenes, art_style, language, audience)

    def _build_story_prompt(
        self,
        idea: str,
        num_scenes: int,
        target_duration: int = None,
        art_style: str = "ghibli",
        language: str = "en",
        audience: str = "general",
        title: str = None
    ) -> str:
        # For Google Flow / Veo acting videos, each video clip is fixed at 8.0s.
        # Spoken narration MUST be <= 7.2 seconds (strictly 12-16 words, absolute maximum 17 words)
        # to ensure the narration concludes before the video finishes, completely
        # avoiding awkward looping or repeating video content.
        calc_duration = target_duration if (target_duration and target_duration > 0) else (num_scenes * 8)
        target_scene_sec = max(5, int(calc_duration / max(1, num_scenes)))
        target_scene_sec = min(target_scene_sec, 8)  # Google Flow / Veo standard is 8.0s
        max_words = min(17, max(12, int((target_scene_sec - 1.0) * 2.3)))

        title_line = f'Project Title: "{title}" (IMPORTANT: Use this exact title for the film)\n' if title else f'Film Title: Catchy, cinematic, specific to the plot in {language}.\n'

        return f"""You are an award-winning animation director and screenwriter at Pixar, Studio Ghibli, and modern AI video studios.
Create a rich, completely unique, and captivating animated short film storyboard tailored for ACTING VIDEO GENERATION (Google Flow / Google Veo / I2V) based on this premise:
Idea: "{idea}"
{title_line}Target Audience: {audience}
Number of Scenes: Exactly {num_scenes} scenes
Art Style: {art_style}
Language for Narration & Titles: {language}

DIRECTORIAL MANDATE FOR CHARACTER VISUAL CONSISTENCY:
1. CHARACTERS SPECIFICATION:
   - Create a specific, detailed visual design for the main protagonist(s).
   - Specify: Name, age/species, exact hairstyle & color, skin tone & facial features, and EXACT signature outfit with specific colors (e.g., "wearing an oversized golden-yellow hoodie, blue denim jeans, and red sneakers").
   - This exact visual design must remain consistent throughout the entire film.

2. ACTING VIDEO DIRECTIVES & PERFORMANCE CHOREOGRAPHY:
   - For EVERY scene, you must provide:
     a) `visual_prompt`: Ultra-detailed scene illustration prompt describing environment, lighting, art style, and the character's signature visual tokens.
     b) `acting_prompt`: Dynamic 8-second acting performance prompt specifically designed for Google Flow / Veo video generation.
        - Describe physical character performance unfolding across 8 seconds: specific body movements, facial expressions, eye gazes, emotional micro-reactions, gestures, and cinematic camera movement (e.g., "Cinematic medium shot, character looks up in astonishment, gasps with parted lips, slowly reaches a trembling hand forward toward the glowing orb as camera smoothly tracks in").
     c) Textless Artwork: Visual & acting descriptions ONLY. Absolutely NO dialogue, quotes, speech bubbles, letters, or subtitles in the prompt.

3. MANDATORY VOICEOVER DURATION CONSTRAINT (EQUAL OR SHORTER THAN 8-SECOND VIDEO):
   - CRITICAL REQUIREMENT: Google Flow / Veo acting video clips have a fixed length of 8.0 seconds.
   - The spoken voiceover narration for EACH scene MUST take no more than 5.0 to 7.2 seconds to speak (STRICTLY MAXIMUM {max_words} WORDS PER SCENE).
   - Under NO circumstances should narration exceed {max_words} words! Longer narrations will force the 8-second video to repeat or loop its content, which is strictly prohibited.
   - Narration must be punchy, rhythmic, emotionally evocative, and concise so it concludes naturally before the 8-second video clip ends.

Requirements:
- Film Title: {"Use '" + title + "'" if title else "Catchy, cinematic, specific to the plot in " + language}.
- Logline: 1 compelling sentence.
- Characters: Visual traits and signature appearance for strict character consistency across all scenes.
- Scenes: Exactly {num_scenes} scenes following a dramatic narrative arc (Beginning -> Rising Tension -> Climax -> Resolution).
  - Each scene MUST have:
    - scene_number (int, from 1 to {num_scenes})
    - title (creative scene title in {language})
    - visual_prompt (setting, lighting, character consistency tokens, 16:9 cinematic framing)
    - acting_prompt (dynamic 8s character acting, physical performance, facial micro-expressions, camera motion)
    - narration (paced for <= 7.2s, STRICTLY 12 to {max_words} words of evocative voiceover narration in {language})
    - camera_motion (choose one: "zoom_in", "zoom_out", "pan_left", "pan_right", "subtle_drift")

Return ONLY valid JSON matching this exact structure:
{{
  "title": "Title",
  "logline": "Logline",
  "characters": "Protagonist: [Name], [Age/Gender], [Hair & Eyes], [Signature Outfit & Colors], [Key visual features]",
  "scenes": [
    {{
      "scene_number": 1,
      "title": "Scene 1 Title",
      "visual_prompt": "...",
      "acting_prompt": "...",
      "narration": "...",
      "camera_motion": "zoom_in"
    }}
  ]
}}
Do NOT wrap the output in markdown code blocks. Return raw JSON only."""

    def _clean_json_response(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        match_fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match_fence:
            candidate = match_fence.group(1).strip()
        else:
            outer_match = re.search(r"(\{[\s\S]*\})", cleaned)
            candidate = outer_match.group(1).strip() if outer_match else cleaned
        return json.loads(candidate)

    @staticmethod
    def parse_imported_storyboard(text: str) -> Dict[str, Any]:
        """
        Robustly parses imported storyboard content in JSON or formatted text from Gemini Pro / ChatGPT / Claude.
        Supports:
        - Raw JSON: {"title": ..., "scenes": [...]}
        - Markdown fenced JSON: ```json ... ```
        - Text with embedded JSON anywhere inside
        - Formatted text screenplay (Title: ..., Scene 1: Visual: ..., Narration: ...)
        """
        cleaned_text = text.strip()

        # 1. Try extracting JSON block
        json_fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_text, re.IGNORECASE)
        candidate_json_str = json_fence_match.group(1).strip() if json_fence_match else None

        if not candidate_json_str:
            outer_match = re.search(r"(\{[\s\S]*\})", cleaned_text)
            if outer_match:
                candidate_json_str = outer_match.group(1).strip()

        if candidate_json_str:
            try:
                parsed = json.loads(candidate_json_str)
                if isinstance(parsed, dict) and "scenes" in parsed and isinstance(parsed["scenes"], list):
                    normalized_scenes = []
                    for idx, sc in enumerate(parsed["scenes"]):
                        if not isinstance(sc, dict):
                            continue
                        normalized_scenes.append({
                            "scene_number": sc.get("scene_number", idx + 1),
                            "title": sc.get("title", f"Scene {idx + 1}"),
                            "visual_prompt": sc.get("visual_prompt") or sc.get("visual") or sc.get("prompt") or sc.get("description", ""),
                            "acting_prompt": sc.get("acting_prompt") or sc.get("acting") or sc.get("motion_prompt") or sc.get("visual_prompt", ""),
                            "narration": sc.get("narration") or sc.get("voiceover") or sc.get("script") or sc.get("text", ""),
                            "camera_motion": sc.get("camera_motion", "zoom_in")
                        })
                    if normalized_scenes:
                        return {
                            "title": parsed.get("title", "Imported Film"),
                            "logline": parsed.get("logline", ""),
                            "characters": parsed.get("characters", ""),
                            "scenes": normalized_scenes
                        }
            except Exception as e:
                print(f"JSON parsing notice ({e}), attempting text-based heuristic parsing...")

        # 2. Heuristic text parser (if user pasted plain text screenplay)
        scene_blocks = re.split(r"(?:^|\n)(?:Scene|Cảnh|Phân cảnh)\s*(\d+)[:\s\-]*", cleaned_text, flags=re.IGNORECASE)

        if len(scene_blocks) > 2:
            title_match = re.search(r"(?:Title|Tiêu đề|Tên phim)[:\s]*(.+)", scene_blocks[0], re.IGNORECASE)
            logline_match = re.search(r"(?:Logline|Tóm tắt)[:\s]*(.+)", scene_blocks[0], re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else "Imported Film"
            logline = logline_match.group(1).strip() if logline_match else ""

            scenes = []
            for i in range(1, len(scene_blocks), 2):
                sc_num = int(scene_blocks[i]) if scene_blocks[i].isdigit() else len(scenes) + 1
                sc_body = scene_blocks[i+1].strip()

                vis_match = re.search(r"(?:Visual|Hình ảnh|Miêu tả)[:\s]*(.+?)(?=(?:Acting|Hành động|Diễn xuất|Narration|Lời thoại|Thuyết minh|$))", sc_body, re.IGNORECASE | re.DOTALL)
                act_match = re.search(r"(?:Acting|Hành động|Diễn xuất)[:\s]*(.+?)(?=(?:Narration|Lời thoại|Thuyết minh|$))", sc_body, re.IGNORECASE | re.DOTALL)
                narr_match = re.search(r"(?:Narration|Lời thoại|Thuyết minh)[:\s]*(.+)", sc_body, re.IGNORECASE | re.DOTALL)

                visual = vis_match.group(1).strip() if vis_match else sc_body[:200]
                acting = act_match.group(1).strip() if act_match else visual
                narration = narr_match.group(1).strip() if narr_match else sc_body

                scenes.append({
                    "scene_number": sc_num,
                    "title": f"Scene {sc_num}",
                    "visual_prompt": visual,
                    "acting_prompt": acting,
                    "narration": narration,
                    "camera_motion": "zoom_in"
                })

            if scenes:
                return {
                    "title": title,
                    "logline": logline,
                    "characters": "",
                    "scenes": scenes
                }

        return {"title": "Imported Story", "logline": "", "scenes": []}

    @staticmethod
    def _extract_gemini_cookies(cookie_input: str) -> tuple:
        s = (cookie_input or "").strip()
        psid, psidts = None, None
        if s.startswith("{"):
            try:
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
                lines = [line.strip() for line in s.splitlines() if line.strip()]
                psid = lines[0]
                if len(lines) > 1:
                    psidts = lines[1]
            elif s:
                psid = s

        # Auto-pair missing token from persistent server-side credentials
        try:
            from backend.config import get_server_credentials, save_server_credentials
            creds = get_server_credentials()
            if not psid:
                psid = creds.get("gemini_cookie_psid")
            if not psidts:
                psidts = creds.get("gemini_cookie_psidts")
            # If both are valid, ensure they remain saved
            if psid and psidts:
                save_server_credentials({
                    "gemini_cookie_psid": psid,
                    "gemini_cookie_psidts": psidts
                })
        except Exception:
            pass

        return psid, psidts

    async def _generate_with_gemini_cookie(self, prompt: str, cookie_input: str) -> Dict[str, Any]:
        from backend.services.gemini_wrapper import GeminiWebWrapper
        wrapper = GeminiWebWrapper.get_instance()
        res = await wrapper.generate_content(
            prompt=prompt,
            model=self.model,
            cookie_override=cookie_input,
            extended_thinking=True
        )
        return self._clean_json_response(res.text)

    def _generate_with_gemini(self, prompt: str, model: str = "gemini-2.0-flash") -> Dict[str, Any]:
        from google import genai
        client = genai.Client(api_key=self.api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt
        )
        return self._clean_json_response(response.text)

    def _generate_with_openai_compatible(self, endpoint: str, api_key: str, model: str, prompt: str) -> Dict[str, Any]:
        url = f"{endpoint.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an award-winning animation director at Pixar and Studio Ghibli. Return ONLY valid JSON."
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return self._clean_json_response(content)

    def _generate_with_anthropic(self, api_key: str, model: str, prompt: str) -> Dict[str, Any]:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": model,
            "max_tokens": 4096,
            "system": "You are an award-winning animation director at Pixar and Studio Ghibli. Return ONLY valid JSON.",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["content"][0]["text"]
            return self._clean_json_response(content)

    def _detect_genre(self, text: str) -> str:
        """Detect the thematic genre of the story idea to tailor the narrative arc."""
        lower = text.lower()
        if any(w in lower for w in ["cyberpunk", "detective", "robot", "neon", "hologram", "city", "future", "tech", "cyborg"]):
            return "cyberpunk"
        elif any(w in lower for w in ["tam cam", "tấm cám", "cổ tích", "vua", "hoàng tử", "công chúa", "fairy tale", "fable", "folklore"]):
            return "folklore"
        elif any(w in lower for w in ["space", "star", "planet", "saturn", "galaxy", "astronaut", "universe", "vũ trụ"]):
            return "space"
        elif any(w in lower for w in ["dragon", "magic", "wizard", "spell", "witch", "castle", "sword", "rồng", "phép thuật"]):
            return "fantasy"
        elif any(w in lower for w in ["cat", "dog", "kitten", "puppy", "animal", "forest", "rabbit", "thỏ", "sóc", "chim"]):
            return "nature_animals"
        return "adventure"

    def _generate_with_story_architect(
        self,
        idea: str,
        num_scenes: int,
        art_style: str,
        language: str,
        audience: str
    ) -> Dict[str, Any]:
        """
        Genre-Aware Creative Story Architect: Generates unique, non-generic,
        tailored screenplays and narrative beats tailored to the story topic.
        """
        clean_idea_raw = idea.strip()
        genre = self._detect_genre(clean_idea_raw)
        is_vi = language.startswith("vi")

        # Strip quotes, dialogue, and multi-line paragraphs to extract a concise subject
        no_dialogue = re.sub(r'["“][^"”]*["”]', '', clean_idea_raw)
        no_dialogue = re.sub(r"['‘][^'’]*['’]", '', no_dialogue)
        first_line = no_dialogue.strip().splitlines()[0] if no_dialogue.strip() else clean_idea_raw
        first_sentence = re.split(r'[.!?\n]', first_line)[0].strip()
        words = [w for w in first_sentence.split() if w]
        clean_idea = " ".join(words[:6]) if words else "the story"
        short_title = " ".join([w.capitalize() for w in words[:4]]) if words else "Animation Story" 

        # Genre narrative templates with distinct story beats
        genre_beats = {
            "cyberpunk": {
                "title_en": f"{short_title}: Shadows of Neon",
                "title_vi": f"{short_title}: Ký Ức Thành Phố Ánh Sáng",
                "logline_en": f"Through rainy neon alleyways and digital echoes, an unexpected mystery unravels in {clean_idea}.",
                "logline_vi": f"Giữa những con hẻm rực ánh đèn neon và tiếng mưa rơi, một bí mật công nghệ bất ngờ được khám phá.",
                "beats": [
                    {
                        "title_en": "Neon Shadows & Digital Rain",
                        "title_vi": "Bóng Đêm Neon & Cơn Mưa Kỹ Thuật Số",
                        "prompt": f"Moody cyberpunk detective scene featuring {clean_idea}, towering holographic neon skyscrapers, rain-drenched pavement reflecting cyan and magenta lights, atmospheric volumetric fog, cinematic framing",
                        "narration_en": f"Beneath the flickering neon billboards of the sprawling metropolis, the investigation begins. Rain slicks the pavement as holographic echoes whisper long-forgotten secrets.",
                        "narration_vi": f"Dưới những biển quảng cáo neon rực rỡ của thành phố tương lai, cuộc điều tra bắt đầu. Cơn mưa đêm phản chiếu ánh đèn rực rỡ, che giấu những bí mật chìm sâu trong dòng dữ liệu.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "Deciphering The Glitch",
                        "title_vi": "Giải Mã Mảnh Vỡ Ký Ức",
                        "prompt": f"High-tech investigation scene in {clean_idea}, glowing blue holographic data streams, cybernetic interface, dark futuristic laboratory room, intense concentration, cinematic depth",
                        "narration_en": f"Every clue pulses with electric urgency. A hidden fragment in the network reveals a trail of forgotten memories that the city attempted to erase.",
                        "narration_vi": f"Từng manh mối ánh lên nhịp đập điện tử dồn dập. Một mảnh dữ liệu ẩn giấu dần hé lộ sự thật mà thành phố này đã cố gắng chôn vùi suốt nhiều năm qua.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "The Rooftop Confrontation",
                        "title_vi": "Đối Đầu Trên Đỉnh Tòa Tháp",
                        "prompt": f"Dramatic climactic confrontation on a futuristic skyscraper rooftop, {clean_idea}, intense lighting, crackling energy discharge, dark stormy clouds above towering skyline",
                        "narration_en": f"High above the clouds atop a towering spire, the truth is finally confronted. Sparks ignite the night air as the final piece of the digital puzzle locks into place.",
                        "narration_vi": f"Trên đỉnh tòa tháp chọc trời mờ mịt gió mưa, khoảnh khắc quyết định đã đến. Ánh sáng năng lượng bùng nổ khi bức tranh sự thật cuối cùng được ghép lại trọn vẹn.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "Dawn Over The Cyber City",
                        "title_vi": "Bình Minh Trên Đô Thị Mới",
                        "prompt": f"Breathtaking dawn rising over a futuristic metropolis, {clean_idea}, warm sunrise light piercing through neon fog, peaceful cinematic wide final shot",
                        "narration_en": f"As the first rays of morning sunlight pierce the neon haze, clarity returns to the city. The memory is saved, and a new legend takes flight.",
                        "narration_vi": f"Khi những tia nắng ban mai đầu tiên xuyên qua làn sương neon, sự yên bình trở lại với đô thị. Ký ức đã được giải thoát, mở ra hy vọng cho một ngày mai tươi sáng.",
                        "motion": "zoom_out"
                    }
                ]
            },
            "folklore": {
                "title_en": f"The Legend of {short_title}",
                "title_vi": f"Huyền Thoại {short_title}",
                "logline_en": f"An ancient folklore tale of resilience, virtue, and miraculous justice exploring {clean_idea}.",
                "logline_vi": f"Câu chuyện cổ tích cảm động về lòng hiếu thảo, sự kiên cường và điều kỳ diệu trong cuộc sống.",
                "beats": [
                    {
                        "title_en": "The Quiet Village Hearth",
                        "title_vi": "Mái Nhà Tranh & Lòng Chăm Chỉ",
                        "prompt": f"Peaceful ancient Vietnamese village setting featuring {clean_idea}, rustic thatched roofs, bamboo grove, warm morning sunlight, serene countryside landscape",
                        "narration_en": f"In a peaceful village bordered by green bamboo groves, our story unfolds with {clean_idea}. Through hardship and silence, a gentle spirit remained pure.",
                        "narration_vi": f"Bên rặng tre xanh rì rào của làng quê thanh bình, câu chuyện bắt đầu với {clean_idea}. Dù gặp muôn vàn gian nan, tấm lòng hiền hậu vẫn luôn ngát hương thơm.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "The Gentle Miracle",
                        "title_vi": "Phép Màu Bụt Ban",
                        "prompt": f"Mystical fairy tale scene featuring {clean_idea}, glowing golden lotus or magical bird, sparkling divine starlight, lush tropical trees, gentle aura",
                        "narration_en": f"When sorrow seemed heaviest, a miraculous presence appeared. From a simple blessing, extraordinary magic began to blossom.",
                        "narration_vi": f"Khi nỗi buồn tưởng chừng sâu nặng nhất, một phép màu dịu hiền đã xuất hiện. Từng giọt hy vọng biến thành những điều kỳ diệu sưởi ấm tâm hồn.",
                        "motion": "subtle_drift"
                    },
                    {
                        "title_en": "The Royal Festival & Triumph",
                        "title_vi": "Ngày Hội & Niềm Vui Trở Về",
                        "prompt": f"Grand ancient royal palace courtyard, festive lanterns, colorful silk banners, joyful celebration of {clean_idea}, radiant golden lighting",
                        "narration_en": f"Truth could not remain hidden in shadows. Before the royal court and the cheering crowd, virtue triumphed over all deception.",
                        "narration_vi": f"Sự thật và lòng nhân ái không bao giờ bị khuất phục. Giữa ngày hội tưng bừng, người hiền đã nhận được hạnh phúc xứng đáng mà trời ban tặng.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "Everlasting Harmony",
                        "title_vi": "Khúc Ca Hạnh Phúc",
                        "prompt": f"Harmonious ending scene of {clean_idea}, blooming golden marigolds, golden hour sunlight, royal happiness and peace, warm fairy tale ending",
                        "narration_en": f"Kindness had weathered every storm. Across the kingdom, songs of justice and everlasting joy echoed through the ages.",
                        "narration_vi": f"Lòng nhân hậu đã vượt qua mọi sóng gió. Khắp đất trời rộn vang tiếng cười hạnh phúc, để lại bài học ý nghĩa lưu truyền mãi ngàn sau.",
                        "motion": "zoom_out"
                    }
                ]
            },
            "space": {
                "title_en": f"{short_title}: Starlight Odyssey",
                "title_vi": f"{short_title}: Hành Trình Các Vì Sao",
                "logline_en": f"A breathtaking cosmic voyage exploring the mysteries of the universe in {clean_idea}.",
                "logline_vi": f"Cuộc phiêu lưu kỳ vĩ xuyên qua các dải ngân hà lấp lánh ánh sao.",
                "beats": [
                    {
                        "title_en": "Launch Towards The Stars",
                        "title_vi": "Khởi Hành Vào Vũ Trụ",
                        "prompt": f"Cosmic establishing shot of {clean_idea}, retro-futuristic cockpit overlooking a sea of glittering nebulae, purple and cyan starlight, awe-inspiring scale",
                        "narration_en": f"Drifting beyond the edge of gravity, the great cosmic expedition begins. Distant stars twinkle like diamonds against the velvet night.",
                        "narration_vi": f"Rời khỏi lực hút của mặt đất, chuyến hải trình giữa các vì sao chính thức bắt đầu. Từng tinh vân lấp lánh như những dải lụa phát sáng giữa màn đêm vô tận.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "Navigating The Celestial Rings",
                        "title_vi": "Xuyên Qua Vành Đai Thiên Thạch",
                        "prompt": f"Dynamic space flight of {clean_idea}, gliding over glowing icy rings of a giant planet, sparkling cosmic dust particles, vibrant aurora reflections",
                        "narration_en": f"Gliding gracefully through shimmering asteroid rings, every turn reveals wonders no mortal eyes have ever witnessed.",
                        "narration_vi": f"Lướt nhẹ qua những vành đai băng lấp lánh của hành tinh khổng lồ, mỗi chuyển động mở ra một kỳ quan tráng lệ chưa từng được biết đến.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "The Heart of The Supernova",
                        "title_vi": "Trái Tim Của Tinh Cầu Kỳ Diệu",
                        "prompt": f"Magnificent celestial discovery scene featuring {clean_idea}, radiant glowing core of light, colorful cosmic waves, dramatic starlight illumination",
                        "narration_en": f"At the center of the deep expanse, a magnificent celestial core awakens, showering the cosmos with ancient brilliant light.",
                        "narration_vi": f"Tại trung tâm của dải ngân hà, một nguồn năng lượng kỳ diệu bừng sáng, tỏa ra những luồng ánh sáng ấm áp nuôi dưỡng muôn vì sao.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "Safe Harbor in Orbit",
                        "title_vi": "Bến Đỗ Bình Yên",
                        "prompt": f"Peaceful closing space scene, {clean_idea} peacefully floating against a glowing blue crescent planet, warm tranquil starlight",
                        "narration_en": f"With stardust in its wake and a heart full of wonder, our traveler rests in the quiet embrace of the universe.",
                        "narration_vi": f"Mang theo bụi sao lấp lánh và những ký ức tuyệt diệu, người du hành nhẹ nhàng dừng chân trong vòng tay êm dịu của vũ trụ bao la.",
                        "motion": "zoom_out"
                    }
                ]
            },
            "nature_animals": {
                "title_en": f"The Adventures of {short_title}",
                "title_vi": f"Chuyện Về {short_title}",
                "logline_en": f"A delightful, heartwarming adventure through nature and friendship in {clean_idea}.",
                "logline_vi": f"Một câu chuyện ấm áp về tình bạn và những điều kỳ thú của thế giới tự nhiên.",
                "beats": [
                    {
                        "title_en": "Morning in The Sunlit Glade",
                        "title_vi": "Buổi Sáng Trong Khu Rừng Nắng Ấm",
                        "prompt": f"Charming storybook forest scene featuring {clean_idea}, golden morning sunbeams filtering through lush canopy, dewdrops on wild strawberries, cute stylized aesthetic",
                        "narration_en": f"As dawn paints the forest in warm amber light, an adventurous soul wakes up ready to discover the world.",
                        "narration_vi": f"Khi ánh bình minh rọi những vạt nắng vàng óng ả qua kẽ lá, một ngày mới tràn ngập niềm vui và sự háo hức bắt đầu.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "A Playful Mishap",
                        "title_vi": "Thử Thách Bất Ngờ",
                        "prompt": f"Playful animated forest scene with {clean_idea}, tumbling across a mossy brook, funny expressive reaction, colorful butterflies fluttering around",
                        "narration_en": f"Curiosity leads down uncharted paths! A playful tumble brings an unexpected surprise by the gurgling brook.",
                        "narration_vi": f"Tính tò mò dẫn lối qua con suối róc rách. Dù gặp một chút vấp váp nhỏ, nụ cười vẫn nở rộ giữa bầy bướm rực rỡ sắc màu.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "The Power of Teamwork",
                        "title_vi": "Sức Mạnh Của Tình Bạn",
                        "prompt": f"Heartwarming animal collaboration scene with {clean_idea}, forest friends helping each other reach a golden glowing prize, joy and unity",
                        "narration_en": f"When a challenge seems too tall to conquer alone, good friends join hands. Together, nothing is impossible.",
                        "narration_vi": f"Khi thử thách dường như quá lớn, những người bạn tốt đã cùng nhau kề vai sát cánh. Sự sẻ chia biến mọi khó khăn thành niềm vui.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "Sunset Celebration",
                        "title_vi": "Lửa Trại & Khúc Ca Hoàng Hôn",
                        "prompt": f"Cozy evening forest clearing, {clean_idea} resting with friends under fireflies and lantern glow, warm heartfelt ending",
                        "narration_en": f"Under the gentle glow of dancing fireflies, the friends celebrate their triumph, grateful for each other's warmth.",
                        "narration_vi": f"Dưới ánh đom đóm lập lòe của buổi chiều tà, bữa tiệc vui khép lại trong sự ấm áp và tình bạn bền chặt mãi mãi.",
                        "motion": "zoom_out"
                    }
                ]
            },
            "adventure": {
                "title_en": f"The Quest of {short_title}",
                "title_vi": f"Hành Trình Diệu Kỳ Của {short_title}",
                "logline_en": f"An imaginative cinematic quest exploring {clean_idea} with bravery and spirit.",
                "logline_vi": f"Cuộc hành trình phiêu lưu kỳ thú tràn đầy lòng dũng cảm và niềm hy vọng.",
                "beats": [
                    {
                        "title_en": "The Call To Adventure",
                        "title_vi": "Lời Kêu Gọi Phiêu Lưu",
                        "prompt": f"Epic establishing shot of {clean_idea}, heroic pose looking out towards distant misty peaks, golden atmospheric rays, cinematic depth",
                        "narration_en": f"The wind carries a whisper of distant horizons. With courage in every breath, the great adventure begins.",
                        "narration_vi": f"Cơn gió mang theo lời mời gọi từ những chân trời xa xôi. Với lòng dũng cảm và niềm tin, chuyến phiêu lưu chính thức bắt đầu.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "Crossing The Frontier",
                        "title_vi": "Vượt Qua Vùng Đất Thử Thách",
                        "prompt": f"Adventurous journey scene featuring {clean_idea}, traversing a canyon bridge or ancient ruins, dramatic lighting, sweeping dynamic angle",
                        "narration_en": f"Across steep valleys and forgotten trails, every step tests resolve and awakens hidden strength.",
                        "narration_vi": f"Băng qua những thung lũng hiểm trở và di tích cổ xưa, mỗi bước đi là một bài học tôi luyện lòng kiên định.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "The Revelation",
                        "title_vi": "Khoảnh Khắc Giác Ngộ",
                        "prompt": f"Dramatic discovery scene of {clean_idea}, uncovering a glowing magical artifact or breathtaking vista, burst of celestial light, epic scale",
                        "narration_en": f"At the heart of the journey, the true secret is revealed: greatness was never about the destination, but the spirit forged along the way.",
                        "narration_vi": f"Giữa đỉnh cao của hành trình, bí mật lớn nhất đã bừng sáng: sức mạnh diệu kỳ nhất chính là niềm tin và trái tim kiên cường.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "The Hero's Return",
                        "title_vi": "Vinh Quang & Bình Yên",
                        "prompt": f"Tranquil triumphant ending scene with {clean_idea}, warm golden sunset, peaceful horizon, cinematic final masterpiece frame",
                        "narration_en": f"Standing tall against the setting sun, our hero smiles at the journey completed and the peaceful dawn that lies ahead.",
                        "narration_vi": f"Đứng trước ánh hoàng hôn rực rỡ, người anh hùng mỉm cười thanh thản, đón chào một tương lai tươi sáng và bình yên.",
                        "motion": "zoom_out"
                    }
                ]
            }
        }

        genre_pack = genre_beats.get(genre, genre_beats["adventure"])
        title = genre_pack["title_vi"] if is_vi else genre_pack["title_en"]
        logline = genre_pack["logline_vi"] if is_vi else genre_pack["logline_en"]
        beats_pool = genre_pack["beats"]

        genre_characters = {
            "cyberpunk": {
                "en": f"Protagonist: Cyra, agile 24-year-old cyberpunk detective with bright neon-cyan undercut hair, glowing cybernetic eye implant, wearing an oversized dark charcoal trench coat with glowing cyan trim, dark tactical pants, and silver boots.",
                "vi": f"Nhân vật chính: Cyra, nữ thám tử cyberpunk 24 tuổi với mái tóc undercut xanh neon, mắt công nghệ phát sáng, khoác áo măng-tô đen viền cyan dạ quang, quần chiến thuật và giày bạc."
            },
            "folklore": {
                "en": f"Protagonist: Tam, a graceful 18-year-old village maiden with long silky jet-black hair tied with a soft pink lotus ribbon, kind almond eyes, wearing an indigo-blue traditional Ao Ba Ba with white trim and wooden clogs.",
                "vi": f"Nhân vật chính: Tấm, thiếu nữ 18 tuổi dịu hiền với mái tóc đen mượt buộc dải lụa sen hồng, đôi mắt bồ câu đôn hậu, mặc áo bà ba chàm mộc mạc và guốc mộc."
            },
            "space": {
                "en": f"Protagonist: Captain Orion, 28-year-old astronaut with short auburn hair, hazel eyes, wearing a sleek white-and-orange pressurized exploration spacesuit with a glowing chest telemetry beacon.",
                "vi": f"Nhân vật chính: Cơ trưởng Orion, phi hành gia 28 tuổi với mái tóc nâu đỏ ngắn, mặc bộ đồ du hành vũ trụ màu trắng phối cam hiện đại với đèn định vị ngực phát sáng."
            },
            "nature_animals": {
                "en": f"Protagonist: Pip, an adorable stylized golden-furred red panda kitten with oversized fluffy striped tail, emerald-green eyes, wearing a tiny leaf-green explorer satchel and carved acorn necklace.",
                "vi": f"Nhân vật chính: Pip, chú gấu trúc đỏ lông vàng cam đáng yêu với chiếc đuôi bông sọc to tròn, đôi mắt xanh ngọc bích lấp lánh, đeo túi thám hiểm lá xanh tí hon."
            },
            "adventure": {
                "en": f"Protagonist: Kael, 16-year-old spirited explorer with tousled chestnut hair, amber eyes, wearing a rugged beige linen adventurer tunic, brown leather belt with brass compass, and worn traveler boots.",
                "vi": f"Nhân vật chính: Kael, nhà thám hiểm 16 tuổi với mái tóc hạt dẻ bồng bềnh, mắt hổ phách, mặc áo vải lanh màu be, thắt lưng da nâu gắn la bàn đồng."
            }
        }
        chosen_char = genre_characters.get(genre, genre_characters["adventure"])["vi" if is_vi else "en"]

        scenes = []
        for i in range(num_scenes):
            beat = beats_pool[i % len(beats_pool)]
            scene_title = beat["title_vi"] if is_vi else beat["title_en"]
            narration = beat["narration_vi"] if is_vi else beat["narration_en"]

            scenes.append({
                "scene_number": i + 1,
                "title": scene_title,
                "visual_prompt": f"{beat['prompt']}, character consistency: {chosen_char}",
                "acting_prompt": f"Cinematic acting performance of {chosen_char}, {beat['prompt']}, fluid natural character motion, expressive gestures, emotional reaction, cinematic 8-second continuous shot",
                "narration": narration,
                "camera_motion": beat.get("motion", "zoom_in")
            })

        return {
            "title": title,
            "logline": logline,
            "characters": chosen_char,
            "scenes": scenes
        }
