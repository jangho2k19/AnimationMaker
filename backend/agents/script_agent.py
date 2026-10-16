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

        # Automatically check server-side stored credentials if api_key was not passed
        if not self.api_key:
            try:
                from backend.config import get_server_credentials
                creds = get_server_credentials()
                psid = creds.get("gemini_cookie_psid")
                psidts = creds.get("gemini_cookie_psidts")
                if psid and self.provider in ("gemini", "gemini_cookie", "gemini_web"):
                    self.api_key = f"{psid}|{psidts}" if psidts else psid
                    self.provider = "gemini_cookie"
                elif creds.get("gemini_api_key") and self.provider == "gemini":
                    self.api_key = creds.get("gemini_api_key")
                elif creds.get("openai_api_key") and self.provider == "openai":
                    self.api_key = creds.get("openai_api_key")
                elif creds.get("claude_api_key") and self.provider in ("claude", "anthropic"):
                    self.api_key = creds.get("claude_api_key")
                elif creds.get("deepseek_api_key") and self.provider == "deepseek":
                    self.api_key = creds.get("deepseek_api_key")
                elif creds.get("nvidia_api_key") and self.provider == "nvidia":
                    self.api_key = creds.get("nvidia_api_key")
                elif psid and not self.api_key:
                    self.api_key = f"{psid}|{psidts}" if psidts else psid
                    self.provider = "gemini_cookie"
            except Exception:
                pass

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
        - Google Gemini Web Session (Cookies / Pro)
        - OpenAI (gpt-4o, gpt-4o-mini, gpt-4-turbo)
        - Anthropic Claude (claude-3-5-sonnet, claude-3-5-haiku, claude-3-opus)
        - DeepSeek (deepseek-chat, deepseek-reasoner)
        - NVIDIA NIM (meta/llama-3.1-70b-instruct, deepseek-r1, etc.)
        - Built-in Genre-Aware Creative Story Architect (offline/zero-key manual mode only)
        """
        # 1. If user supplied an existing multi-scene screenplay/script, parse it directly
        # so their original story, characters, and scenes are 100% preserved.
        imported = self.parse_imported_storyboard(idea)
        if imported and imported.get("scenes") and len(imported["scenes"]) >= 2:
            print(f"🎬 Detected pre-existing screenplay with {len(imported['scenes'])} scenes in user idea! Importing directly...")
            if title and (not imported.get("title") or imported.get("title") == "Imported Film"):
                imported["title"] = title
            return imported

        # 2. Only use offline Story Architect if explicitly requested
        if self.provider in ("builtin", "offline", "architect"):
            print("🏛️ Using offline built-in Story Architect as explicitly configured.")
            return self._generate_with_story_architect(idea, num_scenes, art_style, language, audience)

        prompt = self._build_story_prompt(idea, num_scenes, target_duration, art_style, language, audience, title=title)

        # 3. Check for API key / session cookies
        if not self.api_key:
            # Last-ditch check in server credentials
            try:
                from backend.config import get_server_credentials
                creds = get_server_credentials()
                psid = creds.get("gemini_cookie_psid")
                psidts = creds.get("gemini_cookie_psidts")
                if psid and self.provider in ("gemini", "gemini_cookie", "gemini_web"):
                    self.api_key = f"{psid}|{psidts}" if psidts else psid
                    self.provider = "gemini_cookie"
            except Exception:
                pass

        if not self.api_key:
            raise RuntimeError(
                f"AI Storyboard Error: No API Key or Gemini Cookie found for provider '{self.provider}'. "
                "Please configure your Gemini Cookie or API key in Settings ⚙️ to generate the storyboard with AI."
            )

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

            else:
                raise RuntimeError(f"Unsupported AI provider '{self.provider}'.")

        except Exception as e:
            err_msg = str(e)
            print(f"❌ {self.provider.upper()} AI Storyboard Error: {err_msg}")
            # If cookie error, give actionable guidance
            if "cookie" in self.provider or "__Secure-1PSID" in (self.api_key or ""):
                raise RuntimeError(
                    f"AI Storyboard generation failed ({self.provider.upper()}): {err_msg}. "
                    "Google Gemini session cookies may be expired. Please update __Secure-1PSID and __Secure-1PSIDTS in Settings ⚙️."
                )
            raise RuntimeError(
                f"AI Storyboard generation failed ({self.provider.upper()}): {err_msg}. "
                "Please check your API key, model selection, or network connection."
            )

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

        clean_idea_strip = idea.strip()
        word_count = len(clean_idea_strip.split())
        is_narrative = (
            word_count > 45 or
            "\n\n" in clean_idea_strip or
            any(marker in clean_idea_strip.lower() for marker in [
                "once upon", "in times gone by", "there was a", "long ago",
                "ngày xửa ngày xưa", "thời xa xưa", "câu chuyện", "tại một vương quốc",
                "the king", "the prince", "the princess", "the golden"
            ])
        )

        adaptation_mandate = ""
        if is_narrative:
            adaptation_mandate = f"""
STORY ADAPTATION & FIDELITY MANDATE (ABSOLUTE HIGHEST PRIORITY):
The user provided a COMPLETE, SPECIFIC STORY / FAIRY TALE / NARRATIVE below.
Your role as director is FAITHFUL ADAPTATION of this EXACT story into a {num_scenes}-scene animated short film.

CRITICAL DIRECTORIAL RULES:
1. STRICT PLOT ACCURACY & ZERO CONTRADICTIONS:
   - Adhere strictly to the actual plot, true sequence of events, and canonical characters provided in the story.
   - Do NOT invent an unrelated story or fabricate bizarre plot twists that contradict the source material.
2. PRESERVE ALL CENTRAL CREATURES, MAGICAL ARTIFACTS & TITULAR ENTITIES:
   - Identify the primary entities and titular figures in the story (e.g., if the story centers on a Golden Bird stealing golden apples and dropping a golden feather when shot by an arrow, the Golden Bird MUST appear in Scene 1 at the apple tree!).
   - ABSOLUTE PROHIBITION ON CONFUSING OR SWAPPING CHARACTERS:
     * Never replace one creature with another (e.g., DO NOT replace the Golden Bird with the Fox under the apple tree! The Fox is met later on the road as an ally).
     * DO NOT omit titular or central entities (the Golden Bird must be prominently present in the scenes where it belongs: the midnight theft, the cage quest, the recovery, and the triumphant return!).
3. COMPREHENSIVE NARRATIVE PACING ACROSS {num_scenes} SCENES:
   Distribute the dramatic arc chronologically from the actual beginning to the actual ending:
   - Scene 1: The Inciting Incident & Central Mystery/Wonder (The original starting dilemma, titular creature/wonder, quest initiation).
   - Middle Scenes: The Quest, Allies & Trials (Encountering the faithful guide/Fox, journeying to the foreign castle, the challenge of the cages/horses, securing the treasures and companion).
   - Climax / Crisis: The Turning Point / Treachery / Conflict (Ambush by jealous brothers at the brook, theft of the prizes, betrayal).
   - Final Scene: The Triumphant Return & Resolution (Returning in disguise, the magical creatures/bird singing in recognition, exposure of villains, celebration, and freeing the faithful helper from the curse).
4. CHARACTERS SPECIFICATION:
   - In the "characters" field, describe ALL key figures from the story: the protagonist, key secondary characters, and CRITICALLY any central mythical creatures or animals (e.g., "Prince Eric: 18yo male with messy light brown hair, wearing a forest-green royal tunic with rolled sleeves and worn leather belt. The Golden Bird: radiant mythical bird with feathers glittering like molten gold and brilliant glowing crest. The Faithful Fox: sleek oversized red fox with white-tipped tail and intelligent amber eyes").
"""
        else:
            adaptation_mandate = f"""
STORY FIDELITY DIRECTIVE:
- Develop an engaging animated short film directly rooted in the user's concept.
- If the idea mentions specific characters, animals, or creatures (e.g., a golden bird, a dragon, a fox), ensure all of them are faithfully featured in the character specification and scene visual prompts.
- Never conflate or mix up distinct characters or creatures.
"""

        title_line = f'Project Title: "{title}" (IMPORTANT: Use this exact title for the film)\n' if title else f'Film Title: Catchy, cinematic, specific to the plot in {language}.\n'

        return f"""You are an award-winning animation director and screenwriter at Pixar, Studio Ghibli, and modern AI video studios.
Create an animated short film storyboard tailored for ACTING VIDEO GENERATION (Google Flow / Google Veo 3 / I2V) faithfully representing the provided story:
Story Input:
\"\"\"
{idea}
\"\"\"
{title_line}Target Audience: {audience}
Number of Scenes: Exactly {num_scenes} scenes
Art Style: {art_style}
Language for Narration & Titles: {language}
{adaptation_mandate}

DIRECTORIAL MANDATE FOR CHARACTER VISUAL CONSISTENCY:
1. CHARACTERS SPECIFICATION:
   - Create a specific, detailed visual design for the main protagonist(s), key secondary characters / companions / antagonists, AND ANY CENTRAL MYTHICAL CREATURE OR ANIMAL (e.g., "Prince Eric: 18yo male with sharp jawline, messy light brown hair, wearing forest-green royal tunic with rolled sleeves and worn leather belt. The Golden Bird: radiant mythical bird with feathers glittering like pure molten gold, glowing golden eyes, and an elegant crest. The Faithful Fox: sleek oversized red fox with intelligent amber eyes and distinctive white-tipped tail").
   - These exact visual design tokens must remain consistent throughout the entire film.

2. ACTING VIDEO DIRECTIVES & PERFORMANCE CHOREOGRAPHY (GOOGLE FLOW & VEO 3):
   - For EVERY scene, you must provide:
     a) `visual_prompt`: Ultra-detailed scene illustration prompt describing environment, lighting, art style, framing, and the character's signature visual tokens.
     b) `acting_prompt`: Exhaustive 8-second acting performance prompt formatted specifically for Google Flow / Veo video generation.
        CRITICAL RULES FOR `acting_prompt`:
        - 3-BEAT TEMPORAL PACING (MANDATORY): Structure every 8-second clip into sequential physical beats:
          `0-3s: [Initial physical action, movement, gesture, or establishing character state]`
          `3-6s: [Core physical activity, interaction with props/objects, or spoken dialogue/conflict]`
          `6-8s: [Emotional reaction, physiological response, resolution, and camera settle]`
          `Camera: [Cinematic camera movement]. Lighting: [Atmospheric lighting]. Negative: subtitles, watermark, text overlay.`
        - CHARACTER ACTIVITIES & PHYSICAL ACTIONS:
          Direct concrete, observable physical tasks: examining clues, welding or hammering, climbing, handing over props, drawing weapons, bandaging wounds, turning dials, or fleeing pursuit. Describe physical symptoms of emotion (bead of sweat, pupils dilating, chest heaving, tight jaw).
        - CHARACTER COMMUNICATION & SPOKEN DIALOGUE (MANDATORY in at least 2 scenes):
          Characters MUST communicate, converse, or argue! In dialogue scenes (Two-Shot, Over-The-Shoulder, or Speaking/Reaction), embed their spoken words directly inside the clip using this exact syntax:
          `[Character Name] says: "[Short dialogue line]" (no subtitles) — [tone of voice]`
          (If language is Vietnamese, use: `(không phụ đề) — [giọng nói]`)
          * Dialogue length: STRICTLY 5 to 12 words per character per 8s clip for realistic, crisp lip-sync.
          * Always include the `(no subtitles)` suffix to prevent AI from burning distorted text onto video frames.
        - CINEMATIC SCENE ARCHETYPE VARIETY:
          Blend diverse archetypes across the {num_scenes} scenes:
          - Establishing Shot (world scale, geography, atmospheric lighting, zero or distant character)
          - Action Beat (physical labor, athletic motion, combat, mechanics, escape)
          - Dialogue Two-Shot (two characters in frame, exchanging dialogue, tension, decision)
          - Reaction Focus (close-up on listener's internal shift while dialogue or shock is absorbed)
          - Climax / Resolution (climactic action and poignant closing)
     c) Separation of Narration and In-Scene Dialogue:
        - `narration` field: Voiceover narration spoken by the narrator (TTS). Provides macroscopic lore, emotional depth, and stakes. STRICTLY <= 7.2 seconds ({max_words} words max).
        - `acting_prompt` field: Contains the visual acting, physical performance, and microscopic character dialogue (`Character says: "..."`).

3. MANDATORY VOICEOVER DURATION CONSTRAINT (EQUAL OR SHORTER THAN 8-SECOND VIDEO):
   - CRITICAL REQUIREMENT: Google Flow / Veo acting video clips have a fixed length of 8.0 seconds.
   - The spoken voiceover narration for EACH scene MUST take no more than 5.0 to 7.2 seconds to speak (STRICTLY MAXIMUM {max_words} WORDS PER SCENE).
   - Under NO circumstances should narration exceed {max_words} words! Longer narrations will force the 8-second video to repeat or loop its content, which is strictly prohibited.
   - Narration must be punchy, rhythmic, emotionally evocative, and concise so it concludes naturally before the 8-second video clip ends.

Requirements:
- Film Title: {"Use '" + title + "'" if title else "Catchy, cinematic, specific to the plot in " + language}.
- Logline: 1 compelling sentence.
- Characters: Visual traits and signature appearance for strict character consistency across all scenes, including any titular or mythical beasts.
- Scenes: Exactly {num_scenes} scenes following a dramatic narrative arc (Beginning -> Rising Tension -> Climax -> Resolution).
  - Each scene MUST have:
    - scene_number (int, from 1 to {num_scenes})
    - title (creative scene title in {language})
    - archetype (e.g., "Establishing Shot", "Action Beat", "Dialogue Two-Shot", "Reaction Focus", "Climax")
    - visual_prompt (setting, lighting, character consistency tokens, 16:9 cinematic framing)
    - acting_prompt (3-beat temporal action breakdown: 0-3s, 3-6s, 6-8s with character activities, physical performance, and spoken dialogue if applicable)
    - narration (paced for <= 7.2s, STRICTLY 12 to {max_words} words of evocative voiceover narration in {language})
    - camera_motion (choose one: "zoom_in", "zoom_out", "pan_left", "pan_right", "subtle_drift")

Return ONLY valid JSON matching this exact structure:
{{
  "title": "Title",
  "logline": "Logline",
  "characters": "Protagonist: [Name & Role, Visual description] | Key Creature / Secondary: [Name & Visual description]",
  "scenes": [
    {{
      "scene_number": 1,
      "title": "Scene 1 Title",
      "archetype": "Action Beat",
      "visual_prompt": "...",
      "acting_prompt": "0-3s: ... 3-6s: ... 6-8s: ... Camera: ... Lighting: ... Negative: subtitles, watermark, text overlay.",
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
                        acting = (
                            sc.get("acting_prompt") or
                            sc.get("video_prompt") or
                            sc.get("acting") or
                            sc.get("motion_prompt") or
                            sc.get("visual_prompt", "")
                        )
                        normalized_scenes.append({
                            "scene_number": sc.get("scene_number", idx + 1),
                            "title": sc.get("title", f"Scene {idx + 1}"),
                            "archetype": sc.get("archetype", "Cinematic Scene"),
                            "visual_prompt": sc.get("visual_prompt") or sc.get("visual") or sc.get("prompt") or sc.get("description", ""),
                            "acting_prompt": acting,
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
            quote_title = re.search(r'["“]([^"”\n]+)["”]', scene_blocks[0])
            title = None
            if title_match:
                title = title_match.group(1).strip()
            elif quote_title:
                title = quote_title.group(1).strip()
            else:
                lines = [l.strip() for l in scene_blocks[0].splitlines() if l.strip() and not any(w in l.lower() for w in ["kịch bản", "script", "thể loại", "thời lượng"])]
                if lines:
                    title = lines[0]
            title = title or "Imported Film"

            # Extract message or logline
            msg_match = re.search(r'(?:Thông điệp|Message|Logline|Tóm tắt)[:\s]*(.+)', scene_blocks[0], re.IGNORECASE)
            logline_match = re.search(r"(?:Logline|Tóm tắt)[:\s]*(.+)", scene_blocks[0], re.IGNORECASE)
            logline = msg_match.group(1).strip() if msg_match else (logline_match.group(1).strip() if logline_match else "")

            # Extract characters specification
            char_match = re.search(r'(?:Nhân vật|Characters)[:\s]*\n([\s\S]*?)(?=(?:Mở đầu|CẢNH|Scene|Phân cảnh|Bối cảnh|Thông điệp|$))', scene_blocks[0], re.IGNORECASE)
            characters = ""
            if char_match:
                raw_c = char_match.group(1).strip()
                c_lines = [l.strip() for l in raw_c.splitlines() if l.strip()]
                characters = " | ".join(c_lines[:4])

            scenes = []
            for i in range(1, len(scene_blocks), 2):
                sc_num = int(scene_blocks[i]) if scene_blocks[i].isdigit() else len(scenes) + 1
                sc_body = scene_blocks[i+1].strip()

                lines = [l.strip() for l in sc_body.splitlines() if l.strip()]
                first_line = lines[0] if lines else ""
                clean_title = re.sub(r'^[–\-—:\s]+', '', first_line).strip()
                clean_title = re.sub(r'^(?:NGOẠI|NỘI|EXT|INT)[\.\s]*', '', clean_title, flags=re.IGNORECASE).strip()
                sc_title = clean_title if clean_title and len(clean_title) < 60 else f"Scene {sc_num}"

                body_without_title = "\n".join(lines[1:]) if len(lines) > 1 else sc_body
                vis_match = re.search(r'(?:Visual|Hình ảnh|Miêu tả)[:\s]*(.+?)(?=(?:Âm thanh|Audio|Lời thoại|Dialogue|\n[A-ZÀ-Ỹ\s]{3,}\s*(?:\([^\)]*\))?|\n\n[A-ZÀ-Ỹ]|$))', body_without_title, re.IGNORECASE | re.DOTALL)
                visual = vis_match.group(1).strip() if vis_match else body_without_title[:250]
                visual = re.sub(r'\s+', ' ', visual)

                # Look for dialogues: CHARACTER NAME (tone) \n "line"
                dials = re.findall(r'(?:^|\n)([A-ZÀ-Ỹ]{2,}(?:\s+[A-ZÀ-Ỹ]+)*)\s*(?:\(([^\)]*)\))?\n([^\n]+)', sc_body)
                dial_str = ""
                if dials:
                    spk, tone, line = dials[0]
                    clean_spk = spk.strip().title()
                    clean_tone = f" — {tone.strip()}" if tone else ""
                    dial_str = f'{clean_spk} nói: "{line.strip()}" (không phụ đề){clean_tone}'

                arch_match = re.search(r"(?:Archetype|Thể loại cảnh)[:\s]*(.+?)(?=(?:Visual|Acting|Narration|$))", sc_body, re.IGNORECASE | re.DOTALL)
                if arch_match:
                    archetype = arch_match.group(1).strip()
                elif dial_str:
                    archetype = "Dialogue Scene"
                elif i == 1:
                    archetype = "Establishing Shot"
                else:
                    archetype = "Action Beat"

                acting = (
                    f"0-3s: {visual[:130]}. "
                    f"3-6s: {dial_str if dial_str else 'Diễn xuất và chuyển động tự nhiên của nhân vật trong bối cảnh.'} "
                    f"6-8s: Cảm xúc chuyển biến tự nhiên, ánh mắt kết nối nhịp nhàng sang cảnh tiếp theo. "
                    f"Camera: zoom_in. Lighting: ánh sáng điện ảnh ấm áp. Negative: subtitles, watermark, text overlay."
                )

                # Narration: extract voiceover or summarize visual
                narr_match = re.search(r'(?:Narration|Thuyết minh|Lời dẫn)[:\s]*(.+)', sc_body, re.IGNORECASE | re.DOTALL)
                if narr_match:
                    narration = narr_match.group(1).strip()
                else:
                    sentences = re.split(r'[.!?\n]', visual)
                    narration = sentences[0].strip() if sentences and sentences[0].strip() else visual[:80]
                    if len(narration.split()) > 18:
                        narration = " ".join(narration.split()[:16]) + "..."

                scenes.append({
                    "scene_number": sc_num,
                    "title": sc_title,
                    "archetype": archetype,
                    "visual_prompt": visual,
                    "acting_prompt": acting,
                    "narration": narration,
                    "camera_motion": "zoom_in"
                })

            if scenes:
                return {
                    "title": title,
                    "logline": logline,
                    "characters": characters,
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
            extended_thinking=False
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
        elif any(w in lower for w in [
            "tam cam", "tấm cám", "cổ tích", "vua", "hoàng tử", "công chúa", 
            "fairy tale", "fable", "folklore", "đồng lúa", "làng quê", "cánh đồng", 
            "nông thôn", "cào cào", "ruộng", "bác nông dân", "con trâu", "cây đa"
        ]):
            return "folklore"
        elif any(w in lower for w in ["space", "star", "planet", "saturn", "galaxy", "astronaut", "universe", "vũ trụ"]):
            return "space"
        elif any(w in lower for w in ["dragon", "magic", "wizard", "spell", "witch", "castle", "sword", "rồng", "phép thuật"]):
            return "fantasy"
        elif any(w in lower for w in ["cat", "dog", "kitten", "puppy", "animal", "forest", "rabbit", "thỏ", "sóc", "chim"]):
            return "nature_animals"
        return "adventure"

    def _adapt_narrative_to_storyboard(
        self,
        raw_text: str,
        sentences: List[str],
        num_scenes: int,
        art_style: str,
        language: str,
        audience: str,
        title: str
    ) -> Dict[str, Any]:
        """
        Dynamically extracts and adapts scenes from a user's rich narrative or fairy tale text.
        Guarantees that the storyboard faithfully reflects the user's actual plot and entities.
        """
        is_vi = language.startswith("vi")
        total_s = len(sentences)
        chunk_size = max(1, total_s / float(num_scenes))

        lower_all = raw_text.lower()
        characters_list = []

        if any(w in lower_all for w in ["youngest son", "prince", "king's son", "hoàng tử", "chàng trai"]):
            characters_list.append("The Young Prince: 18yo courageous youth with messy light brown hair, forest-green royal tunic, worn brown leather belt, and sturdy traveling boots")
        elif any(w in lower_all for w in ["girl", "cô gái", "young woman", "nàng"]):
            characters_list.append("The Heroine: youthful courageous female with gentle eyes, flowing hair, and simple linen garments")
        else:
            characters_list.append("Protagonist: determined youthful character with expressive eyes and signature traveler attire")

        if any(w in lower_all for w in ["golden bird", "chim vàng", "bird", "con chim"]):
            characters_list.append("The Golden Bird: radiant mythical bird with feathers glittering like pure molten gold, brilliant golden eyes, and a luminous crest")

        if any(w in lower_all for w in ["fox", "cáo", "con cáo"]):
            characters_list.append("The Faithful Fox: sleek oversized red fox with intelligent amber eyes, mystical wisdom, and distinctive white-tipped tail")

        if any(w in lower_all for w in ["princess", "công chúa"]):
            characters_list.append("Princess: 19yo noble maiden with flowing golden hair, radiant gentle gaze, and sky-blue silk gown")

        if any(w in lower_all for w in ["golden horse", "ngựa vàng", "horse", "con ngựa"]):
            characters_list.append("The Golden Horse: magnificent steed with shimmering golden coat and flowing mane")

        char_string = " | ".join(characters_list[:4])

        scenes = []
        archetypes = ["Establishing Shot", "Action Beat", "Dialogue Two-Shot", "Reaction Focus", "Climax", "Resolution"]

        for idx in range(num_scenes):
            start_i = int(idx * chunk_size)
            end_i = int((idx + 1) * chunk_size) if idx < num_scenes - 1 else total_s
            chunk_sentences = sentences[start_i:end_i]
            if not chunk_sentences:
                chunk_sentences = sentences[-1:] if sentences else [raw_text[:100]]

            chunk_text = " ".join(chunk_sentences)
            arch = archetypes[min(idx, len(archetypes) - 1)]

            clean_words = [w for w in chunk_sentences[0].split() if w]
            narr_raw = " ".join(clean_words[:15]) if clean_words else "The adventure continues through ancient lands."
            if not narr_raw.endswith((".", "!", "?")):
                narr_raw += "."

            if idx == 0:
                sc_title = "The Golden Apple Garden" if "apple" in lower_all else "The Journey Begins"
            elif idx == num_scenes - 1:
                sc_title = "The Triumphant Return" if not is_vi else "Sự Trở Về Vinh Quang"
            elif idx == 1:
                sc_title = "The Fox's Guidance" if "fox" in lower_all else "Crossing The Trials"
            else:
                sc_title = f"The Turn of Fortune" if not is_vi else f"Bước Ngoặt Định Mệnh"

            vis_snippet = chunk_text[:200].replace('"', '')
            vis_prompt = f"{art_style.capitalize()} art style. {vis_snippet}. Cinematic composition, warm atmospheric lighting, high fidelity details."

            acting_prompt = (
                f"0-3s: Character moves with focused intention into the scene. "
                f"3-6s: Key dramatic interaction with the environment and allies. "
                f"6-8s: Emotional shift and resolute focus into the next moment. "
                f"Camera: slow cinematic motion. Lighting: atmospheric cinematic rays. Negative: subtitles, watermark, text overlay."
            )

            motions = ["zoom_in", "pan_right", "subtle_drift", "zoom_out", "pan_left"]
            scenes.append({
                "scene_number": idx + 1,
                "title": sc_title,
                "archetype": arch,
                "visual_prompt": vis_prompt,
                "acting_prompt": acting_prompt,
                "narration": narr_raw,
                "camera_motion": motions[idx % len(motions)]
            })

        return {
            "title": title or "The Golden Bird",
            "logline": "An epic journey of virtue, magical companions, and triumphant destiny.",
            "characters": char_string,
            "scenes": scenes
        }

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

        # 1. Extract quoted title or user-defined title
        quote_title = re.search(r'["“]([^"”\n]+)["”]', clean_idea_raw)
        extracted_title = quote_title.group(1).strip() if quote_title else None

        # Check if user provided a rich story or multi-sentence narrative
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', clean_idea_raw) if len(s.strip()) > 15]
        if len(sentences) >= 3 or len(clean_idea_raw.split()) > 45:
            first_sentence = re.split(r'[.!?\n]', clean_idea_raw)[0].strip()
            w_words = [w for w in first_sentence.split() if w]
            fallback_title = " ".join([w.capitalize() for w in w_words[:4]]) if w_words else "The Golden Bird"
            return self._adapt_narrative_to_storyboard(
                raw_text=clean_idea_raw,
                sentences=sentences,
                num_scenes=num_scenes,
                art_style=art_style,
                language=language,
                audience=audience,
                title=extracted_title or fallback_title
            )

        # 2. Extract character roster from input if specified
        char_match = re.search(r'(?:Nhân vật|Characters)[:\s]*\n([\s\S]*?)(?=(?:Mở đầu|CẢNH|Scene|Phân cảnh|Bối cảnh|Thông điệp|$))', clean_idea_raw, re.IGNORECASE)
        custom_char = ""
        if char_match:
            raw_c = char_match.group(1).strip()
            c_lines = [l.strip() for l in raw_c.splitlines() if l.strip()]
            custom_char = " | ".join(c_lines[:3])

        # 3. Clean topic / subject without generic script boilerplates
        lines = [
            l.strip() for l in clean_idea_raw.splitlines()
            if l.strip() and not any(meta in l.lower() for meta in ["kịch bản", "script", "thể loại", "thời lượng", "bối cảnh", "thông điệp"])
        ]
        if extracted_title:
            short_title = extracted_title
            clean_idea = extracted_title
        elif lines:
            first_sentence = re.split(r'[.!?\n]', lines[0])[0].strip()
            words = [w for w in first_sentence.split() if w]
            short_title = " ".join([w.capitalize() for w in words[:4]]) if words else "Animation Story"
            clean_idea = " ".join(words[:6]) if words else "the story"
        else:
            short_title = "Animation Story"
            clean_idea = "the story"

        # Genre narrative templates with distinct story beats, 3-beat acting choreography, and character communication
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
                        "archetype": "Establishing Shot",
                        "prompt": f"Moody cyberpunk detective scene featuring {clean_idea}, towering holographic neon skyscrapers, rain-drenched pavement reflecting cyan and magenta lights, atmospheric volumetric fog, cinematic framing",
                        "acting_en": f"0-3s: Aerial camera descends over rain-slicked pavement as Cyra steps out under a flickering neon billboard. 3-6s: She pulls up her high trench collar against the rain, tapping her glowing holo-lens. 6-8s: Her glowing cyan eye implant flares as she detects an anomalous digital signature. Camera: slow crane-down. Lighting: neon cyan and magenta reflections on wet asphalt. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Máy quay từ trên cao hạ dần xuống góc phố neon ướt mưa khi Cyra bước qua biển quảng cáo chập chờn. 3-6s: Cô kéo cao cổ áo dạ quang che mưa, tay chạm vào kính điện tử quét dữ liệu. 6-8s: Mắt công nghệ phát sáng xanh khi phát hiện tín hiệu bất thường. Camera: hạ góc mượt mà. Ánh sáng: phản chiếu ánh neon xanh hồng trên mặt đường ướt. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Beneath the flickering neon billboards of the sprawling metropolis, the investigation begins. Rain slicks the pavement as holographic echoes whisper long-forgotten secrets.",
                        "narration_vi": f"Dưới những biển quảng cáo neon rực rỡ của thành phố tương lai, cuộc điều tra bắt đầu. Cơn mưa đêm phản chiếu ánh đèn rực rỡ, che giấu những bí mật chìm sâu trong dòng dữ liệu.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "Deciphering The Glitch",
                        "title_vi": "Giải Mã Mảnh Vỡ Ký Ức",
                        "archetype": "Dialogue Two-Shot",
                        "prompt": f"High-tech investigation scene in {clean_idea}, glowing blue holographic data streams, cybernetic interface, dark futuristic laboratory room, intense concentration, cinematic depth",
                        "acting_en": f"0-3s: Medium two-shot inside dim server bunker. Cyra leans over the glowing blue terminal across from her informant. 3-6s: Cyra points at the corrupted data core. Cyra says: \"This code was erased from inside the network.\" (no subtitles) — low urgent whisper. 6-8s: The informant widens his eyes in shock and nods slowly. Camera: intimate push-in. Lighting: cold blue holographic glow in shadows. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Trung cảnh hai nhân vật trong phòng máy chủ tối. Cyra ghé sát màn hình dữ liệu xanh đối diện người cung cấp tin. 3-6s: Cyra chỉ vào khối mã nguồn bị hỏng. Cyra nói: \"Mã này bị xóa từ bên trong mạng lưới.\" (không phụ đề) — giọng thì thầm khẩn trương. 6-8s: Người đối diện kinh ngạc mở to mắt rồi khẽ gật đầu. Camera: đẩy cận chậm. Ánh sáng: ánh sáng xanh holographic chập chờn. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Every clue pulses with electric urgency. A hidden fragment in the network reveals a trail of forgotten memories that the city attempted to erase.",
                        "narration_vi": f"Từng manh mối ánh lên nhịp đập điện tử dồn dập. Một mảnh dữ liệu ẩn giấu dần hé lộ sự thật mà thành phố này đã cố gắng chôn vùi suốt nhiều năm qua.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "The Rooftop Confrontation",
                        "title_vi": "Đối Đầu Trên Đỉnh Tòa Tháp",
                        "archetype": "Action Beat",
                        "prompt": f"Dramatic climactic confrontation on a futuristic skyscraper rooftop, {clean_idea}, intense lighting, crackling energy discharge, dark stormy clouds above towering skyline",
                        "acting_en": f"0-3s: Low tracking shot along wind-swept metal grates as Cyra sprints through heavy rain. 3-6s: She slides across wet steel, draws an EMP scrambler, and locks onto the rooftop antenna. 6-8s: Brilliant electrical discharge arcs through the air, illuminating her determined face as the signal shatters. Camera: dynamic lateral track. Lighting: strobing electrical sparks against storm clouds. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Góc quay thấp bám theo bước chạy gấp gáp của Cyra trên sàn kim loại lộng gió giữa cơn mưa tầm tã. 3-6s: Cô trượt người trên sàn ướt, rút súng xung điện khóa mục tiêu trạm phát sóng. 6-8s: Luồng điện chớp sáng rực rỡ xé tan màn đêm, soi rõ ánh mắt kiên cường. Camera: lia bám theo hành động. Ánh sáng: tia lửa điện chớp sáng giữa mây dông. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"High above the clouds atop a towering spire, the truth is finally confronted. Sparks ignite the night air as the final piece of the digital puzzle locks into place.",
                        "narration_vi": f"Trên đỉnh tòa tháp chọc trời mờ mịt gió mưa, khoảnh khắc quyết định đã đến. Ánh sáng năng lượng bùng nổ khi bức tranh sự thật cuối cùng được ghép lại trọn vẹn.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "Dawn Over The Cyber City",
                        "title_vi": "Bình Minh Trên Đô Thị Mới",
                        "archetype": "Resolution",
                        "prompt": f"Breathtaking dawn rising over a futuristic metropolis, {clean_idea}, warm sunrise light piercing through neon fog, peaceful cinematic wide final shot",
                        "acting_en": f"0-3s: Wide shot on the rain-clearing helipad as Cyra rests against the railing. 3-6s: Golden sunlight breaks through the neon haze. She lowers her collar, exhales softly, and looks toward the horizon. Cyra says: \"The city is finally awake.\" (no subtitles) — calm resolute tone. 6-8s: Camera pulls back into wide panoramic skyline. Camera: majestic crane pull-back. Lighting: warm golden morning sun mixed with fading neon. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Toàn cảnh sân thượng khi cơn mưa vừa tạnh, Cyra đứng tựa lan can nhìn ra xa. 3-6s: Nắng sớm xuyên qua sương neon. Cô hạ cổ áo, thở phào nhẹ nhõm và ngắm nhìn chân trời. Cyra nói: \"Thành phố cuối cùng đã thức giấc.\" (không phụ đề) — giọng điềm tĩnh, nhẹ nhõm. 6-8s: Máy quay lùi xa mở ra toàn cảnh thành phố rạng rỡ. Camera: lùi cao toàn cảnh. Ánh sáng: ánh bình minh vàng ấm áp. Negative: subtitles, watermark, text overlay.",
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
                        "archetype": "Action Beat",
                        "prompt": f"Peaceful ancient Vietnamese village setting featuring {clean_idea}, rustic thatched roofs, bamboo grove, warm morning sunlight, serene countryside landscape",
                        "acting_en": f"0-3s: Medium shot of Tam carrying a woven bamboo basket by the village pond, morning mist curling over the water. 3-6s: She gently scatters grains to fish, hands moving with practiced care. Tam says: \"Eat well, little ones, tomorrow will be better.\" (no subtitles) — gentle affectionate voice. 6-8s: She pauses, gazing warmly at the golden ripples. Camera: slow tracking push-in. Lighting: soft golden sunrise through green bamboo. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Trung cảnh Tấm bưng thúng tre bên bờ ao làng, sương mai lượn lờ trên mặt nước. 3-6s: Nàng nhẹ nhàng vốc từng nắm thóc thả xuống ao. Tấm nói: \"Các em ăn ngoan, ngày mai trời lại sáng.\" (không phụ đề) — giọng dịu dàng trìu mến. 6-8s: Nàng mỉm cười hiền từ nhìn đàn cá bơi lội. Camera: tiến lại gần chậm rãi. Ánh sáng: nắng sớm xuyên qua rặng tre xanh. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"In a peaceful village bordered by green bamboo groves, our story unfolds with {clean_idea}. Through hardship and silence, a gentle spirit remained pure.",
                        "narration_vi": f"Bên rặng tre xanh rì rào của làng quê thanh bình, câu chuyện bắt đầu với {clean_idea}. Dù gặp muôn vàn gian nan, tấm lòng hiền hậu vẫn luôn ngát hương thơm.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "The Gentle Miracle",
                        "title_vi": "Phép Màu Bụt Ban",
                        "archetype": "Dialogue Two-Shot",
                        "prompt": f"Mystical fairy tale scene featuring {clean_idea}, glowing golden lotus or magical bird, sparkling divine starlight, lush tropical trees, gentle aura",
                        "acting_en": f"0-3s: Close-up on Tam wiping a tear from her cheek under a weeping willow. 3-6s: A celestial glowing presence descends, radiating soft warmth. The benevolent elder speaks with kindness. Elder says: \"Good heart, wipe your tears; justice is near.\" (no subtitles) — deep soothing voice. 6-8s: Tam gasps in awe, hands folding over her heart with glowing hope. Camera: smooth tilt-up to celestial light. Lighting: magical volumetric golden sparkles. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Cận cảnh Tấm khẽ gạt giọt nước mắt dưới bóng liễu rủ. 3-6s: Một vầng hào quang ấm áp bất ngờ tỏa sáng. Ông Bụt hiện ra hiền từ cất tiếng. Bụt nói: \"Con gái ngoan, đừng khóc nữa, phúc lành đã đến.\" (không phụ đề) — giọng ấm áp từ bi. 6-8s: Tấm ngỡ ngàng chắp tay trước ngực, đôi mắt ánh lên niềm hy vọng. Camera: lia ngước lên vầng sáng diệu kỳ. Ánh sáng: bụi sao vàng lung linh huyền ảo. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"When sorrow seemed heaviest, a miraculous presence appeared. From a simple blessing, extraordinary magic began to blossom.",
                        "narration_vi": f"Khi nỗi buồn tưởng chừng sâu nặng nhất, một phép màu dịu hiền đã xuất hiện. Từng giọt hy vọng biến thành những điều kỳ diệu sưởi ấm tâm hồn.",
                        "motion": "subtle_drift"
                    },
                    {
                        "title_en": "The Royal Festival & Triumph",
                        "title_vi": "Ngày Hội & Niềm Vui Trở Về",
                        "archetype": "Action Beat",
                        "prompt": f"Grand ancient royal palace courtyard, festive lanterns, colorful silk banners, joyful celebration of {clean_idea}, radiant golden lighting",
                        "acting_en": f"0-3s: Medium tracking shot through a vibrant royal pavilion crowded with festive banners. 3-6s: Tam steps forward in exquisite embroidered silk robes, fitting the lost golden shoe onto her foot with perfect grace. 6-8s: The young King beams with immense joy and steps forward to welcome her. Camera: fluid arc motion. Lighting: bright festive lantern glow and royal gold. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Máy quay bám theo nhịp bước qua sảnh cung điện tưng bừng cờ hoa. 3-6s: Tấm thanh tú trong bộ áo lụa gấm thêu hoa, nhẹ nhàng xỏ chân vào chiếc hài thêu vừa như in. 6-8s: Nhà vua trẻ mừng rỡ bước tới đỡ lấy tay nàng trong tiếng reo vui của muôn người. Camera: quay vòng cung nhịp nhàng. Ánh sáng: rực rỡ đèn lồng hoàng gia. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Truth could not remain hidden in shadows. Before the royal court and the cheering crowd, virtue triumphed over all deception.",
                        "narration_vi": f"Sự thật và lòng nhân ái không bao giờ bị khuất phục. Giữa ngày hội tưng bừng, người hiền đã nhận được hạnh phúc xứng đáng mà trời ban tặng.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "Everlasting Harmony",
                        "title_vi": "Khúc Ca Hạnh Phúc",
                        "archetype": "Resolution",
                        "prompt": f"Harmonious ending scene of {clean_idea}, blooming golden marigolds, golden hour sunlight, royal happiness and peace, warm fairy tale ending",
                        "acting_en": f"0-3s: Wide static shot of the tranquil palace garden blooming with fragrant lotus flowers. 3-6s: Tam and the King stand side by side under a flowering apricot tree, smiling serenely. Tam says: \"Peace has returned to our kingdom.\" (no subtitles) — sweet heartfelt delivery. 6-8s: Camera pulls back gently as white doves take flight into the sunset. Camera: slow cinematic pull-back. Lighting: warm golden hour twilight. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Toàn cảnh hoa sen khoe sắc rực rỡ trong ngự uyển thanh bình. 3-6s: Tấm cùng nhà vua sánh bước dưới tán mai vàng, mỉm cười rạng rỡ. Tấm nói: \"Đất nước ta nay đã thanh bình.\" (không phụ đề) — giọng trong trẻo xúc động. 6-8s: Máy quay lùi xa khi đàn bồ câu trắng tung cánh bay vút lên bầu trời hoàng hôn. Camera: lùi xa êm đềm. Ánh sáng: ráng chiều vàng óng ả. Negative: subtitles, watermark, text overlay.",
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
                        "archetype": "Establishing Shot",
                        "prompt": f"Cosmic establishing shot of {clean_idea}, retro-futuristic cockpit overlooking a sea of glittering nebulae, purple and cyan starlight, awe-inspiring scale",
                        "acting_en": f"0-3s: Cockpit interior looking past Captain Orion's shoulder out toward a swirling magenta nebula. 3-6s: Orion flips heavy mechanical switches on the console, checking telemetry monitors. Orion says: \"All engines nominal. Engaging warp drive.\" (no subtitles) — steady confident baritone. 6-8s: The starfield outside stretches into brilliant hyper-light streaks. Camera: smooth push-in to windshield. Lighting: pulsing dashboard instruments and starlight glow. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Góc nhìn từ khoang lái qua vai Cơ trưởng Orion hướng về tinh vân ánh tím huyền ảo. 3-6s: Orion bật dãy công tắc cơ khí trên bàn điều khiển, kiểm tra thông số. Orion nói: \"Động cơ đã sẵn sàng. Kích hoạt bước nhảy không gian.\" (không phụ đề) — giọng trầm ấm tự tin. 6-8s: Muôn vì sao ngoài cửa sổ kéo dài thành những vệt sáng lộng lẫy. Camera: tiến chậm về kính lái. Ánh sáng: bảng điện tử phát quang phản chiếu mũ bảo hiểm. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Drifting beyond the edge of gravity, the great cosmic expedition begins. Distant stars twinkle like diamonds against the velvet night.",
                        "narration_vi": f"Rời khỏi lực hút của mặt đất, chuyến hải trình giữa các vì sao chính thức bắt đầu. Từng tinh vân lấp lánh như những dải lụa phát sáng giữa màn đêm vô tận.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "Navigating The Celestial Rings",
                        "title_vi": "Xuyên Qua Vành Đai Thiên Thạch",
                        "archetype": "Action Beat",
                        "prompt": f"Dynamic space flight of {clean_idea}, gliding over glowing icy rings of a giant planet, sparkling cosmic dust particles, vibrant aurora reflections",
                        "acting_en": f"0-3s: Medium shot inside the shaking cockpit as icy asteroids tumble past outside. 3-6s: Orion grips the dual flight yokes firmly, executing a sharp evasive roll with focused precision. 6-8s: Sweat glints on his brow, then relaxes into a proud smile as the ship clears the orbital ring. Camera: dynamic handheld vibration settling into smooth glide. Lighting: azure planet shine through side windows. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Trung cảnh khoang lái rung chuyển nhẹ khi tàu bay sát qua những khối thiên thạch băng khổng lồ. 3-6s: Orion ghì chặt cần lái, điều khiển con tàu nghiêng người lướt qua khoảng hẹp một cách điêu luyện. 6-8s: Vẻ mặt căng thẳng giãn ra thành nụ cười tự tin khi con tàu vượt qua vùng nguy hiểm. Camera: rung lắc nhẹ rồi lướt êm. Ánh sáng: hào quang hành tinh xanh ngọc chiếu qua mạn tàu. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Gliding gracefully through shimmering asteroid rings, every turn reveals wonders no mortal eyes have ever witnessed.",
                        "narration_vi": f"Lướt nhẹ qua những vành đai băng lấp lánh của hành tinh khổng lồ, mỗi chuyển động mở ra một kỳ quan tráng lệ chưa từng được biết đến.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "The Heart of The Supernova",
                        "title_vi": "Trái Tim Của Tinh Cầu Kỳ Diệu",
                        "archetype": "Dialogue Two-Shot",
                        "prompt": f"Magnificent celestial discovery scene featuring {clean_idea}, radiant glowing core of light, colorful cosmic waves, dramatic starlight illumination",
                        "acting_en": f"0-3s: Two astronauts stand before the observation dome, mesmerized by a pulsating cosmic energy sphere. 3-6s: Orion extends a gloved hand toward the transparent dome. Orion says: \"It's alive... it's singing across the frequencies.\" (no subtitles) — hushed awe. 6-8s: Waves of warm harmonic light illuminate both faces in radiant wonder. Camera: slow circular orbit. Lighting: golden cosmic light waves in deep indigo space. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Hai phi hành gia đứng trước vòm kính quan sát ngắm nhìn khối năng lượng vũ trụ lơ lửng phát sáng. 3-6s: Orion đưa bàn tay bọc găng chạm nhẹ vào mặt kính trong suốt. Orion nói: \"Nguồn năng lượng này đang giao thoa cùng chúng ta.\" (không phụ đề) — giọng ngỡ ngàng thì thầm. 6-8s: Từng làn sóng ánh sáng ấm áp phản chiếu trên gương mặt hai người. Camera: lượn vòng cung chậm. Ánh sáng: sóng sáng hoàng kim giữa nền vũ trụ huyền bí. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"At the center of the deep expanse, a magnificent celestial core awakens, showering the cosmos with ancient brilliant light.",
                        "narration_vi": f"Tại trung tâm của dải ngân hà, một nguồn năng lượng kỳ diệu bừng sáng, tỏa ra những luồng ánh sáng ấm áp nuôi dưỡng muôn vì sao.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "Safe Harbor in Orbit",
                        "title_vi": "Bến Đỗ Bình Yên",
                        "archetype": "Resolution",
                        "prompt": f"Peaceful closing space scene, {clean_idea} peacefully floating against a glowing blue crescent planet, warm tranquil starlight",
                        "acting_en": f"0-3s: Wide exterior shot of the exploration vessel coasting into quiet planetary orbit. 3-6s: Orion stands in the observation cupola, helmet off, sipping warm coffee as the blue planet rises below. 6-8s: He offers a gentle salute toward the distant Earth starlight. Camera: graceful crane-out into deep starfield. Lighting: tranquil crescent planetary earthlight. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Toàn cảnh bên ngoài con tàu thám hiểm nhẹ nhàng tiến vào quỹ đạo hành tinh xanh biếc. 3-6s: Orion đứng trong vòm kính ngắm cảnh, cởi mũ bảo hiểm, nhìn ngắm hành tinh quê hương dần hiện ra. 6-8s: Anh mỉm cười giơ tay chào vì sao xa xôi. Camera: lùi xa êm ái vào biển sao. Ánh sáng: ánh xanh dịu dàng từ bề mặt hành tinh. Negative: subtitles, watermark, text overlay.",
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
                        "archetype": "Establishing Shot",
                        "prompt": f"Charming storybook forest scene featuring {clean_idea}, golden morning sunbeams filtering through lush canopy, dewdrops on wild strawberries, cute stylized aesthetic",
                        "acting_en": f"0-3s: Close-up on a cozy hollow tree trunk as little red panda Pip pokes his furry head out and yawns adorably. 3-6s: Pip rubs his emerald eyes, hops onto a mossy root, and straps on his leaf satchel. Pip says: \"Time for a big adventure!\" (no subtitles) — playful cheerful chirp. 6-8s: He sniffs a dewy strawberry and scurries forward happily. Camera: low-angle macro push. Lighting: warm dappled morning sunbeams. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Cận cảnh hốc cây ấm áp khi chú gấu trúc đỏ Pip thò đầu ra ngáp dài đáng yêu. 3-6s: Pip dụi mắt tròn xoe, nhảy tót xuống rễ cây phủ rêu và đeo chiếc túi lá nhỏ xinh. Pip nói: \"Hôm nay sẽ là một chuyến phiêu lưu tuyệt vời!\" (không phụ đề) — giọng trong trẻo nhí nhảnh. 6-8s: Chú hít hà quả dâu rừng rồi nhanh nhảu chạy về phía trước. Camera: góc thấp bám sát mặt đất. Ánh sáng: vạt nắng sớm lung linh qua tán lá. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"As dawn paints the forest in warm amber light, an adventurous soul wakes up ready to discover the world.",
                        "narration_vi": f"Khi ánh bình minh rọi những vạt nắng vàng óng ả qua kẽ lá, một ngày mới tràn ngập niềm vui và sự háo hức bắt đầu.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "A Playful Mishap",
                        "title_vi": "Thử Thách Bất Ngờ",
                        "archetype": "Action Beat",
                        "prompt": f"Playful animated forest scene with {clean_idea}, tumbling across a mossy brook, funny expressive reaction, colorful butterflies fluttering around",
                        "acting_en": f"0-3s: Medium tracking shot as Pip balances precariously across slippery river stones. 3-6s: A shimmering blue butterfly lands on his nose; Pip sneezes, wobbles, and tumbles into soft green ferns with a funny splash. 6-8s: Pip sits up with ferns on his head, blinking in surprise before giggling joyfully. Camera: playful tracking follow. Lighting: sparkling water reflections and sunlight glints. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Trung cảnh Pip nhón chân giữ thăng bằng bước qua những tảng đá rêu trơn trượt bên bờ suối. 3-6s: Một chú bướm xanh đậu lên chóp mũi; Pip hắt xì một cái rồi ngã lăn vào bụi dương xỉ mềm mại. 6-8s: Pip ngồi dậy với chiếc lá trên đầu, chớp mắt ngơ ngác rồi bật cười khúc khích. Camera: chuyển động vui nhộn bám theo. Ánh sáng: ánh nước lấp lánh phản chiếu rực rỡ. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Curiosity leads down uncharted paths! A playful tumble brings an unexpected surprise by the gurgling brook.",
                        "narration_vi": f"Tính tò mò dẫn lối qua con suối róc rách. Dù gặp một chút vấp váp nhỏ, nụ cười vẫn nở rộ giữa bầy bướm rực rỡ sắc màu.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "The Power of Teamwork",
                        "title_vi": "Sức Mạnh Của Tình Bạn",
                        "archetype": "Dialogue Two-Shot",
                        "prompt": f"Heartwarming animal collaboration scene with {clean_idea}, forest friends helping each other reach a golden glowing prize, joy and unity",
                        "acting_en": f"0-3s: Two forest friends—Pip and a friendly badger—stand under a high branch holding a juicy golden peach. 3-6s: Pip climbs onto badger's strong shoulders, reaching his paws upward. Pip says: \"Just a little higher, we got it!\" (no subtitles) — excited joyful squeak. 6-8s: They pluck the fruit together and high-five with cheerful hops. Camera: upward tilt to medium shot. Lighting: warm radiant golden canopy light. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Hai người bạn nhỏ—Pip và chú lửng rừng tốt bụng—đứng dưới cành cây cao có quả đào vàng mọng nước. 3-6s: Pip trèo lên vai bạn, kiễng chân với tay lên cành cây. Pip nói: \"Cố thêm chút nữa, tớ với tới rồi!\" (không phụ đề) — giọng hào hứng reo vang. 6-8s: Hai bạn cùng hái được quả đào và đập tay ăn mừng vui sướng. Camera: hướng chếch lên cao. Ánh sáng: ánh nắng chan hòa ấm áp qua kẽ lá. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"When a challenge seems too tall to conquer alone, good friends join hands. Together, nothing is impossible.",
                        "narration_vi": f"Khi thử thách dường như quá lớn, những người bạn tốt đã cùng nhau kề vai sát cánh. Sự sẻ chia biến mọi khó khăn thành niềm vui.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "Sunset Celebration",
                        "title_vi": "Lửa Trại & Khúc Ca Hoàng Hôn",
                        "archetype": "Resolution",
                        "prompt": f"Cozy evening forest clearing, {clean_idea} resting with friends under fireflies and lantern glow, warm heartfelt ending",
                        "acting_en": f"0-3s: Wide shot of a cozy forest clearing at dusk as glowing fireflies awaken in the tall grass. 3-6s: Pip and his friends share forest berries around a carved wooden stump, laughing together. 6-8s: Pip curls up happily in his mossy bed, waving goodnight toward the viewer. Camera: gentle pull-back into tree branches. Lighting: magical glowing fireflies and amber dusk. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Toàn cảnh khoảng rừng ấm cúng lúc chạng vạng khi đàn đom đóm thắp sáng bãi cỏ. 3-6s: Pip cùng các bạn chia nhau những quả mọng rừng quanh gốc cây cổ thụ, tiếng cười rộn rã. 6-8s: Pip cuộn tròn êm ái trong tổ rêu, vẫy tay chúc ngủ ngon. Camera: lùi nhẹ ra sau tán lá. Ánh sáng: đom đóm vàng lung linh giữa hoàng hôn tím dịu. Negative: subtitles, watermark, text overlay.",
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
                        "archetype": "Establishing Shot",
                        "prompt": f"Epic establishing shot of {clean_idea}, heroic pose looking out towards distant misty peaks, golden atmospheric rays, cinematic depth",
                        "acting_en": f"0-3s: Low angle tracking behind Kael as he reaches the crest of a rugged mountain ridge. 3-6s: Wind whips his hair as he unrolls an ancient leather map, checking the brass compass on his belt. Kael says: \"The lost sanctuary is right past these ridges.\" (no subtitles) — brave determined tone. 6-8s: He folds the map firmly and steps toward the descent. Camera: sweeping crane-up over the mountain ridge. Lighting: golden morning sun piercing mountain fog. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Góc quay thấp bám theo Kael khi cậu bước lên đỉnh vách đá dựng đứng. 3-6s: Gió thổi tung mái tóc khi cậu mở tấm bản đồ da cổ, nhìn la bàn đồng trên thắt lưng. Kael nói: \"Thánh địa thất lạc nằm ngay sau rặng núi này.\" (không phụ đề) — giọng kiên định quả cảm. 6-8s: Cậu gấp gọn bản đồ và vững bước tiến về phía trước. Camera: vút lên cao mở ra toàn cảnh núi non hùng vĩ. Ánh sáng: nắng sớm xuyên qua sương mờ. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"The wind carries a whisper of distant horizons. With courage in every breath, the great adventure begins.",
                        "narration_vi": f"Cơn gió mang theo lời mời gọi từ những chân trời xa xôi. Với lòng dũng cảm và niềm tin, chuyến phiêu lưu chính thức bắt đầu.",
                        "motion": "zoom_in"
                    },
                    {
                        "title_en": "Crossing The Frontier",
                        "title_vi": "Vượt Qua Vùng Đất Thử Thách",
                        "archetype": "Action Beat",
                        "prompt": f"Adventurous journey scene featuring {clean_idea}, traversing a canyon bridge or ancient ruins, dramatic lighting, sweeping dynamic angle",
                        "acting_en": f"0-3s: High angle looking down a precarious rope suspension bridge swaying over a misty chasm. 3-6s: Kael tests the weathered ropes, balances carefully, and dashes across as loose planks tumble into the void. 6-8s: He dives onto solid stone on the opposite cliff, turning to catch his breath with a defiant grin. Camera: dramatic plunging perspective. Lighting: dramatic shafts of sunlight cutting through deep canyon shadows. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Góc quay từ trên cao nhìn xuống cây cầu treo đung đưa qua hẻm vực sâu thăm thẳm. 3-6s: Kael kiểm tra dây thừng, giữ thăng bằng rồi chạy nhanh qua cầu khi vài thanh gỗ mục rơi xuống vực. 6-8s: Cậu nhảy bổ lên bờ đá an toàn phía đối diện, thở dốc rồi nở nụ cười kiêu hãnh. Camera: góc nhìn sâu thẳm đầy kịch tính. Ánh sáng: vệt nắng cắt ngang hẻm núi sương mù. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Across steep valleys and forgotten trails, every step tests resolve and awakens hidden strength.",
                        "narration_vi": f"Băng qua những thung lũng hiểm trở và di tích cổ xưa, mỗi bước đi là một bài học tôi luyện lòng kiên định.",
                        "motion": "pan_right"
                    },
                    {
                        "title_en": "The Revelation",
                        "title_vi": "Khoảnh Khắc Giác Ngộ",
                        "archetype": "Dialogue Two-Shot",
                        "prompt": f"Dramatic discovery scene of {clean_idea}, uncovering a glowing magical artifact or breathtaking vista, burst of celestial light, epic scale",
                        "acting_en": f"0-3s: Two companions enter an ancient stone chamber lined with glowing crystal runes. 3-6s: Kael brushes away moss from a carved celestial altar as radiant amber light pulses forth. Kael says: \"Look at this... it was here all along.\" (no subtitles) — reverent hushed tone. 6-8s: His companion gasps with joy, eyes reflecting the warm golden aura. Camera: slow circular track. Lighting: mystical golden inner glow illuminating ancient ruins. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Hai người bạn đồng hành bước vào căn phòng đá cổ với những ký tự pha lê phát sáng. 3-6s: Kael gạt lớp rêu phong trên bàn thờ đá thiêng khi luồng sáng hoàng kim bừng thức. Kael nói: \"Nhìn này... bí mật bấy lâu vẫn luôn ở đây.\" (không phụ đề) — giọng thì thầm xúc động. 6-8s: Người bạn reo lên mừng rỡ, ánh mắt rực sáng niềm hạnh phúc. Camera: xoay vòng tròn chậm. Ánh sáng: luồng hào quang huyền bí tỏa sáng khắp di tích. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"At the heart of the journey, the true secret is revealed: greatness was never about the destination, but the spirit forged along the way.",
                        "narration_vi": f"Giữa đỉnh cao của hành trình, bí mật lớn nhất đã bừng sáng: sức mạnh diệu kỳ nhất chính là niềm tin và trái tim kiên cường.",
                        "motion": "pan_left"
                    },
                    {
                        "title_en": "The Hero's Return",
                        "title_vi": "Vinh Quang & Bình Yên",
                        "archetype": "Resolution",
                        "prompt": f"Tranquil triumphant ending scene with {clean_idea}, warm golden sunset, peaceful horizon, cinematic final masterpiece frame",
                        "acting_en": f"0-3s: Wide shot on the cliff edge as sunset paints clouds in crimson and gold. 3-6s: Kael raises his carved staff toward the sky, wind billowing his traveler cloak in heroic silhouette. 6-8s: He turns back toward the path home with a serene, triumphant smile. Camera: slow cinematic pull-back. Lighting: breathtaking crimson and amber sunset. Negative: subtitles, watermark, text overlay.",
                        "acting_vi": f"0-3s: Toàn cảnh vách núi khi ráng chiều nhuộm thắm những tầng mây sắc đỏ vàng rực rỡ. 3-6s: Kael giơ cao cây trượng gỗ hướng về phía chân trời, áo choàng bay lộng gió trong tư thế người chiến thắng. 6-8s: Cậu quay nhìn về nẻo đường trở về với nụ cười thanh thản, tự hào. Camera: lùi xa dần vào hoàng hôn. Ánh sáng: ráng chiều lộng lẫy và bình yên. Negative: subtitles, watermark, text overlay.",
                        "narration_en": f"Standing tall against the setting sun, our hero smiles at the journey completed and the peaceful dawn that lies ahead.",
                        "narration_vi": f"Đứng trước ánh hoàng hôn rực rỡ, người anh hùng mỉm cười thanh thản, đón chào một tương lai tươi sáng và bình yên.",
                        "motion": "zoom_out"
                    }
                ]
            }
        }

        genre_pack = genre_beats.get(genre, genre_beats["adventure"])
        title = extracted_title or (genre_pack["title_vi"] if is_vi else genre_pack["title_en"])
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
        chosen_char = custom_char or genre_characters.get(genre, genre_characters["adventure"])["vi" if is_vi else "en"]

        scenes = []
        for i in range(num_scenes):
            beat = beats_pool[i % len(beats_pool)]
            scene_title = beat["title_vi"] if is_vi else beat["title_en"]
            narration = beat["narration_vi"] if is_vi else beat["narration_en"]
            archetype = beat.get("archetype", "Cinematic Scene")
            acting_prompt = (
                beat.get("acting_vi" if is_vi else "acting_en") or
                f"0-3s: {chosen_char} arrives at the scene, assessing the environment with alert eyes. "
                f"3-6s: Engages in focused physical activity, handling equipment or tools with precision. "
                f"6-8s: Reacts with strong emotional resolve, locking gaze forward as camera stabilizes. "
                f"Camera: {beat.get('motion', 'zoom_in')}. Lighting: cinematic volumetric. Negative: subtitles, watermark, text overlay."
            )

            scenes.append({
                "scene_number": i + 1,
                "title": scene_title,
                "archetype": archetype,
                "visual_prompt": f"{beat['prompt']}, character consistency: {chosen_char}",
                "acting_prompt": acting_prompt,
                "narration": narration,
                "camera_motion": beat.get("motion", "zoom_in")
            })

        return {
            "title": title,
            "logline": logline,
            "characters": chosen_char,
            "scenes": scenes
        }
