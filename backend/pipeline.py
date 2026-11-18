import os
import json
import time
import uuid
import re
import asyncio
import shutil
import hashlib
from pathlib import Path
from typing import Dict, Any, Callable, Optional

from backend.config import PROJECTS_DIR, ART_STYLES, VOICES, VIDEO_DIMENSIONS, is_comic_style
from backend.agents.script_agent import ScriptAgent
from backend.agents.voice_agent import VoiceAgent
from backend.services.image_service import ImageService
from backend.services.video_engine import VideoEngine
from backend.services.music_service import MusicService

# Serializes project.json writes across concurrent requests / background renders
import threading
_PROJECT_IO_LOCK = threading.RLock()


def safe_project_dir(project_id: str) -> Optional[Path]:
    """
    Resolves a project folder path and guarantees it stays inside PROJECTS_DIR.
    Returns None for empty / traversal ids (e.g. '..', 'a/../../b', absolute paths).
    """
    if not project_id or not isinstance(project_id, str):
        return None
    if any(sep in project_id for sep in ("/", "\\", "\x00")) or project_id.strip() in ("", ".", ".."):
        return None
    try:
        base = PROJECTS_DIR.resolve()
        candidate = (PROJECTS_DIR / project_id).resolve()
    except (OSError, ValueError):
        return None
    if candidate.parent != base:
        return None
    return PROJECTS_DIR / project_id


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
    def stable_seed(text: str, modulus: int = 999999) -> int:
        """Deterministic seed across process restarts (built-in hash() is randomized per process)."""
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        return int(digest[:12], 16) % modulus

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
            if counter > 10000:
                # Pathological collision count: fall back to a guaranteed-unique suffix
                return f"{base_name} ({uuid.uuid4().hex[:8]})"
        return candidate

    @staticmethod
    def _char_slug(name: str) -> str:
        """Creates a filesystem-safe, Unicode-friendly identifier slug for a character."""
        import unicodedata
        norm = unicodedata.normalize("NFKD", (name or "").strip())
        ascii_only = "".join(c for c in norm if not unicodedata.combining(c))
        ascii_only = ascii_only.replace("đ", "d").replace("Đ", "D")
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', ascii_only.lower()).strip('_')
        return slug or f"char_{uuid.uuid4().hex[:6]}"

    @staticmethod
    def _parse_character_entries(characters_str: str) -> list:
        """Parses a `Name: visual description | ...` string into structured dicts without splitting multi-line descriptions."""
        entries = []
        if not characters_str or not isinstance(characters_str, str):
            return entries
        generic_role_labels = {
            "protagonist", "nhân vật chính", "companion", "creature", "antagonist",
            "hero", "heroine", "villain", "sidekick", "mentor", "vai chính", "vai phụ"
        }
        for raw in ScriptAgent.split_characters_summary(characters_str):
            if not raw:
                continue
            name = ""
            desc = ""
            if ":" in raw:
                left, right = raw.split(":", 1)
                left_s = left.strip()
                right_s = right.strip()
                if left_s.lower() in generic_role_labels or re.match(r'^(?:character|nhân vật)\s*\d+$', left_s, re.IGNORECASE):
                    m_sub = re.match(r'^([^,:\(\)\-]+)(?:[,:\-]\s*(.*))?$', right_s)
                    if m_sub:
                        name = m_sub.group(1).strip()
                        desc = (m_sub.group(2) or "").strip()
                    else:
                        name = right_s
                else:
                    name = left_s
                    desc = right_s
            else:
                m_plain = re.match(r'^([^,:\(\)\-]+)(?:[,:\-]\s*(.*))?$', raw)
                if m_plain:
                    name = m_plain.group(1).strip()
                    desc = (m_plain.group(2) or "").strip()
                else:
                    name = raw
            name = re.sub(r'^[\[\(]|[\)\]]$', '', name).strip()
            if not name or ScriptAgent.is_non_character_label(name):
                continue
            entries.append({"name": name, "description": desc})
        return entries

    @staticmethod
    def _is_fragment_of_other_descriptions(name: str, desc: str, other_norm_descs: list) -> bool:
        """Detects bogus pseudo-characters extracted from inside another character's multi-line description."""
        if not other_norm_descs:
            return False
        norm_name = re.sub(r'\s+', ' ', (name or "")).strip().lower()
        norm_desc = re.sub(r'\s+', ' ', (desc or "")).strip().lower()
        candidates = []
        if len(norm_desc) >= 12:
            candidates.append(norm_desc)
        if norm_name and norm_desc:
            candidates.append(f"{norm_name}: {norm_desc}")
            candidates.append(f"{norm_name} {norm_desc}")
            candidates.append(f"{norm_name}, {norm_desc}")
        if not candidates and len(norm_name) >= 6:
            candidates.append(norm_name)
        for cand in candidates:
            if len(cand) < 10:
                continue
            for o_desc in other_norm_descs:
                if cand in o_desc and len(o_desc) > len(cand) + 12:
                    return True
        return False

    def sync_character_profiles(self, project: Dict[str, Any], sync_back_string: bool = True) -> list:
        """
        Reconciles `project["character_profiles"]` with `characters`, `scenes[].dialogues`,
        and `character_voices`, preserving any existing images, descriptions, and optional voices.
        Heals multi-line fragment pseudo-characters, attribute/table rows, and case/spelling duplicates.
        """
        pid = project.get("id")
        p_dir = safe_project_dir(pid) if pid else None
        chars_dir = (p_dir / "characters") if p_dir else None

        existing_profiles = project.get("character_profiles")
        if not isinstance(existing_profiles, list):
            existing_profiles = []

        spoken_low = {
            (d.get("speaker") or "").strip().lower()
            for sc in project.get("scenes", [])
            for d in (sc.get("dialogues") or [])
            if isinstance(d, dict) and (d.get("speaker") or "").strip()
        }

        norm_descs_all = [
            (idx, re.sub(r'\s+', ' ', (prof.get("description") or "")).strip().lower())
            for idx, prof in enumerate(existing_profiles)
            if isinstance(prof, dict) and (prof.get("description") or "").strip()
        ]

        by_key = {}
        ordered_profiles = []
        used_ids = set()
        dropped_names_low = set()

        def _make_unique_id(base_name: str, preferred_id: str = None) -> str:
            cand = (preferred_id or f"char_{self._char_slug(base_name)}").strip()
            cand = re.sub(r'[^a-zA-Z0-9_\-]', '_', cand) or f"char_{uuid.uuid4().hex[:6]}"
            if cand not in used_ids:
                used_ids.add(cand)
                return cand
            n = 2
            while f"{cand}_{n}" in used_ids:
                n += 1
            uniq = f"{cand}_{n}"
            used_ids.add(uniq)
            return uniq

        for idx, prof in enumerate(existing_profiles):
            if not isinstance(prof, dict) or not (prof.get("name") or "").strip():
                continue
            p_name = prof["name"].strip()
            p_desc = (prof.get("description") or "").strip()
            img_rel = (prof.get("image_path") or "").replace("\\", "/").strip()
            if img_rel and not (PROJECTS_DIR.parent / img_rel).exists():
                img_rel = ""

            if ScriptAgent.is_non_character_label(p_name) and not img_rel:
                dropped_names_low.add(p_name.lower())
                continue

            if not img_rel and p_name.lower() not in spoken_low:
                other_descs = [od for o_idx, od in norm_descs_all if o_idx != idx]
                if self._is_fragment_of_other_descriptions(p_name, p_desc, other_descs):
                    dropped_names_low.add(p_name.lower())
                    continue

            alias_target = next(
                (ex for ex in ordered_profiles if ScriptAgent.is_same_character_alias(p_name, ex["name"], ex.get("description", ""))),
                None
            )
            if alias_target:
                if len(p_desc) > len(alias_target.get("description") or ""):
                    alias_target["description"] = p_desc
                if img_rel and not alias_target.get("image_path"):
                    alias_target["image_path"] = img_rel
                if (prof.get("voice_id") or "").strip() and not (alias_target.get("voice_id") or "").strip():
                    alias_target["voice_id"] = str(prof["voice_id"]).strip()
                if p_name.lower() != alias_target["name"].lower():
                    dropped_names_low.add(p_name.lower())
                continue

            cid = _make_unique_id(p_name, prof.get("id"))
            if not img_rel and chars_dir and chars_dir.exists():
                for ext in (".jpg", ".png", ".jpeg", ".webp"):
                    cand_f = chars_dir / f"{cid}{ext}"
                    if cand_f.exists():
                        img_rel = str(cand_f.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                        break
            item = {
                "id": cid,
                "name": p_name,
                "description": p_desc,
                "voice_id": (prof.get("voice_id") if prof.get("voice_id") is not None else ""),
                "image_path": img_rel,
                "role": prof.get("role") or "character"
            }
            by_key[p_name.lower()] = item
            ordered_profiles.append(item)

        voices_map = project.get("character_voices") or {}
        existing_norm_descs = [
            re.sub(r'\s+', ' ', (p.get("description") or "")).strip().lower()
            for p in ordered_profiles
            if (p.get("description") or "").strip()
        ]

        # Merge from `characters` description string
        for parsed in self._parse_character_entries(project.get("characters") or ""):
            if self._is_fragment_of_other_descriptions(parsed["name"], parsed["description"], existing_norm_descs):
                dropped_names_low.add(parsed["name"].lower())
                continue
            alias_target = next(
                (ex for ex in ordered_profiles if ScriptAgent.is_same_character_alias(parsed["name"], ex["name"], ex.get("description", ""))),
                None
            )
            if alias_target:
                if parsed["description"] and not alias_target["description"]:
                    alias_target["description"] = parsed["description"]
            else:
                key = parsed["name"].lower()
                cid = _make_unique_id(parsed["name"])
                img_rel = ""
                if chars_dir and chars_dir.exists():
                    for ext in (".jpg", ".png", ".jpeg", ".webp"):
                        cand_f = chars_dir / f"{cid}{ext}"
                        if cand_f.exists():
                            img_rel = str(cand_f.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                            break
                item = {
                    "id": cid,
                    "name": parsed["name"],
                    "description": parsed["description"],
                    "voice_id": voices_map.get(parsed["name"], ""),
                    "image_path": img_rel,
                    "role": "character"
                }
                by_key[key] = item
                ordered_profiles.append(item)
                if item["description"]:
                    existing_norm_descs.append(re.sub(r'\s+', ' ', item["description"]).strip().lower())

        # Merge speakers from scenes[].dialogues & valid non-attribute character_voices keys
        speaker_names = []
        for sc in project.get("scenes", []):
            for d in (sc.get("dialogues") or []):
                if isinstance(d, dict) and (d.get("speaker") or "").strip():
                    speaker_names.append(d["speaker"].strip())
        for k in voices_map.keys():
            if k and isinstance(k, str):
                k_s = k.strip()
                if k_s.lower() not in dropped_names_low and not ScriptAgent.is_non_character_label(k_s):
                    speaker_names.append(k_s)

        for spk in speaker_names:
            if ScriptAgent.is_non_character_label(spk):
                continue
            low = spk.lower()
            if low in dropped_names_low:
                continue
            alias_target = next(
                (ex for ex in ordered_profiles if ScriptAgent.is_same_character_alias(spk, ex["name"], ex.get("description", ""))),
                None
            )
            if alias_target:
                # Migrate any orphaned voice assigned to the alias onto the canonical profile
                if not (alias_target.get("voice_id") or "").strip() and (voices_map.get(spk) or "").strip():
                    alias_target["voice_id"] = str(voices_map[spk]).strip()
                if spk != alias_target["name"]:
                    dropped_names_low.add(low)
                continue
            cid = _make_unique_id(spk)
            img_rel = ""
            if chars_dir and chars_dir.exists():
                for ext in (".jpg", ".png", ".jpeg", ".webp"):
                    cand_f = chars_dir / f"{cid}{ext}"
                    if cand_f.exists():
                        img_rel = str(cand_f.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                        break
            item = {
                "id": cid,
                "name": spk,
                "description": "",
                "voice_id": voices_map.get(spk, ""),
                "image_path": img_rel,
                "role": "character"
            }
            by_key[low] = item
            ordered_profiles.append(item)

        # Clean & sync character_voices
        if not isinstance(project.get("character_voices"), dict):
            project["character_voices"] = {"Narrator": project.get("voice") or "en-US-ChristopherNeural"}
        else:
            canonical_by_low = {p["name"].lower(): p["name"] for p in ordered_profiles}
            cleaned_voices = {}
            for vk, vv in project["character_voices"].items():
                vk_s = (vk or "").strip()
                if not vk_s:
                    continue
                if vk_s.lower() == "narrator":
                    cleaned_voices["Narrator"] = vv
                    continue
                if vk_s.lower() in dropped_names_low or ScriptAgent.is_non_character_label(vk_s):
                    continue
                canon_name = canonical_by_low.get(vk_s.lower()) or vk_s
                if canon_name not in cleaned_voices:
                    cleaned_voices[canon_name] = vv
            if "Narrator" not in cleaned_voices:
                cleaned_voices["Narrator"] = project.get("voice") or "en-US-ChristopherNeural"
            project["character_voices"] = cleaned_voices

        for item in ordered_profiles:
            nm = item["name"]
            if item.get("voice_id") not in (None, ""):
                project["character_voices"][nm] = item["voice_id"]
            elif nm in project["character_voices"] and project["character_voices"][nm]:
                item["voice_id"] = project["character_voices"][nm]

        project["character_profiles"] = ordered_profiles
        raw_chars_str = project.get("characters") or ""
        if ordered_profiles and (sync_back_string or "\n" in raw_chars_str or "\t" in raw_chars_str or bool(dropped_names_low)):
            project["characters"] = ScriptAgent.format_characters_summary(ordered_profiles)
        return ordered_profiles

    def resolve_scene_character_references(self, project: Dict[str, Any], scene_idx: int) -> list:
        """
        Determines which character profile portrait images apply to `scenes[scene_idx]`.
        Uses explicit `scene.get("character_ids")` if pinned, otherwise matches character names
        against the scene's prompt, narration, title, and dialogue speakers. Falls back to
        primary character portraits with images if no specific match is found.
        """
        scenes = project.get("scenes", [])
        if scene_idx < 0 or scene_idx >= len(scenes):
            return []
        scene = scenes[scene_idx]
        profiles = self.sync_character_profiles(project, sync_back_string=False)
        with_images = [
            p for p in profiles
            if p.get("image_path") and (PROJECTS_DIR.parent / p["image_path"]).exists()
        ]
        if not with_images:
            return []

        pinned_ids = scene.get("character_ids")
        matched = []
        if isinstance(pinned_ids, list) and len(pinned_ids) > 0:
            pin_set = set(str(cid) for cid in pinned_ids)
            matched = [p for p in with_images if p["id"] in pin_set]

        if not matched:
            scene_speakers = [
                str(d.get("speaker") or "").strip()
                for d in (scene.get("dialogues") or [])
                if isinstance(d, dict) and (d.get("speaker") or "").strip()
            ]
            # Prioritize visual fields + dialogue speakers (who is actually visible on-screen in this shot)
            visual_haystack = " ".join([
                str(scene.get("title") or ""),
                str(scene.get("visual_prompt") or ""),
                " ".join(scene_speakers),
            ])
            for p in with_images:
                if (
                    ScriptAgent.character_appears_in_text(p["name"], p.get("description", ""), visual_haystack)
                    or any(ScriptAgent.is_same_character_alias(spk, p["name"], p.get("description", "")) for spk in scene_speakers)
                ):
                    matched.append(p)

            # Fallback to narration / acting_prompt only if visual fields named no characters
            if not matched:
                fallback_haystack = " ".join([
                    str(scene.get("narration") or ""),
                    str(scene.get("acting_prompt") or ""),
                ])
                for p in with_images:
                    if ScriptAgent.character_appears_in_text(p["name"], p.get("description", ""), fallback_haystack):
                        matched.append(p)

        if not matched:
            matched = with_images[:4]

        refs = []
        for p in matched[:6]:
            full_p = PROJECTS_DIR.parent / p["image_path"]
            if full_p.exists():
                refs.append({
                    "id": p["id"],
                    "name": p["name"],
                    "description": p.get("description", ""),
                    "path": str(full_p)
                })
        return refs

    def create_project(
        self,
        idea: str,
        title: str = "",
        art_style: str = "ghibli",
        voice: str = "en-US-ChristopherNeural",
        num_scenes: int = 4,
        target_duration: int = None,
        aspect_ratio: str = "16:9",
        image_mode: str = "gemini",
        enable_voiceover: bool = True,
        enable_subtitles: bool = True,
        project_type: str = "animation",
        product_info: Optional[Dict[str, Any]] = None,
        enable_multivoice: bool = True,
        camera_on_speaker: bool = False,
        director_skill: str = "auto",
        enable_image_captions: bool = True,
        character_profiles: Optional[list] = None,
        use_char_refs_in_video: bool = True
    ) -> Dict[str, Any]:
        """Initialize a new project record with folder name matching the title."""
        if art_style == "dialogue_cinema":
            art_style = "ghibli"
            camera_on_speaker = True
        chosen_title = (title or "").strip()
        effective_lang = ScriptAgent.detect_language(f"{chosen_title} {idea or ''}", fallback="en", voice=voice or "")
        is_vi_proj = effective_lang.startswith("vi")

        # Auto-align voice with detected language if an English voice was passed for a Vietnamese project
        chosen_voice = voice
        if is_vi_proj and (not chosen_voice or chosen_voice.lower().startswith("en-")):
            chosen_voice = "vi-VN-HoaiMyNeural-story"
        elif (not is_vi_proj) and (chosen_voice and chosen_voice.lower().startswith("vi-")):
            chosen_voice = "en-US-ChristopherNeural"

        base_name = self.sanitize_title_for_folder(chosen_title, fallback=idea)
        project_id = self.get_unique_project_id(base_name)
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        dim = VIDEO_DIMENSIONS.get(aspect_ratio, VIDEO_DIMENSIONS["16:9"])
        is_auto_pacing = target_duration in ("auto", "dynamic", "agent") or (isinstance(target_duration, str) and target_duration.lower() == "auto")
        if is_auto_pacing:
            calc_duration = "auto"
        elif target_duration and isinstance(target_duration, (int, float)) and target_duration > 0:
            calc_duration = int(target_duration)
        elif target_duration and str(target_duration).isdigit() and int(target_duration) > 0:
            calc_duration = int(target_duration)
        else:
            calc_duration = ((num_scenes or 4) * 8)

        project_data = {
            "id": project_id,
            "created_at": time.time(),
            "project_type": project_type,
            "product_info": product_info or {},
            "product_images": [],
            "idea": idea,
            "art_style": art_style,
            "director_skill": director_skill or "auto",
            "camera_on_speaker": bool(camera_on_speaker),
            "language": "vi" if is_vi_proj else "en",
            "voice": chosen_voice,
            "enable_multivoice": enable_multivoice,
            "character_voices": {"Narrator": chosen_voice},
            "ai_provider": self.ai_provider,
            "ai_model": self.ai_model or "",
            "api_key": self.api_key or "",
            "num_scenes": num_scenes,
            "pacing_mode": "auto" if is_auto_pacing else "manual",
            "target_duration": calc_duration,
            "aspect_ratio": aspect_ratio,
            "video_width": dim["width"],
            "video_height": dim["height"],
            "image_mode": image_mode,
            "enable_subtitles": enable_subtitles,
            "enable_voiceover": enable_voiceover,
            "enable_image_captions": bool(enable_image_captions),
            "use_char_refs_in_video": bool(use_char_refs_in_video),
            "title": (title or "").strip(),
            "logline": "",
            "characters": "",
            "character_profiles": [],
            "scenes": [],
            "status": "created",
            "progress": 0,
            "current_step": "Initialized",
            "video_path": None
        }

        if character_profiles and isinstance(character_profiles, list):
            chars_dir = project_dir / "characters"
            chars_dir.mkdir(parents=True, exist_ok=True)
            norm_profiles = []
            for raw_cp in character_profiles:
                if not isinstance(raw_cp, dict) or not (raw_cp.get("name") or "").strip():
                    continue
                cp_name = raw_cp["name"].strip()
                cp_id = (raw_cp.get("id") or f"char_{self._char_slug(cp_name)}").strip()
                cp_id = re.sub(r'[^a-zA-Z0-9_\-]', '_', cp_id)
                cp_desc = (raw_cp.get("description") or "").strip()
                cp_voice = (raw_cp.get("voice_id") or "").strip()
                img_rel = ""
                raw_img = (raw_cp.get("image_path") or "").replace("\\", "/").strip()
                if raw_img:
                    src_img = PROJECTS_DIR.parent / raw_img
                    if src_img.exists():
                        dest_img = chars_dir / f"{cp_id}.jpg"
                        try:
                            shutil.copy2(src_img, dest_img)
                            img_rel = str(dest_img.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                        except Exception:
                            img_rel = raw_img
                norm_profiles.append({
                    "id": cp_id,
                    "name": cp_name,
                    "description": cp_desc,
                    "voice_id": cp_voice,
                    "image_path": img_rel,
                    "role": raw_cp.get("role") or "character"
                })
                if cp_voice:
                    project_data["character_voices"][cp_name] = cp_voice
            project_data["character_profiles"] = norm_profiles
            if norm_profiles:
                project_data["characters"] = ScriptAgent.format_characters_summary(norm_profiles)

        self.save_project(project_data)
        return project_data

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        p_dir = safe_project_dir(project_id)
        if p_dir is None:
            return None
        meta_file = p_dir / "project.json"
        if meta_file.exists():
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[pipeline] Could not read project '{project_id}': {e}")
                return None
            changed = False
            # Normalize legacy 'dialogue_cinema' art_style into combinable visual style + camera_on_speaker
            if data.get("art_style") == "dialogue_cinema":
                data["art_style"] = "ghibli"
                data["camera_on_speaker"] = True
                changed = True
            elif "camera_on_speaker" not in data:
                data["camera_on_speaker"] = False
            for idx, sc in enumerate(data.get("scenes", [])):
                # Auto-recover image_path from disk if missing or file deleted/recreated
                cur_img = sc.get("image_path")
                if not cur_img or not (PROJECTS_DIR.parent / cur_img).exists():
                    for ext in [".jpg", ".png", ".jpeg", ".webp"]:
                        img_file = p_dir / f"scene_{idx + 1}{ext}"
                        if img_file.exists():
                            sc["image_path"] = str(img_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                            changed = True
                            break
                # Auto-recover video_path from disk
                if not sc.get("video_path"):
                    clip_file = p_dir / f"clip_{idx + 1}.mp4"
                    if clip_file.exists():
                        sc["video_path"] = str(clip_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                        changed = True
                # Auto-recover audio_path from disk
                if not sc.get("audio_path"):
                    audio_file = p_dir / f"scene_{idx + 1}.mp3"
                    if audio_file.exists():
                        sc["audio_path"] = str(audio_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                        changed = True
            if "use_char_refs_in_video" not in data:
                data["use_char_refs_in_video"] = True
            before_profiles = json.dumps(data.get("character_profiles", []), ensure_ascii=False, sort_keys=True)
            before_chars = data.get("characters", "")
            before_voices = json.dumps(data.get("character_voices", {}), ensure_ascii=False, sort_keys=True)
            self.sync_character_profiles(data, sync_back_string=False)
            after_profiles = json.dumps(data.get("character_profiles", []), ensure_ascii=False, sort_keys=True)
            after_voices = json.dumps(data.get("character_voices", {}), ensure_ascii=False, sort_keys=True)
            if before_profiles != after_profiles or data.get("characters", "") != before_chars or before_voices != after_voices:
                changed = True
            if changed:
                try:
                    self._atomic_write_json(meta_file, data)
                except Exception as e:
                    print(f"[pipeline] Could not persist recovered paths for '{project_id}': {e}")
            return data
        return None

    @staticmethod
    def _atomic_write_json(meta_file: Path, data: Dict[str, Any]):
        """Write JSON to a temp file then atomically replace, so a crash never leaves a truncated project.json."""
        tmp_file = meta_file.with_name(f".{meta_file.name}.{uuid.uuid4().hex[:8]}.tmp")
        with _PROJECT_IO_LOCK:
            try:
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_file, meta_file)
            finally:
                if tmp_file.exists():
                    try:
                        tmp_file.unlink()
                    except OSError:
                        pass

    def save_project(self, data: Dict[str, Any]):
        project_id = data["id"]
        meta_dir = safe_project_dir(project_id)
        if meta_dir is None:
            raise ValueError(f"Invalid project id: {project_id!r}")
        meta_dir.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = time.time()
        self._atomic_write_json(meta_dir / "project.json", data)

    def list_projects(self) -> list:
        projects = []
        for p_dir in PROJECTS_DIR.iterdir():
            if p_dir.is_dir() and (p_dir / "project.json").exists():
                try:
                    p = self.get_project(p_dir.name)
                    if p:
                        projects.append(p)
                except Exception:
                    pass
        projects.sort(key=lambda x: x.get("created_at", 0), reverse=True)
        return projects

    def list_active_tasks(self) -> list:
        active = []
        for p in self.list_projects():
            status = p.get("status")
            if status in ("rendering", "brainstorming"):
                thumb = None
                for sc in p.get("scenes", []):
                    if sc.get("image_path"):
                        thumb = sc["image_path"].replace("\\", "/")
                        break
                active.append({
                    "id": p.get("id"),
                    "title": p.get("title") or p.get("idea") or "Untitled Film",
                    "status": status,
                    "progress": p.get("progress", 0),
                    "current_step": p.get("current_step", ""),
                    "art_style": p.get("art_style", ""),
                    "scenes_count": len(p.get("scenes", [])),
                    "created_at": p.get("created_at", 0),
                    "updated_at": p.get("updated_at", 0),
                    "video_path": p.get("video_path"),
                    "thumbnail": thumb
                })
        return active

    def delete_project(self, project_id: str) -> bool:
        p_dir = safe_project_dir(project_id)
        if p_dir is None:
            return False
        if p_dir.exists() and p_dir.is_dir():
            shutil.rmtree(p_dir, ignore_errors=True)
            return True
        return False

    def import_project_json(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw_data, dict):
            raise ValueError("Imported project must be a JSON object")
        if not isinstance(raw_data.get("scenes", []), list):
            raise ValueError("Imported project 'scenes' must be a list")
        existing_id = raw_data.get("id")
        if existing_id and safe_project_dir(existing_id) is not None and (PROJECTS_DIR / existing_id).exists():
            project_id = existing_id
        else:
            title = raw_data.get("title") or raw_data.get("idea") or "Imported Project"
            clean_id = self.sanitize_title_for_folder(title)
            project_id = self.get_unique_project_id(clean_id)
            raw_data["id"] = project_id
        p_dir = PROJECTS_DIR / project_id
        p_dir.mkdir(parents=True, exist_ok=True)
        self.save_project(raw_data)
        return self.get_project(project_id) or raw_data

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
        target_dur_param = target_duration if target_duration is not None else project.get("target_duration")
        is_auto_pacing = target_dur_param in ("auto", "dynamic", "agent", None) or (isinstance(target_dur_param, (int, float)) and target_dur_param <= 0)
        calc_duration = "auto" if is_auto_pacing else target_dur_param

        # Detect effective language from project content and align with voice
        effective_lang = ScriptAgent.detect_language(
            f"{project_title} {project.get('idea', '')}",
            fallback=language or project.get("language") or "en",
            voice=project.get("voice") or ""
        )
        is_vi = effective_lang.startswith("vi")
        if is_vi and (not project.get("voice") or project.get("voice", "").lower().startswith("en-")):
            project["voice"] = "vi-VN-HoaiMyNeural-story"
            if "character_voices" in project and "Narrator" in project["character_voices"]:
                project["character_voices"]["Narrator"] = "vi-VN-HoaiMyNeural-story"
        project["language"] = "vi" if is_vi else "en"

        project["status"] = "brainstorming"
        project["current_step"] = "Brainstorming storyboard and scenes..."
        project["progress"] = 15
        # Dynamically use project's configured provider, model, and key if set
        active_provider = project.get("ai_provider") or self.ai_provider
        active_model = project.get("ai_model") or self.ai_model
        active_key = project.get("api_key") or self.api_key
        script_agent = ScriptAgent(api_key=active_key, provider=active_provider, model=active_model)

        story_data = await script_agent.generate_storyboard(
            idea=project["idea"],
            num_scenes=num_scenes,
            target_duration=calc_duration,
            art_style=project["art_style"],
            language=effective_lang,
            audience=audience,
            title=project_title,
            camera_on_speaker=bool(project.get("camera_on_speaker", False)),
            director_skill=project.get("director_skill", "auto"),
            preset_characters=project.get("character_profiles")
        )

        final_title = project_title or story_data.get("title") or "Animated Short Film"
        project["title"] = final_title
        project["logline"] = story_data["logline"]
        chars_val = (story_data.get("characters") or "").strip()
        if not chars_val:
            try:
                deep_info = ScriptAgent.deep_analyze_story_input(
                    idea=project["idea"],
                    title=final_title,
                    art_style=project["art_style"],
                    language=effective_lang,
                    audience=audience,
                    num_scenes=len(story_data.get("scenes", [])),
                    director_skill=project.get("director_skill", "auto"),
                    camera_on_speaker=bool(project.get("camera_on_speaker", False))
                )
                chars_val = deep_info.get("characters_blueprint", "")
            except Exception:
                pass
        if not project.get("characters"):
            project["characters"] = chars_val
        elif chars_val and not project.get("character_profiles"):
            project["characters"] = chars_val
        project["scenes"] = story_data["scenes"]

        # Reconcile character profiles (preserving Stage 1 images & optional user-set voices)
        self.sync_character_profiles(project, sync_back_string=True)

        # Auto-cast character voices for multi-voice dialogue (preserving any Stage 1 explicit voices)
        project["character_voices"] = ScriptAgent.auto_assign_character_voices(
            characters_str=project.get("characters", ""),
            scenes=project.get("scenes", []),
            language=effective_lang,
            narrator_voice=project.get("voice"),
            existing_voices=project.get("character_voices")
        )
        self.sync_character_profiles(project, sync_back_string=True)
        # Record the final scene count (important when Auto mode let the agent decide)
        actual_count = len(project["scenes"])
        if actual_count > 0:
            project["num_scenes_mode"] = "auto" if (not num_scenes or num_scenes <= 0) else "manual"
            project["num_scenes"] = actual_count
            total_calc_dur = 0.0
            for sc in project["scenes"]:
                if not sc.get("duration") or sc.get("duration") <= 0:
                    w_cnt = len((sc.get("narration") or "").split())
                    sc["duration"] = max(5.0, min(12.0, round(w_cnt / 2.3 + 2.0, 1))) if is_auto_pacing else 8.0
                total_calc_dur += float(sc["duration"])
            if is_auto_pacing:
                project["pacing_mode"] = "auto"
                project["target_duration"] = round(total_calc_dur, 1)
            elif not target_dur_param or (isinstance(target_dur_param, (int, float)) and target_dur_param <= 0):
                project["target_duration"] = actual_count * 8
            else:
                project["target_duration"] = target_dur_param
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
                    for prof in project.get("character_profiles", []):
                        if isinstance(prof, dict) and prof.get("image_path"):
                            prof["image_path"] = prof["image_path"].replace(f"projects/{old_id}/", f"projects/{new_id}/")
                    project["id"] = new_id
                    print(f"Renamed project folder from '{old_id}' to title-based folder '{new_id}'")
            except Exception as e_rename:
                print(f"Could not rename project folder to '{new_id}': {e_rename}")

        self.save_project(project)
        return project

    async def generate_scene_image(self, project_id: str, scene_idx: int) -> Dict[str, Any]:
        """Generate image for a specific scene with character consistency from Character Portraits & reference scenes."""
        project = self.get_project(project_id)
        if not project or scene_idx < 0 or scene_idx >= len(project["scenes"]):
            raise ValueError("Invalid project or scene index")

        scene = project["scenes"][scene_idx]
        p_dir = PROJECTS_DIR / project_id
        img_path = p_dir / f"scene_{scene_idx + 1}.jpg"

        w = project.get("video_width", 1280)
        h = project.get("video_height", 720)

        # Resolve matched character portrait reference sheets for this scene
        char_refs = self.resolve_scene_character_references(project, scene_idx)

        # Only attach prior rendered scene_1.jpg when NO dedicated character portrait refs are available;
        # otherwise prior wide shots with smaller/varied headwear or faces override Character Studio portraits.
        ref_img_path = None
        if not char_refs:
            for i in range(scene_idx):
                candidate = p_dir / f"scene_{i + 1}.jpg"
                if candidate.exists():
                    ref_img_path = str(candidate)
                    break
            if not ref_img_path:
                char_portrait = p_dir / "character_ref.jpg"
                if char_portrait.exists():
                    ref_img_path = str(char_portrait)

        if char_refs:
            character_desc = ScriptAgent.format_characters_summary(char_refs)
        else:
            character_desc = (project.get("characters") or "").strip()
        # Stable project character seed anchor for visual consistency across scenes
        char_seed = self.stable_seed(project_id + (character_desc or project.get("idea", "")))
        scene_seed = (char_seed + (scene_idx * 17)) % 999999

        is_spk_cam = bool(
            project.get("camera_on_speaker", False)
            or scene.get("camera_motion") == "speaker_focus"
            or project.get("art_style") == "dialogue_cinema"
        )
        await self.image_service.generate_scene_image(
            prompt=scene["visual_prompt"],
            output_path=str(img_path),
            style_key=project["art_style"],
            seed=scene_seed,
            width=w,
            height=h,
            scene_idx=scene_idx,
            title=scene.get("title", f"Scene {scene_idx + 1}"),
            image_mode=project.get("image_mode", "gemini"),
            character_desc=character_desc,
            reference_image_path=ref_img_path,
            character_references=char_refs,
            api_key=project.get("api_key"),
            provider=project.get("ai_provider"),
            camera_on_speaker=is_spk_cam,
            dialogues=scene.get("dialogues"),
            narration=scene.get("narration", ""),
            dialogue_only=bool(scene.get("dialogue_only", False)),
            enable_image_captions=bool(project.get("enable_image_captions", True))
        )

        # Re-fetch latest project state to avoid race condition overwrite with concurrent scene renders
        fresh_project = self.get_project(project_id) or project
        if img_path.exists():
            rel_image_path = str(img_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            if scene_idx < len(fresh_project.get("scenes", [])):
                fresh_project["scenes"][scene_idx]["image_path"] = rel_image_path
                if char_refs:
                    fresh_project["scenes"][scene_idx]["used_character_ids"] = [c["id"] for c in char_refs]
                self.save_project(fresh_project)
                return fresh_project

            scene["image_path"] = rel_image_path
            self.save_project(project)
            return project

        return fresh_project

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
        if not project or scene_idx < 0 or scene_idx >= len(project["scenes"]):
            raise ValueError("Invalid project or scene index")

        scene = project["scenes"][scene_idx]
        p_dir = PROJECTS_DIR / project_id
        audio_path = p_dir / f"scene_{scene_idx + 1}.mp3"
        srt_path = p_dir / f"scene_{scene_idx + 1}.srt"

        # Keep natural normal narration speed (do not compress audio to an arbitrary max_duration)
        max_dur = None

        scene_dial_only = scene.get("dialogue_only")
        if scene_dial_only is None:
            scene_dial_only = bool(project.get("dialogue_only", False)) or (
                not project.get("enable_voiceover", True) and bool(project.get("enable_multivoice", True))
            )
        else:
            scene_dial_only = bool(scene_dial_only)

        enable_mv = bool(project.get("enable_multivoice", True) or scene_dial_only)
        enable_narrator = False if scene_dial_only else bool(project.get("enable_voiceover", True))
        char_voices = project.get("character_voices") or {}
        sc_dialogues = scene.get("dialogues")

        # Ensure scene dialogues use actual named characters instead of generic "Character"
        named_chars = [c for c in char_voices.keys() if c.lower() not in ("narrator", "người kể chuyện", "character")]
        if (enable_mv or scene_dial_only) and (not sc_dialogues or (named_chars and any((d.get("speaker") or "").lower() == "character" for d in sc_dialogues))):
            from backend.agents.script_agent import ScriptAgent
            fresh_dialogues = ScriptAgent.extract_scene_dialogue_segments(
                narration=scene.get("narration", ""),
                characters=named_chars or project.get("characters"),
                narrator_name="Narrator"
            )
            if fresh_dialogues:
                sc_dialogues = fresh_dialogues
                scene["dialogues"] = fresh_dialogues
                self.save_project(project)

        try:
            res = await self.voice_agent.synthesize(
                text=scene["narration"],
                output_audio_path=str(audio_path),
                output_srt_path=str(srt_path),
                voice=project.get("voice", "en-US-ChristopherNeural"),
                api_key=project.get("api_key"),
                allow_voice_fallback=False,
                max_duration=max_dur,
                dialogues=sc_dialogues,
                character_voices=char_voices,
                enable_multivoice=enable_mv,
                include_narrator=enable_narrator
            )
        except Exception:
            res = await self.voice_agent.synthesize(
                text=scene["narration"],
                output_audio_path=str(audio_path),
                output_srt_path=str(srt_path),
                voice=project.get("voice", "en-US-ChristopherNeural"),
                api_key=project.get("api_key"),
                allow_voice_fallback=True,
                max_duration=max_dur,
                dialogues=sc_dialogues,
                character_voices=char_voices,
                enable_multivoice=enable_mv,
                include_narrator=enable_narrator
            )

        scene["audio_path"] = str(audio_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        scene["srt_path"] = str(srt_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        scene["voiced_narration"] = (scene.get("narration") or "").strip()
        scene["voiced_dialogue_only"] = scene_dial_only
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
        if not project or scene_idx < 0 or scene_idx >= len(project.get("scenes", [])):
            raise ValueError("Invalid project or scene index")

        project_dir = PROJECTS_DIR / project_id
        scene = project["scenes"][scene_idx]

        # 1. Ensure scene illustration exists
        img_file = project_dir / f"scene_{scene_idx + 1}.jpg"
        if force_repaint or not img_file.exists() or not scene.get("image_path"):
            await self.generate_scene_image(project_id, scene_idx)
            project = self.get_project(project_id)
            scene = project["scenes"][scene_idx]

        # 2. Ensure voiceover audio & subtitles exist if enabled
        scene_dial_only = scene.get("dialogue_only")
        if scene_dial_only is None:
            scene_dial_only = bool(project.get("dialogue_only", False)) or (
                not project.get("enable_voiceover", True) and bool(project.get("enable_multivoice", True))
            )
        else:
            scene_dial_only = bool(scene_dial_only)

        enable_subtitles = project.get("enable_subtitles", True)
        enable_voiceover = bool(
            project.get("enable_voiceover", True)
            or project.get("enable_multivoice", False)
            or scene_dial_only
        )
        audio_file = project_dir / f"scene_{scene_idx + 1}.mp3"
        srt_file = project_dir / f"scene_{scene_idx + 1}.srt"
        narration_changed = (
            scene.get("voiced_narration") != (scene.get("narration") or "").strip()
            or scene.get("voiced_dialogue_only") != scene_dial_only
        )
        if enable_voiceover or enable_subtitles:
            if force_revoice or narration_changed or not audio_file.exists() or not srt_file.exists() or not scene.get("audio_path") or not scene.get("srt_path"):
                await self.generate_scene_audio(project_id, scene_idx)
                project = self.get_project(project_id)
                scene = project["scenes"][scene_idx]

        # 3. Render video clip with Ken Burns camera motion & subtitles
        width = project.get("video_width", 1280)
        height = project.get("video_height", 720)
        engine = VideoEngine(width=width, height=height)

        clip_file = project_dir / f"clip_{scene_idx + 1}.mp4"
        img_full = str(PROJECTS_DIR.parent / scene["image_path"]) if scene.get("image_path") else None
        audio_full = str(PROJECTS_DIR.parent / scene["audio_path"]) if (scene.get("audio_path") and enable_voiceover) else None
        srt_full = str(PROJECTS_DIR.parent / scene["srt_path"]) if (scene.get("srt_path") and enable_subtitles) else None
        motion = scene.get("camera_motion", "zoom_in")
        duration = scene.get("duration", 4.0)

        # Check for acting video source (e.g. from Google Flow / I2V generator)
        acting_video_full = None
        raw_acting_cand = project_dir / f"scene_{scene_idx + 1}_acting.mp4"
        if raw_acting_cand.exists():
            acting_video_full = str(raw_acting_cand)
        elif scene.get("raw_video_path"):
            cand_p = PROJECTS_DIR.parent / scene["raw_video_path"]
            if cand_p.exists():
                acting_video_full = str(cand_p)

        await asyncio.to_thread(
            engine.render_scene_clip,
            image_path=img_full,
            audio_path=audio_full,
            srt_path=srt_full,
            output_clip_path=str(clip_file),
            motion_type=motion,
            duration=duration,
            enable_subtitles=enable_subtitles,
            enable_voiceover=enable_voiceover,
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
        notify(35, "Generating scene illustrations with AI...")

        scenes = project["scenes"]
        total_scenes = len(scenes)

        # 1. Images (generated one by one using Character Reference Portraits + consistency)
        for idx, scene in enumerate(scenes):
            existing_rel = scene.get("image_path")
            existing_full = (PROJECTS_DIR.parent / existing_rel) if existing_rel else None
            if existing_full and existing_full.exists():
                continue

            img_file = project_dir / f"scene_{idx + 1}.jpg"
            if not img_file.exists():
                notify(35 + int((idx / max(1, total_scenes)) * 15), f"Painting scene {idx + 1} of {total_scenes} using character reference images...")
                await self.generate_scene_image(project_id, idx)
                project = self.get_project(project_id) or project
                scenes = project.get("scenes", scenes)
                if idx < total_scenes - 1:
                    await asyncio.sleep(0.8)
            else:
                scene["image_path"] = str(img_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
                self.save_project(project)

        any_scene_dial_only = any(bool(s.get("dialogue_only")) for s in scenes)
        enable_voiceover = bool(
            project.get("enable_voiceover", True)
            or project.get("enable_multivoice", False)
            or any_scene_dial_only
        )
        enable_subtitles = project.get("enable_subtitles", True)

        # 2. Voices & Subtitles
        if not enable_voiceover and not enable_subtitles:
            notify(65, "Voiceover narration & subtitles disabled (instrumental only)...")
            for idx, scene in enumerate(scenes):
                raw_acting_cand = project_dir / f"scene_{idx + 1}_acting.mp4"
                if raw_acting_cand.exists():
                    scene["duration"] = engine.get_media_duration(str(raw_acting_cand)) or 8.0
                elif not scene.get("duration") or scene.get("duration") <= 0:
                    scene["duration"] = 5.0
            self.save_project(project)
        else:
            notify(52, "Recording voice actor narration & subtitles..." if enable_voiceover else "Preparing scene subtitles...")

            # Enforce narrator voice consistently across the entire clip (no mid-clip fallback or swapping)
            clip_voice = project.get("voice") or "en-US-ChristopherNeural"
            enable_narrator = project.get("enable_voiceover", True)

            # Up-front audition probe to verify narrator voice health when voiceover is enabled
            if enable_narrator:
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
                scene_dial_only = scene.get("dialogue_only")
                if scene_dial_only is None:
                    scene_dial_only = bool(project.get("dialogue_only", False)) or (
                        not project.get("enable_voiceover", True) and bool(project.get("enable_multivoice", True))
                    )
                else:
                    scene_dial_only = bool(scene_dial_only)

                scene_include_narrator = False if scene_dial_only else bool(project.get("enable_voiceover", True))
                narration_changed = (
                    scene.get("voiced_narration") != (scene.get("narration") or "").strip()
                    or scene.get("voiced_dialogue_only") != scene_dial_only
                )
                if narration_changed or not audio_file.exists() or not srt_file.exists():
                    notify(52 + int((idx / total_scenes) * 15), f"Narrating scene {idx + 1} of {total_scenes}..." if enable_voiceover else f"Preparing scene {idx + 1} subtitles...")
                    enable_mv = bool(project.get("enable_multivoice", True) or scene_dial_only)
                    char_voices = project.get("character_voices") or {}
                    sc_dialogues = scene.get("dialogues")
                    if enable_mv:
                        has_generic_char = any(
                            (d.get("speaker") or "").strip().lower() == "character"
                            for d in (sc_dialogues or [])
                        )
                        named_chars = [
                            k for k in char_voices.keys()
                            if k.lower() not in ("narrator", "người kể chuyện", "character")
                        ]
                        if not sc_dialogues or (has_generic_char and named_chars):
                            sc_dialogues = ScriptAgent.extract_scene_dialogue_segments(
                                narration=scene.get("narration", ""),
                                characters=named_chars or project.get("characters"),
                                narrator_name="Narrator"
                            )
                            scene["dialogues"] = sc_dialogues
                    # Keep natural normal narration speed (video clip dynamically adapts to audio duration)
                    scene_max_dur = None

                    try:
                        res = await self.voice_agent.synthesize(
                            text=scene["narration"],
                            output_audio_path=str(audio_file),
                            output_srt_path=str(srt_file),
                            voice=clip_voice,
                            api_key=project.get("api_key"),
                            allow_voice_fallback=False,
                            max_duration=scene_max_dur,
                            dialogues=sc_dialogues,
                            character_voices=char_voices,
                            enable_multivoice=enable_mv,
                            include_narrator=scene_include_narrator
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
                            allow_voice_fallback=True,
                            max_duration=scene_max_dur,
                            dialogues=sc_dialogues,
                            character_voices=char_voices,
                            enable_multivoice=enable_mv,
                            include_narrator=scene_include_narrator
                        )
                        # If this scene resolved to a fallback voice, update clip_voice so subsequent scenes stay consistent
                        if res.get("is_fallback") and res.get("voice"):
                            clip_voice = res["voice"]
                            project["voice"] = clip_voice
                            self.save_project(project)

                    scene["voiced_narration"] = (scene.get("narration") or "").strip()
                    scene["voiced_dialogue_only"] = scene_dial_only
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

            scene_has_voice = bool(
                project.get("enable_voiceover", True)
                or project.get("enable_multivoice", False)
                or scene.get("dialogue_only", False)
            )
            img_full = str(PROJECTS_DIR.parent / scene["image_path"]) if scene.get("image_path") else None
            audio_full = str(PROJECTS_DIR.parent / scene["audio_path"]) if (scene.get("audio_path") and scene_has_voice) else None
            srt_full = str(PROJECTS_DIR.parent / scene["srt_path"]) if (scene.get("srt_path") and enable_subtitles) else None
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

            await asyncio.to_thread(
                engine.render_scene_clip,
                image_path=img_full,
                audio_path=audio_full,
                srt_path=srt_full,
                output_clip_path=str(clip_file),
                motion_type=motion,
                duration=scene.get("duration", 4.0),
                enable_subtitles=enable_subtitles,
                enable_voiceover=scene_has_voice,
                source_video_path=acting_video_full
            )
            scene["video_path"] = str(clip_file.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            scene_clips.append(str(clip_file))
            self.save_project(project)

        # 4. Synthesize Background Music
        notify(88, "Composing atmospheric ambient soundtrack...")
        bgm_file = project_dir / "soundtrack.mp3"
        total_anim_dur = sum(s.get("duration", 4.0) + 0.4 for s in scenes)
        await asyncio.to_thread(
            self.music_service.generate_ambient_track,
            output_path=str(bgm_file),
            duration=max(15.0, total_anim_dur + 5.0)
        )

        # 5. Final Stitch & Master Audio Mix
        notify(94, "Final mastering and encoding complete animation...")
        final_video = project_dir / "final_animation.mp4"
        bgm_vol = 0.22 if enable_voiceover else 0.75
        await asyncio.to_thread(
            engine.concatenate_and_mix,
            scene_clip_paths=scene_clips,
            output_video_path=str(final_video),
            bgm_path=str(bgm_file),
            bgm_volume=bgm_vol
        )

        project["video_path"] = str(final_video.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
        project["status"] = "completed"
        project["progress"] = 100
        project["current_step"] = "Animation rendered successfully!"
        self.save_project(project)

        notify(100, "Ready! Your animated film has been created!")
        return project

    def set_character_voice(self, project_id: str, character_name: str, voice_id: str) -> Dict[str, Any]:
        """Assigns a specific voice (or optional blank/'none') to a character in the project."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        if "character_voices" not in project or not isinstance(project["character_voices"], dict):
            project["character_voices"] = {}

        project["character_voices"][character_name] = voice_id
        if character_name.lower() in ("narrator", "người kể chuyện"):
            project["voice"] = voice_id

        # Keep character_profiles synced
        for prof in project.get("character_profiles", []):
            if isinstance(prof, dict) and (prof.get("name") or "").strip().lower() == character_name.strip().lower():
                prof["voice_id"] = voice_id

        # Mark scenes featuring this character as needing audio update
        for sc in project.get("scenes", []):
            sc_d = sc.get("dialogues") or []
            if any(d.get("speaker", "").lower() == character_name.lower() for d in sc_d):
                sc["voiced_narration"] = ""

        self.save_project(project)
        return project

    def toggle_multivoice(self, project_id: str, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggles multi-voice character dialogue mode on or off."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        curr = project.get("enable_multivoice", True)
        new_val = (not curr) if enable is None else bool(enable)
        project["enable_multivoice"] = new_val

        # Clear voiced_narration so next preview or render uses the updated mode
        for sc in project.get("scenes", []):
            sc["voiced_narration"] = ""

        self.save_project(project)
        return project

    def auto_cast_project_voices(self, project_id: str) -> Dict[str, Any]:
        """Automatically analyzes character roster and dialogues to assign diverse voices."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        silent_overrides = {
            k: v for k, v in (project.get("character_voices") or {}).items()
            if (v or "").strip().lower() in ("none", "silent", "mute")
        }
        project["character_voices"] = ScriptAgent.auto_assign_character_voices(
            characters_str=project.get("characters", ""),
            scenes=project.get("scenes", []),
            language=project.get("language", "vi" if any(ord(c) > 127 for c in project.get("idea", "")) else "en"),
            narrator_voice=project.get("voice"),
            existing_voices=silent_overrides or None
        )

        # Remove generic "Character" fallback key if specific named characters exist
        has_named_chars = any(k.lower() not in ("narrator", "người kể chuyện", "character") for k in project["character_voices"])
        if has_named_chars and "Character" in project["character_voices"]:
            del project["character_voices"]["Character"]

        for prof in project.get("character_profiles", []):
            if isinstance(prof, dict) and prof.get("name") in project["character_voices"]:
                prof["voice_id"] = project["character_voices"][prof["name"]]

        for sc in project.get("scenes", []):
            sc["voiced_narration"] = ""

        self.save_project(project)
        return self.get_project(project_id) or project

    def toggle_camera_on_speaker(self, project_id: str, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggles Dialogue Film (Camera on Speaker) mode on or off while keeping the chosen Visual Art Style."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        curr = bool(project.get("camera_on_speaker", False) or project.get("art_style") == "dialogue_cinema")
        new_val = (not curr) if enable is None else bool(enable)
        project["camera_on_speaker"] = new_val
        if project.get("art_style") == "dialogue_cinema":
            project["art_style"] = "ghibli"

        art_style = project.get("art_style", "ghibli")
        scenes = project.get("scenes", [])
        if new_val:
            voice_id = (project.get("voice") or "en-US").lower()
            lang = "vi" if voice_id.startswith("vi") else "en"
            ScriptAgent.sync_story_dialogues_to_scenes(
                scenes=scenes,
                idea=project.get("idea", ""),
                art_style=art_style,
                language=lang,
                target="clip",
                characters=project.get("characters"),
                camera_on_speaker=True
            )
        else:
            for idx, sc in enumerate(scenes):
                if sc.get("camera_motion") == "speaker_focus":
                    sc["camera_motion"] = "zoom_in"
                vis = str(sc.get("visual_prompt") or "")
                vis = re.sub(r'(?i)^(?:Góc máy cận cảnh tập trung trực tiếp vào [^,]+ đang nói chuyện,\s*|Medium close-up camera focused directly on [^,]+ speaking,\s*)', '', vis)
                sc["visual_prompt"] = vis
                sc["acting_prompt"] = ScriptAgent.professionalize_video_prompt(
                    acting_prompt=sc.get("acting_prompt", ""),
                    visual_prompt=vis,
                    narration=sc.get("narration", ""),
                    camera_motion=sc.get("camera_motion", "zoom_in"),
                    title=sc.get("title", f"Scene {idx + 1}"),
                    art_style=art_style,
                    camera_on_speaker=False
                )

        project["scenes"] = scenes
        self.save_project(project)
        return project

    def refresh_project_comic_images(self, project_id: str, scene_indices: Optional[list] = None) -> Dict[str, Any]:
        """
        Re-applies (or restores) comic speech bubble overlays on existing painted scene images
        whenever scene dialogues/narration or project art_style change.
        """
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        p_dir = safe_project_dir(project_id)
        if not p_dir:
            return project

        comic_active = is_comic_style(project.get("art_style", "ghibli"))
        scenes = project.get("scenes", [])
        target_set = set(scene_indices) if scene_indices is not None else set(range(len(scenes)))

        for idx, sc in enumerate(scenes):
            if idx not in target_set:
                continue
            img_file = p_dir / f"scene_{idx + 1}.jpg"
            if not img_file.exists():
                continue
            try:
                if comic_active:
                    self.image_service.apply_comic_overlay_to_file(
                        str(img_file),
                        dialogues=sc.get("dialogues"),
                        narration=sc.get("narration", ""),
                        prompt=sc.get("visual_prompt", ""),
                        title=sc.get("title", f"Scene {idx + 1}"),
                        scene_idx=idx,
                        dialogue_only=bool(sc.get("dialogue_only", False)),
                        enable_image_captions=bool(project.get("enable_image_captions", True))
                    )
                else:
                    self.image_service.restore_base_image_file(str(img_file))
            except Exception as e_ov:
                print(f"[pipeline] Notice updating comic overlay for scene {idx + 1}: {e_ov}")
        return project

    def set_project_art_style(self, project_id: str, new_style: str) -> Dict[str, Any]:
        """Updates project art style, synchronizes scene visual prompts (including comic speech bubbles), and updates existing scene images."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        new_style = (new_style or "ghibli").strip()
        project["art_style"] = new_style
        voice_id = (project.get("voice") or "en-US").lower()
        lang = "vi" if (voice_id.startswith("vi") or project.get("language") == "vi") else "en"
        scenes = project.get("scenes", [])
        if scenes:
            ScriptAgent.sync_story_dialogues_to_scenes(
                scenes=scenes,
                idea=project.get("idea", ""),
                art_style=new_style,
                language=lang,
                target="image",
                characters=project.get("characters"),
                camera_on_speaker=bool(project.get("camera_on_speaker", False))
            )
            project["scenes"] = scenes
        self.save_project(project)
        self.refresh_project_comic_images(project_id)
        return self.get_project(project_id) or project

    def toggle_image_captions(self, project_id: str, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggles Caption in Images (the yellow narrator caption box on Comic Book panels) ON or OFF."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        curr = bool(project.get("enable_image_captions", True))
        new_val = (not curr) if enable is None else bool(enable)
        project["enable_image_captions"] = new_val
        self.save_project(project)
        self.refresh_project_comic_images(project_id)
        return self.get_project(project_id) or project

    def toggle_video_char_refs(self, project_id: str, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggles passing character reference portrait images into AI video generation (FlowKit R2V / Veo)."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        curr = bool(project.get("use_char_refs_in_video", True))
        new_val = (not curr) if enable is None else bool(enable)
        project["use_char_refs_in_video"] = new_val
        self.save_project(project)
        return self.get_project(project_id) or project

    def upsert_character_profile(self, project_id: str, char_data: Dict[str, Any]) -> Dict[str, Any]:
        """Creates or updates a character profile (name, description, optional voice, optional image) inside a project."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        profiles = self.sync_character_profiles(project, sync_back_string=False)
        cid = (char_data.get("id") or "").strip()
        c_name = (char_data.get("name") or "").strip()
        if not c_name:
            raise ValueError("Character name is required")
        c_desc = (char_data.get("description") or "").strip()
        c_voice = char_data.get("voice_id")
        if c_voice is None:
            c_voice = ""
        else:
            c_voice = str(c_voice).strip()

        target = None
        if cid:
            target = next((p for p in profiles if p["id"] == cid), None)
        if not target:
            target = next((p for p in profiles if p["name"].lower() == c_name.lower()), None)

        old_name = target["name"] if target else None
        if target:
            target["name"] = c_name
            target["description"] = c_desc
            if "voice_id" in char_data:
                target["voice_id"] = c_voice
            if char_data.get("image_path") is not None:
                target["image_path"] = str(char_data.get("image_path") or "").replace("\\", "/")
        else:
            new_cid = cid or f"char_{self._char_slug(c_name)}"
            existing_ids = {p["id"] for p in profiles}
            if new_cid in existing_ids:
                new_cid = f"{new_cid}_{uuid.uuid4().hex[:4]}"
            img_rel = str(char_data.get("image_path") or "").replace("\\", "/")
            if img_rel and img_rel.startswith("character_staging/"):
                p_dir = PROJECTS_DIR / project_id
                chars_dir = p_dir / "characters"
                chars_dir.mkdir(parents=True, exist_ok=True)
                src_p = PROJECTS_DIR.parent / img_rel
                if src_p.exists():
                    dest_p = chars_dir / f"{new_cid}.jpg"
                    shutil.copy2(src_p, dest_p)
                    img_rel = str(dest_p.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            target = {
                "id": new_cid,
                "name": c_name,
                "description": c_desc,
                "voice_id": c_voice,
                "image_path": img_rel,
                "role": char_data.get("role") or "character"
            }
            profiles.append(target)

        if "character_voices" not in project or not isinstance(project["character_voices"], dict):
            project["character_voices"] = {"Narrator": project.get("voice") or "en-US-ChristopherNeural"}
        if old_name and old_name != c_name and old_name in project["character_voices"]:
            del project["character_voices"][old_name]
        if target.get("voice_id") not in (None, ""):
            project["character_voices"][c_name] = target["voice_id"]
        elif c_name in project["character_voices"] and "voice_id" in char_data and c_voice == "":
            del project["character_voices"][c_name]

        project["character_profiles"] = profiles
        project["characters"] = ScriptAgent.format_characters_summary(profiles)
        self.save_project(project)
        return self.get_project(project_id) or project

    def delete_character_profile(self, project_id: str, char_id: str) -> Dict[str, Any]:
        """Removes a character profile and cleans up its voice/scene pins."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        profiles = self.sync_character_profiles(project, sync_back_string=False)
        removed = next((p for p in profiles if p["id"] == char_id), None)
        profiles = [p for p in profiles if p["id"] != char_id]
        if removed:
            if isinstance(project.get("character_voices"), dict) and removed["name"] in project["character_voices"]:
                del project["character_voices"][removed["name"]]
            for sc in project.get("scenes", []):
                if isinstance(sc.get("character_ids"), list) and char_id in sc["character_ids"]:
                    sc["character_ids"] = [x for x in sc["character_ids"] if x != char_id]
        project["character_profiles"] = profiles
        project["characters"] = ScriptAgent.format_characters_summary(profiles)
        self.save_project(project)
        return self.get_project(project_id) or project

    async def generate_character_portrait(self, project_id: str, char_id: str) -> Dict[str, Any]:
        """Generates a clean 3:4 Character Reference Sheet portrait for a character profile."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        profiles = self.sync_character_profiles(project, sync_back_string=False)
        char = next((p for p in profiles if p["id"] == char_id), None)
        if not char:
            raise ValueError(f"Character '{char_id}' not found")

        p_dir = PROJECTS_DIR / project_id
        chars_dir = p_dir / "characters"
        chars_dir.mkdir(parents=True, exist_ok=True)
        out_path = chars_dir / f"{char_id}.jpg"

        existing_ref = None
        if char.get("image_path"):
            cand = PROJECTS_DIR.parent / char["image_path"]
            if cand.exists():
                existing_ref = str(cand)

        seed = self.stable_seed(f"{project_id}:{char['name']}:{char.get('description', '')}")
        await self.image_service.generate_character_portrait(
            name=char["name"],
            description=char.get("description") or f"{char['name']} character design",
            output_path=str(out_path),
            style_key=project.get("art_style", "ghibli"),
            width=720,
            height=960,
            image_mode=project.get("image_mode", "gemini"),
            reference_image_path=existing_ref,
            seed=seed,
            api_key=project.get("api_key"),
            provider=project.get("ai_provider")
        )

        if out_path.exists():
            char["image_path"] = str(out_path.relative_to(PROJECTS_DIR.parent)).replace("\\", "/")
            project["character_profiles"] = profiles
            self.save_project(project)
        return self.get_project(project_id) or project

    def bulk_import_character_profiles(
        self,
        project_id: str,
        characters: list,
        replace: bool = False,
    ) -> Dict[str, Any]:
        """Bulk imports/merges parsed character definitions into a project's character_profiles."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")

        if replace:
            profiles = []
            narrator_voice = (project.get("character_voices") or {}).get("Narrator") or project.get("voice") or "en-US-ChristopherNeural"
            project["character_voices"] = {"Narrator": narrator_voice}
        else:
            profiles = self.sync_character_profiles(project, sync_back_string=False)

        if "character_voices" not in project or not isinstance(project["character_voices"], dict):
            project["character_voices"] = {"Narrator": project.get("voice") or "en-US-ChristopherNeural"}

        existing_ids = {p["id"] for p in profiles if p.get("id")}
        by_name = {p["name"].strip().lower(): p for p in profiles if p.get("name")}

        for entry in (characters or []):
            if not isinstance(entry, dict):
                continue
            c_name = (entry.get("name") or "").strip()
            if not c_name or c_name.lower() in ("narrator", "người kể chuyện"):
                continue
            c_desc = (entry.get("description") or "").strip()
            c_role = (entry.get("role") or "supporting").strip() or "supporting"
            c_voice = str(entry.get("voice_id") or "").strip()
            c_img = str(entry.get("image_path") or "").replace("\\", "/").strip()

            key = c_name.lower()
            if key in by_name:
                target = by_name[key]
                if c_desc:
                    target["description"] = c_desc
                if c_role and c_role != "character":
                    target["role"] = c_role
                if c_voice:
                    target["voice_id"] = c_voice
                    project["character_voices"][target["name"]] = c_voice
                if c_img and not target.get("image_path"):
                    target["image_path"] = c_img
            else:
                new_cid = (entry.get("id") or f"char_{self._char_slug(c_name)}").strip()
                new_cid = re.sub(r'[^a-zA-Z0-9_\-]', '_', new_cid) or f"char_{uuid.uuid4().hex[:6]}"
                if new_cid in existing_ids:
                    n = 2
                    while f"{new_cid}_{n}" in existing_ids:
                        n += 1
                    new_cid = f"{new_cid}_{n}"
                existing_ids.add(new_cid)
                item = {
                    "id": new_cid,
                    "name": c_name,
                    "description": c_desc,
                    "voice_id": c_voice,
                    "image_path": c_img,
                    "role": c_role,
                }
                profiles.append(item)
                by_name[key] = item
                if c_voice:
                    project["character_voices"][c_name] = c_voice

        project["character_profiles"] = profiles
        project["characters"] = ScriptAgent.format_characters_summary(profiles)
        self.save_project(project)
        return self.get_project(project_id) or project

    async def generate_all_character_portraits(
        self,
        project_id: str,
        force_all: bool = False,
        char_ids: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Generates portrait images sequentially for all (or selected) characters in the project."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        profiles = self.sync_character_profiles(project, sync_back_string=False)
        selected_set = set(char_ids) if char_ids else None
        attempted = 0
        succeeded = 0
        errors = []
        for char in profiles:
            if selected_set is not None and char["id"] not in selected_set:
                continue
            has_img = bool(char.get("image_path") and (PROJECTS_DIR.parent / char["image_path"]).exists())
            if force_all or not has_img:
                attempted += 1
                try:
                    await self.generate_character_portrait(project_id, char["id"])
                    succeeded += 1
                except Exception as err:
                    errors.append(f"{char.get('name', char['id'])}: {err}")
                await asyncio.sleep(0.5)
        if attempted > 0 and succeeded == 0 and errors:
            raise RuntimeError("; ".join(errors))
        updated = self.get_project(project_id) or project
        if errors:
            updated = dict(updated)
            updated["_batch_portrait_warnings"] = errors
        return updated

    def set_scene_characters(self, project_id: str, scene_idx: int, character_ids: list) -> Dict[str, Any]:
        """Pins specific character IDs onto a scene for Scene Image & Video generation."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError("Project not found")
        scenes = project.get("scenes", [])
        if scene_idx < 0 or scene_idx >= len(scenes):
            raise ValueError("Invalid scene index")
        scenes[scene_idx]["character_ids"] = [str(cid) for cid in (character_ids or []) if cid]
        self.save_project(project)
        return self.get_project(project_id) or project


