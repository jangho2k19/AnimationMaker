#!/usr/bin/env python3
"""
🎬 AniStory AI — Script-to-Image-to-Video Pipeline CLI
Automates the full flow:
  1. Generate Storyboard & Script (Scenes, Narration, Visual Prompts, Camera Motion)
  2. Generate HD Illustrations for each scene
  3. Synthesize Voiceovers & Subtitles for each scene
  4. Render individual animated Video clips (.mp4) for each scene
  5. Assemble all scene clips into a final master film
"""

import os
import sys
import asyncio
import argparse

# Auto-switch to virtual environment Python if running outside a venv
if sys.prefix == sys.base_prefix:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    venv_pythons = [
        os.path.join(script_dir, ".venv", "Scripts", "python.exe"),
        os.path.join(script_dir, "venv", "Scripts", "python.exe"),
        os.path.join(script_dir, ".venv", "bin", "python"),
        os.path.join(script_dir, "venv", "bin", "python"),
    ]
    for venv_py in venv_pythons:
        if os.path.isfile(venv_py) and os.path.abspath(sys.executable) != os.path.abspath(venv_py):
            import subprocess
            try:
                sys.exit(subprocess.call([venv_py] + sys.argv))
            except Exception:
                pass

from backend.pipeline import AnimationPipeline
from backend.config import ART_STYLES, VOICES, PROJECTS_DIR

async def main():
    parser = argparse.ArgumentParser(
        description="AniStory AI: Generate Script -> Image -> Video for each scene"
    )
    parser.add_argument(
        "--idea", "-i",
        type=str,
        default="",
        help="Story premise or idea (leave empty for interactive prompt)"
    )
    parser.add_argument(
        "--title", "-t",
        type=str,
        default="",
        help="Custom film title (optional)"
    )
    parser.add_argument(
        "--scenes", "-s",
        type=int,
        default=4,
        help="Number of scenes to generate (default: 4)"
    )
    parser.add_argument(
        "--style",
        type=str,
        default="ghibli",
        choices=list(ART_STYLES.keys()),
        help=f"Art style: {', '.join(ART_STYLES.keys())}"
    )
    parser.add_argument(
        "--voice",
        type=str,
        default="en-US-ChristopherNeural",
        help="Voice identifier (e.g., en-US-ChristopherNeural, vi-VN-HoaiMyNeural, ja-JP-NanamiNeural)"
    )
    parser.add_argument(
        "--ratio",
        type=str,
        default="16:9",
        choices=["16:9", "9:16", "1:1"],
        help="Video aspect ratio: 16:9 (landscape) or 9:16 (vertical/reels)"
    )
    parser.add_argument(
        "--language", "-l",
        type=str,
        default="en",
        help="Story language code ('en', 'vi', 'ja', 'fr', 'es')"
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="gemini",
        help="AI provider ('gemini', 'gemini_cookie', 'openai', etc.)"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API Key for the chosen provider"
    )
    parser.add_argument(
        "--full-film",
        action="store_true",
        default=True,
        help="Also concatenate all scene clips into a final master video with music"
    )

    args = parser.parse_args()

    # Interactive input if idea wasn't supplied
    idea = args.idea.strip()
    if not idea:
        print("\n" + "=" * 65)
        print("🎬 AniStory AI — Script ➔ Image ➔ Video Generator")
        print("=" * 65)
        try:
            idea = input("\n👉 Enter your story idea or premise: ").strip()
        except EOFError:
            pass

    if not idea:
        idea = "A lonely robot in an overgrown greenhouse discovers the last blooming flower."
        print(f"ℹ️ No premise provided. Using default: '{idea}'")

    print("\n" + "=" * 65)
    print("🎬 Starting Production Pipeline")
    print("=" * 65)
    print(f"📖 Premise    : {idea}")
    print(f"🎨 Art Style  : {args.style}")
    print(f"🎙️ Voice      : {args.voice}")
    print(f"📐 Ratio      : {args.ratio}")
    print(f"🎞️ Scene Count: {args.scenes}")
    print("=" * 65 + "\n")

    pipeline = AnimationPipeline(
        api_key=args.api_key,
        ai_provider=args.provider
    )

    # ---------------------------------------------------------
    # STEP 1: CREATE PROJECT & SCRIPT GENERATION
    # ---------------------------------------------------------
    print("✨ [Step 1/4] Writing Screenplay & Scene Storyboard...")
    project = pipeline.create_project(
        idea=idea,
        title=args.title,
        art_style=args.style,
        voice=args.voice,
        num_scenes=args.scenes,
        aspect_ratio=args.ratio
    )
    project_id = project["id"]

    updated_project = await pipeline.generate_story(
        project_id=project_id,
        num_scenes=args.scenes,
        language=args.language,
        title=args.title
    )
    # The project_id might have been updated to match the generated title
    project_id = updated_project["id"]
    scenes = updated_project.get("scenes", [])

    print(f"✅ Storyboard created: '{updated_project.get('title', 'Animated Film')}' ({len(scenes)} scenes)")
    for idx, sc in enumerate(scenes):
        print(f"   • Scene {idx + 1}: {sc.get('title', f'Scene {idx+1}')} [Motion: {sc.get('camera_motion', 'zoom_in')}]")
        print(f"     Narration: {sc.get('narration', '')[:80]}...")

    # ---------------------------------------------------------
    # STEP 2: GENERATE IMAGES FOR EACH SCENE
    # ---------------------------------------------------------
    print("\n🎨 [Step 2/4] Generating Illustrations for each scene...")
    for idx in range(len(scenes)):
        print(f"   🖼️  Painting Scene {idx + 1}/{len(scenes)}...")
        await pipeline.generate_scene_image(project_id, idx)
    print("✅ All scene illustrations generated successfully.")

    # ---------------------------------------------------------
    # STEP 3: RENDER VIDEO CLIP FOR EACH SCENE
    # ---------------------------------------------------------
    print("\n🎬 [Step 3/4] Rendering Animated Video Clips for each scene (Motion + Audio + Subtitles)...")
    for idx in range(len(scenes)):
        print(f"   🎥 Animating Scene {idx + 1}/{len(scenes)}...")
        await pipeline.render_scene_video(project_id, idx)
        fresh_proj = pipeline.get_project(project_id)
        clip_rel = fresh_proj["scenes"][idx].get("video_path")
        print(f"      ➔ Clip saved: output/{clip_rel}")

    # ---------------------------------------------------------
    # STEP 4: ASSEMBLE FULL MASTER FILM (Optional)
    # ---------------------------------------------------------
    if args.full_film and len(scenes) > 1:
        print("\n🎼 [Step 4/4] Assembling Final Master Film with Music...")
        await pipeline.render_full_animation(project_id)
        final_proj = pipeline.get_project(project_id)
        final_video = final_proj.get("video_path")
        print(f"🎉 Complete Film Ready: output/{final_video}")

    print("\n" + "=" * 65)
    print("🚀 All scene videos generated successfully!")
    print(f"📁 Output Directory: {PROJECTS_DIR / project_id}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
