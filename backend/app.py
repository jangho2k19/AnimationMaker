import os
import sys
import io
import json
import uuid
import re
import asyncio
from pathlib import Path

# Ensure UTF-8 console output on Windows across reload workers
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Body
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from PIL import Image

from backend.config import BASE_DIR, OUTPUT_DIR, ART_STYLES, VOICES, CAMERA_MOTIONS, AI_PROVIDERS, IMAGE_MODES, DURATION_PRESETS, VIDEO_DIMENSIONS
from backend.pipeline import AnimationPipeline
from backend.agents.script_agent import ScriptAgent

app = FastAPI(title="AniStory AI - Animated Video Creator Agent", version="1.0.0")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# Request Models
class CreateStoryRequest(BaseModel):
    idea: str
    title: Optional[str] = None
    art_style: str = "ghibli"
    voice: str = "en-US-ChristopherNeural"
    num_scenes: int = 4  # 0 = Auto (agent determines optimal scene count)
    target_duration: Optional[int] = None
    aspect_ratio: str = "16:9"
    language: str = "en"
    audience: str = "general"
    ai_provider: str = "gemini"
    ai_model: Optional[str] = None
    api_key: Optional[str] = None
    image_mode: str = "gemini"
    video_mode: Optional[str] = "acting"
    enable_voiceover: bool = True
    enable_subtitles: bool = True
    enable_multivoice: bool = True

class ImportStoryRequest(BaseModel):
    text: str
    title: Optional[str] = None
    art_style: str = "ghibli"
    voice: str = "en-US-ChristopherNeural"
    aspect_ratio: str = "16:9"
    ai_provider: str = "gemini"
    api_key: Optional[str] = None
    image_mode: str = "gemini"
    enable_voiceover: bool = True
    enable_subtitles: bool = True
    enable_multivoice: bool = True

class SetCharacterVoiceRequest(BaseModel):
    character_name: str
    voice_id: str

class ToggleMultivoiceRequest(BaseModel):
    enable: Optional[bool] = None

class UpdateScenesRequest(BaseModel):
    title: Optional[str] = None
    logline: Optional[str] = None
    characters: Optional[str] = None
    scenes: List[Dict[str, Any]]

class RenderRequest(BaseModel):
    project_id: Optional[str] = None
    api_key: Optional[str] = None
    ai_provider: Optional[str] = None

class RegenerateImageRequest(BaseModel):
    api_key: Optional[str] = None
    ai_provider: Optional[str] = None

class RenderSceneVideoRequest(BaseModel):
    force_revoice: bool = False
    force_repaint: bool = False
    api_key: Optional[str] = None
    ai_provider: Optional[str] = None

class RenderAllSceneVideosRequest(BaseModel):
    force_revoice: bool = False
    api_key: Optional[str] = None
    ai_provider: Optional[str] = None

class DetectModelsRequest(BaseModel):
    api_key: Optional[str] = None
    cookie: Optional[str] = None
    provider: Optional[str] = "gemini"

class AuditionVoiceRequest(BaseModel):
    voice: str
    text: Optional[str] = None
    language: Optional[str] = None
    api_key: Optional[str] = None

class GeminiGenerateRequest(BaseModel):
    prompt: str
    model: Optional[str] = None
    extended_thinking: bool = False
    cookie: Optional[str] = None

class GeminiChatRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    extended_thinking: bool = False
    cookie: Optional[str] = None

class GeminiImageGenRequest(BaseModel):
    prompt: str
    aspect_ratio: str = "16:9"
    cookie: Optional[str] = None

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
    if "gemini_cookie_psid" in creds_dict or "gemini_cookie_psidts" in creds_dict:
        try:
            from backend.services.gemini_web_session import GeminiWebSessionManager
            await GeminiWebSessionManager.get_instance().invalidate()
        except Exception:
            pass
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

    # 1. Cookie-based models (Fast models first)
    cookie_models = [
        {
            "id": "gemini-flash-advanced",
            "name": "Gemini 2.0 Flash Advanced (Web Cookie)",
            "category": "cookie",
            "badge": "⚡ Ultra Fast (~3s)",
            "description": "Blazing fast response powered by Gemini Advanced web session."
        },
        {
            "id": "gemini-pro-advanced",
            "name": "Gemini 2.5 Pro Advanced (Web Cookie)",
            "category": "cookie",
            "badge": "🧠 Deep Reasoning (Pro, ~35s)",
            "description": "Google Gemini 2.5 Pro reasoning model via your paid web session (no quota limit)."
        },
        {
            "id": "gemini-flash",
            "name": "Gemini Flash (Standard Web)",
            "category": "cookie",
            "badge": "💨 Fast Web (~3s)",
            "description": "Lightweight fast web model."
        },
        {
            "id": "gemini-pro",
            "name": "Gemini Pro (Standard Web)",
            "category": "cookie",
            "badge": "🍪 Web Standard",
            "description": "Standard Gemini Pro web chat model."
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
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "category": "api", "badge": "✨ Recommended (~2s)", "description": "Next-gen flagship model with balanced speed and creative intelligence."},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "category": "api", "badge": "⚡ Ultra Fast (~1.5s)", "description": "Versatile high-speed model with sub-second generation."},
        {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash-Lite", "category": "api", "badge": "💨 Sub-Second", "description": "Extremely lightweight model optimized for low latency."},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "category": "api", "badge": "🧠 Deep Reasoning (~30s)", "description": "State-of-the-art multimodal reasoning for intricate short film screenplays."},
        {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "category": "api", "badge": "⚡ Standard Flash", "description": "High performance standard Gemini 1.5 model."},
        {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "category": "api", "badge": "📚 Long Context", "description": "Powerhouse with 2M token context window."}
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

# ====================================================================
# GEMINI WEB WRAPPER ENDPOINTS (Inspired by HanaokaYuzu/Gemini-API)
# ====================================================================

@app.post("/api/gemini/generate")
async def gemini_web_generate(req: GeminiGenerateRequest):
    """Single-turn generation supporting text, thoughts, and images via Gemini Web session."""
    try:
        from backend.services.gemini_wrapper import GeminiWebWrapper
        wrapper = GeminiWebWrapper.get_instance()
        res = await wrapper.generate_content(
            prompt=req.prompt,
            model=req.model,
            extended_thinking=req.extended_thinking,
            cookie_override=req.cookie
        )
        return {
            "status": "success",
            "text": res.text,
            "thoughts": res.thoughts,
            "images": [img.url for img in res.images],
            "model_used": res.model_used
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/gemini/chat")
async def gemini_web_chat(req: GeminiChatRequest):
    """Multi-turn chat session with context persistence and model selection."""
    try:
        from backend.services.gemini_wrapper import GeminiWebWrapper
        wrapper = GeminiWebWrapper.get_instance()
        chat = await wrapper.start_chat(model=req.model, session_id=req.session_id)
        res = await chat.send_message(
            prompt=req.prompt,
            extended_thinking=req.extended_thinking
        )
        return {
            "status": "success",
            "session_id": chat.session_id,
            "text": res.text,
            "thoughts": res.thoughts,
            "images": [img.url for img in res.images],
            "history": chat.history
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/gemini/generate-image")
async def gemini_web_generate_image(req: GeminiImageGenRequest):
    """Generates high-resolution illustration using Google Imagen 3 via Gemini Web."""
    try:
        from backend.services.gemini_wrapper import GeminiWebWrapper
        from backend.config import PROJECTS_DIR, VIDEO_DIMENSIONS
        wrapper = GeminiWebWrapper.get_instance()

        dim = VIDEO_DIMENSIONS.get(req.aspect_ratio, {"width": 1280, "height": 720})
        out_dir = PROJECTS_DIR / "gemini_generated"
        paths = await wrapper.generate_images(
            prompt=req.prompt,
            output_dir=out_dir,
            width=dim.get("width", 1280),
            height=dim.get("height", 720),
            cookie_override=req.cookie
        )
        if not paths:
            raise RuntimeError("No image was returned by Gemini Web.")

        rel_path = str(Path(paths[0]).relative_to(PROJECTS_DIR)).replace("\\", "/")
        return {
            "status": "success",
            "image_path": rel_path,
            "media_url": f"/media/{rel_path}",
            "prompt": req.prompt
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/gemini/models")
async def gemini_web_list_models():
    """Lists available models directly from the active Gemini Web session."""
    try:
        from backend.services.gemini_wrapper import GeminiWebWrapper
        wrapper = GeminiWebWrapper.get_instance()
        models = await wrapper.list_available_models()
        return {"status": "success", "models": models}
    except Exception as e:
        return {"status": "error", "message": str(e), "models": []}

@app.get("/api/gemini/status")
async def gemini_web_status():
    """Returns the authentication and auto-refresh health of the Gemini Web session."""
    from backend.services.gemini_wrapper import GeminiWebWrapper
    wrapper = GeminiWebWrapper.get_instance()
    return await wrapper.get_status()

@app.get("/api/projects")
async def list_projects():
    return pipeline.list_projects()

@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    p = pipeline.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    success = pipeline.delete_project(project_id)
    if not success:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "success", "message": f"Project '{project_id}' deleted"}

@app.post("/api/projects/import-json")
async def import_project_json_file(file: UploadFile = File(...)):
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Invalid project JSON structure")
        imported = pipeline.import_project_json(data)
        return imported
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="File is not valid JSON")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create-story")
async def create_story(req: CreateStoryRequest):
    if not req.idea.strip():
        raise HTTPException(status_code=400, detail="Please provide a story idea.")

    try:
        # Instantiate pipeline with selected provider & model
        custom_pipeline = AnimationPipeline(
            api_key=req.api_key,
            ai_provider=req.ai_provider,
            ai_model=req.ai_model
        )
        target_dur = req.target_duration if (req.target_duration and req.target_duration > 0) else (req.num_scenes * 8)
        project = custom_pipeline.create_project(
            idea=req.idea,
            title=req.title or "",
            art_style=req.art_style,
            voice=req.voice,
            num_scenes=req.num_scenes,
            target_duration=target_dur,
            aspect_ratio=req.aspect_ratio,
            image_mode=req.image_mode,
            enable_voiceover=req.enable_voiceover,
            enable_subtitles=req.enable_subtitles,
            enable_multivoice=req.enable_multivoice
        )
        project["video_mode"] = req.video_mode or "acting"

        # Generate story scenes
        updated_project = await custom_pipeline.generate_story(
            project_id=project["id"],
            num_scenes=req.num_scenes,
            target_duration=req.target_duration,
            language=req.language,
            audience=req.audience,
            title=req.title
        )
        return updated_project
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

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
        initial_title = (req.title or story_data.get("title") or "Imported Story").strip()
        detected_art_style = req.art_style or "ghibli"
        combined_visuals = " ".join((s.get("visual_prompt") or "") for s in story_data.get("scenes", [])).lower()
        if any(k in combined_visuals for k in ("pixar", "3d animated", "3d animation")):
            detected_art_style = "pixar"
        elif any(k in combined_visuals for k in ("studio ghibli", "2d hand-drawn")):
            detected_art_style = "ghibli"
        elif any(k in combined_visuals for k in ("raw photograph", "photorealistic")):
            detected_art_style = "realistic"
        elif any(k in combined_visuals for k in ("stick figure", "stickman", "stick figures", "người que")):
            detected_art_style = "stick_figure"

        project = custom_pipeline.create_project(
            idea=initial_title,
            title=initial_title,
            art_style=detected_art_style,
            voice=req.voice,
            aspect_ratio=req.aspect_ratio,
            image_mode=req.image_mode,
            enable_voiceover=req.enable_voiceover,
            enable_subtitles=req.enable_subtitles,
            num_scenes=len(story_data["scenes"]),
            enable_multivoice=req.enable_multivoice
        )
        project["title"] = req.title or story_data.get("title", "Imported Animated Story")
        project["logline"] = story_data.get("logline", "")
        project["characters"] = story_data.get("characters", "")
        project["scenes"] = story_data["scenes"]
        project["character_voices"] = ScriptAgent.auto_assign_character_voices(
            characters_str=project.get("characters", ""),
            scenes=project.get("scenes", []),
            language="vi" if any(ord(c) > 127 for c in req.text) else "en",
            narrator_voice=project.get("voice"),
            existing_voices=None
        )
        project["status"] = "storyboard_ready"
        project["progress"] = 30
        project["current_step"] = "AI Storyboard imported and ready for review"
        custom_pipeline.save_project(project)
        return project
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create project from storyboard: {str(e)}")

class SetSceneProductImageRequest(BaseModel):
    scene_idx: Optional[int] = None
    scene_index: Optional[int] = None
    image_path: str
    product_image_name: Optional[str] = None

@app.post("/api/advertisement/create")
async def create_advertisement(
    product_name: str = Form(...),
    description: str = Form(...),
    brand: Optional[str] = Form(""),
    specs: Optional[str] = Form(""),
    target_audience: Optional[str] = Form("General"),
    ad_style: Optional[str] = Form("cinematic_commercial"),
    call_to_action: Optional[str] = Form("Order now!"),
    pricing_offer: Optional[str] = Form(""),
    num_scenes: int = Form(4),
    target_duration: Optional[int] = Form(None),
    art_style: str = Form("realistic"),
    voice: str = Form("en-US-ChristopherNeural"),
    aspect_ratio: str = Form("16:9"),
    language: str = Form("en"),
    ai_provider: Optional[str] = Form("gemini"),
    ai_model: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    image_mode: str = Form("gemini"),
    video_mode: Optional[str] = Form("acting"),
    enable_voiceover: bool = Form(True),
    enable_subtitles: bool = Form(True),
    images: List[UploadFile] = File(default=[])
):
    if not product_name.strip():
        raise HTTPException(status_code=400, detail="Please provide a product or goods name.")
    if not description.strip():
        raise HTTPException(status_code=400, detail="Please provide a description or key selling points.")

    try:
        custom_pipeline = AnimationPipeline(
            api_key=api_key,
            ai_provider=ai_provider or "gemini",
            ai_model=ai_model
        )

        clean_name = product_name.strip()
        clean_brand = (brand or "").strip()
        title_display = f"{clean_name} — Commercial" if not clean_brand else f"{clean_brand}: {clean_name}"

        # Auto scene count (0) for commercials: derive from duration or use the classic 5-beat ad structure
        if not num_scenes or num_scenes <= 0:
            num_scenes = max(3, min(10, int(round(target_duration / 8.0)))) if (target_duration and target_duration > 0) else 5

        calc_duration = target_duration if (target_duration and target_duration > 0) else (num_scenes * 8)

        project = custom_pipeline.create_project(
            idea=f"Commercial advertisement for {clean_name}. {description.strip()}",
            title=title_display,
            art_style=art_style or "realistic",
            voice=voice,
            num_scenes=num_scenes,
            target_duration=calc_duration,
            aspect_ratio=aspect_ratio,
            image_mode=image_mode,
            enable_voiceover=enable_voiceover,
            enable_subtitles=enable_subtitles,
            project_type="advertisement",
            product_info={
                "product_name": clean_name,
                "brand": clean_brand,
                "description": description.strip(),
                "specs": (specs or "").strip(),
                "target_audience": target_audience,
                "ad_style": ad_style,
                "call_to_action": call_to_action,
                "pricing_offer": pricing_offer
            }
        )
        project["video_mode"] = video_mode or "acting"
        project_id = project["id"]
        p_dir = Path(OUTPUT_DIR) / "projects" / project_id
        p_dir.mkdir(parents=True, exist_ok=True)

        # 1. Process uploaded product photos and fit to aspect ratio
        saved_product_images = []
        w = project.get("video_width", 1280)
        h = project.get("video_height", 720)

        for idx, img_file in enumerate(images):
            if not img_file.filename:
                continue
            content = await img_file.read()
            if not content:
                continue
            save_name = f"product_raw_{idx + 1}.jpg"
            save_path = p_dir / save_name
            try:
                pil_img = Image.open(io.BytesIO(content))
                fitted = custom_pipeline.image_service.fit_image_to_aspect_ratio(pil_img, w, h)
                fitted.save(save_path, "JPEG", quality=92)
            except Exception:
                with open(save_path, "wb") as f_out:
                    f_out.write(content)

            rel_path = str(save_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
            saved_product_images.append(rel_path)

        project["product_images"] = saved_product_images

        # 2. Generate commercial storyboard
        script_agent = ScriptAgent(
            api_key=api_key or custom_pipeline.api_key,
            provider=ai_provider or custom_pipeline.ai_provider,
            model=ai_model or custom_pipeline.ai_model
        )

        ad_story = await script_agent.generate_advertisement_storyboard(
            product_name=clean_name,
            description=description.strip(),
            specs=(specs or "").strip(),
            brand=clean_brand,
            target_audience=target_audience,
            ad_style=ad_style,
            call_to_action=call_to_action,
            pricing_offer=pricing_offer,
            num_scenes=num_scenes,
            target_duration=calc_duration,
            art_style=art_style or "realistic",
            language=language
        )

        project["title"] = ad_story.get("title") or title_display
        project["logline"] = ad_story.get("logline", "")
        project["characters"] = ad_story.get("characters", f"Product: {clean_name}")
        scenes = ad_story.get("scenes", [])

        # 3. Assign uploaded product images to scenes
        import shutil
        for s_idx, sc in enumerate(scenes):
            if s_idx < len(saved_product_images):
                scene_img_name = f"scene_{s_idx + 1}.jpg"
                scene_img_path = p_dir / scene_img_name
                src_path = Path(OUTPUT_DIR) / saved_product_images[s_idx]
                if src_path.exists():
                    shutil.copy2(src_path, scene_img_path)
                sc["image_path"] = str(scene_img_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
                sc["is_product_photo"] = True
            elif saved_product_images:
                # Fallback to hero product image for remaining scenes
                scene_img_name = f"scene_{s_idx + 1}.jpg"
                scene_img_path = p_dir / scene_img_name
                src_path = Path(OUTPUT_DIR) / saved_product_images[0]
                if src_path.exists():
                    shutil.copy2(src_path, scene_img_path)
                sc["image_path"] = str(scene_img_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
                sc["is_product_photo"] = True
            else:
                sc["is_product_photo"] = False

        project["scenes"] = scenes
        project["status"] = "storyboard_ready"
        project["progress"] = 30
        project["current_step"] = "Commercial storyboard and product assets ready for review"
        custom_pipeline.save_project(project)
        return project
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/set-scene-product-image")
async def set_scene_product_image(project_id: str, req: SetSceneProductImageRequest):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    target_idx = req.scene_idx if req.scene_idx is not None else (req.scene_index if req.scene_index is not None else 0)
    scenes = project.get("scenes", [])
    if target_idx < 0 or target_idx >= len(scenes):
        raise HTTPException(status_code=404, detail=f"Scene index {target_idx} not found")

    target_img = req.image_path or req.product_image_name or ""
    src_path = Path(OUTPUT_DIR) / target_img
    if not src_path.exists():
        alt_path = Path(OUTPUT_DIR) / "projects" / project_id / target_img
        if alt_path.exists():
            src_path = alt_path
        else:
            raise HTTPException(status_code=404, detail=f"Selected product image '{target_img}' not found")

    p_dir = Path(OUTPUT_DIR) / "projects" / project_id
    scene_img_name = f"scene_{target_idx + 1}.jpg"
    scene_img_path = p_dir / scene_img_name
    import shutil
    shutil.copy2(src_path, scene_img_path)

    scene = scenes[target_idx]
    scene["image_path"] = str(scene_img_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
    scene["is_product_photo"] = True
    pipeline.save_project(project)
    return {"status": "success", "image_path": scene["image_path"], "project": project}

@app.post("/api/projects/{project_id}/scenes/{scene_idx}/refine-video-prompt")
async def refine_scene_video_prompt(project_id: str, scene_idx: int):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    scenes = project.get("scenes", [])
    if scene_idx < 0 or scene_idx >= len(scenes):
        raise HTTPException(status_code=400, detail="Invalid scene index")

    scene = scenes[scene_idx]
    current_act = scene.get("acting_prompt") or scene.get("visual_prompt") or scene.get("title") or ""
    refined = ScriptAgent.professionalize_video_prompt(
        acting_prompt=current_act,
        visual_prompt=scene.get("visual_prompt", ""),
        narration=scene.get("narration", ""),
        camera_motion=scene.get("camera_motion", "zoom_in"),
        title=scene.get("title", f"Scene {scene_idx + 1}"),
        art_style=project.get("art_style", "ghibli"),
        is_commercial=bool(scene.get("is_product_photo"))
    )
    scene["acting_prompt"] = refined
    pipeline.save_project(project)
    return {"status": "success", "scene_idx": scene_idx, "acting_prompt": refined, "scene": scene}

@app.post("/api/projects/{project_id}/refine-all-video-prompts")
async def refine_all_video_prompts(project_id: str):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    scenes = project.get("scenes", [])
    for idx, scene in enumerate(scenes):
        current_act = scene.get("acting_prompt") or scene.get("visual_prompt") or scene.get("title") or ""
        refined = ScriptAgent.professionalize_video_prompt(
            acting_prompt=current_act,
            visual_prompt=scene.get("visual_prompt", ""),
            narration=scene.get("narration", ""),
            camera_motion=scene.get("camera_motion", "zoom_in"),
            title=scene.get("title", f"Scene {idx + 1}"),
            art_style=project.get("art_style", "ghibli"),
            is_commercial=bool(scene.get("is_product_photo"))
        )
        scene["acting_prompt"] = refined
    pipeline.save_project(project)
    return {"status": "success", "scenes": scenes, "project": project}

@app.put("/api/projects/{project_id}/scenes")
async def update_scenes(project_id: str, req: UpdateScenesRequest):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    old_title = project.get("title", "")
    new_title = (req.title or "").strip()
    if new_title:
        project["title"] = new_title

    # Synchronize folder name if title changed in storyboard stage
    if new_title and new_title != old_title and project.get("status") in ["created", "storyboard_ready"]:
        clean_target = AnimationPipeline.sanitize_title_for_folder(new_title)
        if clean_target != project_id:
            new_id = AnimationPipeline.get_unique_project_id(clean_target, current_id=project_id)
            old_dir = Path(OUTPUT_DIR) / "projects" / project_id
            new_dir = Path(OUTPUT_DIR) / "projects" / new_id
            try:
                if old_dir.exists() and not new_dir.exists():
                    os.rename(old_dir, new_dir)
                    for sc in project.get("scenes", []):
                        for k in ["image_path", "audio_path", "srt_path"]:
                            if sc.get(k):
                                sc[k] = sc[k].replace(f"projects/{project_id}/", f"projects/{new_id}/")
                    project["id"] = new_id
                    project_id = new_id
            except Exception as e_rn:
                print(f"Could not rename project folder: {e_rn}")

    if req.logline:
        project["logline"] = req.logline
    if req.characters is not None:
        project["characters"] = req.characters

    # Preserve existing scene assets if incoming payload omitted or has null
    existing_scenes = project.get("scenes", [])
    p_dir = Path(OUTPUT_DIR) / "projects" / project_id
    for idx, sc in enumerate(req.scenes):
        if idx < len(existing_scenes):
            old_sc = existing_scenes[idx]
            old_narr = (old_sc.get("narration") or "").strip()
            new_narr = (sc.get("narration") or "").strip()
            for asset_key in ["image_path", "video_path", "audio_path", "srt_path", "duration", "voiced_narration"]:
                if not sc.get(asset_key) and old_sc.get(asset_key):
                    sc[asset_key] = old_sc[asset_key]
            # If voiceover narration changed, invalidate cached audio/SRT so next render synthesizes the new dialogue
            if new_narr != old_narr:
                sc["voiced_narration"] = None
                for stale_f in [p_dir / f"scene_{idx + 1}.mp3", p_dir / f"scene_{idx + 1}.srt"]:
                    if stale_f.exists():
                        try:
                            os.remove(stale_f)
                        except Exception:
                            pass

    project["scenes"] = req.scenes
    pipeline.save_project(project)
    return project

class SyncDialoguesRequest(BaseModel):
    scene_idx: Optional[int] = None
    target: str = "all"  # "all" | "narration" | "clip" | "image"
    re_render_clips: bool = False

@app.post("/api/projects/{project_id}/sync-dialogues")
async def sync_project_dialogues(project_id: str, req: SyncDialoguesRequest = Body(default=SyncDialoguesRequest())):
    """
    Extracts character dialogues from the project's story (`idea`) and scene fields,
    and adds/synchronizes them to Voiceover Narration (`narration`), Image Prompt (`visual_prompt`),
    and Video Clip Prompt (`acting_prompt`).
    """
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    scenes = project.get("scenes", [])
    if not scenes:
        raise HTTPException(status_code=400, detail="Project has no scenes")

    old_narrations = [(sc.get("narration") or "").strip() for sc in scenes]
    old_visuals = [(sc.get("visual_prompt") or "").strip() for sc in scenes]
    old_actings = [(sc.get("acting_prompt") or "").strip() for sc in scenes]

    voice_id = (project.get("voice") or "en-US").lower()
    lang = "vi" if voice_id.startswith("vi") else "en"

    ScriptAgent.sync_story_dialogues_to_scenes(
        scenes=scenes,
        idea=project.get("idea", ""),
        art_style=project.get("art_style", "ghibli"),
        language=lang,
        target=req.target or "all",
        target_scene_idx=req.scene_idx,
        auto_invent=(req.scene_idx is not None),
        characters=project.get("characters")
    )

    p_dir = Path(OUTPUT_DIR) / "projects" / project_id
    updated_indices = []
    narration_changed_indices = []

    for idx, sc in enumerate(scenes):
        n_changed = (sc.get("narration") or "").strip() != old_narrations[idx]
        v_changed = (sc.get("visual_prompt") or "").strip() != old_visuals[idx]
        a_changed = (sc.get("acting_prompt") or "").strip() != old_actings[idx]
        if n_changed or v_changed or a_changed:
            updated_indices.append(idx)
        if n_changed:
            narration_changed_indices.append(idx)
            sc["voiced_narration"] = None
            for stale_f in [p_dir / f"scene_{idx + 1}.mp3", p_dir / f"scene_{idx + 1}.srt"]:
                if stale_f.exists():
                    try:
                        os.remove(stale_f)
                    except Exception:
                        pass

    project["scenes"] = scenes
    pipeline.save_project(project)

    # If requested (or if clip MP4 already exists on disk and re_render_clips is enabled), re-voice & re-render affected scene clips
    if req.re_render_clips and narration_changed_indices:
        for idx in narration_changed_indices:
            clip_cand = p_dir / f"clip_{idx + 1}.mp4"
            img_cand = p_dir / f"scene_{idx + 1}.jpg"
            if clip_cand.exists() or img_cand.exists():
                try:
                    await pipeline.render_scene_video(project_id, idx, force_revoice=True, force_repaint=False)
                except Exception as e_rerender:
                    print(f"Notice re-rendering scene {idx + 1} after dialogue sync: {e_rerender}")
        project = pipeline.get_project(project_id) or project

    return {
        "project": project,
        "updated_scenes": updated_indices,
        "narration_changed_scenes": narration_changed_indices
    }

@app.post("/api/projects/{project_id}/toggle-subtitles")
async def toggle_subtitles(project_id: str):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    new_val = not project.get("enable_subtitles", True)
    project["enable_subtitles"] = new_val
    pipeline.save_project(project)

    # Re-composite any existing scene clips on disk so subtitles take instant effect
    p_dir = Path(OUTPUT_DIR) / "projects" / project_id
    re_composited_any = False
    scenes = project.get("scenes", [])
    for idx, sc in enumerate(scenes):
        clip_cand = p_dir / f"clip_{idx + 1}.mp4"
        if clip_cand.exists() and sc.get("video_path"):
            try:
                await pipeline.render_scene_video(project_id, idx, force_revoice=False, force_repaint=False)
                re_composited_any = True
            except Exception as e_recomp:
                print(f"Notice re-compositing scene {idx + 1} on subtitle toggle: {e_recomp}")

    # Re-mix final film if already created
    final_cand = p_dir / "final_animation.mp4"
    if re_composited_any and final_cand.exists() and project.get("video_path"):
        try:
            valid_clips = [str(p_dir / f"clip_{i + 1}.mp4") for i in range(len(scenes)) if (p_dir / f"clip_{i + 1}.mp4").exists()]
            if valid_clips:
                bgm_file = p_dir / "soundtrack.mp3"
                has_bgm = bgm_file.exists()
                w = project.get("video_width", 1280)
                h = project.get("video_height", 720)
                eng = VideoEngine(width=w, height=h)
                bgm_vol = 0.22 if (project.get("enable_voiceover", True) or project.get("enable_multivoice", False)) else 0.75
                eng.concatenate_and_mix(
                    scene_clip_paths=valid_clips,
                    output_video_path=str(final_cand),
                    bgm_path=str(bgm_file) if has_bgm else None,
                    bgm_volume=bgm_vol
                )
        except Exception as e_mix:
            print(f"Notice re-mixing film on subtitle toggle: {e_mix}")

    fresh = pipeline.get_project(project_id) or project
    return {"enable_subtitles": fresh.get("enable_subtitles", new_val), "project": fresh}

@app.post("/api/projects/{project_id}/toggle-voiceover")
async def toggle_voiceover(project_id: str):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    curr = project.get("enable_voiceover", True)
    new_val = not curr
    project["enable_voiceover"] = new_val

    # If Multi-Voice is active, toggling Voiceover switches between Narrator+Dialogue and Dialogue-Only,
    # so mark scenes for audio re-synthesis on next preview/render.
    if project.get("enable_multivoice", False):
        for sc in project.get("scenes", []):
            sc["voiced_narration"] = ""
        pipeline.save_project(project)
        return {"enable_voiceover": new_val, "project": project}

    pipeline.save_project(project)

    # Re-composite any existing scene clips on disk so voiceover mute/unmute takes instant effect
    p_dir = Path(OUTPUT_DIR) / "projects" / project_id
    re_composited_any = False
    scenes = project.get("scenes", [])
    for idx, sc in enumerate(scenes):
        clip_cand = p_dir / f"clip_{idx + 1}.mp4"
        if clip_cand.exists() and sc.get("video_path"):
            try:
                await pipeline.render_scene_video(project_id, idx, force_revoice=False, force_repaint=False)
                re_composited_any = True
            except Exception as e_recomp:
                print(f"Notice re-compositing scene {idx + 1} on voiceover toggle: {e_recomp}")

    # Re-mix final film if already created
    final_cand = p_dir / "final_animation.mp4"
    if re_composited_any and final_cand.exists() and project.get("video_path"):
        try:
            valid_clips = [str(p_dir / f"clip_{i + 1}.mp4") for i in range(len(scenes)) if (p_dir / f"clip_{i + 1}.mp4").exists()]
            if valid_clips:
                bgm_file = p_dir / "soundtrack.mp3"
                has_bgm = bgm_file.exists()
                w = project.get("video_width", 1280)
                h = project.get("video_height", 720)
                eng = VideoEngine(width=w, height=h)
                bgm_vol = 0.22 if (project.get("enable_voiceover", True) or project.get("enable_multivoice", False)) else 0.75
                eng.concatenate_and_mix(
                    scene_clip_paths=valid_clips,
                    output_video_path=str(final_cand),
                    bgm_path=str(bgm_file) if has_bgm else None,
                    bgm_volume=bgm_vol
                )
        except Exception as e_mix:
            print(f"Notice re-mixing film on voiceover toggle: {e_mix}")

    fresh = pipeline.get_project(project_id) or project
    return {"enable_voiceover": fresh.get("enable_voiceover", new_val), "project": fresh}

class SetProjectVoiceRequest(BaseModel):
    voice: str

@app.post("/api/projects/{project_id}/set-voice")
async def set_project_voice(project_id: str, req: SetProjectVoiceRequest):
    project = pipeline.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    new_voice = (req.voice or "").strip()
    if not new_voice:
        raise HTTPException(status_code=400, detail="Voice ID is required")
    old_voice = project.get("voice", "")
    project["voice"] = new_voice

    # Invalidate cached scene audio & SRT when voice changes so next render synthesizes with the new voice
    if new_voice != old_voice:
        p_dir = Path(OUTPUT_DIR) / "projects" / project_id
        for idx, sc in enumerate(project.get("scenes", [])):
            sc["voiced_narration"] = None
            for stale_f in [p_dir / f"scene_{idx + 1}.mp3", p_dir / f"scene_{idx + 1}.srt"]:
                if stale_f.exists():
                    try:
                        os.remove(stale_f)
                    except Exception:
                        pass

    pipeline.save_project(project)
    return {"status": "ok", "voice": new_voice, "project": project}

@app.post("/api/projects/{project_id}/toggle-multivoice")
async def toggle_project_multivoice(project_id: str, req: Optional[ToggleMultivoiceRequest] = None):
    try:
        updated = pipeline.toggle_multivoice(project_id, enable=req.enable if req else None)
        return {"status": "ok", "enable_multivoice": updated.get("enable_multivoice", True), "project": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/set-character-voice")
async def set_project_character_voice(project_id: str, req: SetCharacterVoiceRequest):
    if not req.character_name or not req.voice_id:
        raise HTTPException(status_code=400, detail="Both character_name and voice_id are required")
    try:
        updated = pipeline.set_character_voice(project_id, req.character_name, req.voice_id)
        return {"status": "ok", "character_voices": updated.get("character_voices", {}), "project": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/auto-cast-voices")
async def auto_cast_project_voices(project_id: str):
    try:
        updated = pipeline.auto_cast_project_voices(project_id)
        return {"status": "ok", "character_voices": updated.get("character_voices", {}), "project": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
    scene["image_path"] = str(img_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
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

@app.post("/api/projects/{project_id}/generate-images")
async def generate_all_images(project_id: str, req: Optional[RegenerateImageRequest] = None):
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

        updated = await pipeline.generate_all_scene_images(project_id)
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

@app.post("/api/audition-voice")
async def audition_voice(req: AuditionVoiceRequest):
    try:
        # Determine appropriate language
        lang_code = (req.language or "en").lower()
        voice_lower = (req.voice or "").lower()
        voice_meta = next((v for v in VOICES if v["id"].lower() == voice_lower), None)
        if "vi-" in voice_lower or "gtts-vi" in voice_lower or "gemini-" in voice_lower or (voice_meta and voice_meta.get("lang") == "vi"):
            lang_code = "vi"
        elif "ja-" in voice_lower:
            lang_code = "ja"
        elif "fr-" in voice_lower:
            lang_code = "fr"
        elif "es-" in voice_lower:
            lang_code = "es"

        # Localized & persona-tailored sample phrases
        samples = {
            "vi": "Xin chào! Đây là giọng đọc mẫu của AniStory AI trên nền tảng phim hoạt hình điện ảnh.",
            "ja": "こんにちは！AniStory AIの音声プレビューです。映画のようなアニメーションをお届けします。",
            "fr": "Bonjour ! Bienvenue sur AniStory AI, la plateforme d'animation cinématographique.",
            "es": "¡Hola! Bienvenidos a AniStory AI, creando historias animadas cinematográficas.",
            "en": "Welcome to AniStory AI. Bringing your stories to life with cinematic animation!"
        }
        if not req.text and lang_code == "vi":
            if "-story" in voice_lower or "kore" in voice_lower or "charon" in voice_lower:
                sample_text = "Ngày xửa ngày xưa, ở một làng quê thanh bình, có một câu chuyện kỳ diệu sắp bắt đầu."
            elif "-energetic" in voice_lower or "puck" in voice_lower or "zephyr" in voice_lower:
                sample_text = "Chào các bạn nhỏ! Hôm nay chúng mình cùng khám phá một chuyến phiêu lưu vô cùng thú vị nhé!"
            elif "-heroic" in voice_lower or "fenrir" in voice_lower:
                sample_text = "Giữa chốn công đường uy nghiêm, sự thật cuối cùng cũng được sáng tỏ trước bao ánh mắt ngỡ ngàng."
            elif "-sweet" in voice_lower or "leda" in voice_lower:
                sample_text = "Ánh nắng chiều dịu dàng buông xuống cánh đồng lúa chín vàng, mang theo hương đồng gió nội êm đềm."
            elif "-drama" in voice_lower or "callirrhoe" in voice_lower:
                sample_text = "Trong khoảnh khắc tĩnh lặng ấy, một câu hỏi bất ngờ vang lên khiến cả khán phòng chết lặng."
            elif "-documentary" in voice_lower or "orus" in voice_lower:
                sample_text = "Mỗi khung hình hoạt hình đều được trau chuốt tỉ mỉ để tái hiện trọn vẹn từng cung bậc cảm xúc."
            elif "-commercial" in voice_lower or "-fast" in voice_lower:
                sample_text = "Trải nghiệm công nghệ đột phá ngay hôm nay với thiết kế sang trọng cùng ưu đãi đặc biệt nhất trong năm!"
            elif "-elder" in voice_lower:
                sample_text = "Các cháu hãy lắng nghe nhé, câu chuyện cổ tích ngày xưa của ông bà vẫn còn lưu truyền mãi đến hôm nay."
            else:
                sample_text = samples["vi"]
        else:
            sample_text = req.text or samples.get(lang_code, samples["en"])

        temp_audio_dir = Path(OUTPUT_DIR) / "temp_audition"
        temp_audio_dir.mkdir(parents=True, exist_ok=True)

        # Cache preview sample per voice + lang so subsequent auditions are instant
        safe_voice = re.sub(r"[^a-zA-Z0-9_\-]", "_", req.voice or "default")
        cached_file = temp_audio_dir / f"sample_{safe_voice}_{lang_code}.mp3"

        if cached_file.exists() and cached_file.stat().st_size > 2000 and not req.text:
            rel_path = str(cached_file.relative_to(OUTPUT_DIR)).replace("\\", "/")
            return {
                "status": "ok",
                "audio_url": f"/media/{rel_path}",
                "sample_text": sample_text,
                "duration": pipeline.voice_agent.get_audio_duration(str(cached_file)),
                "voice": req.voice,
                "effective_voice": req.voice,
                "is_fallback": False,
                "cached": True
            }

        target_file = cached_file if not req.text else temp_audio_dir / f"audition_{uuid.uuid4().hex[:8]}.mp3"

        res = await pipeline.voice_agent.synthesize(
            text=sample_text,
            output_audio_path=str(target_file),
            voice=req.voice,
            api_key=req.api_key,
            allow_voice_fallback=True
        )

        is_fallback = res.get("is_fallback", False)
        effective_voice = res.get("voice", req.voice)

        # If it was a fallback, do not keep target_file as cached_file so quota restoration uses real Gemini
        if is_fallback and target_file == cached_file:
            alt_path = temp_audio_dir / f"audition_fallback_{uuid.uuid4().hex[:8]}.mp3"
            try:
                if target_file.exists():
                    os.rename(target_file, alt_path)
                    target_file = alt_path
            except Exception:
                pass

        rel_path = str(target_file.relative_to(OUTPUT_DIR)).replace("\\", "/")
        return {
            "status": "ok",
            "audio_url": f"/media/{rel_path}",
            "sample_text": sample_text,
            "duration": res.get("duration", 3.0),
            "voice": req.voice,
            "effective_voice": effective_voice,
            "is_fallback": is_fallback,
            "cached": False
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# In-memory tracking for concurrent background rendering tasks
active_render_tasks: Dict[str, asyncio.Task] = {}

async def run_render_task(project_id: str):
    try:
        await pipeline.render_full_animation(project_id)
    except asyncio.CancelledError:
        print(f"Render task for project '{project_id}' was cancelled.")
        p = pipeline.get_project(project_id)
        if p:
            p["status"] = "storyboard_ready"
            p["current_step"] = "Rendering cancelled by user."
            pipeline.save_project(p)
    except Exception as e:
        print(f"Error during video rendering for project '{project_id}': {e}")
        p = pipeline.get_project(project_id)
        if p:
            p["status"] = "error"
            p["current_step"] = f"Rendering error: {str(e)}"
            pipeline.save_project(p)
    finally:
        active_render_tasks.pop(project_id, None)

@app.get("/api/tasks/active")
async def get_active_tasks():
    tasks = pipeline.list_active_tasks()
    for t in tasks:
        tid = t["id"]
        t["is_running"] = tid in active_render_tasks and not active_render_tasks[tid].done()
    return {"active_count": len(tasks), "tasks": tasks}

@app.post("/api/projects/{project_id}/cancel")
async def cancel_render_endpoint(project_id: str):
    task = active_render_tasks.get(project_id)
    if task and not task.done():
        task.cancel()
    active_render_tasks.pop(project_id, None)

    p = pipeline.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")

    p["status"] = "storyboard_ready"
    p["current_step"] = "Rendering cancelled by user."
    pipeline.save_project(p)
    return {"status": "success", "message": f"Render cancelled for project {project_id}", "project": p}

@app.post("/api/tasks/cancel-all")
async def cancel_all_renders_endpoint():
    cancelled = []
    for tid, task in list(active_render_tasks.items()):
        if not task.done():
            task.cancel()
        cancelled.append(tid)
    active_render_tasks.clear()
    for tid in cancelled:
        p = pipeline.get_project(tid)
        if p and p.get("status") == "rendering":
            p["status"] = "storyboard_ready"
            p["current_step"] = "Rendering cancelled."
            pipeline.save_project(p)
    return {"status": "success", "cancelled_count": len(cancelled), "cancelled_ids": cancelled}

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

    # Spawn independent background asyncio Task so multiple renders run concurrently in parallel
    task = asyncio.create_task(run_render_task(project_id))
    active_render_tasks[project_id] = task
    return {"message": "Rendering started", "project_id": project_id, "active_count": len(active_render_tasks)}

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

@app.post("/api/projects/{project_id}/render-scene-video/{scene_idx}")
async def render_scene_video_endpoint(
    project_id: str,
    scene_idx: int,
    req: Optional[RenderSceneVideoRequest] = None
):
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

        force_revoice = req.force_revoice if req else False
        force_repaint = req.force_repaint if req else False
        updated_project = await pipeline.render_scene_video(
            project_id=project_id,
            scene_idx=scene_idx,
            force_revoice=force_revoice,
            force_repaint=force_repaint
        )
        scene = updated_project["scenes"][scene_idx]
        return {
            "status": "success",
            "scene_idx": scene_idx,
            "scene": scene,
            "video_url": f"/media/{scene['video_path']}" if scene.get("video_path") else None,
            "project": updated_project
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/render-all-scene-videos")
async def render_all_scene_videos_endpoint(
    project_id: str,
    req: Optional[RenderAllSceneVideosRequest] = None
):
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

        force_revoice = req.force_revoice if req else False
        updated_project = await pipeline.render_all_scene_videos(
            project_id=project_id,
            force_revoice=force_revoice
        )
        return {
            "status": "success",
            "project": updated_project
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/download-scene-video/{scene_idx}")
async def download_scene_video(project_id: str, scene_idx: int):
    project = pipeline.get_project(project_id)
    if not project or scene_idx >= len(project.get("scenes", [])):
        raise HTTPException(status_code=404, detail="Scene not found")

    scene = project["scenes"][scene_idx]
    video_path = scene.get("video_path")
    if not video_path:
        clip_cand = OUTPUT_DIR / "projects" / project_id / f"clip_{scene_idx + 1}.mp4"
        if clip_cand.exists():
            video_path = str(clip_cand.relative_to(OUTPUT_DIR)).replace("\\", "/")
            scene["video_path"] = video_path
            pipeline.save_project(project)
        else:
            raise HTTPException(status_code=404, detail="Scene video clip not yet rendered")

    full_path = OUTPUT_DIR / video_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Scene video clip missing from disk")

    project_title = project.get("title", "story")[:30].strip().replace(" ", "_")
    filename = f"{project_title}_scene_{scene_idx + 1}.mp4"
    return FileResponse(str(full_path), media_type="video/mp4", filename=filename)

# ====================================================================
# GOOGLE FLOW BROWSER & EXTENSION ENDPOINTS
# ====================================================================

@app.get("/api/flow/status")
async def get_flow_status():
    """Checks Google Flow bridge status via FlowKit."""
    from backend.services.flowkit_service import FlowKitService
    return await FlowKitService.get_instance().get_status()

@app.post("/api/flow/open")
async def open_flow_browser(target_url: Optional[str] = "https://flow.google.com"):
    """Opens Google Flow in the user's default browser."""
    import webbrowser
    url = target_url or "https://flow.google.com"
    try:
        webbrowser.open(url)
        return {"status": "success", "url": url, "message": "Opened Google Flow in browser"}
    except Exception as e:
        return {"status": "error", "error": str(e), "url": url}

@app.post("/api/projects/{project_id}/upload-acting-clip/{scene_idx}")
async def upload_acting_clip(project_id: str, scene_idx: int, file: UploadFile = File(...)):
    """Uploads an acting MP4 video clip (e.g. from Google Flow / I2V) and immediately composites it with voiceover and subtitles."""
    project = pipeline.get_project(project_id)
    if not project or scene_idx >= len(project.get("scenes", [])):
        raise HTTPException(status_code=404, detail="Invalid project or scene index")

    p_dir = Path(OUTPUT_DIR) / "projects" / project_id
    acting_video_path = p_dir / f"scene_{scene_idx + 1}_acting.mp4"

    content = await file.read()
    with open(acting_video_path, "wb") as f:
        f.write(content)

    # Only synthesize audio/subtitles if voiceover or subtitles are enabled
    enable_voice = bool(project.get("enable_voiceover", True) or project.get("enable_multivoice", False))
    enable_subs = project.get("enable_subtitles", True)
    if enable_voice or enable_subs:
        await pipeline.generate_scene_audio(project_id, scene_idx)

    # Immediately render scene clip using this acting video and mixed audio
    updated = await pipeline.render_scene_video(project_id, scene_idx, force_revoice=False)
    return {
        "status": "success",
        "scene_idx": scene_idx,
        "clip_url": f"/media/{updated['scenes'][scene_idx]['video_path']}",
        "project": updated
    }

# ====================================================================
# FLOWKIT (CHROME EXTENSION BRIDGE) AUTOMATED VEO GENERATION
# ====================================================================

@app.get("/api/flowkit/status")
async def get_flowkit_status():
    """Checks if FlowKit bridge server and Chrome Extension are connected."""
    from backend.services.flowkit_service import FlowKitService
    return await FlowKitService.get_instance().get_status()

@app.post("/api/projects/{project_id}/generate-flowkit-video/{scene_idx}")
async def generate_flowkit_scene_video(project_id: str, scene_idx: int):
    """Automatically triggers Google Veo via FlowKit for the scene, then composites voiceover and subtitles."""
    from backend.services.flowkit_service import FlowKitService
    project = pipeline.get_project(project_id)
    if not project or scene_idx >= len(project.get("scenes", [])):
        raise HTTPException(status_code=404, detail="Invalid project or scene index")

    scene = project["scenes"][scene_idx]
    p_dir = Path(OUTPUT_DIR) / "projects" / project_id

    # Ensure scene image exists first
    img_path = p_dir / f"scene_{scene_idx + 1}.jpg"
    if not img_path.exists():
        await pipeline.generate_scene_image(project_id, scene_idx)
        project = pipeline.get_project(project_id)
        scene = project["scenes"][scene_idx]

    acting_out = p_dir / f"scene_{scene_idx + 1}_acting.mp4"
    # Ensure director-grade professional cinematic prompt for Google Flow / Veo
    raw_prompt = scene.get("acting_prompt") or scene.get("visual_prompt") or scene.get("title") or "character action animation"
    prompt = ScriptAgent.professionalize_video_prompt(
        acting_prompt=raw_prompt,
        visual_prompt=scene.get("visual_prompt", ""),
        narration=scene.get("narration", ""),
        camera_motion=scene.get("camera_motion", "zoom_in"),
        title=scene.get("title", f"Scene {scene_idx + 1}"),
        art_style=project.get("art_style", "ghibli"),
        is_commercial=bool(scene.get("is_product_photo"))
    )
    if prompt != scene.get("acting_prompt"):
        scene["acting_prompt"] = prompt
        pipeline.save_project(project)

    flowkit = FlowKitService.get_instance()
    status = await flowkit.get_status()
    if not status.get("extension_connected"):
        raise HTTPException(503, "FlowKit Chrome Extension is not connected. Please open flow.google.com in Chrome with FlowKit extension enabled.")

    aspect = project.get("aspect_ratio", "9:16")
    flow_aspect = "VIDEO_ASPECT_RATIO_PORTRAIT" if "9:16" in aspect or "portrait" in str(aspect).lower() else "VIDEO_ASPECT_RATIO_LANDSCAPE"

    try:
        await flowkit.generate_acting_video(
            image_path=str(img_path),
            prompt=prompt,
            output_video_path=str(acting_out),
            aspect_ratio=flow_aspect,
            duration_s=8
        )
    except Exception as e:
        raise HTTPException(502, f"FlowKit Veo generation error: {str(e)}")

    # Only synthesize audio/subtitles if voiceover or subtitles are enabled
    enable_voice = bool(project.get("enable_voiceover", True) or project.get("enable_multivoice", False))
    enable_subs = project.get("enable_subtitles", True)
    if enable_voice or enable_subs:
        await pipeline.generate_scene_audio(project_id, scene_idx)

    # Composite with voiceover & subtitles
    updated = await pipeline.render_scene_video(project_id, scene_idx, force_revoice=False)
    return {
        "status": "success",
        "scene_idx": scene_idx,
        "clip_url": f"/media/{updated['scenes'][scene_idx]['video_path']}",
        "project": updated
    }

# Mount media directory for images, audio, and videos
app.mount("/media", StaticFiles(directory=str(OUTPUT_DIR)), name="media")

# Mount frontend static files
static_dir = BASE_DIR / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
