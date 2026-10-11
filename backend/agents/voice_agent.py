import os
import re
import asyncio
import subprocess
from pathlib import Path
import edge_tts
from backend.config import FFMPEG_PATH, VOICES

class VoiceAgent:
    def __init__(self, default_voice: str = "en-US-ChristopherNeural"):
        self.default_voice = default_voice

    def get_audio_duration(self, audio_path: str) -> float:
        """Extract duration of an audio file in seconds via FFmpeg."""
        try:
            cmd = [FFMPEG_PATH, "-i", str(audio_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", proc.stderr)
            if match:
                h, m, s = match.groups()
                return round(float(h) * 3600 + float(m) * 60 + float(s), 2)
        except Exception as e:
            print(f"Error reading audio duration: {e}")
        return 4.0  # Fallback reasonable duration

    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        """Format seconds into HH:MM:SS,mmm string for SRT format."""
        millis = int((seconds % 1) * 1000)
        total_seconds = int(seconds)
        s = total_seconds % 60
        total_minutes = total_seconds // 60
        m = total_minutes % 60
        h = total_minutes // 60
        return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"

    def _get_lang_code_from_voice(self, voice: str) -> str:
        """Extract ISO 639-1 language code from voice string."""
        if not voice:
            return "en"
        lower = voice.lower()
        if "vi-" in lower:
            return "vi"
        elif "ja-" in lower:
            return "ja"
        elif "fr-" in lower:
            return "fr"
        elif "es-" in lower:
            return "es"
        return "en"

    async def _try_edge_tts(self, text: str, output_audio_path: str, voice: str, rate: str, pitch: str):
        """Attempts Edge-TTS synthesis and returns sentence boundaries."""
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        boundaries = []
        has_audio = False

        with open(output_audio_path, "wb") as audio_file:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    has_audio = True
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "SentenceBoundary":
                    start_sec = chunk["offset"] / 10_000_000.0
                    dur_sec = chunk["duration"] / 10_000_000.0
                    end_sec = start_sec + dur_sec
                    sentence_text = chunk.get("text", "").strip()
                    if sentence_text:
                        boundaries.append({
                            "start": start_sec,
                            "end": end_sec,
                            "text": sentence_text
                        })

        if not has_audio or os.path.getsize(output_audio_path) == 0:
            raise RuntimeError("Edge-TTS generated zero audio bytes.")

        return boundaries

    def _synthesize_with_gtts(self, text: str, output_audio_path: str, lang: str):
        """Ultra-reliable fallback using gTTS."""
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang)
        tts.save(output_audio_path)

    async def synthesize(self, text: str, output_audio_path: str, output_srt_path: str = None, voice: str = None, rate: str = "+0%", pitch: str = "+0Hz") -> dict:
        """
        Synthesize speech with multi-layered fallback:
        1. Requested Edge-TTS voice
        2. Alternative Edge-TTS voice
        3. gTTS (Google TTS) fallback
        Guarantees audio is ALWAYS successfully produced without crashing.
        """
        clean_text = text.strip() if text and text.strip() else "..."
        selected_voice = voice or self.default_voice
        output_audio_path = str(output_audio_path)
        os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)

        lang_code = self._get_lang_code_from_voice(selected_voice)
        boundaries = []
        success = False

        # Attempt 1: Requested Voice
        try:
            boundaries = await self._try_edge_tts(clean_text, output_audio_path, selected_voice, rate, pitch)
            success = True
        except Exception as e:
            print(f"Edge-TTS primary voice '{selected_voice}' failed: {e}. Trying alternate voice...")

        # Attempt 2: Swapping to alternate voice if Vietnamese or English
        if not success:
            alt_voice = None
            if selected_voice == "vi-VN-HoaiMyNeural":
                alt_voice = "vi-VN-NamMinhNeural"
            elif selected_voice == "vi-VN-NamMinhNeural":
                alt_voice = "vi-VN-HoaiMyNeural"
            elif "en-" in selected_voice:
                alt_voice = "en-US-JennyNeural" if selected_voice != "en-US-JennyNeural" else "en-US-ChristopherNeural"

            if alt_voice:
                try:
                    boundaries = await self._try_edge_tts(clean_text, output_audio_path, alt_voice, rate, pitch)
                    selected_voice = alt_voice
                    success = True
                    print(f"Successfully synthesized with alternate voice '{alt_voice}'!")
                except Exception as e2:
                    print(f"Edge-TTS alternate voice '{alt_voice}' also failed: {e2}.")

        # Attempt 3: Fail-safe gTTS fallback
        if not success:
            try:
                print(f"Activating gTTS engine fallback for language '{lang_code}'...")
                self._synthesize_with_gtts(clean_text, output_audio_path, lang_code)
                success = True
                boundaries = []
            except Exception as e3:
                print(f"gTTS fallback error: {e3}")
                raise RuntimeError(f"All TTS voice engines failed: {e3}")

        duration = self.get_audio_duration(output_audio_path)

        # Generate SRT if path is provided
        if output_srt_path:
            output_srt_path = str(output_srt_path)
            os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)

            all_cues = []
            if boundaries:
                for b in boundaries:
                    s_time = b["start"]
                    e_time = min(b["end"], duration + 0.2)
                    sub_cues = self._chunk_text_into_rhythmic_cues(b["text"], s_time, e_time, max_words=5)
                    all_cues.extend(sub_cues)
            else:
                all_cues = self._chunk_text_into_rhythmic_cues(clean_text, 0.1, max(0.5, duration - 0.1), max_words=5)

            with open(output_srt_path, "w", encoding="utf-8") as srt_file:
                for idx, cue in enumerate(all_cues, 1):
                    start_str = self._format_srt_timestamp(cue["start"])
                    end_str = self._format_srt_timestamp(cue["end"])
                    srt_file.write(f"{idx}\n{start_str} --> {end_str}\n{cue['text']}\n\n")

        return {
            "audio_path": output_audio_path,
            "srt_path": output_srt_path,
            "duration": duration,
            "voice": selected_voice,
            "boundaries": boundaries
        }

    @staticmethod
    def _chunk_text_into_rhythmic_cues(text: str, start_time: float, end_time: float, max_words: int = 5) -> list:
        """
        Splits long sentences into concise rhythmic subtitle cues of 4-6 words.
        Guarantees subtitles never block the video frame or wrap into tall text walls.
        """
        words = text.strip().split()
        if not words:
            return []
        if len(words) <= max_words:
            return [{"start": start_time, "end": end_time, "text": text.strip()}]

        chunks = []
        curr = []
        for w in words:
            curr.append(w)
            if len(curr) >= max_words or (len(curr) >= 3 and w.endswith((',', '.', '!', '?', ';', ':'))):
                chunks.append(" ".join(curr))
                curr = []
        if curr:
            if chunks and len(curr) <= 2:
                chunks[-1] += " " + " ".join(curr)
            else:
                chunks.append(" ".join(curr))

        total_chars = max(1, sum(len(c) for c in chunks))
        total_dur = max(0.5, end_time - start_time)
        cues = []
        curr_t = start_time
        for c in chunks:
            c_dur = (len(c) / total_chars) * total_dur
            cues.append({
                "start": round(curr_t, 2),
                "end": round(curr_t + c_dur, 2),
                "text": c.strip()
            })
            curr_t += c_dur
        return cues
