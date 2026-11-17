import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import httpx

logger = logging.getLogger("flowkit_service")

FLOWKIT_BASE_URL = os.environ.get("FLOWKIT_URL", "http://127.0.0.1:8100")

class FlowKitService:
    """
    Client for FlowKit's local agent bridge to Google Flow (flow.google.com).
    Communicates with FlowKit on http://127.0.0.1:8100, which routes requests
    through the open Google Flow Chrome tab via the FlowKit Chrome extension.
    """

    _instance: Optional["FlowKitService"] = None

    def __init__(self, base_url: str = FLOWKIT_BASE_URL):
        self.base_url = base_url.rstrip("/")

    @classmethod
    def get_instance(cls) -> "FlowKitService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_status(self) -> Dict[str, Any]:
        """Checks if FlowKit server is running and if the Chrome extension is connected."""
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    ext_conn = data.get("extension_connected", False)
                    return {
                        "online": True,
                        "extension_connected": ext_conn,
                        "version": data.get("version", "1.0"),
                        "status_message": "Ready (Extension connected)" if ext_conn else "Waiting for Chrome Extension connection (open flow.google.com in Chrome)"
                    }
        except Exception as e:
            return {
                "online": False,
                "extension_connected": False,
                "error": str(e),
                "status_message": "FlowKit server offline (start with python -m agent.main)"
            }
        return {"online": False, "extension_connected": False}

    async def _upload_image_detailed(self, image_path: str, project_id: str = "") -> Tuple[str, str]:
        """Uploads a local image file to Google Flow via FlowKit and returns (media_id, flow_project_id)."""
        img_p = Path(image_path)
        if not img_p.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        url = f"{self.base_url}/api/flow/upload-image-file"
        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(img_p, "rb") as f:
                files = {"file": (img_p.name, f, "image/jpeg")}
                form_data = {"project_id": project_id} if project_id else {}
                resp = await client.post(url, files=files, data=form_data)
                if resp.status_code != 200:
                    raise RuntimeError(f"FlowKit image upload failed: {resp.text}")
                data = resp.json()
                media_id = data.get("media_id") or data.get("id")
                resolved_pid = data.get("project_id") or project_id or ""
                if not media_id:
                    raise RuntimeError(f"No media_id returned by FlowKit: {data}")
                return media_id, resolved_pid

    async def upload_image_to_flow(self, image_path: str, project_id: str = "") -> str:
        """Uploads a scene or character image file to Google Flow via FlowKit and returns media_id."""
        media_id, _ = await self._upload_image_detailed(image_path, project_id=project_id)
        return media_id

    async def generate_reference_image(
        self,
        prompt: str,
        output_image_path: str,
        reference_image_paths: Optional[List[str]] = None,
        aspect_ratio: str = "IMAGE_ASPECT_RATIO_LANDSCAPE",
        seed: Optional[int] = None,
    ) -> str:
        """
        Generates an image via FlowKit (/api/flow/generate-image), optionally uploading and
        attaching character/scene reference images in the same Flow project so character
        likeness stays consistent across scenes.
        """
        flow_project_id = ""
        ref_media_ids: List[str] = []
        seen_paths = set()
        for rp in (reference_image_paths or []):
            if not rp:
                continue
            abs_p = str(Path(rp).resolve())
            if abs_p in seen_paths or not os.path.exists(abs_p):
                continue
            seen_paths.add(abs_p)
            mid, flow_project_id = await self._upload_image_detailed(abs_p, project_id=flow_project_id)
            ref_media_ids.append(mid)
            if len(ref_media_ids) >= 4:
                break

        payload: Dict[str, Any] = {
            "prompt": prompt,
            "project_id": flow_project_id,
            "aspect_ratio": aspect_ratio,
            "count": 1,
        }
        if seed is not None:
            payload["seed"] = max(1, int(seed) % 1_000_000_000)
        if ref_media_ids:
            payload["reference_media_ids"] = ref_media_ids
            payload["character_media_ids"] = ref_media_ids

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(f"{self.base_url}/api/flow/generate-image", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"FlowKit image generation failed: {resp.text}")
            data = resp.json()

        media_list = data.get("media") or []
        if not media_list:
            raise RuntimeError(f"FlowKit image generation returned no media: {data}")
        first = media_list[0]
        img_url = first.get("fifeUrl") or first.get("url")
        if not img_url and first.get("mediaId"):
            async with httpx.AsyncClient(timeout=30.0) as client:
                m_resp = await client.get(f"{self.base_url}/api/flow/media/{first['mediaId']}")
                if m_resp.status_code == 200:
                    m_data = m_resp.json()
                    img_url = ((m_data.get("image") or {}).get("fifeUrl")) or m_data.get("fifeUrl") or m_data.get("url")
        if not img_url:
            raise RuntimeError(f"FlowKit generated image had no downloadable URL: {first}")

        out_p = Path(output_image_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=90.0) as client:
            img_resp = await client.get(img_url)
            if img_resp.status_code != 200:
                raise RuntimeError(f"Failed to download FlowKit generated image: {img_resp.status_code}")
            with open(out_p, "wb") as f:
                f.write(img_resp.content)
        return str(out_p)

    async def generate_acting_video(
        self,
        image_path: Optional[str],
        prompt: str,
        output_video_path: str,
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
        duration_s: int = 8,
        resolution: str = "720p",
        timeout_sec: int = 360,
        character_image_paths: Optional[List[str]] = None,
        character_names: Optional[List[str]] = None,
        video_engine: str = "auto"
    ) -> str:
        """
        End-to-End Image-to-Video / Reference-to-Video generation via Google Flow:
        1. Uploads clean scene image (prefers un-bubbled `_base` art if present) and matched character reference images.
        2. When character reference portraits exist and `video_engine` is 'omni_r2v' or 'auto', submits
           Omni Flash Reference-to-Video (/api/flow/generate-video-refs) with [scene_image, ...char_portraits]
           (gracefully falling back to Veo I2V off the start frame if Omni R2V is unavailable for the account).
        3. Polls until video rendering completes.
        4. Downloads .mp4 video to output_video_path.
        """
        flow_project_id = ""
        scene_media_id = None
        char_media_ids: List[str] = []

        # Prefer clean un-bubbled base art if scene image is comic-overlaid
        clean_scene_path = None
        if image_path and os.path.exists(image_path):
            sp = Path(image_path)
            base_cand = sp.with_name(f"{sp.stem}_base{sp.suffix}")
            clean_scene_path = str(base_cand) if base_cand.exists() else str(sp)
            logger.info("Uploading scene image %s to Google Flow via FlowKit...", clean_scene_path)
            scene_media_id, flow_project_id = await self._upload_image_detailed(clean_scene_path, project_id=flow_project_id)
            logger.info("Scene image uploaded to Flow. Media ID: %s (project=%s)", scene_media_id, flow_project_id)

        # Upload unique character portrait reference images into the same Flow project
        seen_char_paths = set()
        if clean_scene_path:
            seen_char_paths.add(str(Path(clean_scene_path).resolve()))
        uploaded_char_labels: List[str] = []
        for idx, cp in enumerate(character_image_paths or []):
            if not cp or not os.path.exists(cp):
                continue
            abs_cp = str(Path(cp).resolve())
            if abs_cp in seen_char_paths:
                continue
            seen_char_paths.add(abs_cp)
            c_mid, flow_project_id = await self._upload_image_detailed(abs_cp, project_id=flow_project_id)
            char_media_ids.append(c_mid)
            if character_names and idx < len(character_names) and character_names[idx]:
                uploaded_char_labels.append(str(character_names[idx]))
            if len(char_media_ids) >= 5:
                break

        engine_mode = (video_engine or "auto").strip().lower()
        all_ref_ids = ([scene_media_id] if scene_media_id else []) + char_media_ids
        all_ref_ids = all_ref_ids[:7]

        effective_prompt = prompt
        if char_media_ids and uploaded_char_labels:
            effective_prompt = (
                f"{prompt.rstrip()} "
                f"(Strictly preserve character likeness and outfits from attached reference portraits: {', '.join(uploaded_char_labels)}.)"
            )

        scene_tag = f"scene_{Path(image_path).stem}" if image_path else "scene_char_ref"

        async def _submit_veo_i2v(start_mid: str) -> Dict[str, Any]:
            req_payload = {
                "start_image_media_id": start_mid,
                "prompt": effective_prompt,
                "project_id": flow_project_id,
                "scene_id": scene_tag,
                "aspect_ratio": aspect_ratio,
                "model_family": "veo",
                "duration_s": duration_s,
                "resolution": resolution
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self.base_url}/api/flow/generate-video", json=req_payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Flow generation submit failed: {resp.text}")
                return resp.json()

        async def _submit_omni_r2v(ref_ids: List[str]) -> Dict[str, Any]:
            omni_dur = duration_s if duration_s in (4, 6, 8, 10) else 8
            req_payload = {
                "reference_media_ids": ref_ids,
                "prompt": effective_prompt,
                "project_id": flow_project_id,
                "scene_id": scene_tag,
                "aspect_ratio": aspect_ratio,
                "model_family": "omni_flash",
                "duration_s": omni_dur,
                "resolution": resolution if resolution in ("360p", "720p") else "720p"
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{self.base_url}/api/flow/generate-video-refs", json=req_payload)
                if resp.status_code != 200:
                    raise RuntimeError(f"Flow Omni R2V submit failed: {resp.text}")
                return resp.json()

        gen_data: Dict[str, Any]
        if engine_mode == "omni_r2v" and all_ref_ids:
            gen_data = await _submit_omni_r2v(all_ref_ids)
        elif engine_mode == "auto" and char_media_ids and len(all_ref_ids) >= 2:
            try:
                logger.info(
                    "Submitting Character+Scene Multi-Reference Video (Omni R2V, %d refs: %s)...",
                    len(all_ref_ids),
                    uploaded_char_labels,
                )
                gen_data = await _submit_omni_r2v(all_ref_ids)
            except Exception as e_r2v:
                err_low = str(e_r2v).lower()
                if "unusual_activity" in err_low or "cooldown" in err_low:
                    raise
                if scene_media_id:
                    logger.warning("Omni R2V unavailable (%s); falling back cleanly to Veo I2V off scene image.", e_r2v)
                    gen_data = await _submit_veo_i2v(scene_media_id)
                elif char_media_ids:
                    logger.warning("Omni R2V unavailable (%s); falling back cleanly to Veo I2V off primary character image.", e_r2v)
                    gen_data = await _submit_veo_i2v(char_media_ids[0])
                else:
                    raise
        elif scene_media_id:
            gen_data = await _submit_veo_i2v(scene_media_id)
        elif char_media_ids:
            gen_data = await _submit_omni_r2v(char_media_ids) if len(char_media_ids) > 1 else await _submit_veo_i2v(char_media_ids[0])
        else:
            raise ValueError("Either a scene image or at least one character portrait image is required for Flow video generation.")

        logger.info("Flow generate response: %s", gen_data)
        ops = gen_data.get("operations") or []
        workflows = (gen_data.get("flowkitPolling") or {}).get("workflows") or gen_data.get("workflows") or []
        operation_id = None
        if ops and isinstance(ops, list) and len(ops) > 0:
            first = ops[0]
            operation_id = (first.get("operation") or {}).get("name") or first.get("name")
        if not operation_id:
            operation_id = gen_data.get("operation_id") or gen_data.get("id")

        video_media_id = gen_data.get("media_id")

        # Poll until finished
        start_time = asyncio.get_event_loop().time()
        video_url = None

        logger.info("Waiting for Google Flow to render video (operation_id=%s, workflows=%s)...", operation_id, len(workflows))
        async with httpx.AsyncClient(timeout=30.0) as client:
            while (asyncio.get_event_loop().time() - start_time) < timeout_sec:
                await asyncio.sleep(6)

                if workflows and not operation_id:
                    w_resp = await client.post(
                        f"{self.base_url}/api/flow/check-omni-status",
                        json={"workflows": workflows, "project_id": flow_project_id}
                    )
                    if w_resp.status_code == 200:
                        w_data = w_resp.json()
                        for wf in w_data.get("workflows", []):
                            cand_u = ((wf.get("media") or {}).get("url")) or ((wf.get("media") or {}).get("fifeUrl"))
                            if cand_u:
                                video_url = cand_u
                                break
                        if video_url:
                            break

                # Check via check-status (POST with operations list)
                if operation_id:
                    check_payload = {"operations": [{"operation": {"name": operation_id}}]}
                    s_resp = await client.post(f"{self.base_url}/api/flow/check-status", json=check_payload)
                    if s_resp.status_code == 200:
                        s_data = s_resp.json()
                        ret_ops = s_data.get("operations", [])
                        for op in ret_ops:
                            status_val = op.get("status")
                            meta = (op.get("operation") or {}).get("metadata", {})
                            vid_meta = meta.get("video") or {}
                            fife_url = vid_meta.get("fifeUrl") or vid_meta.get("url")
                            if fife_url:
                                video_url = fife_url
                                break
                            if status_val == "MEDIA_GENERATION_STATUS_SUCCESSFUL":
                                if vid_meta.get("mediaId"):
                                    video_media_id = vid_meta["mediaId"]
                                if fife_url:
                                    video_url = fife_url
                                    break

                        if video_url:
                            break

                # Fallback: check status via media record
                if video_media_id and not video_url:
                    m_resp = await client.get(f"{self.base_url}/api/flow/media/{video_media_id}")
                    if m_resp.status_code == 200:
                        m_data = m_resp.json()
                        cand_url = m_data.get("url") or m_data.get("video_url") or m_data.get("download_url") or m_data.get("fifeUrl")
                        if cand_url:
                            video_url = cand_url
                            break

        if not video_url:
            raise TimeoutError("Timed out waiting for Google Veo video to finish rendering.")

        # Download video to output_video_path
        logger.info("Downloading rendered Veo video from %s...", video_url)
        out_p = Path(output_video_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=90.0) as client:
            v_resp = await client.get(video_url)
            if v_resp.status_code != 200:
                raise RuntimeError(f"Failed to download video file: {v_resp.status_code}")
            with open(out_p, "wb") as f:
                f.write(v_resp.content)

        logger.info("Successfully saved acting video to %s", output_video_path)
        return str(out_p)
