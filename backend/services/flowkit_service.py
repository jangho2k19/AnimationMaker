import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, Any
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

    async def upload_image_to_flow(self, image_path: str) -> str:
        """Uploads a scene image file to Google Flow via FlowKit and returns media_id."""
        img_p = Path(image_path)
        if not img_p.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        url = f"{self.base_url}/api/flow/upload-image-file"
        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(img_p, "rb") as f:
                files = {"file": (img_p.name, f, "image/jpeg")}
                resp = await client.post(url, files=files)
                if resp.status_code != 200:
                    raise RuntimeError(f"FlowKit image upload failed: {resp.text}")
                data = resp.json()
                media_id = data.get("media_id") or data.get("id")
                if not media_id:
                    raise RuntimeError(f"No media_id returned by FlowKit: {data}")
                return media_id

    async def generate_acting_video(
        self,
        image_path: str,
        prompt: str,
        output_video_path: str,
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
        duration_s: int = 8,
        resolution: str = "720p",
        timeout_sec: int = 360
    ) -> str:
        """
        End-to-End Image-to-Video generation via Google Flow:
        1. Uploads starting frame image to Flow.
        2. Submits generation request to Google Veo.
        3. Polls until video rendering completes.
        4. Downloads .mp4 video to output_video_path.
        """
        logger.info("Uploading %s to Google Flow via FlowKit...", image_path)
        media_id = await self.upload_image_to_flow(image_path)
        logger.info("Image uploaded to Flow. Media ID: %s", media_id)

        req_payload = {
            "start_image_media_id": media_id,
            "prompt": prompt,
            "scene_id": f"scene_{Path(image_path).stem}",
            "aspect_ratio": aspect_ratio,
            "model_family": "veo",
            "duration_s": duration_s,
            "resolution": resolution
        }

        url = f"{self.base_url}/api/flow/generate-video"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=req_payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Flow generation submit failed: {resp.text}")
            gen_data = resp.json()

        logger.info("Flow generate response: %s", gen_data)
        ops = gen_data.get("operations") or []
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

        logger.info("Waiting for Google Veo to render video (operation_id=%s)...", operation_id)
        async with httpx.AsyncClient(timeout=30.0) as client:
            while (asyncio.get_event_loop().time() - start_time) < timeout_sec:
                await asyncio.sleep(6)

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
