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

        # If provider is explicitly builtin / offline, do not search or overwrite with cloud credentials
        if self.provider in ("builtin", "offline", "architect"):
            return

        # Automatically check server-side stored credentials if api_key was not passed
        if not self.api_key:
            try:
                from backend.config import get_server_credentials
                creds = get_server_credentials()
                psid = creds.get("gemini_cookie_psid")
                psidts = creds.get("gemini_cookie_psidts")
                if self.provider == "gemini":
                    if creds.get("gemini_api_key") and creds["gemini_api_key"].startswith("AIzaSy"):
                        self.api_key = creds.get("gemini_api_key")
                    elif psid:
                        self.api_key = f"{psid}|{psidts}" if psidts else psid
                        self.provider = "gemini_cookie"
                    elif creds.get("gemini_api_key"):
                        self.api_key = creds.get("gemini_api_key")
                elif self.provider in ("gemini_cookie", "gemini_web"):
                    if psid:
                        self.api_key = f"{psid}|{psidts}" if psidts else psid
                elif creds.get("openai_api_key") and self.provider == "openai":
                    self.api_key = creds.get("openai_api_key")
                elif creds.get("claude_api_key") and self.provider in ("claude", "anthropic"):
                    self.api_key = creds.get("claude_api_key")
                elif creds.get("deepseek_api_key") and self.provider == "deepseek":
                    self.api_key = creds.get("deepseek_api_key")
                elif creds.get("nvidia_api_key") and self.provider == "nvidia":
                    self.api_key = creds.get("nvidia_api_key")
            except Exception:
                pass

    @classmethod
    def estimate_optimal_scene_count(cls, idea: str, target_duration: int = None) -> int:
        """
        Analyzes the input story's length, paragraph structure, dialogue turns, and narrative beats
        to automatically determine the optimal number of 8-second scenes.
        """
        if target_duration and target_duration > 0:
            return max(3, min(16, int(round(target_duration / 8.0))))

        clean = (idea or "").strip()
        if not clean:
            return 4

        # Check explicit scene headers (e.g. Scene 1, Cảnh 1)
        scene_headers = re.findall(r'(?:^|\n)\s*(?:Scene|Cảnh|Phân cảnh)\s*\d+', clean, re.IGNORECASE)
        if len(scene_headers) >= 2:
            return max(2, min(24, len(scene_headers)))

        words = clean.split()
        word_count = len(words)
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', clean) if len(p.strip()) > 10]
        sentences = [s.strip() for s in re.split(r'(?<=[.!?…])\s+|\n+', clean) if len(s.strip()) > 8]
        dialogue_turns = re.findall(r'(?:^|\n)\s*[–\-—]\s*[^\n]+|["“][^"”\n]{4,}["”]', clean)

        if word_count <= 25 and len(dialogue_turns) <= 1:
            return 4
        if word_count <= 45 and len(dialogue_turns) <= 2:
            return 5

        by_words = int(round(word_count / 20.0))
        by_sentences = int(round(len(sentences) * 0.75))
        by_dialogues = len(dialogue_turns) + 2
        by_paragraphs = len(paragraphs) + 1 if len(paragraphs) >= 3 else 4

        estimated = max(4, by_words, by_sentences, by_dialogues, by_paragraphs)
        return max(4, min(16, estimated))

    async def generate_storyboard(
        self,
        idea: str,
        num_scenes: int = 0,
        target_duration: int = None,
        art_style: str = "ghibli",
        language: str = "en",
        audience: str = "general",
        title: str = None,
        camera_on_speaker: bool = False
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
        if art_style == "dialogue_cinema":
            art_style = "ghibli"
            camera_on_speaker = True

        # 1. If user supplied an existing multi-scene screenplay/script, parse it directly
        # so their original story, characters, and scenes are 100% preserved.
        imported = self.parse_imported_storyboard(idea)
        if imported and imported.get("scenes") and len(imported["scenes"]) >= 2:
            print(f"🎬 Detected pre-existing screenplay with {len(imported['scenes'])} scenes in user idea! Importing directly...")
            if title and (not imported.get("title") or imported.get("title") == "Imported Film"):
                imported["title"] = title
            imported["scenes"] = [
                self.ensure_separate_prompts(sc, art_style=art_style, language=language, camera_on_speaker=camera_on_speaker)
                for sc in imported["scenes"]
                if isinstance(sc, dict)
            ]
            imported["scenes"] = self.sync_story_dialogues_to_scenes(
                imported["scenes"],
                idea=idea,
                art_style=art_style,
                language=language,
                target="all",
                characters=imported.get("characters"),
                camera_on_speaker=camera_on_speaker
            )
            return imported

        # 2. Only use offline Story Architect if explicitly requested
        if self.provider in ("builtin", "offline", "architect"):
            print("🏛️ Using offline built-in Story Architect as explicitly configured.")
            story = self._generate_with_story_architect(idea, num_scenes, art_style, language, audience)
            if story and isinstance(story.get("scenes"), list):
                story["scenes"] = [
                    self.ensure_separate_prompts(sc, art_style=art_style, language=language, camera_on_speaker=camera_on_speaker)
                    for sc in story["scenes"]
                    if isinstance(sc, dict)
                ]
                story["scenes"] = self.sync_story_dialogues_to_scenes(
                    story["scenes"],
                    idea=idea,
                    art_style=art_style,
                    language=language,
                    target="all",
                    characters=story.get("characters"),
                    camera_on_speaker=camera_on_speaker
                )
            return story

        prompt = self._build_story_prompt(
            idea,
            num_scenes,
            target_duration,
            art_style,
            language,
            audience,
            title=title,
            camera_on_speaker=camera_on_speaker
        )

        try:
            story = await self._dispatch_llm_request(prompt)
            if story and isinstance(story, dict) and "scenes" in story and isinstance(story["scenes"], list):
                story["scenes"] = [
                    self.ensure_separate_prompts(sc, art_style=art_style, language=language, camera_on_speaker=camera_on_speaker)
                    for sc in story["scenes"]
                    if isinstance(sc, dict)
                ]
                story["scenes"] = self.sync_story_dialogues_to_scenes(
                    story["scenes"],
                    idea=idea,
                    art_style=art_style,
                    language=language,
                    target="all",
                    characters=story.get("characters"),
                    camera_on_speaker=camera_on_speaker
                )
            return story

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

    async def _dispatch_llm_request(self, prompt: str) -> Dict[str, Any]:
        """Dispatches a prompt across the configured AI provider and returns structured JSON."""
        if not self.api_key and self.provider not in ("builtin", "offline", "architect"):
            try:
                from backend.config import get_server_credentials
                creds = get_server_credentials()
                psid = creds.get("gemini_cookie_psid")
                psidts = creds.get("gemini_cookie_psidts")
                if self.provider == "gemini":
                    if creds.get("gemini_api_key") and creds["gemini_api_key"].startswith("AIzaSy"):
                        self.api_key = creds.get("gemini_api_key")
                    elif psid:
                        self.api_key = f"{psid}|{psidts}" if psidts else psid
                        self.provider = "gemini_cookie"
                    elif creds.get("gemini_api_key"):
                        self.api_key = creds.get("gemini_api_key")
                elif self.provider in ("gemini_cookie", "gemini_web"):
                    if psid:
                        self.api_key = f"{psid}|{psidts}" if psidts else psid
                elif creds.get("openai_api_key") and self.provider == "openai":
                    self.api_key = creds.get("openai_api_key")
                elif creds.get("claude_api_key") and self.provider in ("claude", "anthropic"):
                    self.api_key = creds.get("claude_api_key")
                elif creds.get("deepseek_api_key") and self.provider == "deepseek":
                    self.api_key = creds.get("deepseek_api_key")
                elif creds.get("nvidia_api_key") and self.provider == "nvidia":
                    self.api_key = creds.get("nvidia_api_key")
            except Exception:
                pass

        if not self.api_key:
            raise RuntimeError(
                f"AI Generation Error: No API Key or Gemini Cookie found for provider '{self.provider}'. "
                "Please configure your Gemini Cookie or API key in Settings ⚙️."
            )

        is_cookie = (
            self.provider in ("gemini_cookie", "gemini_web") or
            ("__Secure-1PSID" in self.api_key) or
            (self.provider == "gemini" and len(self.api_key) > 70 and not self.api_key.startswith("AIzaSy"))
        )

        if is_cookie:
            return await self._generate_with_gemini_cookie(prompt, self.api_key)
        elif self.provider == "gemini":
            return await self._generate_with_gemini(prompt, self.model or "gemini-2.5-flash")
        elif self.provider == "openai":
            return await self._generate_with_openai_compatible(
                endpoint="https://api.openai.com/v1",
                api_key=self.api_key,
                model=self.model or "gpt-4o-mini",
                prompt=prompt
            )
        elif self.provider in ("claude", "anthropic"):
            return await self._generate_with_anthropic(
                api_key=self.api_key,
                model=self.model or "claude-3-5-haiku-20241022",
                prompt=prompt
            )
        elif self.provider == "deepseek":
            return await self._generate_with_openai_compatible(
                endpoint="https://api.deepseek.com/v1",
                api_key=self.api_key,
                model=self.model or "deepseek-chat",
                prompt=prompt
            )
        elif self.provider == "nvidia":
            return await self._generate_with_openai_compatible(
                endpoint="https://integrate.api.nvidia.com/v1",
                api_key=self.api_key,
                model=self.model or "meta/llama-3.1-70b-instruct",
                prompt=prompt
            )
        else:
            raise RuntimeError(f"Unsupported AI provider '{self.provider}'.")

    async def generate_advertisement_storyboard(
        self,
        product_name: str,
        description: str,
        specs: str = "",
        brand: str = "",
        target_audience: str = "General",
        ad_style: str = "cinematic_commercial",
        call_to_action: str = "Order now!",
        pricing_offer: str = "",
        num_scenes: int = 4,
        target_duration: int = None,
        art_style: str = "realistic",
        language: str = "en"
    ) -> Dict[str, Any]:
        """
        Generates an electrifying, high-converting product commercial storyboard.
        Tailored for advertising goods with product photos, technical specs, and persuasive copy.
        """
        # If offline/builtin mode requested:
        if self.provider in ("builtin", "offline", "architect"):
            print("🛍️ Using built-in offline Commercial Generator...")
            return self._generate_offline_advertisement(
                product_name=product_name,
                description=description,
                specs=specs,
                brand=brand,
                target_audience=target_audience,
                ad_style=ad_style,
                call_to_action=call_to_action,
                pricing_offer=pricing_offer,
                num_scenes=num_scenes,
                art_style=art_style,
                language=language
            )

        prompt = self._build_advertisement_prompt(
            product_name=product_name,
            description=description,
            specs=specs,
            brand=brand,
            target_audience=target_audience,
            ad_style=ad_style,
            call_to_action=call_to_action,
            pricing_offer=pricing_offer,
            num_scenes=num_scenes,
            target_duration=target_duration,
            art_style=art_style,
            language=language
        )

        try:
            story = await self._dispatch_llm_request(prompt)
            if not story or not isinstance(story.get("scenes"), list) or len(story["scenes"]) == 0:
                print("⚠️ AI returned empty ad storyboard. Falling back to built-in commercial director...")
                story = self._generate_offline_advertisement(
                    product_name=product_name,
                    description=description,
                    specs=specs,
                    brand=brand,
                    target_audience=target_audience,
                    ad_style=ad_style,
                    call_to_action=call_to_action,
                    pricing_offer=pricing_offer,
                    num_scenes=num_scenes,
                    art_style=art_style,
                    language=language
                )
            else:
                story["scenes"] = [
                    self.ensure_separate_prompts(sc, art_style=art_style, language=language)
                    for sc in story["scenes"]
                    if isinstance(sc, dict)
                ]
            return story
        except Exception as e:
            print(f"⚠️ Commercial AI generation error ({e}). Using offline Commercial Generator fallback...")
            return self._generate_offline_advertisement(
                product_name=product_name,
                description=description,
                specs=specs,
                brand=brand,
                target_audience=target_audience,
                ad_style=ad_style,
                call_to_action=call_to_action,
                pricing_offer=pricing_offer,
                num_scenes=num_scenes,
                art_style=art_style,
                language=language
            )

    def _build_story_prompt(
        self,
        idea: str,
        num_scenes: int,
        target_duration: int = None,
        art_style: str = "ghibli",
        language: str = "en",
        audience: str = "general",
        title: str = None,
        camera_on_speaker: bool = False
    ) -> str:
        is_auto_scenes = not num_scenes or num_scenes <= 0
        est_scenes = self.estimate_optimal_scene_count(idea, target_duration) if is_auto_scenes else num_scenes
        min_auto_scenes = max(3, est_scenes - 1)
        max_auto_scenes = min(20, est_scenes + 2)

        calc_duration = target_duration if (target_duration and target_duration > 0) else (est_scenes * 8)
        target_scene_sec = max(5, int(calc_duration / max(1, est_scenes)))
        target_scene_sec = min(target_scene_sec, 8)
        max_words = min(24, max(15, int((target_scene_sec - 0.5) * 2.8)))

        clean_idea_strip = idea.strip()
        word_count = len(clean_idea_strip.split())
        has_dialogue_markers = bool(re.search(r'(?:^|\n)\s*[–\-—]|["“”]', clean_idea_strip))
        is_narrative = (
            word_count > 30 or
            has_dialogue_markers or
            "\n\n" in clean_idea_strip or
            any(marker in clean_idea_strip.lower() for marker in [
                "once upon", "in times gone by", "there was a", "long ago",
                "ngày xửa ngày xưa", "thời xa xưa", "câu chuyện", "tại một vương quốc",
                "truyện", "kịch bản", "the king", "the prince", "the princess", "the golden"
            ])
        )

        scene_count_desc = (
            f"an optimal number of scenes determined by you (recommended {min_auto_scenes} to {max_auto_scenes} scenes based on the story's natural beats and dialogues)"
            if is_auto_scenes
            else f"{num_scenes} scenes"
        )
        arc_header = (
            f"1. 3-ACT NARRATIVE ARC & AUTONOMOUS SCENE COUNTING (AUTO MODE — Recommended {min_auto_scenes}–{max_auto_scenes} scenes):\n"
            f"   - Analyze the story's plot beats, setting shifts, character interactions, and dialogues to decide the exact number of scenes needed.\n"
            f"   - Give each distinct action beat, dialogue exchange, and the final twist/punchline its own dedicated 8-second scene so no scene is rushed or overcrowded."
            if is_auto_scenes
            else f"1. 3-ACT NARRATIVE ARC (Across {num_scenes} scenes):"
        )
        seq_continuity_desc = (
            "from Scene 1 through the final scene"
            if is_auto_scenes
            else f"from Scene 1 to Scene {num_scenes}"
        )

        adaptation_mandate = ""
        if is_narrative:
            adaptation_mandate = (
                f"- FAITHFUL STORY & DIALOGUE ADAPTATION: Follow the user's EXACT plot, canonical characters, dialogues, twists, and punchline/ending chronologically across {scene_count_desc} without omitting or replacing key figures or key lines."
            )
        else:
            adaptation_mandate = (
                f"- COHESIVE ORIGINAL STORY ARC: Create an emotionally engaging, cause-and-effect story arc rooted in \"{clean_idea_strip}\" with consistent characters across {scene_count_desc}."
            )

        title_clause = f'Film Title: "{title}"' if title else f'Film Title: Catchy, cinematic title in {language}'

        dialogue_cinema_directive = ""
        if camera_on_speaker or art_style == "dialogue_cinema":
            dialogue_cinema_directive = f"""
   - DIALOGUE FILM (CAMERA ON SPEAKING CHARACTER — SHOT-REVERSE-SHOT MANDATE IN {art_style.upper()} VISUAL STYLE):
     * Render all visuals in the chosen **{art_style}** animation style while directing the camera like a cinematic dialogue film.
     * Whenever a character speaks in a scene, the camera MUST focus directly on the SPEAKING CHARACTER (Medium Close-Up on the active speaker's face & upper body, or Over-The-Shoulder shot looking directly at the character who is speaking).
     * Across conversational exchanges, use Shot-Reverse-Shot editing: cut the camera focus to whichever character is speaking in that scene.
     * In `visual_prompt`, explicitly state which character the camera is focused on in {art_style} style (e.g. "Medium close-up camera focused directly on [Speaker Name] speaking expressively with natural mouth articulation in {art_style} style, warm key lighting on [Speaker Name]'s face, shallow 50mm depth of field...").
     * In `acting_prompt`, explicitly state the camera focus on the speaking character (e.g. "Medium close-up focused directly on [Speaker Name] as they speak. The camera executes a smooth intimate push-in toward [Speaker Name]'s face at eye level... 3-6s: Camera holds focus on [Speaker Name] speaking with expressive facial micro-expressions and natural lip-sync mouth movement. [Speaker Name] says in an expressive voice: \\"...\\" (no subtitles).").
     * Set `camera_motion` to `"speaker_focus"` for all scenes where a character is speaking."""

        return f"""You are a master animation director at Pixar, Studio Ghibli, and premier cinematic AI studios (Google Flow / Google Veo 3 / Imagen 3).
Transform the provided input into a breathtaking, emotionally resonant animated short film storyboard tailored for ACTING VIDEO GENERATION (8-second scenes, Google Flow / Veo 3 I2V).

Story Input:
\"\"\"
{clean_idea_strip}
\"\"\"

Parameters:
- {title_clause}
- Target Audience: {audience} | Art Style: {art_style} | Narration Language: {language}
{adaptation_mandate}

CINEMATIC DIRECTIVES:
{arc_header}
   - Act I (Exposition & Catalyst): Establish the world, introduce the protagonist's specific situation, and ignite the central conflict or adventure.
   - Act II (Rising Action & Confrontation): Escalating obstacles, key character interactions and dialogues, stakes rising to peak tension.
   - Act III (Climax & Resolution): Deliver the decisive emotional climax, twist, or punchline, followed by a resonant conclusion tied directly to the premise.{dialogue_cinema_directive}

2. SEPARATE PROMPTS FOR IMAGE & VIDEO (MANDATORY REQUIREMENT):
   - You MUST generate TWO ENTIRELY SEPARATE, DIFFERENT prompts for each scene:
     a) `visual_prompt` (STILL IMAGE PROMPT for Midjourney / Google Imagen 3):
        * A detailed, rich visual description of the single frozen frame in {art_style} art style.
        * Focus on: scene composition, character visual appearance & outfit, environment background, color palette, lighting atmosphere, artistic textures.
        * STRICT PROHIBITION: Do NOT include 0-3s timestamps, camera motion instructions, negative prompts, or spoken dialogue quotes.
     b) `acting_prompt` (PROFESSIONAL CINEMATIC VIDEO PROMPT for Google Flow / Veo 3 / Kling / Sora):
        * Write as natural, director-grade cinematic prose (90-140 words) in ENGLISH only regardless of project narration language.
        * Structure:
          - [Shot Framing & Camera Movement]: Define shot type (e.g. Medium wide tracking shot, Low-angle cinematic tracking shot) and describe the continuous camera motion as a dedicated cinematic sentence (e.g. "The camera executes a smooth, slow dolly push-in at eye level with steady fluid stabilization."). NEVER write "Camera: zoom_in".
          - [Physically Reasonable 8-Second Performance]: Ground the character's movement in realistic physical inertia and natural progression tied to the scene's story event:
            * 0-3s (Initiation): Organic movement starting from the keyframe pose (breathing, ambient breeze stirring hair and clothing, subtle weight shift, turning gaze).
            * 3-6s (Core Acting Beat): Focused physical action and emotional nuance matching the scene's narrative beat. If speaking, keep dialogue strictly under 6 words so it delivers naturally: Character says in a [vocal tone] voice: "..." (no subtitles).
            * 6-8s (Settling & Landing): Emotional reaction settling, steady breath or subtle nod, holding composition steady for a clean scene transition.
          - [Atmospheric Lighting & Optics]: Define lighting setup (e.g. "Volumetric golden-hour rim lighting cutting through ambient dust motes, shot on 35mm lens with shallow depth of field and creamy background falloff.").
          - [Veo 3 Audio & Negative Prompt]:
            Audio: [natural atmospheric soundscape, gentle ambient breeze, no background music].
            SFX: [1-2 subtle, realistic physical foley sound effects].
            Negative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, extra fingers, jittery motion, blurry faces, abrupt camera snap.
        * STRICT REASONABILITY MANDATE: Avoid impossible morphing, violent acrobatics, rapid multi-angle cutting, or chaotic scene jumps. Keep the physical performance grounded, elegant, and believable for an 8-second single take.
   - `visual_prompt` and `acting_prompt` MUST NEVER be identical. They serve two completely different AI engines.

3. CHARACTER CONSISTENCY BLUEPRINT:
   - In `characters`: Define immutable visual anchors for each key character (e.g. "Protagonist: Leo, 10yo boy with tousled amber-brown hair, expressive hazel eyes, signature mustard yellow knitted sweater, blue denim shorts, leather satchel").
   - MANDATORY: Every `visual_prompt` MUST include these EXACT visual anchor tokens whenever that character appears to guarantee cross-scene character consistency in Imagen 3 and Veo 3.

4. CAMERA SHOT GRAMMAR:
   - Progress shots dynamically across the arc: "Extreme Wide Establishing Shot", "Medium Character Profile", "Speaker Close-Up Focus", "Over-The-Shoulder Dialogue Shot", "Intimate Two-Shot Dialogue", "Dynamic Low-Angle Action Tracking", "Close-Up Heroic Climax", "Sweeping Panoramic Pull-Out".
   - `camera_motion`: Choose kinetic, purposeful movement: "speaker_focus" (when a character is speaking), "zoom_in", "zoom_out", "pan_left", "pan_right", or "subtle_drift".

5. VOICEOVER NARRATION — MUST TIE DIRECTLY TO THE STORY (CRITICAL MANDATE):
   - `narration`: Engaging, story-driven voiceover narration in {language} that serves as the primary storytelling audio and subtitle track of the film.
   - DIRECT STORY TIE-IN: Every scene's `narration` MUST directly narrate the specific plot event, character action, cause-and-effect progression, and emotional beat happening in that scene.
   - SEQUENTIAL STORY CONTINUITY: When read {seq_continuity_desc}, the `narration` lines MUST form a complete, cohesive, self-contained story that faithfully tells the user's premise from beginning to end.
   - PRESERVE KEY DIALOGUE & PUNCHLINES: When a scene involves a pivotal question, answer, revelation, or comedic/dramatic punchline from the story, `narration` MUST explicitly include or quote that key spoken line in {language} (e.g., 'Chàng trai kinh hãi lắp bắp hỏi: "Quan cũng có mặt ở đó sao? Chẳng lẽ..."'), NEVER replace key story dialogue or punchlines with vague, detached third-person meta-summaries (such as "Anh lắp bắp hỏi lại trong sợ hãi và nghi ngờ").
   - NO GENERIC FILLER OR SCENERY STUBS: Never write disconnected 3-5 word weather/scenery fragments or generic atmospheric platitudes that do not advance the story.
   - PACING RULE: Aim for 14 to {max_words} words per scene so the narration tells the story clearly while fitting comfortably within an 8-second scene clip.

6. MULTI-VOICE CHARACTER DIALOGUES (STUDIO PRODUCTION QUALITY):
   - In scenes where characters speak or converse, output a `dialogues` array segmenting the scene speech: `[{{"speaker": "Narrator", "text": "Intro..."}}, {{"speaker": "Character Name", "text": "Spoken line..."}}]`.
   - Keep speaker names consistent with the names declared in `characters` so individual character neural voices can be auto-cast.

Return ONLY raw JSON matching this structure:
{{
  "title": "Title",
  "logline": "1-sentence logline",
  "characters": "Protagonist: [Name & Role, Immutable visual tokens] | Companion/Creature: [Name, Immutable visual tokens]",
  "scenes": [
    {{
      "scene_number": 1,
      "title": "Scene 1 Title",
      "archetype": "Establishing Shot",
      "visual_prompt": "Detailed static illustration description: frozen composition, character visual details and outfit, environment, color palette, lighting in {art_style} art style. (NO timing, NO camera moves, NO dialogue quotes)",
      "acting_prompt": "Medium wide shot of [Character] in [Setting]. The camera executes a smooth slow dolly push-in at eye level with fluid stabilization. 0-3s: [Character] steps forward naturally as ambient wind stirs clothing and hair. 3-6s: [Character] pauses to inspect [prop/surroundings], eyes filled with quiet resolve. Character says in a calm voice: \\\"We are close.\\\" (no subtitles). 6-8s: [Character] takes a steady breath as the scene holds composition. Volumetric atmospheric rim lighting with soft 35mm depth of field.\\n\\nAudio: gentle mountain breeze, distant bird calls, no background music.\\nSFX: soft footsteps on stone, cloth rustle.\\nNegative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, extra fingers, jittery motion, blurry faces.",
      "narration": "...",
      "dialogues": [
        {{"speaker": "Narrator", "text": "..."}},
        {{"speaker": "Character Name", "text": "..."}}
      ],
      "camera_motion": "zoom_in"
    }}
  ]
}}"""

    def _clean_json_response(self, text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        match_fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
        if match_fence:
            candidate = match_fence.group(1).strip()
        else:
            outer_match = re.search(r"(\{[\s\S]*\})", cleaned)
            candidate = outer_match.group(1).strip() if outer_match else cleaned
        # Strip trailing citation brackets such as [cite: 1] if generated by Gemini Web
        candidate = re.sub(r'\[cite:[^\]]+\]', '', candidate).strip()
        return json.loads(candidate)

    @classmethod
    def professionalize_video_prompt(
        cls,
        acting_prompt: str,
        visual_prompt: str = "",
        narration: str = "",
        camera_motion: str = "zoom_in",
        title: str = "",
        art_style: str = "ghibli",
        is_commercial: bool = False,
        speaker_name: str = "",
        camera_on_speaker: bool = False
    ) -> str:
        """
        Transforms any raw, robotic, or placeholder video prompt into a professional,
        physically reasonable, director-grade cinematic video prompt optimized for
        Google Flow, Google Veo 3, Kling, and Sora.
        """
        raw_prompt = (acting_prompt or "").strip()
        vis_text = (visual_prompt or "").strip()
        narr_text = (narration or "").strip()
        clean_title = (title or "").strip()
        style_key = (art_style or "ghibli").lower()

        # 1. Safety & Policy Filtering (Safe Prompting for Veo/Flow)
        safe_replacements = [
            (r'\b(?:attack|strike|bomb|missile)\b', 'strategic maneuver'),
            (r'\b(?:kill|kills|killing|killed|dead|corpse|body bags?)\b', 'fall'),
            (r'\b(?:blood|bloody|wound|wounded|injury|gore)\b', 'dust and debris'),
            (r'\b(?:explosion|blast|detonate)\b', 'radiant shockwave'),
            (r'\b(?:destroy|devastate|annihilate)\b', 'impact'),
            (r'\b(?:chaos|carnage|massacre)\b', 'tense aftermath'),
            (r'\b(?:aggressive|menace|threaten)\b', 'resolute and firm'),
            (r'\b(?:angry|furious|rage)\b', 'intense determination'),
            (r'\b(?:hostage|torture|prisoner)\b', 'diplomatic standoff'),
            (r'\b(?:pointing aggressively)\b', 'gesturing firmly'),
        ]
        for pattern, replacement in safe_replacements:
            raw_prompt = re.sub(pattern, replacement, raw_prompt, flags=re.IGNORECASE)

        # 2. Extract and Normalize Spoken Dialogue (from acting_prompt or narration)
        dialogue_match = re.search(
            r'(?:character says|nhân vật nói|[A-Za-zÀ-ỹ\s]+(?:nói|hỏi|đáp|thưa|kêu|thì thầm)|says|whispers|murmurs|asks|replies|gasps|shouts|crying out|cries|explains|blurts|exclaims|mutters|calls out)[^:"“\n]{0,45}[:\s]+["“]([^"”]+)["”]',
            raw_prompt,
            re.IGNORECASE
        )
        if not dialogue_match and narr_text:
            dialogue_match = re.search(r'["“]([^"”]{2,})["”]', narr_text)
        dialogue_text = ""
        if dialogue_match:
            cand_diag = dialogue_match.group(1).strip()
            words = cand_diag.split()
            if len(words) > 18:
                cand_diag = " ".join(words[:16]).rstrip(' ,;:-') + "..."
            dialogue_text = cand_diag

        # 3. Detect and Map Camera Motion to Director-Grade Prose
        cam_match = re.search(r'(?i)Camera\s*:\s*([a-zA-Z_\-]+)', raw_prompt)
        detected_cam = (cam_match.group(1) if cam_match else camera_motion or "zoom_in").lower().replace("-", "_")
        is_speaker_focus = bool(camera_on_speaker or style_key == "dialogue_cinema" or detected_cam == "speaker_focus")
        if is_speaker_focus and dialogue_text and detected_cam in ("zoom_in", "subtle_drift"):
            detected_cam = "speaker_focus"

        spk_label = (speaker_name or "").strip()
        if spk_label.lower() in ("narrator", "người kể chuyện", "character", "none"):
            spk_label = ""

        if is_commercial:
            camera_prose_map = {
                "speaker_focus": "The camera performs a smooth, high-precision motorized slider push-in toward the hero subject.",
                "zoom_in": "The camera performs a smooth, high-precision motorized slider push-in toward the product hero silhouette.",
                "dolly_in": "The camera performs a smooth, high-precision motorized slider push-in toward the product hero silhouette.",
                "zoom_out": "The camera smoothly dollies out with a steady pedestal pull-back, revealing the full premium product lineup.",
                "dolly_out": "The camera smoothly dollies out with a steady pedestal pull-back, revealing the full premium product lineup.",
                "pan_left": "The camera glides in a graceful horizontal tracking pan to the left, capturing sleek metallic edges and reflections.",
                "pan_right": "The camera executes a smooth 360-degree orbital turntable tracking glide to the right, highlighting flawless textures.",
                "subtle_drift": "A steady locked-off macro hero shot with subtle organic drift and high-end commercial depth of field.",
                "static": "A locked-off studio beauty shot with crisp commercial depth of field.",
                "crane_down": "The camera performs an elegant vertical crane sweep gliding downward smoothly to product eye level.",
                "tilt_up": "The camera slowly tilts upward along the product contours, highlighting its sculpted architectural lines."
            }
        else:
            spk_target = f"{spk_label}'s face" if spk_label else "the speaking character's face"
            camera_prose_map = {
                "speaker_focus": f"The camera focuses directly on {spk_label or 'the speaking character'} in an intimate medium close-up, executing a smooth slow push-in toward {spk_target} at eye level as they speak.",
                "zoom_in": "The camera executes a smooth, slow cinematic dolly push-in toward the subject at eye level with fluid stabilization.",
                "dolly_in": "The camera executes a smooth, slow cinematic dolly push-in toward the subject at eye level with fluid stabilization.",
                "zoom_out": "The camera smoothly dollies out with a steady pedestal pull-back, gradually revealing the expansive atmospheric environment.",
                "dolly_out": "The camera smoothly dollies out with a steady pedestal pull-back, gradually revealing the expansive atmospheric environment.",
                "pan_left": "The camera performs a graceful horizontal tracking pan to the left, smoothly following the subject's eyeline.",
                "pan_right": "The camera glides in a smooth cinematic tracking pan to the right with fluid stabilization.",
                "subtle_drift": "A steady locked-off camera with subtle organic handheld drift and shallow depth of field.",
                "static": "A steady locked-off medium shot with subtle organic handheld drift and shallow depth of field.",
                "crane_down": "The camera performs a graceful crane shot gliding downward smoothly to eye level.",
                "tilt_up": "The camera slowly tilts upward, capturing the majestic scale and vertical expanse of the scene.",
                "tracking": "A steady low-angle tracking arc shot glides gracefully around the subject with fluid motion.",
                "orbit": "A steady orbital arc pan smoothly glides around the character, capturing their expression and surroundings."
            }
        camera_sentence = camera_prose_map.get(detected_cam, camera_prose_map.get("zoom_in", "The camera executes a smooth cinematic push-in."))

        # 4. Extract or Derive Scene Subject & Context
        def clean_vis(v: str) -> str:
            c = re.sub(
                r'(?i)^(?:một phân cảnh hoạt hình[^,.\n]*[,.\s]*|phong cách\s+[^,.\n]*[,.\s]*|photorealistic cinematic live-action|studio ghibli 2d|ghibli|anime|3d pixar|pixar 3d animation style|pixar|disney|comic book|cyberpunk|watercolor|retro 80s|pixel art|realistic)\s*(?:art|style)?[,.\s]*',
                '',
                v
            )
            c = re.sub(r'(?i)^(?:góc quay[^,.\n]*[,.\s]*)', '', c)
            c = re.sub(r'(?i)\b(?:cinematic composition|rich atmospheric lighting|masterpiece (?:illustration|photography)|high fidelity details|intricate environmental details|tỉ lệ \d+:\d+|không chữ)\b[,.\s]*', '', c)
            return c.strip(' .,-')

        subject_context = clean_vis(vis_text)
        if not subject_context or len(subject_context) < 10:
            subject_context = clean_title or "the scene"

        if len(subject_context) > 130:
            subject_context = subject_context[:125].rsplit(' ', 1)[0]

        # If subject_context contains non-ASCII (e.g. Vietnamese visual_prompt), keep the English framing clean
        has_non_ascii_subj = any(ord(ch) > 127 for ch in subject_context)
        if has_non_ascii_subj:
            subject_context_lower = "the character in the scene setting"
        elif subject_context.startswith("A "):
            subject_context_lower = "a " + subject_context[2:]
        elif subject_context.startswith("An "):
            subject_context_lower = "an " + subject_context[3:]
        elif subject_context.startswith("The "):
            subject_context_lower = "the " + subject_context[4:]
        else:
            subject_context_lower = subject_context

        # 5. Determine whether existing prompt has meaningful custom beats or is placeholder
        is_placeholder = (
            not raw_prompt or
            "Character moves naturally into the scene" in raw_prompt or
            "Core emotional action beat" in raw_prompt or
            "Core emotional performance beat" in raw_prompt or
            "Diễn xuất và chuyển động tự nhiên" in raw_prompt or
            "Cảm xúc chuyển biến tự nhiên" in raw_prompt or
            "Character begins action in the scene" in raw_prompt or
            len(raw_prompt) < 25
        )

        # 6. Build Grounded, Reasonable 3-Beat Motion
        if is_placeholder:
            if is_commercial:
                beat1 = f"0-3s: Fluid camera glide slowly reveals pristine geometric contours and subtle light reflections on {subject_context_lower}."
                beat2 = "3-6s: Dynamic tactile interaction highlights responsive controls and fine material craftsmanship."
                beat3 = "6-8s: The composition settles into an authoritative hero angle with ultimate brand prestige."
            else:
                char_ref = spk_label or "The character"
                beat1 = f"0-3s: {char_ref} initiates natural, measured movement in the setting, hair and clothing gently stirring in the ambient breeze."
                if dialogue_text:
                    if is_speaker_focus or detected_cam == "speaker_focus":
                        beat2 = f'3-6s: Camera holds intimate focus on {char_ref} speaking with expressive facial micro-expressions and natural lip-sync articulation. {char_ref} says in a clear, expressive voice: "{dialogue_text}" (no subtitles).'
                    else:
                        beat2 = f'3-6s: {char_ref} pauses with focused poise. {char_ref} says in a calm, resolute voice: "{dialogue_text}" (no subtitles).'
                elif narr_text and len(narr_text) < 40:
                    beat2 = "3-6s: The character performs a focused, deliberate interaction with the immediate setting, eyes reflecting thoughtful determination."
                else:
                    beat2 = "3-6s: The character performs a focused, deliberate interaction with the immediate environment, their gaze steady and expressive."
                beat3 = f"6-8s: {char_ref} takes a steadying breath, settling into a grounded posture as their expression deepens with quiet confidence."
            body_beats = f"{beat1} {beat2} {beat3}"
        else:
            # Clean existing prompt from clunky metadata tags and bracketed tags
            cleaned_body = raw_prompt
            cleaned_body = re.sub(r'(?i)Camera\s*:[^.\n]*\.?', '', cleaned_body)
            cleaned_body = re.sub(r'(?i)Lighting\s*:[^.\n]*\.?', '', cleaned_body)
            cleaned_body = re.sub(r'(?i)Negative\s*:[^.\n]*\.?', '', cleaned_body)
            cleaned_body = re.sub(r'(?i)Audio\s*:[^.\n]*\.?', '', cleaned_body)
            cleaned_body = re.sub(r'(?i)SFX\s*:[^.\n]*\.?', '', cleaned_body)
            cleaned_body = re.sub(r'(?i)Music\s*:[^.\n]*\.?', '', cleaned_body)
            cleaned_body = re.sub(r'\(\s*(?:không phụ đề|no subtitles)\s*\)', '', cleaned_body, flags=re.IGNORECASE)
            cleaned_body = re.sub(r'(?i)\b(?:không phụ đề|no subtitles)\b', '', cleaned_body)
            cleaned_body = re.sub(r'\(\s*\)', '', cleaned_body)

            # Strip existing camera prose sentences to ensure idempotency when re-refined
            for c_val in [
                "The camera executes a smooth, slow cinematic dolly push-in toward the subject at eye level with fluid stabilization.",
                "The camera smoothly dollies out with a steady pedestal pull-back, gradually revealing the expansive atmospheric environment.",
                "The camera performs a graceful horizontal tracking pan to the left, smoothly following the subject's eyeline.",
                "The camera glides in a smooth cinematic tracking pan to the right with fluid stabilization.",
                "A steady locked-off camera with subtle organic handheld drift and shallow depth of field.",
                "A steady locked-off medium shot with subtle organic handheld drift and shallow depth of field.",
                "The camera performs a graceful crane shot gliding downward smoothly to eye level.",
                "The camera slowly tilts upward, capturing the majestic scale and vertical expanse of the scene.",
                "A steady low-angle tracking arc shot glides gracefully around the subject with fluid motion.",
                "A steady orbital arc pan smoothly glides around the character, capturing their expression and surroundings.",
                "The camera performs a smooth, high-precision motorized slider push-in toward the product hero silhouette.",
                "The camera smoothly dollies out with a steady pedestal pull-back, revealing the full premium product lineup.",
                "The camera glides in a graceful horizontal tracking pan to the left, capturing sleek metallic edges and reflections.",
                "The camera executes a smooth 360-degree orbital turntable tracking glide to the right, highlighting flawless textures.",
                "A steady locked-off macro hero shot with subtle organic drift and high-end commercial depth of field.",
                "A locked-off studio beauty shot with crisp commercial depth of field.",
                "The camera performs an elegant vertical crane sweep gliding downward smoothly to product eye level.",
                "The camera slowly tilts upward along the product contours, highlighting its sculpted architectural lines."
            ]:
                cleaned_body = cleaned_body.replace(c_val, "")

            # Strip existing lighting prose
            for l_prose in [
                "Commercial studio softbox key light with crisp edge reflections and immaculate specular highlights, shot on 50mm f/1.8 lens.",
                "Volumetric cinematic rim lighting, shot on 35mm anamorphic lens with shallow depth of field and creamy background falloff.",
                "Painted volumetric sunlight filtering through the atmosphere, soft rim highlights, beautiful anime depth of field.",
                "Soft studio-grade three-point lighting with gentle specular highlights, rich cinematic 3D depth of field.",
                "Atmospheric volumetric lighting with rich highlights and gentle shadow roll-off, shallow depth of field."
            ]:
                cleaned_body = cleaned_body.replace(l_prose, "")

            cleaned_body = re.sub(r'(?i)^(?:Medium shot of [^.]*\.\s*)', '', cleaned_body)
            cleaned_body = re.sub(r'\s+', ' ', cleaned_body).strip(' .,-')

            # Translate common Vietnamese phrasing into professional English if present
            cleaned_body = re.sub(r'(?i)nhân vật bước vào', 'the character steps into', cleaned_body)
            cleaned_body = re.sub(r'(?i)nhân vật mỉm cười', 'the character smiles gently', cleaned_body)
            cleaned_body = re.sub(r'(?i)nhân vật nhìn', 'the character looks', cleaned_body)
            cleaned_body = re.sub(r'(?i)khu đền cổ', 'the ancient temple', cleaned_body)
            cleaned_body = re.sub(r'(?i)khu vườn', 'the garden', cleaned_body)
            cleaned_body = re.sub(r'(?i)góc quay lướt chậm', 'the camera glides slowly', cleaned_body)
            cleaned_body = re.sub(r'(?i)ánh sáng viền', 'rim light highlights', cleaned_body)
            cleaned_body = re.sub(r'(?i)nhân vật nói\s*[:\-]*\s*["“]([^"”]+)["”]', r'Character says in a clear voice: "\1" (no subtitles)', cleaned_body)

            # Check if timestamps already exist
            has_timestamps = bool(re.search(r'\b\d+-\d+s\s*:', cleaned_body))
            if has_timestamps:
                cleaned_body = re.sub(
                    r'((?:says|whispers|gasps|shouts|asks|replies|nói|hỏi|đáp|thưa)[^"\n]*["“][^"”]+["”])(?!\s*\(no subtitles\))',
                    r'\1 (no subtitles)',
                    cleaned_body,
                    flags=re.IGNORECASE
                )
                # If dialogue_text exists (e.g. from narration) but is not yet in cleaned_body, inject it into 3-6s beat
                if dialogue_text and not re.search(r'["“][^"”]+["”]', cleaned_body):
                    if re.search(r'\b3-6s\s*:', cleaned_body):
                        cleaned_body = re.sub(
                            r'(\b3-6s\s*:[^6\n]*?)(\s*\b6-8s\s*:|$)',
                            lambda m: f'{m.group(1).rstrip(" .")}. Character says in an expressive voice: "{dialogue_text}" (no subtitles). {m.group(2).lstrip()}',
                            cleaned_body,
                            count=1
                        )
                    else:
                        cleaned_body = cleaned_body.rstrip(' .') + f'. 3-6s: Character says in an expressive voice: "{dialogue_text}" (no subtitles).'
                if not re.search(r'\b[56]-\d+s\s*:', cleaned_body):
                    cleaned_body = cleaned_body.rstrip(' .') + ". 6-8s: The character settles into a calm, grounded posture as the scene reaches a steady cinematic hold."
                body_beats = cleaned_body
            else:
                if dialogue_text and not re.search(r'["“][^"”]+["”]', cleaned_body):
                    beat2_str = f'3-6s: The character speaks with expressive emotion. Character says in a clear voice: "{dialogue_text}" (no subtitles).'
                else:
                    beat2_str = "3-6s: The motion continues with smooth momentum and expressive nuance."
                body_beats = f"0-3s: {cleaned_body.rstrip(' .')}. {beat2_str} 6-8s: The subject settles naturally into frame with cinematic poise."

        # 7. Optics & Atmospheric Lighting
        if is_commercial:
            lighting_prose = "Commercial studio softbox key light with crisp edge reflections and immaculate specular highlights, shot on 50mm f/1.8 lens."
        elif "realistic" in style_key:
            lighting_prose = "Volumetric cinematic rim lighting, shot on 35mm anamorphic lens with shallow depth of field and creamy background falloff."
        elif "ghibli" in style_key or "anime" in style_key:
            lighting_prose = "Painted volumetric sunlight filtering through the atmosphere, soft rim highlights, beautiful anime depth of field."
        elif "pixar" in style_key or "3d" in style_key:
            lighting_prose = "Soft studio-grade three-point lighting with gentle specular highlights, rich cinematic 3D depth of field."
        elif "stick" in style_key or "stickman" in style_key:
            lighting_prose = "Clean high-contrast vector lighting, sharp silhouette outlines, Alan Becker stick figure animation aesthetics."
        elif is_speaker_focus or detected_cam == "speaker_focus":
            lighting_prose = "Warm cinematic key light focused on the speaking character's face with soft 50mm f/1.8 shallow depth of field and creamy background bokeh."
        else:
            lighting_prose = "Atmospheric volumetric lighting with rich highlights and gentle shadow roll-off, shallow depth of field."

        # 8. Audio, SFX & Negative Prompt (Veo 3 Audio Standards)
        if is_commercial:
            audio_prose = "Audio: upbeat sophisticated ambient electronic rhythm, no lyrics."
            sfx_prose = "SFX: subtle tactile click, gentle smooth slider sound."
        elif "stick" in style_key or "stickman" in style_key:
            audio_prose = "Audio: crisp rhythmic ambient soundscape, subtle motion hum, no background music."
            sfx_prose = "SFX: snappy stick figure whoosh, subtle tactile impact sound."
        else:
            audio_prose = "Audio: natural atmospheric ambient soundscape, gentle ambient breeze, no background music."
            sfx_prose = "SFX: subtle realistic footsteps, gentle cloth movement."

        if "stick" in style_key or "stickman" in style_key:
            negative_prose = "Negative: photorealistic human, detailed facial features, realistic eyes, realistic skin, complex realistic clothing, 3D render, subtitles, captions, watermark, text overlay, jittery motion."
        else:
            negative_prose = "Negative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, extra fingers, jittery motion, blurry faces, abrupt camera snap."

        if not body_beats.endswith('.'):
            body_beats += '.'

        if is_placeholder:
            body_text = f"Medium shot of {subject_context_lower}. {camera_sentence} {body_beats} {lighting_prose}"
        else:
            body_text = f"{camera_sentence} {body_beats} {lighting_prose}"

        full_prompt = (
            f"{body_text}\n\n"
            f"{audio_prose}\n"
            f"{sfx_prose}\n"
            f"{negative_prose}"
        )

        full_prompt = re.sub(r' +', ' ', full_prompt)
        full_prompt = re.sub(r'\.\s*\.', '.', full_prompt)
        full_prompt = full_prompt.replace('\n ', '\n')

        return full_prompt.strip()

    @staticmethod
    def ensure_story_tied_narration(scene: Dict[str, Any], language: str = "en", story_context: str = "") -> str:
        """
        Guarantees that the scene's voiceover `narration` ties directly to the story's
        plot progression, character actions, and key spoken dialogue / punchlines.
        Prevents detached 3-5 word scenery stubs (e.g. 'Trời nhuộm màu cam', 'Máy gặt đến gần')
        and vague meta-summaries that omit key spoken dialogue or punchlines.
        """
        narr = str(scene.get("narration") or "").strip()
        vis = str(scene.get("visual_prompt") or "").strip()
        act = str(scene.get("acting_prompt") or "").strip()
        title = str(scene.get("title") or "").strip()
        is_vi = language.startswith("vi") or any(ord(c) > 127 for c in (narr or vis or title or story_context))

        # Extract spoken dialogue from acting_prompt if present
        spoken_quotes = re.findall(
            r'(?:character says|nhân vật nói|[A-Za-zÀ-ỹ\s]+(?:nói|hỏi|đáp|thưa)|says|whispers|murmurs|asks|replies|gasps|shouts|crying out|cries|explains|blurts|exclaims|mutters|calls out)[^:"“\n]{0,45}[:\s]+["“]([^"”]+)["”]',
            act,
            re.IGNORECASE
        )
        primary_quote = spoken_quotes[0].strip() if spoken_quotes else ""

        # Clean visual description of style boilerplates and speaker headers
        clean_vis = re.sub(
            r'(?i)^(?:một phân cảnh hoạt hình[^,.\n]*[,.\s]*|phong cách\s+[^,.\n]*[,.\s]*|photorealistic cinematic live-action|studio ghibli 2d|ghibli|anime|3d pixar|pixar 3d animation style|pixar|disney|comic book|cyberpunk|watercolor|retro 80s|pixel art|realistic)\s*(?:art|style)?[,.\s]*',
            '',
            vis
        )
        clean_vis = re.sub(r'(?i)\b(?:cinematic composition|rich atmospheric lighting|masterpiece (?:illustration|photography)|high fidelity details|intricate environmental details|tỉ lệ \d+:\d+|không chữ)\b[,.\s]*', '', clean_vis)
        clean_vis = re.sub(r'\s+', ' ', clean_vis).strip(' .,-')

        narr_words = narr.split()
        vis_sentences = [s.strip() for s in re.split(r'[.!?\n]+', clean_vis) if s.strip()]
        first_vis_sent = vis_sentences[0] if vis_sentences else ""

        # Detect if narration is missing or is a bare scenery stub (e.g. "Trời nhuộm màu cam", "Máy gặt đến gần", or exact first sentence of visual_prompt without story resolution)
        is_scenery_stub = (
            not narr or
            len(narr_words) <= 5 or
            (first_vis_sent and narr.rstrip('.!?').strip().lower() == first_vis_sent.lower() and (len(vis_sentences) > 1 or primary_quote))
        )

        if is_scenery_stub:
            # Build a story-tied narration from the full visual action + spoken dialogue
            action_sents = []
            for s in vis_sentences:
                # Skip pure 3-4 word weather stubs if there are real character action sentences
                if len(s.split()) <= 4 and len(vis_sentences) > 1 and any(w in s.lower() for w in ["trời", "ánh nắng", "mưa", "buổi sáng", "chiều", "sky", "sunlight", "morning"]):
                    continue
                # Strip raw ALL-CAPS dialogue blocks if accidentally leaked into visual
                s_clean = re.sub(r'\b[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]{2,}(?:\s+[A-ZÀ-Ỹ]{2,})*\s*(?:\([^\)]*\))?\s*', '', s).strip()
                if s_clean:
                    action_sents.append(s_clean)
                if len(" ".join(action_sents).split()) >= 16:
                    break

            base_story = ". ".join(action_sents).strip(' .')
            if not base_story and first_vis_sent:
                base_story = first_vis_sent.strip(' .')
            if not base_story:
                base_story = title or ("Câu chuyện tiếp diễn." if is_vi else "The story unfolds.")

            if primary_quote and primary_quote.lower() not in base_story.lower():
                quote_is_vi = any(ord(c) > 127 for c in primary_quote)
                if is_vi == quote_is_vi:
                    narr = f'{base_story}: "{primary_quote}"'
                else:
                    narr = f"{base_story}."
            else:
                narr = f"{base_story}."

        elif primary_quote:
            # Ensure spoken dialogue from acting_prompt is included in voiceover narration when not already present
            quote_is_vi = any(ord(c) > 127 for c in primary_quote)
            has_quote_in_narr = ('"' in narr or '“' in narr or '”' in narr or primary_quote.lower().rstrip('.!?') in narr.lower())
            if not has_quote_in_narr and (is_vi == quote_is_vi):
                lower_narr = narr.lower()
                clean_n = narr.rstrip(' .!?')
                if is_vi:
                    speech_endings_vi = (
                        "hỏi", "nói", "thưa", "đáp", "kêu lên", "thốt lên", "trình báo",
                        "giải thích", "thì thầm", "bẩm", "than", "gọi", "bảo"
                    )
                    if any(clean_n.lower().endswith(w) for w in speech_endings_vi):
                        narr = f'{clean_n}: "{primary_quote}"'
                    elif (
                        any(w in lower_narr for w in ["hai tên trộm", "bọn trộm", "kẻ trộm tinh ranh", "chúng nhìn nhau", "chúng phối hợp", "khiêng nguyên", "lén", "âm thầm", "chúng dắt"])
                        and not any(w in lower_narr for w in ["chẳng tên trộm", "trình báo", "công đường", "quan huyện"])
                    ):
                        narr = f'{clean_n}, khẽ bảo nhau: "{primary_quote}"'
                    elif "ngủ" in lower_narr and not any(w in lower_narr for w in ["hai tên trộm", "bọn trộm", "khiêng"]):
                        narr = f'{clean_n}, khẽ mớ: "{primary_quote}"'
                    elif primary_quote.endswith("?") and not any(w in lower_narr for w in ["hỏi", "thắc mắc"]):
                        narr = f'{clean_n}, thốt lên: "{primary_quote}"'
                    else:
                        narr = f'{clean_n}: "{primary_quote}"'
                else:
                    narr = f'{clean_n}: "{primary_quote}"'

        if narr and not narr.endswith(('.', '!', '?', '"', '”', '…')):
            narr += "."
        scene["narration"] = narr
        return narr

    @staticmethod
    def extract_story_dialogues(idea_text: str) -> List[Dict[str, Any]]:
        """
        Extracts character dialogues from raw story prose or screenplay text.
        Supports:
        1. Screenplay speaker blocks (ALL-CAPS speaker header followed by dialogue line)
        2. Dash-prefixed dialogue lines (– / - / — common in Vietnamese & European stories)
        3. Quoted dialogue in narrative prose ("..." or “...”)
        Returns list of dicts: {"speaker": str, "tone": str, "intro": str, "line": str, "scene_num": Optional[int]}
        """
        if not idea_text or not str(idea_text).strip():
            return []

        raw_lines = [ln.strip() for ln in str(idea_text).splitlines()]
        extracted: List[Dict[str, Any]] = []
        current_scene_num = None
        last_narrative = ""

        scene_header_re = re.compile(
            r'^(?:\*{0,2})(?:CẢNH|PHÂN CẢNH|SCENE)\s*(?:(\d+)|CUỐI|KẾT)(?:\*{0,2})(?:\s*[:\-–—\s]\s*(.*))?$',
            re.IGNORECASE
        )
        speaker_re = re.compile(
            r'^([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ][A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ\s\d\.]{1,28}?)(?:\s*\(([^\)]+)\))?\s*$'
        )
        meta_prefixes = (
            "thể loại:", "thời lượng:", "bối cảnh:", "thông điệp:", "nhân vật",
            "hình ảnh:", "âm thanh:", "âm nhạc:", "góc máy:", "ánh sáng:", "chữ trên màn hình"
        )
        section_headers = {
            "mở đầu", "phát triển", "cao trào", "kết", "kết thúc", "hết", "hết.",
            "act 1", "act 2", "act 3", "intro", "climax", "outro", "ending"
        }

        idx = 0
        scene_counter = 0
        while idx < len(raw_lines):
            ln = raw_lines[idx]
            if not ln:
                idx += 1
                continue

            m_sc = scene_header_re.match(ln)
            if m_sc:
                scene_counter += 1
                current_scene_num = int(m_sc.group(1)) if m_sc.group(1) else scene_counter
                last_narrative = ""
                idx += 1
                continue

            if ln.lower().strip(' .:') in section_headers or any(ln.lower().startswith(p) for p in meta_prefixes):
                idx += 1
                continue

            # 1. Screenplay ALL-CAPS speaker line followed by dialogue
            m_spk = speaker_re.match(ln)
            if m_spk and idx + 1 < len(raw_lines) and raw_lines[idx + 1]:
                spk_cand = m_spk.group(1).strip()
                if spk_cand.upper() not in ("CHỮ TRÊN MÀN HÌNH", "TEXT ON SCREEN", "SUPER", "TITLE", "NHÂN VẬT", "MỞ ĐẦU", "CAO TRÀO", "KẾT"):
                    spk_name = spk_cand.title()
                    spk_tone = (m_spk.group(2) or "").strip()
                    dial_line = raw_lines[idx + 1].strip(' "“”')
                    if dial_line:
                        extracted.append({
                            "speaker": spk_name,
                            "tone": spk_tone,
                            "intro": last_narrative,
                            "line": dial_line,
                            "scene_num": current_scene_num
                        })
                    last_narrative = ""
                    idx += 2
                    continue

            # 1b. Screenplay or prose inline "Speaker: Dialogue line" (e.g. "Bà Tư: Tư ơi, tin gì..." or "Ông Tư: Tin Mỹ đó bà...")
            m_spk_inline = re.match(r'^([A-ZÀ-ỹa-zà-ỹ0-9_\s]{2,28})\s*:\s*(.+)$', ln)
            if m_spk_inline:
                spk_cand = m_spk_inline.group(1).strip()
                dial_cand = m_spk_inline.group(2).strip(' "“”')
                if (
                    dial_cand
                    and spk_cand.lower() not in ("tiêu đề", "title", "bối cảnh", "setting", "thời lượng", "duration", "thể loại", "genre", "nhân vật", "characters", "hình ảnh", "âm thanh")
                    and not any(dial_cand.lower().startswith(p) for p in meta_prefixes)
                ):
                    extracted.append({
                        "speaker": spk_cand.strip(),
                        "tone": "",
                        "intro": last_narrative,
                        "line": dial_cand,
                        "scene_num": current_scene_num
                    })
                    last_narrative = ""
                    idx += 1
                    continue

            # 2. Dash-prefixed dialogue line (– ... or - ... or — ...)
            m_dash = re.match(r'^[–\-—]\s*(.+)$', ln)
            if m_dash:
                d_text = m_dash.group(1).strip(' "“”')
                # Filter out pure 3rd-person narrator transition bullets (e.g. "- Hát rồi vẫn yêu cầu hát nữa, đã ba bốn lần nhưng khán giả vẫn không chịu cho nghỉ.")
                is_narrator_bullet = bool(
                    re.search(r'\b(?:khán giả vẫn không chịu|đã ba bốn lần nhưng|nhưng không ai chịu)\b', d_text, re.IGNORECASE)
                    and not d_text.endswith(('?', '!'))
                )
                if d_text and not is_narrator_bullet and not any(d_text.lower().startswith(p) for p in meta_prefixes):
                    extracted.append({
                        "speaker": "",
                        "tone": "",
                        "intro": last_narrative,
                        "line": d_text,
                        "scene_num": current_scene_num
                    })
                last_narrative = ""
                idx += 1
                continue

            # 3. Inline quoted dialogue in prose (preceded by speech context or >= 4 words)
            inline_quotes = re.findall(r'([^"“”\n]{0,60})["“]([^"”]{3,})["”]', ln)
            added_inline = False
            for prefix_ctx, q_str in inline_quotes:
                q_clean = q_str.strip()
                has_speech_verb = bool(re.search(
                    r'\b(?:nói|hỏi|đáp|thưa|kêu|thì thầm|thốt|bẩm|gọi|bảo|mớ|said|asked|replied|whispered|shouted|exclaimed|cried|says|asks)\b',
                    prefix_ctx or last_narrative,
                    re.IGNORECASE
                ))
                if has_speech_verb or len(q_clean.split()) >= 5 or q_clean.endswith(('?', '!')):
                    extracted.append({
                        "speaker": "",
                        "tone": "",
                        "intro": (prefix_ctx.strip(' :,-') or last_narrative),
                        "line": q_clean,
                        "scene_num": current_scene_num
                    })
                    added_inline = True

            if not added_inline:
                # Only keep narrative intro lines that introduce speech (not stray web questions or headers)
                if (
                    not re.match(r'^(?:truyện cười|tiêu đề|nguồn)\s*:', ln, re.IGNORECASE)
                    and not ln.endswith('?')
                    and (ln.endswith(':') or re.search(r'\b(?:trình|hỏi|thưa|nói|đáp|kêu|bẩm|lắp bắp|giải thích)\b', ln, re.IGNORECASE))
                ):
                    last_narrative = ln.rstrip(' :').split('.')[-1].strip()
                else:
                    last_narrative = ""
            idx += 1

        return extracted

    @staticmethod
    def extract_scene_dialogue_segments(
        narration: str,
        characters: Union[List[str], str, None] = None,
        narrator_name: str = "Narrator",
        matched_dialogues: List[Dict[str, Any]] = None
    ) -> List[Dict[str, str]]:
        """
        Extracts structured speaker segments from scene narration for multi-voice synthesis.
        Splits between third-person narrator lines and authentic quoted character dialogue.
        """
        if not narration or not narration.strip():
            return []

        clean_narr = narration.strip()
        chars = []
        if isinstance(characters, list):
            chars = [str(c).strip() for c in characters if c and str(c).strip() and str(c).lower() not in ("narrator", "người kể chuyện", "character")]
        elif isinstance(characters, str) and characters.strip():
            for p in re.split(r'[|\n]+', characters):
                m_c = re.match(r'^(?:[A-Za-z0-9_\s]+:)?\s*([^,:\(\)]+)', p.strip())
                if m_c:
                    c_n = m_c.group(1).strip()
                    if c_n and c_n.lower() not in ("narrator", "người kể chuyện", "character"):
                        chars.append(c_n)

        # 1. If explicit matched dialogues exist from story analysis, segment based on them
        if matched_dialogues:
            segments = []
            curr_text = clean_narr
            for md in matched_dialogues:
                d_line = (md.get("line") or "").strip(' "“”')
                spk = (md.get("speaker") or "").strip()
                if not d_line:
                    continue
                pos = curr_text.find(d_line)
                prefix_candidate = curr_text[:pos].rstrip(' "“”:\t\n') if pos != -1 else curr_text

                # If speaker is missing or generic "Character", resolve using known character roster & prefix
                if not spk or spk.lower() == "character":
                    found_spk = None
                    if chars:
                        matched_chars = []
                        for c in chars:
                            p_idx = prefix_candidate.lower().find(c.lower())
                            if p_idx != -1:
                                matched_chars.append((p_idx, c))
                        if matched_chars:
                            matched_chars.sort(key=lambda x: x[0])
                            found_spk = matched_chars[0][1]
                    spk = found_spk or (chars[0] if len(chars) == 1 else "Character")

                if pos != -1:
                    prefix = curr_text[:pos].rstrip(' "“”:\t\n')
                    if prefix:
                        segments.append({"speaker": narrator_name, "text": prefix})
                    segments.append({"speaker": spk, "text": d_line})
                    curr_text = curr_text[pos + len(d_line):].lstrip(' "“”\t\n')
                else:
                    segments.append({"speaker": spk, "text": d_line})
            if curr_text.strip(' "“”'):
                segments.append({"speaker": narrator_name, "text": curr_text.strip(' "“”')})
            if segments:
                return segments

        # 2. Extract quotes with speaker heuristic
        quote_pattern = re.compile(r'([^"“”\n]*?)["“]([^"”]+)["”]')
        segments = []
        last_end = 0

        for match in quote_pattern.finditer(clean_narr):
            prefix = match.group(1).strip()
            quote = match.group(2).strip()

            speaker = "Character"
            found_char = None
            if chars:
                matched_chars = []
                for c in chars:
                    p_pos = prefix.lower().find(c.lower())
                    if p_pos != -1:
                        matched_chars.append((p_pos, c))
                if matched_chars:
                    matched_chars.sort(key=lambda x: x[0])
                    found_char = matched_chars[0][1]

            if found_char:
                speaker = found_char
            else:
                # 1. Check capitalized subject at beginning of prefix (e.g. "Bà Tư bước đến gần...", "Ông Tư ngước lên...")
                m_lead = re.match(r'^([A-ZÀ-ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-ỹ][a-zà-ỹ]+){0,3})\b', prefix.strip())
                if m_lead and m_lead.group(1).lower() not in (
                    "buổi", "sau", "khi", "trong", "tại", "một", "hai", "bỗng", "lúc",
                    "người", "nhưng", "rồi", "vừa", "đoạn", "hồi", "thế", "còn", "thì",
                    "the", "after", "when", "in", "at", "one", "suddenly", "then", "while"
                ):
                    speaker = m_lead.group(1).strip()
                else:
                    m_spk = re.search(
                        r'([A-Za-zÀ-ỹ\s]{2,25})\s*(?:thưa|nói|hỏi|đáp|kêu|bảo|quát|la|cười|mắng|than|nghĩ|lắp bắp|chữa cháy|thốt|chia sẻ|phân tích|tuyên bố|gặng hỏi|said|asked|replied|shouted|exclaimed|gasped|yelled)',
                        prefix,
                        re.IGNORECASE
                    )
                    if m_spk:
                        cand = m_spk.group(1).strip()
                        cand = re.sub(r'\b(?:liền|bèn|vội|hớt hải|ngơ ngác|sợ hãi|tức giận)\b', '', cand, flags=re.IGNORECASE).strip()
                        if cand:
                            speaker = cand.title()
                    elif ':' in prefix:
                        cand = prefix.split(':')[-1].strip()
                        if 2 <= len(cand) <= 25:
                            speaker = cand.title()
                    elif len(chars) == 1:
                        speaker = chars[0]

            if prefix:
                segments.append({"speaker": narrator_name, "text": prefix})
            if quote:
                segments.append({"speaker": speaker, "text": quote})
            last_end = match.end()

        remainder = clean_narr[last_end:].strip(' \t\n')
        if remainder:
            segments.append({"speaker": narrator_name, "text": remainder})

        if not segments:
            segments.append({"speaker": narrator_name, "text": clean_narr})

        return segments

    @staticmethod
    def auto_assign_character_voices(
        characters_str: str = "",
        scenes: List[Dict[str, Any]] = None,
        language: str = "vi",
        narrator_voice: str = None,
        existing_voices: Dict[str, str] = None
    ) -> Dict[str, str]:
        """
        Intelligently analyzes the story character roster and dialogue speakers,
        detecting gender, age (child, adult, elder), and personality archetype,
        then casts distinct, highly expressive voices from the voice catalog.
        """
        character_voices = dict(existing_voices or {})

        # Default narrator voice
        if "Narrator" not in character_voices or not character_voices["Narrator"]:
            if narrator_voice:
                character_voices["Narrator"] = narrator_voice
            elif (language or "").startswith("vi"):
                character_voices["Narrator"] = "vi-VN-HoaiMyNeural-story"
            else:
                character_voices["Narrator"] = "en-US-ChristopherNeural"

        char_names = []
        if characters_str:
            parts = re.split(r'[|\n]+', characters_str)
            for p in parts:
                p_strip = p.strip()
                if not p_strip:
                    continue
                m = re.match(r'^(?:[A-Za-z0-9_\s]+:)?\s*([^,:\(\)]+)', p_strip)
                if m:
                    c_name = m.group(1).strip()
                    if c_name and c_name.lower() not in ("narrator", "người kể chuyện", "bối cảnh", "setting", "title", "character"):
                        if c_name not in char_names:
                            char_names.append(c_name)

        if scenes:
            for sc in scenes:
                d_list = sc.get("dialogues") or []
                for d in d_list:
                    spk = (d.get("speaker") or "").strip()
                    if spk and spk.lower() not in ("narrator", "người kể chuyện", "none", "", "character") and spk not in char_names:
                        char_names.append(spk)

        assigned_voices = set(character_voices.values())

        # Curated pools for Vietnamese
        male_energetic_pool = ["vi-VN-NamMinhNeural-energetic", "gemini-Puck", "vi-VN-NamMinhNeural"]
        male_heroic_pool = ["vi-VN-NamMinhNeural-heroic", "gemini-Fenrir", "gemini-Charon", "vi-VN-NamMinhNeural-documentary"]
        male_elder_pool = ["vi-VN-NamMinhNeural-elder", "vi-VN-NamMinhNeural-story", "gemini-Orus"]
        male_standard_pool = ["vi-VN-NamMinhNeural", "gemini-Enceladus", "vi-VN-NamMinhNeural-commercial"]

        female_energetic_pool = ["vi-VN-HoaiMyNeural-energetic", "gemini-Zephyr", "gemini-Leda"]
        female_sweet_pool = ["vi-VN-HoaiMyNeural-sweet", "gemini-Callirrhoe", "gemini-Kore"]
        female_elder_pool = ["vi-VN-HoaiMyNeural-elder", "vi-VN-HoaiMyNeural-story"]
        female_drama_pool = ["vi-VN-HoaiMyNeural-drama", "gemini-Aoede", "vi-VN-HoaiMyNeural-commercial"]
        female_standard_pool = ["vi-VN-HoaiMyNeural", "gtts-vi"]

        # English pools
        en_male_pool = ["en-US-GuyNeural", "en-GB-RyanNeural", "en-US-ChristopherNeural"]
        en_female_pool = ["en-US-JennyNeural", "en-GB-SoniaNeural", "en-US-AriaNeural"]

        def pick_from_pool(pool):
            for vid in pool:
                if vid not in assigned_voices:
                    assigned_voices.add(vid)
                    return vid
            return pool[0]

        is_vi = (language or "").startswith("vi")

        for name in char_names:
            if name in character_voices and character_voices[name]:
                continue

            context = ""
            for p in re.split(r'[|\n]+', characters_str or ""):
                if name.lower() in p.lower():
                    context = p.lower()
                    break
            low_name = f"{name} {context}".lower()

            is_elder = any(w in low_name for w in ["ông", "cụ", "bà lão", "già", "bụt", "tiên", "old", "elder", "grandfather", "grandmother"])
            is_child_energetic = any(w in low_name for w in ["bé", "nhỏ", "tí", "khôi", "con", "child", "young boy", "kid", "boy", "lively", "energetic"])
            is_female = any(w in low_name for w in ["cô", "bé gái", "nữ", "mẹ", "bà", "nàng", "chị", "em gái", "lan", "phương", "mai", "hoa", "girl", "woman", "mother", "female", "princess", "queen", "daughter", "lady"])
            is_heroic_official = any(w in low_name for w in ["quan", "huyện", "đại nhân", "tướng", "vua", "hoàng đế", "phán quan", "thẩm phán", "heroic", "magistrate", "judge", "king", "general", "warrior"])

            if is_vi:
                if is_female:
                    if is_elder:
                        voice = pick_from_pool(female_elder_pool)
                    elif is_child_energetic:
                        voice = pick_from_pool(female_energetic_pool)
                    elif any(w in low_name for w in ["kịch tính", "ác", "tức giận", "drama", "giận"]):
                        voice = pick_from_pool(female_drama_pool)
                    else:
                        voice = pick_from_pool(female_sweet_pool)
                else:
                    if is_elder:
                        voice = pick_from_pool(male_elder_pool)
                    elif is_heroic_official:
                        voice = pick_from_pool(male_heroic_pool)
                    elif is_child_energetic:
                        voice = pick_from_pool(male_energetic_pool)
                    else:
                        voice = pick_from_pool(male_standard_pool)
            else:
                if is_female:
                    voice = pick_from_pool(en_female_pool)
                else:
                    voice = pick_from_pool(en_male_pool)

            character_voices[name] = voice

        return character_voices

    @staticmethod
    def sync_story_dialogues_to_scenes(
        scenes: List[Dict[str, Any]],
        idea: str = "",
        art_style: str = "ghibli",
        language: str = "en",
        target: str = "all",
        target_scene_idx: int = None,
        auto_invent: bool = False,
        characters: Union[List[str], str, None] = None,
        camera_on_speaker: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Extracts dialogues from the story (`idea`) and scene fields, and synchronizes/adds them to:
        - `narration` (Voiceover Narration): weaves authentic character dialogue(s) into the scene voiceover
        - `visual_prompt` (Image Prompt): adds expressive character dialogue/speaking visual cues
        - `acting_prompt` (Video Clip Prompt): embeds the spoken dialogue into the 3-6s performance beat
        `target`: "all" | "narration" | "clip" | "image"
        """
        if not scenes or not isinstance(scenes, list):
            return scenes

        target_norm = (target or "all").lower().strip()
        update_narration = target_norm in ("all", "narration", "voiceover")
        update_image = target_norm in ("all", "clip", "image", "image_clip", "video")
        update_clip = target_norm in ("all", "clip", "video", "image_clip")

        story_dialogues = ScriptAgent.extract_story_dialogues(idea) if idea else []

        char_names_list = []
        if isinstance(characters, list):
            char_names_list = [str(c).strip() for c in characters if c and str(c).strip() and str(c).lower() not in ("narrator", "character")]
        elif isinstance(characters, str) and characters.strip():
            for p in re.split(r'[|\n]+', characters):
                m_c = re.match(r'^(?:[A-Za-z0-9_\s]+:)?\s*([^,:\(\)]+)', p.strip())
                if m_c:
                    c_n = m_c.group(1).strip()
                    if c_n and c_n.lower() not in ("narrator", "người kể chuyện", "character"):
                        char_names_list.append(c_n)
        if not char_names_list and story_dialogues:
            for d in story_dialogues:
                spk = (d.get("speaker") or "").strip()
                if spk and spk.lower() not in ("narrator", "người kể chuyện", "character") and spk not in char_names_list:
                    char_names_list.append(spk)

        # Helper to tokenize Vietnamese/English content words for matching
        stop_words = {
            "và", "của", "những", "một", "các", "trong", "cho", "với", "được", "này", "đó",
            "thì", "mà", "là", "có", "không", "ra", "vào", "lên", "xuống", "đi", "lại",
            "con", "chúng", "nó", "anh", "ta", "cái", "chiếc",
            "the", "and", "for", "with", "that", "this", "from", "into", "his", "her", "their"
        }

        def get_tokens(txt: str) -> set:
            words = re.findall(r'[a-zA-ZÀ-ỹ0-9]+', (txt or "").lower())
            return {w for w in words if len(w) >= 2 and w not in stop_words}

        # Map story_dialogues to scene indices
        scene_dialogue_map: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(len(scenes))}

        if story_dialogues:
            has_explicit_scene_nums = any(d.get("scene_num") is not None for d in story_dialogues)
            if has_explicit_scene_nums:
                for d in story_dialogues:
                    sc_num = d.get("scene_num")
                    if sc_num is not None and 1 <= sc_num <= len(scenes):
                        scene_dialogue_map[sc_num - 1].append(d)
            else:
                # Prose story dialogues: determine which scenes are conversational/dialogue scenes
                # (e.g., courtroom scenes mentioning quan/trình/khai/hỏi/thưa/giải thích) vs pure setup scenes
                all_dial_text = " ".join(f"{d.get('intro', '')} {d.get('line', '')}" for d in story_dialogues).lower()
                is_courtroom_conversation = ("bẩm quan" in all_dial_text or "trình quan" in all_dial_text)

                candidate_scene_indices = []
                if is_courtroom_conversation:
                    for sc_idx, sc in enumerate(scenes):
                        sc_combined = f"{sc.get('title', '')} {sc.get('narration', '')} {sc.get('visual_prompt', '')}".lower()
                        if any(k in sc_combined for k in ["quan", "trình", "kiện", "khai", "phán", "tòa", "courthouse", "magistrate", "courtroom", "judge"]):
                            candidate_scene_indices.append(sc_idx)

                if not candidate_scene_indices:
                    candidate_scene_indices = list(range(len(scenes)))

                min_allowed_sc_idx = candidate_scene_indices[0]
                num_d = len(story_dialogues)
                num_cand = len(candidate_scene_indices)

                for d_idx, d in enumerate(story_dialogues):
                    d_tokens = get_tokens(f"{d.get('intro', '')} {d.get('line', '')}")
                    d_line_tokens = get_tokens(d.get("line", ""))
                    rel_d = d_idx / max(1, num_d - 1)
                    best_sc_idx = None
                    best_score = -999.0

                    for cand_pos, sc_idx in enumerate(candidate_scene_indices):
                        if sc_idx < min_allowed_sc_idx:
                            continue
                        sc = scenes[sc_idx]
                        sc_narr = str(sc.get("narration") or "")
                        sc_act = str(sc.get("acting_prompt") or "")
                        sc_title = str(sc.get("title") or "")
                        sc_vis = str(sc.get("visual_prompt") or "")

                        # Extract existing quote in scene acting_prompt or narration (excluding previously synced full quotes)
                        base_sc_narr = re.split(r'\s*:\s*["“]', sc_narr)[0]
                        existing_quotes = re.findall(r'["“\']([^"”\']{2,})["”\']', f"{sc_act} {sc_narr}")
                        quote_tokens = get_tokens(" ".join(q for q in existing_quotes if len(q.split()) <= 16))
                        narr_tokens = get_tokens(f"{base_sc_narr} {sc_title}")
                        full_narr_tokens = get_tokens(sc_narr)
                        vis_tokens = get_tokens(sc_vis)

                        # Weighted token overlap + chronological story progression alignment
                        overlap_quote = len(d_line_tokens & quote_tokens) * 4.0
                        overlap_narr = len(d_tokens & narr_tokens) * 2.5
                        overlap_full_narr = len(d_line_tokens & full_narr_tokens) * 3.5
                        overlap_vis = len(d_tokens & vis_tokens) * 0.5
                        rel_sc = cand_pos / max(1, num_cand - 1)
                        chrono_bonus = (1.0 - abs(rel_d - rel_sc)) * 8.0

                        score = overlap_quote + overlap_narr + overlap_full_narr + overlap_vis + chrono_bonus
                        if d_line_tokens and len(d_line_tokens & full_narr_tokens) >= max(2, int(len(d_line_tokens) * 0.65)):
                            score += 20.0
                        d_line_low = d.get("line", "").lower()
                        narr_title_low = f"{base_sc_narr} {sc_title}".lower()

                        # Speaker-role alignment (petitioner vs magistrate/judge)
                        if "bẩm quan" in d_line_low:
                            if any(k in narr_title_low for k in ["trình", "thưa", "khai", "kiện"]):
                                score += 8.0
                            if any(k in narr_title_low for k in ["quan huyện liền", "phán quyết", "giải thích rằng"]):
                                score -= 10.0
                        elif any(k in d_line_low for k in ["mày ", "ngươi "]):
                            if any(k in narr_title_low for k in ["quan huyện liền", "phán quyết", "giải thích"]):
                                score += 8.0

                        if re.search(r'\b(?:trình|quan|hỏi|thưa|đáp|giải thích|lắp bắp|ngớ người|kinh khiếp|nói|kêu)\b', base_sc_narr.lower()):
                            score += 1.5
                        if num_cand >= 2:
                            score -= len(scene_dialogue_map[sc_idx]) * 5.0
                        if score > best_score:
                            best_score = score
                            best_sc_idx = sc_idx

                    if best_sc_idx is not None and best_score >= 3.0:
                        scene_dialogue_map[best_sc_idx].append(d)
                        # Advance min_allowed_sc_idx gradually so earlier dialogues cannot skip over intermediate dialogue scenes
                        if best_sc_idx > min_allowed_sc_idx:
                            min_allowed_sc_idx = min(best_sc_idx, min_allowed_sc_idx + 1)

                # Ensure conversational reply lines (like Magistrate's retort right after cowherd's report)
                # are paired with their preceding question/report scene if unassigned
                for d_i, d_item in enumerate(story_dialogues):
                    if not any(d_item in d_list for d_list in scene_dialogue_map.values()):
                        # Prefer the scene assigned to the immediately preceding dialogue (d_i - 1)
                        placed = False
                        for prev_i in range(d_i - 1, -1, -1):
                            prev_d = story_dialogues[prev_i]
                            for sc_i, d_list in scene_dialogue_map.items():
                                if prev_d in d_list:
                                    scene_dialogue_map[sc_i].append(d_item)
                                    placed = True
                                    break
                            if placed:
                                break
                        if not placed and candidate_scene_indices:
                            scene_dialogue_map[candidate_scene_indices[0]].append(d_item)

        # Now process each scene
        for idx, sc in enumerate(scenes):
            if target_scene_idx is not None and idx != target_scene_idx:
                continue

            narr = str(sc.get("narration") or "").strip()
            vis = str(sc.get("visual_prompt") or "").strip()
            act = str(sc.get("acting_prompt") or "").strip()
            title = str(sc.get("title") or f"Scene {idx + 1}").strip()
            camera = str(sc.get("camera_motion") or "zoom_in").strip()
            is_vi = language.startswith("vi") or any(ord(c) > 127 for c in (narr or vis or title or idea))

            matched_d = scene_dialogue_map.get(idx, [])

            # Extract any existing spoken quote from acting_prompt and narration
            act_quotes = re.findall(
                r'(?:character says|nhân vật nói|[A-Za-zÀ-ỹ\s]+(?:nói|hỏi|đáp|thưa)|says|whispers|murmurs|asks|replies|gasps|shouts|crying out|cries|explains|blurts|exclaims|mutters|calls out)[^:"“\n]{0,45}[:\s]+["“]([^"”]+)["”]',
                act,
                re.IGNORECASE
            )
            narr_quotes = re.findall(r'["“]([^"”]{2,})["”]', narr)

            primary_clip_quote = ""
            if matched_d:
                # Build authentic story dialogue string for narration and clip
                if len(matched_d) == 1:
                    d_line = matched_d[0]["line"].strip()
                    spk = matched_d[0].get("speaker", "").strip()
                    primary_clip_quote = d_line
                    if update_narration:
                        d_toks = get_tokens(d_line)
                        n_toks = get_tokens(narr)
                        already_in_narr = (
                            d_line.lower().rstrip('.!?…') in narr.lower()
                            or (d_toks and len(d_toks & n_toks) >= max(2, int(len(d_toks) * 0.75)))
                        )
                        if not already_in_narr:
                            # Strip any abbreviated/synthetic trailing quote in narration (e.g. : "Bẩm quan con mất bò.")
                            base_narr = re.split(r'\s*:\s*["“]', narr)[0].strip(' .!?')
                            if not base_narr:
                                base_narr = narr.rstrip(' .!?')
                            narr = f'{base_narr}: "{d_line}"'
                else:
                    # Multiple dialogues in this scene
                    has_screenplay_speakers = any(d.get("speaker") for d in matched_d)
                    if has_screenplay_speakers and narr_quotes:
                        primary_clip_quote = narr_quotes[-1] if len(narr_quotes[0].split()) <= 3 and len(narr_quotes) > 1 else narr_quotes[0]
                    else:
                        is_courtroom_sc = any(k in f"{narr} {title}".lower() for k in ["quan", "công đường", "trình", "bẩm quan", "tòa"])
                        if len(matched_d) >= 3 and len(scenes) <= 4 and is_courtroom_sc:
                            selected_lines = [matched_d[0]["line"], matched_d[-2]["line"], matched_d[-1]["line"]]
                            primary_clip_quote = matched_d[-1]["line"]
                            if update_narration:
                                base_narr = re.split(r'\s*:\s*["“]', narr)[0].strip(' .!?')
                                narr = (
                                    f'{base_narr}: "{selected_lines[0]}" '
                                    f'Quan giải thích: "{selected_lines[1]}" '
                                    f'Chàng trai kinh hãi hỏi: "{selected_lines[2]}"'
                                )
                        else:
                            d1 = matched_d[0]["line"].strip()
                            d2 = matched_d[1]["line"].strip()
                            primary_clip_quote = d2 if "bẩm quan" in d2.lower() else d1
                            if update_narration:
                                base_narr = re.split(r'\s*:\s*["“]', narr)[0].strip(' .!?')
                                if is_courtroom_sc and "bẩm quan" in d2.lower() and "thưa" in base_narr.lower():
                                    first_intro = matched_d[0].get("intro") or ("Quan ngơ ngác hỏi" if is_vi else "The magistrate asks")
                                    narr = f'{first_intro}: "{d1}" {base_narr}: "{d2}"'
                                elif is_courtroom_sc:
                                    reply_intro = matched_d[1].get("intro") or (
                                        "Anh thưa" if "bẩm quan" in d2.lower() else ("Quan hỏi lại" if is_vi else "They reply")
                                    )
                                    narr = f'{base_narr}: "{d1}" {reply_intro}: "{d2}"'
                                else:
                                    reply_intro = matched_d[1].get("intro") or ("Rồi đáp" if is_vi else "Then replies")
                                    narr = f'{base_narr}: "{d1}" {reply_intro}: "{d2}"'
            else:
                # No story-level dialogue mapped from `idea`; sync between `narration` and `acting_prompt`
                if narr_quotes:
                    primary_clip_quote = narr_quotes[-1] if len(narr_quotes) > 1 and len(narr_quotes[0].split()) <= 3 else narr_quotes[0]
                elif act_quotes:
                    primary_clip_quote = act_quotes[0].strip()
                    if update_narration:
                        sc["narration"] = narr
                        narr = ScriptAgent.ensure_story_tied_narration(sc, language="vi" if is_vi else language)
                elif auto_invent:
                    # User explicitly clicked +Dialogue on a scene without existing dialogue: derive a natural line
                    clean_base = narr.rstrip(' .!?')
                    if is_vi:
                        derived_line = f"{title}!" if len(title.split()) >= 2 else "Thật tuyệt vời!"
                        if update_narration:
                            narr = f'{clean_base}: "{derived_line}"'
                        primary_clip_quote = derived_line
                    else:
                        derived_line = f"{title}!" if len(title.split()) >= 2 else "This changes everything!"
                        if update_narration:
                            narr = f'{clean_base}: "{derived_line}"'
                        primary_clip_quote = derived_line

            if narr and not narr.endswith(('.', '!', '?', '"', '”', '…')):
                narr += "."
            if update_narration:
                sc["narration"] = narr

            # Populate / sync structured dialogue segments for multi-voice casting
            sc["dialogues"] = ScriptAgent.extract_scene_dialogue_segments(
                narration=sc.get("narration", narr),
                characters=char_names_list,
                narrator_name="Narrator",
                matched_dialogues=matched_d
            )

            # Identify active speaking character in this scene
            active_speaker = ""
            for d_seg in (sc.get("dialogues") or []):
                s_cand = (d_seg.get("speaker") or "").strip()
                if s_cand and s_cand.lower() not in ("narrator", "người kể chuyện", "character", "none"):
                    active_speaker = s_cand
                    break

            is_speaker_focus = bool(camera_on_speaker or art_style == "dialogue_cinema" or camera == "speaker_focus")
            if is_speaker_focus and primary_clip_quote:
                camera = "speaker_focus"
                sc["camera_motion"] = "speaker_focus"

            # Update Image Prompt (`visual_prompt`) with expressive dialogue visual cues if scene has dialogue
            if update_image and primary_clip_quote and vis:
                vis_is_vi = any(ord(c) > 127 for c in vis)
                if is_speaker_focus and active_speaker:
                    if vis_is_vi:
                        spk_prefix = f"Góc máy cận cảnh tập trung trực tiếp vào {active_speaker} đang nói chuyện, "
                        if active_speaker.lower() not in vis[:45].lower() and "góc máy cận cảnh tập trung" not in vis.lower():
                            vis = spk_prefix + vis
                    else:
                        spk_prefix = f"Medium close-up camera focused directly on {active_speaker} speaking, "
                        if active_speaker.lower() not in vis[:55].lower() and "camera focused directly on" not in vis.lower():
                            vis = spk_prefix + vis
                if vis_is_vi:
                    if "biểu cảm đối thoại" not in vis.lower() and "khẩu hình" not in vis.lower():
                        vis = vis.rstrip(' .') + ", biểu cảm gương mặt và khẩu hình đối thoại sinh động, ánh mắt giao tiếp tự nhiên, không bong bóng thoại, không chữ."
                else:
                    if "expressive speaking" not in vis.lower() and "dialogue expression" not in vis.lower():
                        vis = vis.rstrip(' .') + ", expressive speaking pose and vivid facial dialogue expression, natural conversational gesture, no speech bubbles, no text."
                sc["visual_prompt"] = vis

            # Update Video Clip Prompt (`acting_prompt`) with the authentic spoken dialogue
            if update_clip and primary_clip_quote:
                words = primary_clip_quote.split()
                clip_quote_trimmed = " ".join(words[:16]).rstrip(' ,;:-') + "..." if len(words) > 18 else primary_clip_quote
                if re.search(
                    r'(?:character says|nhân vật nói|[A-Za-zÀ-ỹ\s]+(?:nói|hỏi|đáp|thưa)|says|whispers|murmurs|asks|replies|gasps|shouts|crying out|cries|explains|blurts|exclaims|mutters|calls out)[^:"“\n]{0,45}[:\s]+["“][^"”]+["”]',
                    act,
                    re.IGNORECASE
                ):
                    act = re.sub(
                        r'((?:character says|nhân vật nói|[A-Za-zÀ-ỹ\s]+(?:nói|hỏi|đáp|thưa)|says|whispers|murmurs|asks|replies|gasps|shouts|crying out|cries|explains|blurts|exclaims|mutters|calls out)[^:"“\n]{0,45}[:\s]+["“])([^"”]+)(["”])',
                        lambda m: f"{m.group(1)}{clip_quote_trimmed}{m.group(3)}",
                        act,
                        count=1,
                        flags=re.IGNORECASE
                    )
                if active_speaker:
                    act = re.sub(r'\bCharacter says\b', f'{active_speaker} says', act)
                sc["acting_prompt"] = ScriptAgent.professionalize_video_prompt(
                    acting_prompt=act,
                    visual_prompt=sc.get("visual_prompt", vis),
                    narration=sc.get("narration", narr),
                    camera_motion=camera,
                    title=title,
                    art_style=art_style,
                    speaker_name=active_speaker,
                    camera_on_speaker=is_speaker_focus
                )

        return scenes

    @staticmethod
    def ensure_separate_prompts(
        scene: Dict[str, Any],
        art_style: str = "ghibli",
        language: str = "en",
        camera_on_speaker: bool = False
    ) -> Dict[str, Any]:
        """
        Guarantees that visual_prompt (for still image generation), acting_prompt (for video motion),
        and narration (story-tied voiceover) are distinctly populated, correctly formatted, and never identical.
        Applies professional cinematic standards to acting_prompt.
        """
        if art_style == "dialogue_cinema":
            art_style = "ghibli"
            camera_on_speaker = True
        raw_vis = str(scene.get("visual_prompt") or scene.get("image_prompt") or scene.get("visual") or scene.get("prompt") or "").strip()
        raw_act = str(scene.get("acting_prompt") or scene.get("video_prompt") or scene.get("motion_prompt") or scene.get("acting") or "").strip()
        title = scene.get("title", f"Scene {scene.get('scene_number', 1)}")
        narration = scene.get("narration", "")
        camera = scene.get("camera_motion", "zoom_in")
        is_vi = language.startswith("vi") or any(ord(c) > 127 for c in (narration or title or raw_vis))

        def clean_acting_to_visual(text: str) -> str:
            c = re.sub(r'(?i)\b\d+-\d+s\s*:\s*', '', text)
            c = re.sub(r'(?i)(?:The\s+)?camera\s+(?:executes|performs|glides|smoothly|slowly)[^.]*\.?', '', c)
            c = re.sub(r'(?i)Camera\s*:[^.]*\.?', '', c)
            c = re.sub(r'(?i)Lighting\s*:[^.]*\.?', '', c)
            c = re.sub(r'(?i)Negative\s*:[^.\n]*\.?', '', c)
            c = re.sub(r'(?i)Audio\s*:[^.\n]*\.?', '', c)
            c = re.sub(r'(?i)SFX\s*:[^.\n]*\.?', '', c)
            c = re.sub(r'["“][^"”]+["”]', '', c)
            c = re.sub(r'(?i)\b(?:nhân vật nói|character says|không phụ đề|no subtitles)\b[:\s]*', '', c)
            c = re.sub(r'\s+', ' ', c).strip(' .,-')
            return c

        style_name_map = {
            "ghibli": ("Studio Ghibli 2D hand-drawn anime", "masterpiece anime illustration"),
            "pixar": ("3D Pixar / Disney Animation", "masterpiece 3D animation render"),
            "storybook": ("Classic Storybook Watercolor Fairy Tale", "masterpiece storybook illustration"),
            "anime_cinematic": ("Makoto Shinkai Modern Anime Cinema", "masterpiece cinematic anime still"),
            "cyberpunk": ("Cyberpunk Neon Sci-Fi Anime", "masterpiece cyberpunk illustration"),
            "comic": ("Modern Graphic Novel / Comic Art", "masterpiece comic book illustration"),
            "stick_figure": ("Minimalist Stick Figure Animation", "masterpiece stickman animation"),
            "realistic": ("Photorealistic cinematic live-action", "masterpiece photography")
        }
        style_tag, render_word = style_name_map.get(art_style, (f"{art_style.capitalize()} art", "masterpiece illustration"))
        speaker_framing_note = " Intimate medium close-up camera focused on the speaking character." if camera_on_speaker else ""

        # Case 1: Both are completely empty
        if not raw_vis and not raw_act:
            raw_vis = f"{style_tag} style. {title}.{speaker_framing_note} Cinematic composition, rich atmospheric lighting, detailed background."
            raw_act = ""

        # Case 2: Only acting prompt was provided
        elif raw_act and not raw_vis:
            clean_desc = clean_acting_to_visual(raw_act)
            if not clean_desc or len(clean_desc) < 10:
                clean_desc = title
            raw_vis = f"{style_tag} style. {clean_desc}.{speaker_framing_note} Cinematic composition, {render_word}, intricate environmental details."

        # Case 3: Only visual prompt was provided
        elif raw_vis and not raw_act:
            raw_act = ""

        # Case 4: Both were provided but are identical
        elif raw_vis == raw_act:
            if "0-3s:" in raw_act or "Camera:" in raw_act or "Negative:" in raw_act:
                clean_desc = clean_acting_to_visual(raw_act)
                raw_vis = f"{style_tag} style. {clean_desc or title}.{speaker_framing_note} Cinematic composition, beautiful lighting, rich details."
            else:
                raw_act = ""

        scene["visual_prompt"] = raw_vis
        scene["acting_prompt"] = raw_act

        # Ensure voiceover narration ties directly to the story and scene events
        narration = ScriptAgent.ensure_story_tied_narration(
            scene,
            language="vi" if is_vi else language
        )

        # Professionalize acting prompt to director-grade standard
        pro_acting = ScriptAgent.professionalize_video_prompt(
            acting_prompt=raw_act,
            visual_prompt=raw_vis,
            narration=narration,
            camera_motion=camera,
            title=title,
            art_style=art_style,
            camera_on_speaker=camera_on_speaker
        )

        scene["visual_prompt"] = raw_vis
        scene["acting_prompt"] = pro_acting
        scene["narration"] = narration
        if not scene.get("dialogues") and narration:
            scene["dialogues"] = ScriptAgent.extract_scene_dialogue_segments(narration)
        return scene

    @staticmethod
    def parse_imported_storyboard(text: str) -> Dict[str, Any]:
        """
        Robustly parses imported storyboard content in JSON or formatted text from Gemini Pro / ChatGPT / Claude.
        Supports:
        - Raw JSON: {"title": ..., "scenes": [...]}
        - Markdown fenced JSON: ```json ... ```
        - Text with embedded JSON anywhere inside
        - Formatted text screenplay (Title: ..., Scene 1 / Cảnh 1 / Cảnh cuối: Visual: ..., Dialogues, Narration: ...)
        """
        cleaned_text = text.strip()
        # Normalize HTML entities & markdown line-continuation escapes commonly produced when copying from ChatGPT/Gemini web UI
        cleaned_text = re.sub(r'(?i)&(?:#x0*20|#0*32|nbsp);', ' ', cleaned_text)
        cleaned_text = cleaned_text.replace('\u00a0', ' ').replace('&amp;', '&')

        def sanitize_json_candidate(raw_s: str) -> str:
            s = raw_s.strip()
            s = re.sub(r'(?i)&(?:#x0*20|#0*32|nbsp);', ' ', s)
            s = s.replace('\u00a0', ' ').replace('&amp;', '&')
            # Strip trailing markdown line-continuation backslashes at end of lines (e.g. "{\", "  \"title\": \"...\",\")
            s = re.sub(r'\\[ \t]*(\r?\n)', r'\1', s)
            s = re.sub(r'\\[ \t]*$', '', s)
            # Collapse double-escaped quotes (\\") into valid JSON escaped quotes (\")
            s = re.sub(r'\\\\"', r'\\"', s)
            # Remove trailing commas before } or ]
            s = re.sub(r',\s*([}\]])', r'\1', s)
            return s

        # 1. Try extracting JSON block
        json_fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned_text, re.IGNORECASE)
        candidate_json_str = json_fence_match.group(1).strip() if json_fence_match else None

        if not candidate_json_str:
            outer_match = re.search(r"(\{[\s\S]*\})", cleaned_text)
            if outer_match:
                candidate_json_str = outer_match.group(1).strip()

        if candidate_json_str:
            parsed = None
            for attempt_str in (candidate_json_str, sanitize_json_candidate(candidate_json_str)):
                try:
                    parsed = json.loads(attempt_str, strict=False)
                    if isinstance(parsed, dict) and "scenes" in parsed:
                        break
                except Exception:
                    parsed = None

            # Fallback regex scene-object extractor if JSON string has unescaped internal quotes or truncation
            if not (isinstance(parsed, dict) and isinstance(parsed.get("scenes"), list) and parsed.get("scenes")):
                try:
                    repaired = sanitize_json_candidate(candidate_json_str)
                    m_title = re.search(r'"title"\s*:\s*"((?:\\.|[^"\\])*)"', repaired)
                    m_logline = re.search(r'"logline"\s*:\s*"((?:\\.|[^"\\])*)"', repaired)
                    m_chars = re.search(r'"characters"\s*:\s*"((?:\\.|[^"\\])*)"', repaired)
                    sc_blocks = re.findall(r'\{\s*"scene_number"\s*:[\s\S]*?"camera_motion"\s*:\s*"[^"]*"\s*\}', repaired)
                    if sc_blocks:
                        extracted_scenes = []
                        for idx_b, b_str in enumerate(sc_blocks):
                            try:
                                sc_obj = json.loads(b_str, strict=False)
                            except Exception:
                                def _get_f(key: str, default: str = "") -> str:
                                    m_f = re.search(rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', b_str)
                                    return m_f.group(1).replace('\\"', '"').replace('\\n', '\n') if m_f else default
                                sc_obj = {
                                    "scene_number": idx_b + 1,
                                    "title": _get_f("title", f"Scene {idx_b + 1}"),
                                    "archetype": _get_f("archetype", "Cinematic Scene"),
                                    "visual_prompt": _get_f("visual_prompt", ""),
                                    "acting_prompt": _get_f("acting_prompt", ""),
                                    "narration": _get_f("narration", ""),
                                    "camera_motion": _get_f("camera_motion", "zoom_in")
                                }
                            extracted_scenes.append(sc_obj)
                        parsed = {
                            "title": m_title.group(1) if m_title else "Imported Film",
                            "logline": m_logline.group(1) if m_logline else "",
                            "characters": m_chars.group(1) if m_chars else "",
                            "scenes": extracted_scenes
                        }
                except Exception as e_fallback:
                    print(f"Regex JSON fallback notice: {e_fallback}")

            if isinstance(parsed, dict) and "scenes" in parsed and isinstance(parsed["scenes"], list):
                normalized_scenes = []
                for idx, sc in enumerate(parsed["scenes"]):
                    if not isinstance(sc, dict):
                        continue
                    normalized_sc = {
                        "scene_number": sc.get("scene_number", idx + 1),
                        "title": sc.get("title", f"Scene {idx + 1}"),
                        "archetype": sc.get("archetype", "Cinematic Scene"),
                        "visual_prompt": sc.get("visual_prompt") or sc.get("image_prompt") or sc.get("visual") or sc.get("prompt") or sc.get("description", ""),
                        "acting_prompt": sc.get("acting_prompt") or sc.get("video_prompt") or sc.get("motion_prompt") or sc.get("acting", ""),
                        "narration": sc.get("narration") or sc.get("voiceover") or sc.get("script") or sc.get("text", ""),
                        "camera_motion": sc.get("camera_motion", "zoom_in")
                    }
                    normalized_sc = ScriptAgent.ensure_separate_prompts(normalized_sc)
                    normalized_scenes.append(normalized_sc)
                if normalized_scenes:
                    return {
                        "title": parsed.get("title", "Imported Film"),
                        "logline": parsed.get("logline", ""),
                        "characters": parsed.get("characters", ""),
                        "scenes": normalized_scenes
                    }

        # 2. Heuristic text parser (if user pasted plain text screenplay)
        scene_blocks = re.split(
            r"(?:^|\n)((?:Scene|Cảnh|Phân cảnh)\s*\d+|CẢNH\s+CUỐI|CẢNH\s+KẾT|FINAL\s+SCENE)[:\s\-–—]*",
            cleaned_text,
            flags=re.IGNORECASE
        )

        if len(scene_blocks) > 2:
            header_block = scene_blocks[0]
            title_match = re.search(r"(?:Title|Tiêu đề|Tên phim)[:\s]*(.+)", header_block, re.IGNORECASE)
            quote_title = re.search(r'["“]([^"”\n]+)["”]', header_block)
            title = None
            if title_match:
                title = title_match.group(1).strip()
            elif quote_title:
                title = quote_title.group(1).strip()
            else:
                lines = [
                    l.strip() for l in header_block.splitlines()
                    if l.strip() and not any(w in l.lower() for w in ["kịch bản", "script", "thể loại", "thời lượng", "bối cảnh", "thông điệp", "nhân vật", "mở đầu"])
                ]
                if lines:
                    title = lines[0]
            title = title or "Imported Film"

            # Extract message or logline
            msg_match = re.search(r'(?:Thông điệp|Message|Logline|Tóm tắt)[:\s]*(.+)', header_block, re.IGNORECASE)
            logline = msg_match.group(1).strip() if msg_match else ""

            # Extract characters specification
            char_match = re.search(r'(?:Nhân vật|Characters)[:\s]*\n([\s\S]*?)(?=(?:Mở đầu|CẢNH|Scene|Phân cảnh|Bối cảnh|Thông điệp|$))', header_block, re.IGNORECASE)
            characters = ""
            if char_match:
                raw_c = char_match.group(1).strip()
                c_lines = [l.strip() for l in raw_c.splitlines() if l.strip()]
                characters = " | ".join(c_lines[:4])

            section_headers = {
                "mở đầu", "phát triển", "cao trào", "kết", "kết thúc", "hết", "hết.", "the end", "opening", "climax", "ending"
            }
            speaker_re = re.compile(
                r'^([A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ]{2,}(?:\s+[A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ0-9]+)*)\s*(?:\(([^\)]*)\))?$'
            )

            scenes = []
            motion_cycle = ["zoom_in", "pan_right", "subtle_drift", "zoom_out", "pan_left"]

            for i in range(1, len(scene_blocks), 2):
                marker_str = scene_blocks[i].strip()
                num_m = re.search(r'(\d+)', marker_str)
                sc_num = int(num_m.group(1)) if num_m else (len(scenes) + 1)
                is_final_marker = any(k in marker_str.upper() for k in ["CUỐI", "KẾT", "FINAL"])
                sc_body = scene_blocks[i + 1].strip()

                raw_lines = [l.strip() for l in sc_body.splitlines() if l.strip()]
                if not raw_lines:
                    continue

                # Determine scene title vs first content line
                first_line = raw_lines[0]
                is_location_header = bool(re.match(r'^(?:NGOẠI|NỘI|EXT|INT)\b', first_line, re.IGNORECASE))
                is_short_header = (
                    not is_final_marker and
                    len(first_line) < 60 and
                    not first_line.endswith(('.', '!', '?')) and
                    not re.match(r'^(?:Visual|Hình ảnh|Miêu tả|Narration|Thuyết minh|Lời dẫn|Acting|Âm thanh|Audio)[:\s]', first_line, re.IGNORECASE)
                )

                if is_location_header or is_short_header:
                    clean_title = re.sub(r'^[–\-—:\s]+', '', first_line).strip()
                    clean_title = re.sub(r'^(?:NGOẠI|NỘI|EXT|INT)[\.\s\-–—]*', '', clean_title, flags=re.IGNORECASE).strip()
                    sc_title = clean_title or (f"Cảnh Cuối" if is_final_marker else f"Scene {sc_num}")
                    content_lines = raw_lines[1:]
                else:
                    sc_title = "Cảnh Cuối – Dư Âm" if is_final_marker else f"Scene {sc_num}"
                    content_lines = raw_lines

                explicit_visuals = []
                narrative_actions = []
                dialogues = []
                explicit_narration = ""
                explicit_acting = ""
                screen_message = ""
                archetype_override = ""

                idx_line = 0
                while idx_line < len(content_lines):
                    line = content_lines[idx_line]
                    low_line = line.lower().strip(' .:')

                    # Skip structural section dividers like "Phát triển", "Cao trào", "Kết", "Hết."
                    if low_line in section_headers:
                        idx_line += 1
                        continue

                    # Check for on-screen text / moral header
                    if re.match(r'^(?:CHỮ TRÊN MÀN HÌNH|TEXT ON SCREEN|THÔNG ĐIỆP CUỐI)[:\s]*$', line, re.IGNORECASE):
                        if idx_line + 1 < len(content_lines):
                            screen_message = content_lines[idx_line + 1].strip(' "“”')
                            idx_line += 2
                            continue
                        idx_line += 1
                        continue

                    # Check labeled fields
                    m_vis = re.match(r'^(?:Visual|Hình ảnh|Miêu tả)[:\s]+(.+)', line, re.IGNORECASE)
                    if m_vis:
                        explicit_visuals.append(m_vis.group(1).strip())
                        idx_line += 1
                        continue

                    m_aud = re.match(r'^(?:Âm thanh|Audio|Âm nhạc|Music|SFX)[:\s]+(.+)', line, re.IGNORECASE)
                    if m_aud:
                        idx_line += 1
                        continue

                    m_arch = re.match(r'^(?:Archetype|Thể loại cảnh)[:\s]+(.+)', line, re.IGNORECASE)
                    if m_arch:
                        archetype_override = m_arch.group(1).strip()
                        idx_line += 1
                        continue

                    m_act = re.match(r'^(?:Acting|Video|Motion|Diễn xuất|Hành động)[:\s]+(.+)', line, re.IGNORECASE)
                    if m_act:
                        explicit_acting = m_act.group(1).strip()
                        idx_line += 1
                        continue

                    m_narr = re.match(r'^(?:Narration|Thuyết minh|Lời dẫn|Voiceover)[:\s]+(.+)', line, re.IGNORECASE)
                    if m_narr:
                        explicit_narration = m_narr.group(1).strip()
                        idx_line += 1
                        continue

                    # Check ALL-CAPS speaker line followed by dialogue
                    m_spk = speaker_re.match(line)
                    if m_spk and idx_line + 1 < len(content_lines):
                        spk_name = m_spk.group(1).strip().title()
                        spk_tone = (m_spk.group(2) or "").strip()
                        dial_line = content_lines[idx_line + 1].strip(' "“”')
                        dialogues.append((spk_name, spk_tone, dial_line))
                        idx_line += 2
                        continue

                    # Regular narrative action / stage direction line
                    clean_action = re.sub(r'^(?:Cảnh chuyển|Chuyển cảnh|Cut to)[:\s]+', '', line, flags=re.IGNORECASE).strip()
                    if clean_action and clean_action.lower().strip(' .') not in section_headers:
                        narrative_actions.append(clean_action)
                    idx_line += 1

                # 1. Construct clean visual_prompt (NO speaker headers, NO raw dialogue blocks)
                vis_parts = list(explicit_visuals)
                for act_line in narrative_actions:
                    if len(" ".join(vis_parts).split()) < 45:
                        vis_parts.append(act_line)
                visual = " ".join(vis_parts).strip()
                if not visual:
                    visual = sc_title
                if dialogues and "biểu cảm" not in visual.lower():
                    visual = visual.rstrip(' .') + ". Biểu cảm gương mặt và khẩu hình đối thoại sinh động, ánh mắt giao tiếp tự nhiên, không bong bóng thoại, không chữ."

                # Select the primary dialogue / conversational pair for both narration and acting_prompt
                selected_pair_idx = 0
                if len(dialogues) >= 2:
                    selected_pair_idx = len(dialogues) - 2
                    best_score = -1
                    for d_i in range(len(dialogues) - 1):
                        spk_a, _, line_a = dialogues[d_i]
                        spk_b, _, line_b = dialogues[d_i + 1]
                        score = len(line_a.split()) + len(line_b.split())
                        if spk_a != spk_b:
                            score += 6
                        if score > best_score:
                            best_score = score
                            selected_pair_idx = d_i

                # 2. Construct acting_prompt with primary dialogue
                dial_str = ""
                if dialogues:
                    if len(dialogues) == 1:
                        chosen_spk, chosen_tone, chosen_line = dialogues[0]
                    else:
                        f_spk, f_tone, f_line = dialogues[selected_pair_idx]
                        s_spk, s_tone, s_line = dialogues[selected_pair_idx + 1]
                        if len(f_line.split()) >= len(s_line.split()):
                            chosen_spk, chosen_tone, chosen_line = f_spk, f_tone, f_line
                        else:
                            chosen_spk, chosen_tone, chosen_line = s_spk, s_tone, s_line
                    tone_suffix = f" — {chosen_tone}" if chosen_tone else ""
                    dial_str = f'Character says in an expressive voice: "{chosen_line}" (no subtitles){tone_suffix}'

                if archetype_override:
                    archetype = archetype_override
                elif is_final_marker:
                    archetype = "Resolution"
                elif dialogues:
                    archetype = "Dialogue Scene"
                elif len(scenes) == 0:
                    archetype = "Establishing Shot"
                else:
                    archetype = "Action Beat"

                acting = explicit_acting
                if not acting:
                    # Build clean 0-3s beat using complete sentences (never slicing mid-word)
                    vis_sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', " ".join(vis_parts).strip()) if s.strip()]
                    beat1_sents = []
                    for vs in vis_sents:
                        if len(" ".join(beat1_sents + [vs]).split()) <= 24 or not beat1_sents:
                            beat1_sents.append(vs.rstrip('.!?'))
                        else:
                            break
                    beat1_str = ". ".join(beat1_sents).strip(' .') or sc_title
                    act_beat_3 = narrative_actions[-1].rstrip('.!?') if len(narrative_actions) > 1 else "Cảm xúc chuyển biến tự nhiên, ánh mắt kết nối nhịp nhàng sang cảnh tiếp theo"
                    acting = (
                        f"0-3s: {beat1_str}. "
                        f"3-6s: {dial_str if dial_str else 'Diễn xuất và chuyển động tự nhiên của nhân vật trong bối cảnh.'} "
                        f"6-8s: {act_beat_3}. "
                        f"Camera: {motion_cycle[len(scenes) % len(motion_cycle)]}. Lighting: ánh sáng điện ảnh ấm áp. Negative: subtitles, watermark, text overlay."
                    )

                # 3. Construct STORY-TIED Voiceover Narration (`narration`)
                if explicit_narration:
                    narration = explicit_narration
                else:
                    # Build a true storytelling voiceover that ties together the scene's action, dialogue, and message!
                    story_parts = []

                    # Combine explicit_visuals and narrative_actions to find the best scene-opening story sentence
                    all_scene_sents = []
                    pure_scenery_prefixes = (
                        "ánh nắng xuyên qua", "cánh đồng lúa chín", "trời nhuộm màu",
                        "toàn cảnh cánh đồng", "máy gặt đến gần", "thầy giáo đang viết",
                        "gió lùa tạo", "tí đứng bật dậy", "tí chìa tay ra", "tí cúi đầu", "tí ngẩng lên"
                    )
                    for s in (explicit_visuals + narrative_actions):
                        for sub_s in re.split(r'(?<=[.!?])\s+', s):
                            sub_s = sub_s.strip()
                            if not sub_s:
                                continue
                            if any(sub_s.lower().startswith(p) for p in pure_scenery_prefixes):
                                continue
                            all_scene_sents.append(sub_s)

                    if not all_scene_sents:
                        for s in (explicit_visuals + narrative_actions):
                            for sub_s in re.split(r'(?<=[.!?])\s+', s):
                                if sub_s.strip():
                                    all_scene_sents.append(sub_s.strip())

                    # Add key opening action/context sentence
                    if all_scene_sents:
                        story_parts.append(all_scene_sents[0].rstrip('.!?'))

                    # Weave in key character dialogue(s) so the voiceover tells the actual conversation/plot
                    if dialogues:
                        if len(dialogues) == 1:
                            spk, tone, d_line = dialogues[0]
                            verb = "hỏi" if d_line.strip().endswith("?") else "nói"
                            story_parts.append(f'{spk} {verb}: "{d_line}"')
                        else:
                            first_spk, _, first_line = dialogues[selected_pair_idx]
                            second_spk, _, second_line = dialogues[selected_pair_idx + 1]
                            v1 = "hỏi" if first_line.strip().endswith("?") else "nói"
                            if first_spk == second_spk:
                                story_parts.append(f'{first_spk} {v1}: "{second_line}"')
                            else:
                                v2 = "hỏi lại" if second_line.strip().endswith("?") else "đáp"
                                story_parts.append(f'{first_spk} {v1}: "{first_line}", và {second_spk} {v2}: "{second_line}"')

                    # Add closing action turn or on-screen moral if present
                    if screen_message:
                        story_parts.append(screen_message.rstrip('.!?'))
                    elif not dialogues and len(all_scene_sents) > 1:
                        for extra_s in all_scene_sents[1:]:
                            clean_extra = extra_s.rstrip('.!?')
                            if clean_extra not in story_parts and len(" ".join(story_parts + [clean_extra]).split()) <= 32:
                                story_parts.append(clean_extra)
                        if all_scene_sents[-1].rstrip('.!?') not in story_parts:
                            story_parts.append(all_scene_sents[-1].rstrip('.!?'))
                    elif len(all_scene_sents) > 1 and len(" ".join(story_parts).split()) < 24:
                        last_act = all_scene_sents[-1].rstrip('.!?')
                        if last_act not in story_parts:
                            story_parts.append(last_act)

                    narration = ". ".join(p for p in story_parts if p).strip()
                    narration = re.sub(r'([.!?]"?)\.', r'\1', narration)
                    if narration and not narration.endswith(('.', '!', '?', '"', '”', '…')):
                        narration += "."

                sc_dict = {
                    "scene_number": len(scenes) + 1,
                    "title": sc_title,
                    "archetype": archetype,
                    "visual_prompt": visual,
                    "acting_prompt": acting,
                    "narration": narration,
                    "camera_motion": motion_cycle[len(scenes) % len(motion_cycle)]
                }
                sc_dict = ScriptAgent.ensure_separate_prompts(sc_dict)
                scenes.append(sc_dict)

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
        target_model = self.model
        is_pro = bool(target_model and "pro" in target_model.lower())
        if not target_model or target_model == "default":
            target_model = "gemini-pro-advanced" if is_pro else "gemini-flash-advanced"
        elif is_pro and "advanced" not in target_model.lower():
            target_model = "gemini-pro-advanced"
        elif not is_pro and "advanced" not in target_model.lower():
            target_model = "gemini-flash-advanced"

        res = await wrapper.generate_content(
            prompt=prompt,
            model=target_model,
            cookie_override=cookie_input,
            extended_thinking=is_pro
        )
        return self._clean_json_response(res.text)

    async def _generate_with_gemini(self, prompt: str, model: str = "gemini-2.5-flash") -> Dict[str, Any]:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=self.api_key)
        target_model = (model or "gemini-2.5-flash").strip()
        is_pro = "pro" in target_model.lower()

        config_kwargs = {
            "response_mime_type": "application/json",
            "temperature": 0.7
        }
        # Turn off thinking delay on Flash models for fast execution
        if not is_pro and any(tag in target_model.lower() for tag in ["2.5", "flash", "thinking"]):
            try:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            except Exception:
                pass
        elif is_pro and "2.5" in target_model.lower():
            # Deep reasoning budget for Pro
            try:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=2048)
            except Exception:
                pass

        try:
            config = types.GenerateContentConfig(**config_kwargs)
            response = await client.aio.models.generate_content(
                model=target_model,
                contents=prompt,
                config=config
            )
            return self._clean_json_response(response.text)
        except Exception as e:
            # Check if cookie session is available as a fallback
            try:
                from backend.config import get_server_credentials
                creds = get_server_credentials()
                psid = creds.get("gemini_cookie_psid")
                psidts = creds.get("gemini_cookie_psidts")
                if psid:
                    cookie_token = f"{psid}|{psidts}" if psidts else psid
                    print(f"⚠️ Google GenAI API returned ({e}). Auto-falling back to persistent Gemini Web Session...")
                    return await self._generate_with_gemini_cookie(prompt, cookie_token)
            except Exception:
                pass
            raise e

    async def _generate_with_openai_compatible(self, endpoint: str, api_key: str, model: str, prompt: str) -> Dict[str, Any]:
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
        if any(k in endpoint.lower() or k in model.lower() for k in ["openai", "gpt", "deepseek"]):
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return self._clean_json_response(content)

    async def _generate_with_anthropic(self, api_key: str, model: str, prompt: str) -> Dict[str, Any]:
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
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
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
        if not num_scenes or num_scenes <= 0:
            num_scenes = self.estimate_optimal_scene_count(raw_text)
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

            # Build a complete, story-tied narration from the chunk without mid-sentence truncation
            narr_parts = []
            for cs in chunk_sentences:
                cs_clean = re.sub(r'\s+', ' ', cs).strip()
                if not cs_clean:
                    continue
                if len(" ".join(narr_parts + [cs_clean]).split()) <= 26 or not narr_parts:
                    narr_parts.append(cs_clean)
                else:
                    break

            narr_raw = " ".join(narr_parts).strip()
            if len(narr_raw.split()) > 28:
                # Trim cleanly at a clause boundary (comma, semicolon, dash) if overly long
                clauses = re.split(r'([,;–—:])', narr_raw)
                acc = ""
                for c_piece in clauses:
                    if len((acc + c_piece).split()) <= 24 or not acc:
                        acc += c_piece
                    else:
                        break
                narr_raw = acc.strip(' ,;–—:')
                if len(narr_raw.split()) > 26:
                    narr_raw = " ".join(narr_raw.split()[:24])

            if not narr_raw:
                narr_raw = "Câu chuyện tiếp tục mở ra những tình tiết bất ngờ." if is_vi else "The adventure continues through ancient lands."
            if not narr_raw.endswith((".", "!", "?", '"', '”', '…')):
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
            if art_style == "realistic":
                style_tag = "Photorealistic cinematic live-action"
            elif art_style == "stick_figure":
                style_tag = "Minimalist Stick Figure Animation"
            else:
                style_tag = f"{art_style.capitalize()} art"
            vis_prompt = f"{style_tag} style. {vis_snippet}. Cinematic composition, warm atmospheric lighting, high fidelity details."

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
        if not num_scenes or num_scenes <= 0:
            num_scenes = self.estimate_optimal_scene_count(clean_idea_raw)
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

    def _build_advertisement_prompt(
        self,
        product_name: str,
        description: str,
        specs: str = "",
        brand: str = "",
        target_audience: str = "General",
        ad_style: str = "cinematic_commercial",
        call_to_action: str = "Order now!",
        pricing_offer: str = "",
        num_scenes: int = 4,
        target_duration: int = None,
        art_style: str = "realistic",
        language: str = "en"
    ) -> str:
        calc_duration = target_duration if (target_duration and target_duration > 0) else (num_scenes * 8)
        target_scene_sec = max(5, int(calc_duration / max(1, num_scenes)))
        target_scene_sec = min(target_scene_sec, 8)
        max_words = min(18, max(12, int((target_scene_sec - 1.0) * 2.4)))

        ad_styles_guide = {
            "cinematic_commercial": "High-end cinematic broadcast commercial (Apple / Nike style), dramatic rim lighting, 35mm shallow depth of field, sleek and awe-inspiring",
            "viral_reels": "Fast-paced TikTok / Instagram Reels / YouTube Shorts style, explosive hook, dynamic camera transitions, punchy and trending",
            "spec_breakdown": "Tech review & feature deep-dive, ultra-sharp macro close-ups, highlighting precise engineering specs and functional superiority",
            "luxury_macro": "Ultra-luxury premium showcase (Rolex / Porsche aesthetic), slow elegant motion, golden hour or moody studio lighting, velvety textures",
            "problem_solution": "Relatable problem -> Hero product introduction -> Complete transformation & effortless satisfaction"
        }
        chosen_style_desc = ad_styles_guide.get(ad_style, ad_styles_guide["cinematic_commercial"])
        brand_str = brand.strip() if (brand and brand.strip()) else "Exclusive"

        return f"""You are an elite commercial director and master advertising copywriter from premier global agencies (Apple, Ogilvy, Nike commercials, Wieden+Kennedy).
Craft an electrifying, high-converting product commercial storyboard tailored for high-impact AI advertising video generation (Google Flow / Google Veo 3 I2V, Midjourney / Imagen 3).

Product Details:
- Product Name: {product_name}
- Brand: {brand_str}
- Overview & Core Benefits: {description}
- Technical Specs & Features: {specs or "State-of-the-art engineering and craftsmanship"}
- Target Audience: {target_audience}
- Commercial Vibe & Style: {chosen_style_desc}
- Special Offer / Pricing: {pricing_offer or "Limited Time Exclusive Offer"}
- Call to Action (CTA): {call_to_action}
- Voiceover Narration Language: {language}
- Visual Art Style: {art_style} (e.g. realistic 35mm photography)

COMMERCIAL STRUCTURE (Across {num_scenes} scenes):
- Scene 1 [THE HOOK]: Magnetic visual hook that captures 100% attention in the first 1.5 seconds. Highlights the user desire, curiosity, or dynamic silhouette tease of the product.
- Scene 2 [THE HERO REVEAL]: Breathtaking reveal of {product_name} in cinematic studio lighting. Sleek angles, pristine reflections, highlighting brand craftsmanship.
- Scene 3 [TECH SPECS & FEATURES IN ACTION]: Spotlight on core technical specs: {specs}. Show how the engineering specs directly solve customer problems with close-up macro shots.
- Scene 4 [LIFESTYLE & ELEVATED EXPERIENCE]: A confident, satisfied customer experiencing the joy, performance, and transformative benefits of the product.
- Scene 5 [IRRESISTIBLE OFFER & CALL TO ACTION]: Grand beauty shot with special offer ({pricing_offer}), brand logo, and urgent call to action ({call_to_action}).

CRITICAL CINEMATIC DIRECTIVES:
1. SEPARATE PROMPTS (MANDATORY):
   a) `visual_prompt`: Detailed static photograph description: studio lighting setup, product geometry, materials, 35mm lens, camera angle, atmospheric background in {art_style} style. NO timestamps, NO camera moves, NO dialogue quotes.
   b) `acting_prompt` (PROFESSIONAL COMMERCIAL VIDEO PROMPT for Google Flow / Veo 3 / Kling):
      * 8-second commercial camera motion & dynamic movement written as natural, luxury cinematic prose (90-130 words) in ENGLISH only.
      * Start with camera movement as a dedicated sentence: e.g. "The camera performs a smooth, high-precision motorized slider push-in toward the product hero silhouette."
      * Detail physically grounded product dynamics across 3 beats:
        - 0-3s: Fluid camera glide slowly reveals pristine geometric contours and subtle light reflections.
        - 3-6s: Dynamic tactile interaction highlights responsive controls and fine material craftsmanship.
        - 6-8s: The composition settles into an authoritative hero angle with ultimate brand prestige.
      * Studio Lighting & Optics: "Commercial studio softbox key light with crisp edge reflections and immaculate specular highlights, shot on 50mm f/1.8 lens."
      * Veo 3 Audio & Negative:
        Audio: upbeat sophisticated ambient electronic rhythm, no lyrics.
        SFX: subtle tactile click, gentle smooth slider sound.
        Negative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, jittery motion.
2. NARRATION:
   - Punchy, persuasive commercial voiceover in {language}.
   - STRICT PACING: Strictly 10 to {max_words} words per scene (under 7.2s speaking time).
3. CAMERA MOTIONS:
   - Choose kinetic motions: "zoom_in", "pan_right", "pan_left", "subtle_drift", or "zoom_out".

Return ONLY raw JSON matching this structure:
{{
  "title": "{product_name} — Official Commercial",
  "logline": "1-sentence high-converting ad hook",
  "characters": "Product: {product_name} ({brand_str}) | User: Modern customer enjoying the product",
  "scenes": [
    {{
      "scene_number": 1,
      "title": "The Hook",
      "archetype": "The Hook",
      "visual_prompt": "Detailed commercial photography description of frozen frame in {art_style} style...",
      "acting_prompt": "The camera performs a smooth, high-precision motorized slider push-in toward {product_name}. 0-3s: Fluid camera glide slowly reveals pristine geometric contours and subtle light reflections. 3-6s: Dynamic tactile interaction highlights responsive controls and fine material craftsmanship. 6-8s: The composition settles into an authoritative hero angle with ultimate brand prestige. Commercial studio softbox key light with crisp edge reflections, shot on 50mm f/1.8 lens.\\n\\nAudio: upbeat sophisticated ambient electronic rhythm, no lyrics.\\nSFX: subtle tactile click, gentle smooth slider sound.\\nNegative: subtitles, captions, watermark, text overlay, distorted anatomy, morphing limbs, jittery motion.",
      "narration": "Short, punchy commercial voiceover in {language} (10-{max_words} words)...",
      "camera_motion": "zoom_in"
    }}
  ]
}}"""

    def _generate_offline_advertisement(
        self,
        product_name: str,
        description: str,
        specs: str = "",
        brand: str = "",
        target_audience: str = "General",
        ad_style: str = "cinematic_commercial",
        call_to_action: str = "Order now!",
        pricing_offer: str = "",
        num_scenes: int = 4,
        art_style: str = "realistic",
        language: str = "en"
    ) -> Dict[str, Any]:
        """Built-in offline Commercial Generator for advertising goods."""
        is_vi = language.startswith("vi")
        brand_name = brand.strip() if (brand and brand.strip()) else "Official"
        clean_name = product_name.strip() or "Premium Product"
        clean_specs = specs.strip() or "Advanced engineering, premium materials, high performance"
        clean_offer = pricing_offer.strip() or ("Ưu đãi giới hạn hôm nay!" if is_vi else "Limited-time exclusive offer!")
        clean_cta = call_to_action.strip() or ("Đặt hàng ngay hôm nay!" if is_vi else "Order now to claim your discount!")

        style_prefix = "Photorealistic cinematic 35mm photograph" if art_style == "realistic" else f"{art_style.capitalize()} style"

        ad_templates = [
            {
                "archetype": "The Hook",
                "title_en": "The Hook: Experience Better",
                "title_vi": "Mở Đầu: Đỉnh Cao Trải Nghiệm",
                "vis_en": f"{style_prefix}. Dramatic moody studio lighting casting rim reflections across the sleek silhouette of {clean_name}. High-end product photography, shallow depth of field, 8k resolution.",
                "vis_vi": f"{style_prefix}. Ánh sáng studio điện ảnh tạo viền sáng ấn tượng trên thân máy sang trọng của {clean_name}. Nhiếp ảnh sản phẩm cao cấp, độ phân giải 8k.",
                "act_en": f"0-3s: Camera glides slowly across the sleek contours of {clean_name}. 3-6s: An elegant sweep of golden rim light reveals the fine surface textures. 6-8s: Camera locks onto the signature silhouette.",
                "act_vi": f"0-3s: Camera glides slowly across the sleek contours of {clean_name}. 3-6s: An elegant sweep of golden rim light reveals the fine surface textures. 6-8s: Camera locks onto the signature silhouette.",
                "narr_en": "Are you ready to elevate your daily routine? Discover what you've been missing.",
                "narr_vi": "Bạn đã sẵn sàng nâng tầm trải nghiệm mỗi ngày? Hãy khám phá sự khác biệt.",
                "motion": "zoom_in"
            },
            {
                "archetype": "The Product Reveal",
                "title_en": f"Meet {clean_name}",
                "title_vi": f"Giới Thiệu {clean_name}",
                "vis_en": f"{style_prefix}. Hero beauty shot of {clean_name} ({brand_name}), perfectly centered on a minimalist reflective pedestal with soft atmospheric backlight, flawless industrial design.",
                "vis_vi": f"{style_prefix}. Bức ảnh tôn vinh tuyệt đẹp của {clean_name} ({brand_name}), đặt trên bệ trưng bày tối giản với ánh sáng nền dịu nhẹ, thiết kế hoàn mỹ.",
                "act_en": f"0-3s: {clean_name} rotates smoothly on an invisible turntable. 3-6s: Sleek accents glow subtly as the device activates. 6-8s: Camera pulls to an authoritative hero angle.",
                "act_vi": f"0-3s: {clean_name} rotates smoothly on an invisible turntable. 3-6s: Sleek accents glow subtly as the device activates. 6-8s: Camera pulls to an authoritative hero angle.",
                "narr_en": f"Introducing {clean_name}. Crafted by {brand_name} for those who demand absolute excellence.",
                "narr_vi": f"Giới thiệu {clean_name}. Được chế tác bởi {brand_name} dành riêng cho những ai yêu thích sự hoàn hảo.",
                "motion": "pan_right"
            },
            {
                "archetype": "Tech Specs & Features",
                "title_en": "Precision Engineering & Specs",
                "title_vi": "Thông Số & Hiệu Năng Đột Phá",
                "vis_en": f"{style_prefix}. Extreme macro close-up highlighting technical details and materials: {clean_specs}. Pristine textures, precision craftsmanship, 8k uhd clarity.",
                "vis_vi": f"{style_prefix}. Cận cảnh góc siêu macro thể hiện chi tiết kỹ thuật và vật liệu cao cấp: {clean_specs}. Kết cấu tinh xảo, độ sắc nét 8k.",
                "act_en": f"0-3s: Camera glides into a high-detail macro shot of the functional interface. 3-6s: Dynamic movement demonstrates responsiveness and flawless build quality. 6-8s: Settle back to three-quarter view.",
                "act_vi": f"0-3s: Camera glides into a high-detail macro shot of the functional interface. 3-6s: Dynamic movement demonstrates responsiveness and flawless build quality. 6-8s: Settle back to three-quarter view.",
                "narr_en": f"Engineered with {clean_specs[:55]}. Every millimeter built for uncompromising peak performance.",
                "narr_vi": f"Tích hợp {clean_specs[:55]}. Từng chi tiết nhỏ nhất đều tối ưu cho hiệu năng đỉnh cao.",
                "motion": "zoom_in"
            },
            {
                "archetype": "Lifestyle Experience",
                "title_en": "Elevated Daily Living",
                "title_vi": "Trải Nghiệm Cuộc Sống Đỉnh Cao",
                "vis_en": f"{style_prefix}. Elegant lifestyle scene of modern user seamlessly enjoying {clean_name} in an aesthetic contemporary space. Warm golden sunlight streaming in, natural joyful expression.",
                "vis_vi": f"{style_prefix}. Khung cảnh phong cách sống hiện đại, người dùng thư thái tận hưởng {clean_name} trong không gian sang trọng. Ánh nắng sớm ấm áp, nụ cười hài lòng.",
                "act_en": f"0-3s: User interacts effortlessly with {clean_name}, feeling immediate tactile delight. 3-6s: Genuine smile and feeling of elevated comfort and confidence. 6-8s: Smooth pan back to the glowing product.",
                "act_vi": f"0-3s: User interacts effortlessly with {clean_name}, feeling immediate tactile delight. 3-6s: Genuine smile and feeling of elevated comfort and confidence. 6-8s: Smooth pan back to the glowing product.",
                "narr_en": "Feel the seamless difference every single day. Effortless, intuitive, and truly transformative.",
                "narr_vi": "Cảm nhận sự tiện nghi vượt trội mỗi ngày. Đơn giản, tinh tế và đầy cảm hứng.",
                "motion": "subtle_drift"
            },
            {
                "archetype": "Special Offer & CTA",
                "title_en": "Exclusive Offer & Call to Action",
                "title_vi": "Ưu Đãi Đặc Biệt & Đặt Hàng",
                "vis_en": f"{style_prefix}. Grand cinematic finale beauty shot of {clean_name} with official packaging and premium accessories, glowing luxury backdrop, celebratory lighting.",
                "vis_vi": f"{style_prefix}. Khung hình kết thúc hoành tráng của {clean_name} cùng trọn bộ phụ kiện cao cấp, phông nền tỏa sáng rực rỡ, góc chụp ấn tượng.",
                "act_en": f"0-3s: Camera pulls back smoothly revealing {clean_name} in its full glory. 3-6s: A celebratory light flare shimmers across the brand emblem. 6-8s: Hero stance settles with ultimate brand prestige.",
                "act_vi": f"0-3s: Camera pulls back smoothly revealing {clean_name} in its full glory. 3-6s: A celebratory light flare shimmers across the brand emblem. 6-8s: Hero stance settles with ultimate brand prestige.",
                "narr_en": f"{clean_offer} {clean_cta}",
                "narr_vi": f"{clean_offer} {clean_cta}",
                "motion": "zoom_out"
            }
        ]

        scenes = []
        for i in range(num_scenes):
            template = ad_templates[i % len(ad_templates)]
            if i == num_scenes - 1 and num_scenes > 1:
                template = ad_templates[-1]  # Always finish on CTA
            elif i == 0:
                template = ad_templates[0]   # Always start on Hook
            elif i == 1:
                template = ad_templates[1]   # Always introduce product

            title_s = template["title_vi"] if is_vi else template["title_en"]
            vis_s = template["vis_vi"] if is_vi else template["vis_en"]
            act_s = template["act_en"]  # Video prompts must always be in English
            narr_s = template["narr_vi"] if is_vi else template["narr_en"]

            pro_act = ScriptAgent.professionalize_video_prompt(
                acting_prompt=act_s,
                visual_prompt=vis_s,
                narration=narr_s,
                camera_motion=template["motion"],
                title=title_s,
                art_style=art_style,
                is_commercial=True
            )

            scenes.append({
                "scene_number": i + 1,
                "title": title_s,
                "archetype": template["archetype"],
                "visual_prompt": vis_s,
                "acting_prompt": pro_act,
                "narration": narr_s,
                "camera_motion": template["motion"],
                "is_product_photo": True
            })

        return {
            "title": f"{clean_name} — Commercial",
            "logline": f"Discover {clean_name} by {brand_name}: {description[:90]}. {clean_offer}",
            "characters": f"Product: {clean_name} ({brand_name}) | Target: {target_audience}",
            "scenes": scenes
        }
