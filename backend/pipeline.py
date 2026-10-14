import os
import json
import time
import uuid
import re
import asyncio
from pathlib import Path
from typing import Dict, Any, Callable, Optional

from backend.config import PROJECTS_DIR, ART_STYLES, VOICES, VIDEO_DIMENSIONS
from backend.agents.script_agent import ScriptAgent
from backend.agents.voice_agent import VoiceAgent
from backend.services.image_service import ImageService
from backend.services.video_engine import VideoEngine
from backend.services.music_service import MusicService

class AnimationPipeline:
    def __init__(self, api_key: str = None, ai_provider: str = "gemini", ai_model: str = None):
        self.api_key = api_key
        self.ai_provider = ai_provider or "gemini"
        self.ai_model = ai_model
        self.script_agent = ScriptAgent(api_key=api_key, provider=self.ai_provider, model=ai_model)
        self.voice_agent = VoiceAgent()
        self.image_service = ImageService(api_key=api_key, provider=self.ai_provider)
        self.video_engine = VideoEngine()
        self.music_service = MusicService()

    @staticmethod
    def sanitize_title_for_folder(title: str, fallback: str = "") -> str:
        """Sanitizes project title into a clean, filesystem-safe folder name."""
        raw = (title or "").strip()
        if not raw and fallback:
            raw = fallback.strip()[:40]
        if not raw:
            raw = "Animated Story"

        # Remove illegal Windows / Linux filesystem characters: \ / : * ? " < > |
        clean = re.sub(r'[\\/:*?"<>|\r\n\t]', '', raw).strip()
        clean = re.sub(r'\s+', ' ', clean).strip('. ')
        if not clean:
            clean = "Animated Story"
        return clean

    @staticmethod
    def get_unique_project_id(base_name: str, current_id: str = None) -> str:
        """Finds an unused project folder name by appending (2), (3), etc. if needed."""
        candidate = base_name
        if current_id and candidate == current_id:
            return candidate
        counter = 2
        while (PROJECTS_DIR / candidate).exists() and candidate != current_id:
            candidate = f"{base_name} ({counter})"
            counter += 1
        return candidate

    def create_project(
        self,
        idea: str,
        title: str = "",
        art_style: str = "ghibli",
        voice: str = "en-US-ChristopherNeural",
        num_scenes: int = 4,
        target_duration: int = None,
        aspect_ratio: str = "16:9",
        image_mode: str = "server"
    ) -> Dict[str, Any]:
        """Initialize a new project record with folder name matching the title."""
        chosen_title = (title or "").strip()
        base_name = self.sanitize_title_for_folder(chosen_title, fallback=idea)
        project_id = self.get_unique_project_id(base_name)
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        dim = VIDEO_DIMENSIONS.get(aspect_ratio, VIDEO_DIMENSIONS["16:9"])
        calc_duration = target_duration if (target_duration and target_duration > 0) else (num_scenes * 12)

        project_data = {
            "id": project_id,
            "created_at": time.time(),
            "idea": idea,
            "art_style": art_style,
            "voice": voice,
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model or "",
            "api_key": self.api_key or "",
            "num_scenes": num_scenes,
            "target_duration": calc_duration,
            "aspect_ratio": aspect_ratio,
            "video_width": dim["width"],
            "video_height": dim["height"],
            "image_mode": image_mode,
            "enable_subtitles": True,
            "title": (title or "").strip(),
            "logline": "",
            "characters": "",
            "scenes": [],
            "status": "created",
            "progress": 0,
            "current_step": "Initialized",
            "video_path": None
        }

        self.save_project(project_data)
        return project_data

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        meta_file = PROJECTS_DIR / project_id / "project.json"
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                p_dir = PROJECTS_DIR / project_id
                changed = False
                for idx, sc in enumerate(data.get("scenes", [])):
                    if not sc.get("video_path"):
                        clip_file = p_dir / f"clip_{idx + 1}.mp4"
                        if clip_file.exists():
                            sc["video_path"] = str(clip_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                            changed = True
                if changed:
                    try:
                        with open(meta_file, "w", encoding="utf-8") as fw:
                            json.dump(data, fw, indent=2, ensure_ascii=False)
                    except Exception:
                        pass
                return data
        return None

    def save_project(self, data: Dict[str, Any]):
        project_id = data["id"]
        meta_file = PROJECTS_DIR / project_id / "project.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def list_projects(self) -> list:
        projects = []
        for p_dir in PROJECTS_DIR.iterdir():
            if p_dir.is_dir() and (p_dir / "project.json").exists():
                try:
                    with open(p_dir / "project.json", "r", encoding="utf-8") as f:
                        data = json.load(f)
                        data["id"] = p_dir.name
                        projects.append(data)
                except Exception:
                    pass
        projects.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return projects

    async def generate_story(
        self,
        project_id: str,
        num_scenes: int = 4,
        target_duration: int = None,
        language: str = "en",
        audience: str = "general",
        title: str = None
    ) -> Dict[str, Any]:
        """Step 1: Brainstorm story and scenes."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        project_title = (title or project.get("title") or "").strip()
        calc_duration = target_duration or project.get("target_duration") or (num_scenes * 12)

        project["status"] = "brainstorming"
        project["current_step"] = "Brainstorming storyboard and scenes..."
        project["progress"] = 15
        self.save_project(project)

        story_data = await self.script_agent.generate_storyboard(
            idea=project["idea"],
            num_scenes=num_scenes,
            target_duration=calc_duration,
            art_style=project["art_style"],
            language=language,
            audience=audience,
            title=project_title
        )

        final_title = project_title or story_data.get("title") or "Animated Short Film"
        project["title"] = final_title
        project["logline"] = story_data["logline"]
        project["characters"] = story_data.get("characters", "")
        project["scenes"] = story_data["scenes"]
        project["status"] = "storyboard_ready"
        project["progress"] = 30
        project["current_step"] = "Storyboard ready for review"

        # If project folder was created without custom title, rename folder to the AI story title
        old_id = project["id"]
        target_folder_name = self.sanitize_title_for_folder(final_title)
        if target_folder_name != old_id and not (title and title.strip()):
            new_id = self.get_unique_project_id(target_folder_name, current_id=old_id)
            old_dir = PROJECTS_DIR / old_id
            new_dir = PROJECTS_DIR / new_id
            try:
                if old_dir.exists() and not new_dir.exists():
                    os.rename(old_dir, new_dir)
                    project["id"] = new_id
                    print(f"Renamed project folder from '{old_id}' to title-based folder '{new_id}'")
            except Exception as e_rename:
                print(f"Could not rename project folder to '{new_id}': {e_rename}")

        self.save_project(project)
        return project

    async def generate_scene_image(self, project_id: str, scene_idx: int) -> Dict[str, Any]:
        """Generate image for a specific scene with character consistency from reference scenes."""
        project = self.get_project(project_id)
        if not project or scene_idx >= len(project["scenes"]):
            raise ValueError("Invalid project or scene index")

        scene = project["scenes"][scene_idx]
        p_dir = PROJECTS_DIR / project_id
        img_path = p_dir / f"scene_{scene_idx + 1}.jpg"

        if project.get("api_key"):
            self.image_service.api_key = project["api_key"]
        if project.get("ai_provider"):
            self.image_service.provider = project["ai_provider"]

        w = project.get("video_width", 1280)
        h = project.get("video_height", 720)

        # Character consistency: search for reference image from earlier scenes
        ref_img_path = None
        for i in range(scene_idx):
            candidate = p_dir / f"scene_{i + 1}.jpg"
            if candidate.exists():
                ref_img_path = str(candidate)
                break
        if not ref_img_path:
            char_portrait = p_dir / "character_ref.jpg"
            if char_portrait.exists():
                ref_img_path = str(char_portrait)

        character_desc = (project.get("characters") or "").strip()
        # Stable project character seed anchor for visual consistency across scenes
        char_seed = abs(hash(project_id + (character_desc or project.get("idea", "")))) % 999999
        scene_seed = (char_seed + (scene_idx * 17)) % 999999

        await self.image_service.generate_scene_image(
            prompt=scene["visual_prompt"],
            output_path=str(img_path),
            style_key=project["art_style"],
            seed=scene_seed,
            width=w,
            height=h,
            scene_idx=scene_idx,
            title=scene.get("title", f"Scene {scene_idx + 1}"),
            image_mode=project.get("image_mode", "server"),
            character_desc=character_desc,
            reference_image_path=ref_img_path
        )

        # Re-fetch latest project state to avoid race condition overwrite with concurrent scene renders
        fresh_project = self.get_project(project_id) or project
        if scene_idx < len(fresh_project["scenes"]):
            fresh_project["scenes"][scene_idx]["image_path"] = str(img_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            self.save_project(fresh_project)
            return fresh_project

        scene["image_path"] = str(img_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        self.save_project(project)
        return project

    async def generate_all_scene_images(self, project_id: str) -> Dict[str, Any]:
        """Generate images for all scenes in a project strictly one by one, preserving character consistency."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        scenes = project.get("scenes", [])
        for idx, scene in enumerate(scenes):
            if not scene.get("image_path"):
                await self.generate_scene_image(project_id, idx)
                await asyncio.sleep(0.5)

        return self.get_project(project_id) or project

    async def generate_scene_audio(self, project_id: str, scene_idx: int) -> Dict[str, Any]:
        """Regenerate voiceover and subtitles for a specific scene."""
        project = self.get_project(project_id)
        if not project or scene_idx >= len(project["scenes"]):
            raise ValueError("Invalid project or scene index")

        scene = project["scenes"][scene_idx]
        p_dir = PROJECTS_DIR / project_id
        audio_path = p_dir / f"scene_{scene_idx + 1}.mp3"
        srt_path = p_dir / f"scene_{scene_idx + 1}.srt"

        try:
            res = await self.voice_agent.synthesize(
                text=scene["narration"],
                output_audio_path=str(audio_path),
                output_srt_path=str(srt_path),
                voice=project.get("voice", "en-US-ChristopherNeural"),
                api_key=project.get("api_key"),
                allow_voice_fallback=False
            )
        except Exception:
            res = await self.voice_agent.synthesize(
                text=scene["narration"],
                output_audio_path=str(audio_path),
                output_srt_path=str(srt_path),
                voice=project.get("voice", "en-US-ChristopherNeural"),
                api_key=project.get("api_key"),
                allow_voice_fallback=True
            )

        scene["audio_path"] = str(audio_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        scene["srt_path"] = str(srt_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        scene["duration"] = res.get("duration", 4.0) if res else self.voice_agent.get_audio_duration(str(audio_path))
        self.save_project(project)
        return project

    async def render_scene_video(
        self,
        project_id: str,
        scene_idx: int,
        force_revoice: bool = False,
        force_repaint: bool = False
    ) -> Dict[str, Any]:
        """
        Renders an animated video clip for a single scene:
        1. Ensures scene image is generated (with character consistency)
        2. Ensures voiceover narration & subtitles SRT are synthesized
        3. Renders MP4 clip using Ken Burns camera motion & burnt-in subtitles
        """
        project = self.get_project(project_id)
        if not project or scene_idx >= len(project.get("scenes", [])):
            raise ValueError("Invalid project or scene index")

        project_dir = PROJECTS_DIR / project_id
        scene = project["scenes"][scene_idx]

        # 1. Ensure scene illustration exists
        img_file = project_dir / f"scene_{scene_idx + 1}.jpg"
        if force_repaint or not img_file.exists() or not scene.get("image_path"):
            await self.generate_scene_image(project_id, scene_idx)
            project = self.get_project(project_id)
            scene = project["scenes"][scene_idx]

        # 2. Ensure voiceover audio & subtitles exist
        audio_file = project_dir / f"scene_{scene_idx + 1}.mp3"
        srt_file = project_dir / f"scene_{scene_idx + 1}.srt"
        if force_revoice or not audio_file.exists() or not srt_file.exists() or not scene.get("audio_path") or not scene.get("srt_path"):
            await self.generate_scene_audio(project_id, scene_idx)
            project = self.get_project(project_id)
            scene = project["scenes"][scene_idx]

        # 3. Render video clip with Ken Burns camera motion & subtitles
        width = project.get("video_width", 1280)
        height = project.get("video_height", 720)
        engine = VideoEngine(width=width, height=height)

        clip_file = project_dir / f"clip_{scene_idx + 1}.mp4"
        img_full = str(PROJECTS_DIR.parent / scene["image_path"])
        audio_full = str(PROJECTS_DIR.parent / scene["audio_path"])
        srt_full = str(PROJECTS_DIR.parent / scene["srt_path"])
        motion = scene.get("camera_motion", "zoom_in")
        duration = scene.get("duration", 4.0)
        enable_subtitles = project.get("enable_subtitles", True)

        # Check for acting video source (e.g. from Google Flow / I2V generator)
        acting_video_full = None
        raw_acting_cand = project_dir / f"scene_{scene_idx + 1}_acting.mp4"
        if raw_acting_cand.exists():
            acting_video_full = str(raw_acting_cand)
        elif scene.get("raw_video_path"):
            cand_p = PROJECTS_DIR.parent / scene["raw_video_path"]
            if cand_p.exists():
                acting_video_full = str(cand_p)

        engine.render_scene_clip(
            image_path=img_full,
            audio_path=audio_full,
            srt_path=srt_full,
            output_clip_path=str(clip_file),
            motion_type=motion,
            duration=duration,
            enable_subtitles=enable_subtitles,
            source_video_path=acting_video_full
        )

        scene["video_path"] = str(clip_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        self.save_project(project)
        return project

    async def render_all_scene_videos(
        self,
        project_id: str,
        force_revoice: bool = False,
        progress_callback: Optional[Callable[[int, str, int], None]] = None
    ) -> Dict[str, Any]:
        """Renders animation video clips for all scenes in the project sequentially."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        total_scenes = len(project.get("scenes", []))
        if total_scenes == 0:
            return project

        for idx in range(total_scenes):
            if progress_callback:
                progress_callback(idx + 1, f"Rendering animation for scene {idx + 1} of {total_scenes}...", total_scenes)
            await self.render_scene_video(project_id, idx, force_revoice=force_revoice)
            await asyncio.sleep(0.3)

        return self.get_project(project_id) or project

    async def render_full_animation(
        self,
        project_id: str,
        progress_callback: Callable[[int, str], None] = None
    ) -> Dict[str, Any]:
        """
        Executes end-to-end rendering:
        1. Generates images for all scenes if not already present
        2. Synthesizes voiceovers & subtitles for all scenes
        3. Renders each animated scene clip (Ken Burns + Subtitles)
        4. Synthesizes background music
        5. Concatenates & mixes into final MP4
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        project_dir = PROJECTS_DIR / project_id
        width = project.get("video_width", 1280)
        height = project.get("video_height", 720)
        engine = VideoEngine(width=width, height=height)

        def notify(pct: int, msg: str):
            project["progress"] = pct
            project["current_step"] = msg
            self.save_project(project)
            if progress_callback:
                progress_callback(pct, msg)

        project["status"] = "rendering"
        if project.get("api_key"):
            self.image_service.api_key = project["api_key"]
        if project.get("ai_provider"):
            self.image_service.provider = project["ai_provider"]
        notify(35, "Generating scene illustrations with AI...")

        scenes = project["scenes"]
        total_scenes = len(scenes)

        # 1. Images (generated one by one with character consistency)
        for idx, scene in enumerate(scenes):
            img_file = project_dir / f"scene_{idx + 1}.jpg"
            if not img_file.exists():
                notify(35 + int((idx / total_scenes) * 15), f"Painting scene {idx + 1} of {total_scenes} (preserving character consistency)...")
                ref_img_path = None
                for i in range(idx):
                    candidate = project_dir / f"scene_{i + 1}.jpg"
                    if candidate.exists():
                        ref_img_path = str(candidate)
                        break
                if not ref_img_path:
                    char_portrait = project_dir / "character_ref.jpg"
                    if char_portrait.exists():
                        ref_img_path = str(char_portrait)

                character_desc = (project.get("characters") or "").strip()
                char_seed = abs(hash(project_id + (character_desc or project.get("idea", "")))) % 999999
                scene_seed = (char_seed + (idx * 17)) % 999999

                await self.image_service.generate_scene_image(
                    prompt=scene["visual_prompt"],
                    output_path=str(img_file),
                    style_key=project["art_style"],
                    seed=scene_seed,
                    width=width,
                    height=height,
                    scene_idx=idx,
                    title=scene.get("title", f"Scene {idx + 1}"),
                    image_mode=project.get("image_mode", "server"),
                    character_desc=character_desc,
                    reference_image_path=ref_img_path
                )
            scene["image_path"] = str(img_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            if idx < total_scenes - 1:
                await asyncio.sleep(0.8)

        # 2. Voices & Subtitles
        notify(52, "Recording voice actor narration & subtitles...")

        # Enforce exactly ONE voice consistently across the entire clip (no mid-clip fallback or swapping)
        clip_voice = project.get("voice") or "en-US-ChristopherNeural"

        # Up-front audition probe to verify voice operational health and establish 100% clip voice consistency
        try:
            probe_path = project_dir / ".probe_voice.mp3"
            probe_text = "Xin chào, bắt đầu câu chuyện." if ("vi" in clip_voice.lower() or any(ord(c) > 127 for c in scenes[0].get("narration", ""))) else "Welcome, beginning the story."
            probe_res = await self.voice_agent.synthesize(
                text=probe_text,
                output_audio_path=str(probe_path),
                voice=clip_voice,
                api_key=project.get("api_key"),
                allow_voice_fallback=True
            )
            if probe_path.exists():
                try:
                    os.remove(probe_path)
                except Exception:
                    pass
            if probe_res.get("is_fallback") and probe_res.get("voice"):
                clip_voice = probe_res["voice"]
                project["voice"] = clip_voice
                self.save_project(project)
                print(f"Audition probe established consistent clip voice: {clip_voice}")
        except Exception as e_probe:
            print(f"Voice probe notice: {e_probe}")

        for idx, scene in enumerate(scenes):
            audio_file = project_dir / f"scene_{idx + 1}.mp3"
            srt_file = project_dir / f"scene_{idx + 1}.srt"
            if not audio_file.exists() or not srt_file.exists():
                notify(52 + int((idx / total_scenes) * 15), f"Narrating scene {idx + 1} of {total_scenes}...")
                try:
                    res = await self.voice_agent.synthesize(
                        text=scene["narration"],
                        output_audio_path=str(audio_file),
                        output_srt_path=str(srt_file),
                        voice=clip_voice,
                        api_key=project.get("api_key"),
                        allow_voice_fallback=False
                    )
                except Exception as e_voice_fail:
                    print(f"Scene {idx + 1} primary voice notice ({e_voice_fail}). Engaging resilient fallback...")
                    # Fallback allowed so video rendering never fatal-crashes
                    res = await self.voice_agent.synthesize(
                        text=scene["narration"],
                        output_audio_path=str(audio_file),
                        output_srt_path=str(srt_file),
                        voice=clip_voice,
                        api_key=project.get("api_key"),
                        allow_voice_fallback=True
                    )
                    # If this scene resolved to a fallback voice, update clip_voice so subsequent scenes stay consistent
                    if res.get("is_fallback") and res.get("voice"):
                        clip_voice = res["voice"]
                        project["voice"] = clip_voice
                        self.save_project(project)

                scene["duration"] = res.get("duration", 4.0) if res else self.voice_agent.get_audio_duration(str(audio_file))
                await asyncio.sleep(1.2)  # Pace requests to avoid socket throttling and preserve voice consistency
            else:
                scene["duration"] = self.voice_agent.get_audio_duration(str(audio_file))

            scene["audio_path"] = str(audio_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            scene["srt_path"] = str(srt_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")

        # 3. Render scene clips with Ken Burns camera motion & subtitles
        notify(70, "Applying camera animations (zoom & pan) and burning subtitles...")
        scene_clips = []
        for idx, scene in enumerate(scenes):
            clip_file = project_dir / f"clip_{idx + 1}.mp4"
            notify(70 + int((idx / total_scenes) * 15), f"Rendering camera motion for scene {idx + 1}...")

            img_full = str(PROJECTS_DIR.parent / scene["image_path"])
            audio_full = str(PROJECTS_DIR.parent / scene["audio_path"])
            srt_full = str(PROJECTS_DIR.parent / scene["srt_path"])
            # Check for acting video source (e.g. from Google Flow / I2V generator)
            acting_video_full = None
            raw_acting_cand = project_dir / f"scene_{idx + 1}_acting.mp4"
            if raw_acting_cand.exists():
                acting_video_full = str(raw_acting_cand)
            elif scene.get("raw_video_path"):
                cand_p = PROJECTS_DIR.parent / scene["raw_video_path"]
                if cand_p.exists():
                    acting_video_full = str(cand_p)

            motion = scene.get("camera_motion", "zoom_in")

            engine.render_scene_clip(
                image_path=img_full,
                audio_path=audio_full,
                srt_path=srt_full,
                output_clip_path=str(clip_file),
                motion_type=motion,
                duration=scene.get("duration", 4.0),
                enable_subtitles=project.get("enable_subtitles", True),
                source_video_path=acting_video_full
            )
            scene["video_path"] = str(clip_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            scene_clips.append(str(clip_file))
            self.save_project(project)

        # 4. Synthesize Background Music
        notify(88, "Composing atmospheric ambient soundtrack...")
        bgm_file = project_dir / "soundtrack.mp3"
        total_anim_dur = sum(s.get("duration", 4.0) + 0.4 for s in scenes)
        self.music_service.generate_ambient_track(
            output_path=str(bgm_file),
            duration=max(15.0, total_anim_dur + 5.0)
        )

        # 5. Final Stitch & Master Audio Mix
        notify(94, "Final mastering and encoding complete animation...")
        final_video = project_dir / "final_animation.mp4"
        engine.concatenate_and_mix(
            scene_clip_paths=scene_clips,
            output_video_path=str(final_video),
            bgm_path=str(bgm_file),
            bgm_volume=0.12
        )

        project["video_path"] = str(final_video.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        project["status"] = "completed"
        project["progress"] = 100
        project["current_step"] = "Animation rendered successfully!"
        self.save_project(project)

        notify(100, "Ready! Your animated film has been created!")
        return project
