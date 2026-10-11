import os
import sys
import io
from pathlib import Path

# Ensure UTF-8 console output on Windows across reload workers
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image

from backend.config import BASE_DIR, OUTPUT_DIR, ART_STYLES, VOICES, CAMERA_MOTIONS, AI_PROVIDERS, IMAGE_MODES, DURATION_PRESETS, VIDEO_DIMENSIONS
from backend.pipeline import AnimationPipeline
from backend.agents.script_agent import ScriptAgent

app = FastAPI(title="AniStory AI - Animated Video Creator Agent", version="1.0.0")

# Request Models
class CreateStoryRequest(BaseModel):
    idea: str
    art_style: str = "ghibli"
    voice: str = "en-US-ChristopherNeural"
    num_scenes: int = 4
    target_duration: int = 60
    aspect_ratio: str = "16:9"
    language: str = "en"
    audience: str = "general"
    ai_provider: str = "gemini"
    ai_model: Optional[str] = None
    api_key: Optional[str] = None
    image_mode: str = "server"

class ImportStoryRequest(BaseModel):
    text: str
    art_style: str = "ghibli"
    voice: str = "en-US-ChristopherNeural"
    aspect_ratio: str = "16:9"
    ai_provider: str = "gemini"
    api_key: Optional[str] = None
    image_mode: str = "server"

class UpdateScenesRequest(BaseModel):
    title: Optional[str] = None
    logline: Optional[str] = None
    scenes: List[Dict[str, Any]]

class RenderRequest(BaseModel):
    project_id: Optional[str] = None
    api_key: Optional[str] = None
    ai_provider: Optional[str] = None

class RegenerateImageRequest(BaseModel):
    api_key: Optional[str] = None
    ai_provider: Optional[str] = None

class DetectModelsRequest(BaseModel):
    api_key: Optional[str] = None
    cookie: Optional[str] = None
    provider: Optional[str] = "gemini"

pipeline = AnimationPipeline()

class SaveCredentialsRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_cookie_psid: Optional[str] = None
    gemini_cookie_psidts: Optional[str] = None
    neural_love_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    claude_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    nvidia_api_key: Optional[str] = None

@app.post("/api/save-credentials")
async def save_credentials(req: SaveCredentialsRequest):
    from backend.config import save_server_credentials
    creds_dict = {}
    if req.gemini_api_key: creds_dict["gemini_api_key"] = req.gemini_api_key
    if req.gemini_cookie_psid: creds_dict["gemini_cookie_psid"] = req.gemini_cookie_psid
    if req.gemini_cookie_psidts: creds_dict["gemini_cookie_psidts"] = req.gemini_cookie_psidts
    if req.neural_love_key: creds_dict["neural_love_key"] = req.neural_love_key
    if req.openai_api_key: creds_dict["openai_api_key"] = req.openai_api_key
    if req.claude_api_key: creds_dict["claude_api_key"] = req.claude_api_key
    if req.deepseek_api_key: creds_dict["deepseek_api_key"] = req.deepseek_api_key
    if req.nvidia_api_key: creds_dict["nvidia_api_key"] = req.nvidia_api_key
    save_server_credentials(creds_dict)
    return {"status": "success", "saved_keys": list(creds_dict.keys())}

@app.get("/api/credentials")
async def get_credentials():
    from backend.config import get_server_credentials
    creds = get_server_credentials()
    return {
        "gemini_cookie_psid": creds.get("gemini_cookie_psid", ""),
        "gemini_cookie_psidts": creds.get("gemini_cookie_psidts", ""),
        "neural_love_key": creds.get("neural_love_key", ""),
        "has_gemini_api_key": bool(creds.get("gemini_api_key")),
        "has_gemini_cookie": bool(creds.get("gemini_cookie_psid")),
        "has_neural_love_key": bool(creds.get("neural_love_key")),
        "has_openai_key": bool(creds.get("openai_api_key")),
        "has_claude_key": bool(creds.get("claude_api_key")),
        "has_deepseek_key": bool(creds.get("deepseek_api_key")),
        "has_nvidia_key": bool(creds.get("nvidia_api_key"))
    }

@app.get("/api/config")
async def get_config():
    return {
        "art_styles": ART_STYLES,
        "voices": VOICES,
        "camera_motions": CAMERA_MOTIONS,
        "ai_providers": AI_PROVIDERS,
        "image_modes": IMAGE_MODES,
        "duration_presets": DURATION_PRESETS,
        "video_dimensions": VIDEO_DIMENSIONS
    }

@app.post("/api/gemini/detect-models")
@app.get("/api/gemini/detect-models")
async def detect_gemini_models(
    api_key: Optional[str] = None,
    cookie: Optional[str] = None,
    provider: Optional[str] = None,
    req: Optional[DetectModelsRequest] = None
):
    key_input = (req.api_key if req and req.api_key else api_key) or os.environ.get("GEMINI_API_KEY", "") or ""
    cookie_input = (req.cookie if req and req.cookie else cookie) or os.environ.get("GEMINI_COOKIE", "") or ""
    
    if "__Secure-1PSID" in key_input and not cookie_input:
        cookie_input = key_input

    active_provider = (req.provider if req and req.provider else provider)
    if not active_provider:
        active_provider = "gemini_cookie" if ("__Secure-1PSID" in key_input or cookie_input) else "gemini"
    provider_clean = str(active_provider).lower()

    # 1. Cookie-based models
    cookie_models = [
        {
            "id": "gemini-pro-advanced",
            "name": "Gemini 2.5 Pro Advanced (Web Cookie)",
            "category": "cookie",
            "badge": "🧠 Deep Reasoning (Pro)",
            "description": "Google Gemini 2.5 Pro reasoning model via your paid web session (no quota limit)."
        },
        {
            "id": "gemini-flash-advanced",
            "name": "Gemini 2.0 Flash Advanced (Web Cookie)",
            "category": "cookie",
            "badge": "⚡ Fast (Pro)",
            "description": "Ultra fast response powered by Gemini Advanced web session."
        },
        {
            "id": "gemini-pro",
            "name": "Gemini Pro (Standard Web)",
            "category": "cookie",
            "badge": "🍪 Web Standard",
            "description": "Standard Gemini Pro web chat model."
        },
        {
            "id": "gemini-flash",
            "name": "Gemini Flash (Standard Web)",
            "category": "cookie",
            "badge": "💨 Fast Web",
            "description": "Lightweight fast web model."
        },
        {
            "id": "default",
            "name": "Gemini Default Web Model",
            "category": "cookie",
            "badge": "🍪 Default",
            "description": "Default active chat model on gemini.google.com."
        }
    ]

    # 2. Curated API models
    curated_api = [
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "category": "api", "badge": "✨ Recommended / Fast", "description": "Next-gen flagship model with balanced speed and creative intelligence."},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "category": "api", "badge": "🧠 Deep Reasoning", "description": "State-of-the-art multimodal reasoning for intricate short film screenplays."},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "category": "api", "badge": "⚡ High Throughput", "description": "Versatile high-speed model with sub-second generation."},
        {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash-Lite", "category": "api", "badge": "💨 Ultra Fast", "description": "Extremely lightweight model optimized for low latency."},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "category": "api", "badge": "📚 Long Context", "description": "Powerhouse with 2M token context window."},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "category": "api", "badge": "⚡ Standard Flash", "description": "High performance standard Gemini 1.5 model."}
    ]

    live_detected = []
    has_live_api = False
    warning_msg = None

    if key_input and "__Secure-1PSID" not in key_input:
        try:
            from google import genai
            client = genai.Client(api_key=key_input)
            for m in client.models.list():
                raw_id = m.name or ""
                clean_id = raw_id.replace("models/", "")
                clean_lower = clean_id.lower()
                if "gemini" in clean_lower and not any(x in clean_lower for x in ["embedding", "aqa", "eval", "imagen", "robot"]):
                    display = m.display_name or clean_id
                    desc = m.description or ""
                    badge = "⚡ Fast" if "flash" in clean_lower else ("🧠 Pro" if "pro" in clean_lower else "✨ Gemini")
                    if "2.5" in clean_lower:
                        badge = "✨ Next-Gen"
                    elif "thinking" in clean_lower or "exp" in clean_lower:
                        badge = "🧪 Experimental"

                    live_detected.append({
                        "id": clean_id,
                        "name": display if display != clean_id else clean_id,
                        "category": "api",
                        "badge": badge,
                        "description": desc[:100] if desc else clean_id
                    })

            def model_rank(item):
                mid = item["id"].lower()
                if "2.5-flash" in mid: return 0
                if "2.5-pro" in mid: return 1
                if "2.0-flash" in mid and "lite" not in mid: return 2
                if "1.5-pro" in mid: return 3
                if "1.5-flash" in mid: return 4
                if "2." in mid: return 5
                return 6

            live_detected.sort(key=model_rank)
            if live_detected:
                has_live_api = True
        except Exception as e:
            warning_msg = str(e)

    active_api = live_detected if has_live_api else curated_api

    models_to_return = cookie_models if provider_clean in ("gemini_cookie", "gemini_web") else active_api

    return {
        "status": "ok",
        "provider": provider_clean,
        "has_live_api": has_live_api,
        "has_cookie": bool(cookie_input),
        "models": models_to_return,
        "api_models": active_api,
        "cookie_models": cookie_models,
        "total_api": len(active_api),
        "total_cookie": len(cookie_models),
        "warning": warning_msg
    }

@app.get("/api/projects")
async def list_projects():
    return pipeline.list_projects()

@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    p = pipeline.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p

@app.post("/api/create-story")
async def create_story(req: CreateStoryRequest):
    if not req.idea.strip():
        raise HTTPException(status_code=400, detail="Please provide a story idea.")

    # Instantiate pipeline with selected provider & model
    custom_pipeline = AnimationPipeline(
        api_key=req.api_key,
        ai_provider=req.ai_provider,
        ai_model=req.ai_model
    )
    project = custom_pipeline.create_project(
        idea=req.idea,
        art_style=req.art_style,
        voice=req.voice,
        num_scenes=req.num_scenes,
        target_duration=req.target_duration,
        aspect_ratio=req.aspect_ratio,
        image_mode=req.image_mode
    )

    # Generate story scenes
    updated_project = await custom_pipeline.generate_story(
        project_id=project["id"],
        num_scenes=req.num_scenes,
        target_duration=req.target_duration,
        language=req.language,
        audience=req.audience
    )
    return updated_project

@app.post("/api/import-story")
async def import_story(req: ImportStoryRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Please paste storyboard content.")

    try:
        story_data = ScriptAgent.parse_imported_storyboard(req.text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse storyboard content: {str(e)}")

    if not story_data.get("scenes"):
        raise HTTPException(status_code=400, detail="Could not extract any scenes from pasted content. Please check the JSON format.")

    try:
        custom_pipeline = AnimationPipeline(api_key=req.api_key) if req.api_key else pipeline
        project = custom_pipeline.create_project(
            idea=story_data.get("title", "Imported Story"),
            art_style=req.art_style,
            voice=req.voice,
            aspect_ratio=req.aspect_ratio,
            image_mode=req.image_mode
        )
        project["title"] = story_data.get("title", "Imported Animated Story")
        project["logline"] = story_data.get("logline", "")
        project["characters"] = story_data.get("characters", "")
        project["scenes"] = story_data["scenes"]
        project["status"] = "storyboard_ready"
        project["progress"] = 30
        project["current_step"] = "AI Storyboard imported and ready for review"
        custom_pipeline.save_project(project)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project from storyboard: {str(e)}")

@app.put("/api/projects/{project_id}/scenes")
async def update_scenes(project_id: str, req: UpdateScenesRequest):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if req.title:
        project["title"] = req.title
    if req.logline:
        project["logline"] = req.logline
    project["scenes"] = req.scenes
    pipeline.save_project(project)
    return project

@app.post("/api/projects/{project_id}/toggle-subtitles")
async def toggle_subtitles(project_id: str):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["enable_subtitles"] = not project.get("enable_subtitles", True)
    pipeline.save_project(project)
    return {"enable_subtitles": project["enable_subtitles"]}

@app.post("/api/projects/{project_id}/upload-image/{scene_idx}")
async def upload_scene_image(project_id: str, scene_idx: int, file: UploadFile = File(...)):
    project = pipeline.get_project(project_id)
    if not project or scene_idx >= len(project["scenes"]):
        raise HTTPException(status_code=404, detail="Invalid project or scene index")

    p_dir = Path(OUTPUT_DIR) / "projects" / project_id
    img_path = p_dir / f"scene_{scene_idx + 1}.jpg"

    content = await file.read()
    w = project.get("video_width", 1280)
    h = project.get("video_height", 720)

    # Automatically crop & fit image to project's exact aspect ratio & resolution
    try:
        pil_img = Image.open(io.BytesIO(content))
        fitted = pipeline.image_service.fit_image_to_aspect_ratio(pil_img, w, h)
        fitted.save(img_path, "JPEG", quality=92)
    except Exception as e_fit:
        with open(img_path, "wb") as f:
            f.write(content)

    scene = project["scenes"][scene_idx]
    scene["image_path"] = str(img_path.relative_to(OUTPUT_DIR))
    pipeline.save_project(project)
    return project

@app.post("/api/projects/{project_id}/regenerate-image/{scene_idx}")
async def regenerate_scene_image(project_id: str, scene_idx: int, req: Optional[RegenerateImageRequest] = None):
    try:
        project = pipeline.get_project(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        if req:
            if req.api_key:
                project["api_key"] = req.api_key
            if req.ai_provider:
                project["ai_provider"] = req.ai_provider
            pipeline.save_project(project)

        updated = await pipeline.generate_scene_image(project_id, scene_idx)
        return updated
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/regenerate-audio/{scene_idx}")
async def regenerate_scene_audio(project_id: str, scene_idx: int):
    try:
        updated = await pipeline.generate_scene_audio(project_id, scene_idx)
        return updated
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def run_render_task(project_id: str):
    try:
        await pipeline.render_full_animation(project_id)
    except Exception as e:
        print(f"Error during video rendering: {e}")
        p = pipeline.get_project(project_id)
        if p:
            p["status"] = "error"
            p["current_step"] = f"Rendering error: {str(e)}"
            pipeline.save_project(p)

@app.post("/api/projects/{project_id}/render")
async def start_render(project_id: str, background_tasks: BackgroundTasks, req: Optional[RenderRequest] = None):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if req:
        if req.api_key:
            project["api_key"] = req.api_key
        if req.ai_provider:
            project["ai_provider"] = req.ai_provider

    project["status"] = "rendering"
    project["progress"] = 35
    project["current_step"] = "Queued for video rendering..."
    pipeline.save_project(project)

    background_tasks.add_task(run_render_task, project_id)
    return {"message": "Rendering started", "project_id": project_id}

@app.get("/api/download/{project_id}")
async def download_video(project_id: str):
    project = pipeline.get_project(project_id)
    if not project or not project.get("video_path"):
        raise HTTPException(status_code=404, detail="Video file not found or not yet rendered")

    full_path = OUTPUT_DIR / project["video_path"]
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Video file missing from disk")

    filename = f"{project.get('title', 'animation')[:30].replace(' ', '_')}.mp4"
    return FileResponse(str(full_path), media_type="video/mp4", filename=filename)

# Mount media directory for images, audio, and videos
app.mount("/media", StaticFiles(directory=str(OUTPUT_DIR)), name="media")

# Mount frontend static files
static_dir = BASE_DIR / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
