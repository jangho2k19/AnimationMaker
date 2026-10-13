import os
import json
import time
import uuid
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

    def create_project(
        self,
        idea: str,
        art_style: str = "ghibli",
        voice: str = "en-US-ChristopherNeural",
        num_scenes: int = 4,
        target_duration: int = 60,
        aspect_ratio: str = "16:9",
        image_mode: str = "server"
    ) -> Dict[str, Any]:
        """Initialize a new project record."""
        project_id = str(uuid.uuid4())[:8]
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        dim = VIDEO_DIMENSIONS.get(aspect_ratio, VIDEO_DIMENSIONS["16:9"])

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
            "target_duration": target_duration,
            "aspect_ratio": aspect_ratio,
            "video_width": dim["width"],
            "video_height": dim["height"],
            "image_mode": image_mode,
            "enable_subtitles": True,
            "title": "",
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
                return json.load(f)
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
                        projects.append(json.load(f))
                except Exception:
                    pass
        projects.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return projects

    async def generate_story(
        self,
        project_id: str,
        num_scenes: int = 4,
        target_duration: int = 60,
        language: str = "en",
        audience: str = "general"
    ) -> Dict[str, Any]:
        """Step 1: Brainstorm story and scenes."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        project["status"] = "brainstorming"
        project["current_step"] = "Brainstorming storyboard and scenes..."
        project["progress"] = 15
        self.save_project(project)

        story_data = await self.script_agent.generate_storyboard(
            idea=project["idea"],
            num_scenes=num_scenes,
            target_duration=target_duration,
            art_style=project["art_style"],
            language=language,
            audience=audience
        )

        project["title"] = story_data["title"]
        project["logline"] = story_data["logline"]
        project["characters"] = story_data.get("characters", "")
        project["scenes"] = story_data["scenes"]
        project["status"] = "storyboard_ready"
        project["progress"] = 30
        project["current_step"] = "Storyboard ready for review"
        self.save_project(project)
        return project

    async def generate_scene_image(self, project_id: str, scene_idx: int) -> Dict[str, Any]:
        """Regenerate image for a specific scene."""
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

        await self.image_service.generate_scene_image(
            prompt=scene["visual_prompt"],
            output_path=str(img_path),
            style_key=project["art_style"],
            seed=int(time.time() * 1000) % 999999,
            width=w,
            height=h,
            scene_idx=scene_idx,
            title=scene.get("title", f"Scene {scene_idx + 1}"),
            image_mode=project.get("image_mode", "server")
        )

        scene["image_path"] = str(img_path.relative_to(PROJECTS_DIR.parent))
        self.save_project(project)
        return project

    async def generate_scene_audio(self, project_id: str, scene_idx: int) -> Dict[str, Any]:
        """Regenerate voiceover and subtitles for a specific scene."""
        project = self.get_project(project_id)
        if not project or scene_idx >= len(project["scenes"]):
            raise ValueError("Invalid project or scene index")

        scene = project["scenes"][scene_idx]
        p_dir = PROJECTS_DIR / project_id
        audio_path = p_dir / f"scene_{scene_idx + 1}.mp3"
        srt_path = p_dir / f"scene_{scene_idx + 1}.srt"

        res = await self.voice_agent.synthesize(
            text=scene["narration"],
            output_audio_path=str(audio_path),
            output_srt_path=str(srt_path),
            voice=project["voice"]
        )

        scene["audio_path"] = str(audio_path.relative_to(PROJECTS_DIR.parent))
        scene["srt_path"] = str(srt_path.relative_to(PROJECTS_DIR.parent))
        scene["duration"] = res.get("duration", 4.0) if res else self.voice_agent.get_audio_duration(str(audio_path))
        self.save_project(project)
        return project

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

        # 1. Images
        for idx, scene in enumerate(scenes):
            img_file = project_dir / f"scene_{idx + 1}.jpg"
            if not img_file.exists():
                notify(35 + int((idx / total_scenes) * 15), f"Painting scene {idx + 1} of {total_scenes}...")
                await self.image_service.generate_scene_image(
                    prompt=scene["visual_prompt"],
                    output_path=str(img_file),
                    style_key=project["art_style"],
                    seed=hash(project["idea"] + str(idx)) & 0xffffff,
                    width=width,
                    height=height,
                    scene_idx=idx,
                    title=scene.get("title", f"Scene {idx + 1}"),
                    image_mode=project.get("image_mode", "server")
                )
            scene["image_path"] = str(img_file.relative_to(PROJECTS_DIR.parent))
            if idx < total_scenes - 1:
                await asyncio.sleep(1.0)

        # 2. Voices & Subtitles
        notify(52, "Recording voice actor narration & subtitles...")
        for idx, scene in enumerate(scenes):
            audio_file = project_dir / f"scene_{idx + 1}.mp3"
            srt_file = project_dir / f"scene_{idx + 1}.srt"
            if not audio_file.exists() or not srt_file.exists():
                notify(52 + int((idx / total_scenes) * 15), f"Narrating scene {idx + 1} of {total_scenes}...")
                res = await self.voice_agent.synthesize(
                    text=scene["narration"],
                    output_audio_path=str(audio_file),
                    output_srt_path=str(srt_file),
                    voice=project["voice"]
                )
                scene["duration"] = res.get("duration", 4.0) if res else self.voice_agent.get_audio_duration(str(audio_file))
            else:
                scene["duration"] = self.voice_agent.get_audio_duration(str(audio_file))

            scene["audio_path"] = str(audio_file.relative_to(PROJECTS_DIR.parent))
            scene["srt_path"] = str(srt_file.relative_to(PROJECTS_DIR.parent))

        # 3. Render scene clips with Ken Burns camera motion & subtitles
        notify(70, "Applying camera animations (zoom & pan) and burning subtitles...")
        scene_clips = []
        for idx, scene in enumerate(scenes):
            clip_file = project_dir / f"clip_{idx + 1}.mp4"
            notify(70 + int((idx / total_scenes) * 15), f"Rendering camera motion for scene {idx + 1}...")

            img_full = str(PROJECTS_DIR.parent / scene["image_path"])
            audio_full = str(PROJECTS_DIR.parent / scene["audio_path"])
            srt_full = str(PROJECTS_DIR.parent / scene["srt_path"])
            motion = scene.get("camera_motion", "zoom_in")

            engine.render_scene_clip(
                image_path=img_full,
                audio_path=audio_full,
                srt_path=srt_full,
                output_clip_path=str(clip_file),
                motion_type=motion,
                duration=scene.get("duration", 4.0),
                enable_subtitles=project.get("enable_subtitles", True)
            )
            scene_clips.append(str(clip_file))

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

        project["video_path"] = str(final_video.relative_to(PROJECTS_DIR.parent))
        project["status"] = "completed"
        project["progress"] = 100
        project["current_step"] = "Animation rendered successfully!"
        self.save_project(project)

        notify(100, "Ready! Your animated film has been created!")
        return project
