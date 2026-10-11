import os
import subprocess
from pathlib import Path
from typing import List, Dict
from backend.config import FFMPEG_PATH

class VideoEngine:
    def __init__(self, fps: int = 30, width: int = 1280, height: int = 720):
        self.fps = fps
        self.width = width
        self.height = height

    def _escape_path_for_ffmpeg_filter(self, file_path: str) -> str:
        """Escape Windows file path for FFmpeg filter graph (colons and backslashes)."""
        clean_path = os.path.abspath(file_path).replace("\\", "/")
        if ":" in clean_path:
            drive, rest = clean_path.split(":", 1)
            return f"{drive}\\:{rest}"
        return clean_path

    def _get_zoompan_filter(self, motion_type: str, total_frames: int) -> str:
        """Constructs smooth mathematical Ken Burns camera motions."""
        w, h = self.width, self.height
        motion = motion_type.lower()

        if motion == "zoom_in":
            # Gradually zooms in from 1.0 to 1.20 centered
            return f"zoompan=z='min(zoom+0.0010,1.20)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={self.fps}"

        elif motion == "zoom_out":
            # Starts zoomed at 1.20 and recedes to 1.02
            return f"zoompan=z='if(lte(zoom,1.0),1.20,max(1.002,zoom-0.0010))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={self.fps}"

        elif motion == "pan_left":
            # Zooms to 1.15 and drifts right to left
            return f"zoompan=z='1.15':x='if(lte(on,-1),(iw-iw/zoom)/2,max(0,x-1.0))':y='ih/2-(ih/zoom/2)':d={total_frames}:s={w}x{h}:fps={self.fps}"

        elif motion == "pan_right":
            # Zooms to 1.15 and drifts left to right
            return f"zoompan=z='1.15':x='if(lte(on,-1),0,min(iw-iw/zoom,x+1.0))':y='ih/2-(ih/zoom/2)':d={total_frames}:s={w}x{h}:fps={self.fps}"

        else:  # subtle_drift or default
            return f"zoompan=z='min(zoom+0.0006,1.10)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={self.fps}"

    def render_scene_clip(
        self,
        image_path: str,
        audio_path: str,
        srt_path: str,
        output_clip_path: str,
        motion_type: str = "zoom_in",
        duration: float = 4.0,
        enable_subtitles: bool = True
    ) -> str:
        """
        Renders a single scene into an MP4 clip:
        - Image transformed by Ken Burns camera motion
        - Burnt styled subtitles at bottom center
        - Synchronized narration audio
        """
        output_clip_path = str(output_clip_path)
        os.makedirs(os.path.dirname(output_clip_path), exist_ok=True)

        # Pad duration slightly by 0.4s for natural narrative breathing room
        clip_duration = max(2.5, duration + 0.4)
        total_frames = int(clip_duration * self.fps)

        zoompan_expr = self._get_zoompan_filter(motion_type, total_frames)

        # Build video filter chain
        vf_filters = [zoompan_expr]

        if enable_subtitles and srt_path and os.path.exists(srt_path):
            escaped_srt = self._escape_path_for_ffmpeg_filter(srt_path)
            # Modern cinematic subtitle style: crisp white with clean black outline and shadow (BorderStyle=1)
            # Scaled strictly by width so text never forms tall multi-line walls that cover the video
            font_size = max(16, min(22, int(self.width * 0.026)))
            margin_v = max(24, min(65, int(self.height * 0.065)))
            sub_style = (
                f"FontSize={font_size},"
                "PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,"
                "BackColour=&H60000000,"
                "BorderStyle=1,"
                "Outline=2.0,"
                "Shadow=1.0,"
                f"MarginV={margin_v},"
                "Alignment=2,"
                "Spacing=0.5"
            )
            vf_filters.append(f"subtitles='{escaped_srt}':force_style='{sub_style}'")

        vf_chain = ",".join(vf_filters)

        cmd = [
            FFMPEG_PATH, "-y",
            "-loop", "1",
            "-t", str(clip_duration),
            "-i", str(image_path),
            "-i", str(audio_path),
            "-vf", vf_chain,
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_clip_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            print(f"FFmpeg scene render error: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed to render scene: {result.stderr[:400]}")

        return output_clip_path

    def concatenate_and_mix(
        self,
        scene_clip_paths: List[str],
        output_video_path: str,
        bgm_path: str = None,
        bgm_volume: float = 0.12
    ) -> str:
        """
        Concatenates scene clips and mixes soft background music.
        """
        output_video_path = str(output_video_path)
        out_dir = Path(output_video_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        concat_list_file = out_dir / "concat_manifest.txt"
        with open(concat_list_file, "w", encoding="utf-8") as f:
            for clip in scene_clip_paths:
                clean_clip = os.path.abspath(clip).replace("\\", "/")
                f.write(f"file '{clean_clip}'\n")

        merged_temp_path = str(out_dir / "scenes_merged_temp.mp4")

        # Step 1: Concat video scenes
        concat_cmd = [
            FFMPEG_PATH, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            merged_temp_path
        ]
        concat_res = subprocess.run(concat_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if concat_res.returncode != 0:
            raise RuntimeError(f"Concat failed: {concat_res.stderr[:400]}")

        # Step 2: Mix background music if provided
        if bgm_path and os.path.exists(bgm_path):
            mix_cmd = [
                FFMPEG_PATH, "-y",
                "-i", merged_temp_path,
                "-stream_loop", "-1",
                "-i", str(bgm_path),
                "-filter_complex",
                f"[0:a]volume=1.0[voice];[1:a]volume={bgm_volume}[music];[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                "-map", "0:v",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                output_video_path
            ]
            mix_res = subprocess.run(mix_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if mix_res.returncode == 0:
                if Path(merged_temp_path).exists():
                    Path(merged_temp_path).unlink()
                if concat_list_file.exists():
                    concat_list_file.unlink()
                return output_video_path

        # If no bgm or mixing skipped, move merged file to final destination
        if Path(output_video_path).exists():
            Path(output_video_path).unlink()
        Path(merged_temp_path).rename(output_video_path)

        if concat_list_file.exists():
            concat_list_file.unlink()

        return output_video_path
