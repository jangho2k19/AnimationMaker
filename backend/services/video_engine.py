import os
import shutil
import logging
import subprocess
from pathlib import Path
from typing import List, Dict
from backend.config import FFMPEG_PATH

logger = logging.getLogger("video_engine")

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

    def _has_audio_stream(self, file_path: str) -> bool:
        """Checks if a media file contains an audio stream."""
        cmd = [FFMPEG_PATH, "-i", str(file_path)]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return "Audio:" in res.stderr

    def get_media_duration(self, file_path: str) -> float:
        """Extracts precise duration of an audio or video file via FFmpeg."""
        if not file_path or not os.path.exists(str(file_path)):
            return 0.0
        try:
            import re
            cmd = [FFMPEG_PATH, "-i", str(file_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", proc.stderr)
            if match:
                h, m, s = match.groups()
                return round(float(h) * 3600 + float(m) * 60 + float(s), 2)
        except Exception as e:
            logger.warning("Error getting media duration for %s: %s", file_path, e)
        return 0.0

    def render_scene_clip(
        self,
        image_path: str = None,
        audio_path: str = None,
        srt_path: str = None,
        output_clip_path: str = None,
        motion_type: str = "zoom_in",
        duration: float = 4.0,
        enable_subtitles: bool = True,
        enable_voiceover: bool = True,
        source_video_path: str = None
    ) -> str:
        """
        Renders a single scene into an MP4 clip:
        - If source_video_path is provided (from Google Flow / I2V acting video):
          Uses full acting video duration (typically 8s). Voiceover narration is synchronized
          and plays within the video clip if enabled. Video is NEVER looped to prevent repeated content.
        - Else (static image fallback):
          transforms image with Ken Burns camera motion
        - Burns high-contrast cinematic subtitles (if enabled)
        - Synchronizes voiceover narration audio (if enabled)
        """
        output_clip_path = str(output_clip_path)
        os.makedirs(os.path.dirname(output_clip_path), exist_ok=True)

        has_acting_video = bool(source_video_path and os.path.exists(source_video_path))
        has_audio = bool(enable_voiceover and audio_path and os.path.exists(audio_path))

        vf_filters = []
        if has_acting_video:
            # Probe exact durations
            acting_video_dur = self.get_media_duration(source_video_path)
            audio_dur = self.get_media_duration(audio_path) if has_audio else 0.0

            # Scale video to fit project dimensions cleanly
            vf_filters.append(
                f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black"
            )

            # Prevent video repeat:
            # 1. If voiceover duration <= acting video duration:
            #    clip_duration = acting_video_dur (e.g. 8.0s). The full acting performance plays once.
            # 2. If voiceover is slightly longer than acting video:
            #    Freeze the last frame using tpad rather than looping the action from the start!
            if acting_video_dur > 0:
                if audio_dur <= acting_video_dur:
                    clip_duration = acting_video_dur
                else:
                    clip_duration = round(audio_dur + 0.3, 2)
                    extra_freeze = round(clip_duration - acting_video_dur, 2)
                    if extra_freeze > 0:
                        vf_filters.append(f"tpad=stop_mode=clone:stop_duration={extra_freeze}")
            else:
                clip_duration = max(2.5, duration + 0.4)
        else:
            clip_duration = max(2.5, duration + 0.4)
            total_frames = int(clip_duration * self.fps)
            zoompan_expr = self._get_zoompan_filter(motion_type, total_frames)
            vf_filters.append(zoompan_expr)

        if enable_subtitles and srt_path and os.path.exists(srt_path):
            escaped_srt = self._escape_path_for_ffmpeg_filter(srt_path)
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
        source_has_audio = bool(has_acting_video and self._has_audio_stream(source_video_path))

        cmd = [FFMPEG_PATH, "-y"]
        if has_acting_video:
            cmd.extend([
                "-i", str(source_video_path),
            ])
        else:
            cmd.extend([
                "-loop", "1",
                "-t", str(clip_duration),
                "-i", str(image_path),
            ])

        filter_complex_clauses = []
        filter_complex_clauses.append(f"[0:v]{vf_chain}[vout]")

        if source_has_audio and has_audio:
            # Both Google Flow ambient video audio AND synthesized voiceover audio are present:
            # Mix them together so neither the acting motion sounds nor the spoken dialogue are lost!
            cmd.extend(["-i", str(audio_path)])
            filter_complex_clauses.append(
                f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.85[a_src];"
                f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1.30[a_vox];"
                f"[a_src][a_vox]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
            audio_map = "[aout]"

        elif source_has_audio and not has_audio:
            # Google Flow video has native audio track: preserve it directly
            filter_complex_clauses.append(
                f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[aout]"
            )
            audio_map = "[aout]"

        elif has_audio:
            # Video is silent (standard from Google Flow text-to-video): attach crystal-clear voiceover audio
            cmd.extend(["-i", str(audio_path)])
            filter_complex_clauses.append(
                f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo[aout]"
            )
            audio_map = "[aout]"

        else:
            # Fallback silence generator only if both are unavailable
            cmd.extend(["-f", "lavfi", "-t", str(clip_duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
            filter_complex_clauses.append(
                f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo[aout]"
            )
            audio_map = "[aout]"

        filter_graph = ";".join(filter_complex_clauses)
        cmd.extend([
            "-filter_complex", filter_graph,
            "-map", "[vout]",
            "-map", audio_map,
            "-t", str(clip_duration),
            "-r", "24",
            "-c:v", "libx264",
            "-preset", "fast",
        ])
        if not has_acting_video:
            cmd.extend(["-tune", "stillimage"])
        cmd.extend([
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "48000",
            "-b:a", "192k",
            output_clip_path
        ])

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            logger.error("FFmpeg scene render error: %s", result.stderr)
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
        Concatenates all scene clips into a master film and mixes background music.
        Uses filter_complex to normalize dimensions, framerate (24fps), and audio (48kHz stereo),
        guaranteeing seamless concatenation without dropped scenes, audio drift, or format errors.
        """
        output_video_path = str(output_video_path)
        out_dir = Path(output_video_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        valid_clips = [str(c) for c in scene_clip_paths if c and os.path.exists(str(c))]
        if not valid_clips:
            raise ValueError("No valid scene clips found to concatenate.")

        has_bgm = bool(bgm_path and os.path.exists(str(bgm_path)))

        # Case 1: Single scene clip
        if len(valid_clips) == 1:
            single_clip = valid_clips[0]
            if has_bgm:
                mix_cmd = [
                    FFMPEG_PATH, "-y",
                    "-i", str(single_clip),
                    "-stream_loop", "-1",
                    "-i", str(bgm_path),
                    "-filter_complex",
                    f"[0:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                    f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24,format=yuv420p[vout];"
                    f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice];"
                    f"[1:a]volume={bgm_volume}[music];"
                    f"[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]",
                    "-map", "[vout]",
                    "-map", "[aout]",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-pix_fmt", "yuv420p",
                    "-r", "24",
                    "-c:a", "aac",
                    "-ar", "48000",
                    "-b:a", "192k",
                    output_video_path
                ]
                mix_res = subprocess.run(mix_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
                if mix_res.returncode == 0:
                    return output_video_path
                else:
                    logger.warning("Single clip BGM mix warning: %s", mix_res.stderr)

            # If no BGM or mix failed, copy single clip to output_video_path
            shutil.copyfile(single_clip, output_video_path)
            return output_video_path

        # Case 2: Multiple scene clips -> Robust filter_complex concat
        cmd = [FFMPEG_PATH, "-y"]
        for c in valid_clips:
            cmd.extend(["-i", str(c)])

        if has_bgm:
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

        num_scenes = len(valid_clips)
        filter_chains = []
        concat_inputs = []

        for i, clip_p in enumerate(valid_clips):
            filter_chains.append(
                f"[{i}:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps=24,format=yuv420p[v{i}]"
            )
            if self._has_audio_stream(clip_p):
                filter_chains.append(
                    f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]"
                )
            else:
                filter_chains.append(
                    f"aevalsrc=0:channel_layout=stereo:sample_rate=48000[a{i}]"
                )
            concat_inputs.append(f"[v{i}][a{i}]")

        concat_clause = "".join(concat_inputs) + f"concat=n={num_scenes}:v=1:a=1[vcat][acat_pre]"
        filter_chains.append(concat_clause)

        if has_bgm:
            bgm_idx = num_scenes
            filter_chains.append(f"[{bgm_idx}:a]volume={bgm_volume}[bgm]")
            filter_chains.append(f"[acat_pre][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]")
            audio_map = "[aout]"
        else:
            audio_map = "[acat_pre]"

        filter_graph = ";".join(filter_chains)

        cmd.extend([
            "-filter_complex", filter_graph,
            "-map", "[vcat]",
            "-map", audio_map,
            "-c:v", "libx264",
            "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "48000",
            "-b:a", "192k",
            output_video_path
        ])

        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            logger.error("FFmpeg filter_complex concat error: %s", res.stderr)
            raise RuntimeError(f"Failed to combine scene videos into full film: {res.stderr[:400]}")

        return output_video_path
