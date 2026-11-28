"""
Smart Reference Image Selector (adapted from HKUDS/ViMax agents/reference_image_selector.py).

Selects the most visually relevant prior rendered scene frame for environment, lighting,
and spatial continuity instead of blindly grabbing Scene 1.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


_STOPWORDS: Set[str] = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "under",
    "near", "while", "where", "when", "then", "than", "their", "there", "these",
    "those", "scene", "shot", "view", "frame", "style", "anime", "cinematic",
    "lighting", "light", "color", "colors", "palette", "detailed", "quality",
    "masterpiece", "illustration", "image", "render", "background", "foreground",
    "camera", "focus", "close", "medium", "wide", "angle", "very", "more", "most",
    "cảnh", "hình", "ảnh", "ánh", "sáng", "màu", "phong", "cách", "với", "trong",
    "của", "một", "những", "đang", "được", "trên", "dưới", "giữa", "bên", "cạnh",
}


def _extract_visual_tokens(text: str) -> Set[str]:
    """Extracts meaningful lowercase content tokens for setting/environment similarity."""
    raw = (text or "").lower()
    tokens = re.findall(r"[a-zà-ỹ0-9]{3,}", raw)
    return {t for t in tokens if t not in _STOPWORDS and not t.isdigit()}


def _scene_text_blob(scene: Dict[str, Any]) -> str:
    return " ".join([
        str(scene.get("title") or ""),
        str(scene.get("visual_prompt") or ""),
        str(scene.get("archetype") or ""),
    ])


def select_best_prior_scene_reference(
    project: Dict[str, Any],
    scene_idx: int,
    project_dir: Path,
    min_similarity: float = 0.08,
) -> Optional[str]:
    """
    Scores all already-rendered prior scenes (`0 .. scene_idx - 1`) by setting/visual token
    overlap + recency continuity and returns the best matching prior frame path (or None).
    """
    scenes = project.get("scenes") or []
    if scene_idx <= 0 or scene_idx >= len(scenes):
        return None

    target_tokens = _extract_visual_tokens(_scene_text_blob(scenes[scene_idx]))
    best_path: Optional[str] = None
    best_score: float = -1.0
    most_recent_path: Optional[str] = None

    for prev_idx in range(scene_idx - 1, -1, -1):
        cand = project_dir / f"scene_{prev_idx + 1}.jpg"
        if not cand.exists():
            continue
        if most_recent_path is None:
            most_recent_path = str(cand)

        prev_tokens = _extract_visual_tokens(_scene_text_blob(scenes[prev_idx]))
        if target_tokens and prev_tokens:
            overlap = len(target_tokens & prev_tokens)
            union = len(target_tokens | prev_tokens)
            jaccard = overlap / max(1, union)
        else:
            jaccard = 0.0

        # Small recency bonus (contiguous shots are more likely to share location & lighting)
        distance = scene_idx - prev_idx
        recency_bonus = 0.06 if distance == 1 else (0.03 if distance == 2 else 0.0)
        score = jaccard + recency_bonus

        if score > best_score:
            best_score = score
            best_path = str(cand)

    if best_path and best_score >= min_similarity:
        return best_path
    return most_recent_path


def select_scene_references(
    project: Dict[str, Any],
    scene_idx: int,
    project_dir: Path,
    matched_char_refs: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    Combines matched Character Studio portrait refs with the best prior scene frame:
    - Keeps matched character portraits as primary visual identity anchors.
    - When no character portraits exist, selects the highest-similarity prior scene frame
      (instead of blindly grabbing scene_1.jpg), falling back to `character_ref.jpg`.
    - When character portraits DO exist, attaches a high-similarity prior scene frame
      ONLY when the setting strongly overlaps (score >= 0.22) so environment/lighting
      stays coherent without overriding Character Studio faces.
    """
    if not matched_char_refs:
        best_prior = select_best_prior_scene_reference(project, scene_idx, project_dir, min_similarity=0.05)
        if best_prior:
            return [], best_prior
        char_portrait = project_dir / "character_ref.jpg"
        if char_portrait.exists():
            return [], str(char_portrait)
        return [], None

    # With character portraits present, only add a prior scene ref for strong same-location continuity
    env_ref = select_best_prior_scene_reference(project, scene_idx, project_dir, min_similarity=0.22)
    return matched_char_refs, env_ref
