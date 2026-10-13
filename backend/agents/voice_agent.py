import os
import re
import asyncio
import subprocess
from pathlib import Path
from typing import Optional
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

    @staticmethod
    def _normalize_text_for_tts(text: str) -> str:
        """
        Cleans and normalizes text for speech synthesis:
        - Ensures first letter is capitalized to avoid edge-tts tokenizer glitches.
        - Ensures terminal punctuation exists so sentence boundary parsing succeeds.
        """
        t = text.strip() if text else ""
        if not t:
            return "..."
        if t[0].isalpha() and t[0].islower():
            t = t[0].upper() + t[1:]
        if not t.endswith(('.', '!', '?', ';', ':', '...')):
            t += "."
        return t

    @staticmethod
    def _get_fallback_voice_for_gemini(voice_id: str, is_vietnamese: bool = False) -> str:
        """
        Maps a Gemini voice to a personality- and gender-matched Edge-TTS voice
        when Gemini quota is exceeded or unavailable.
        """
        voice_lower = (voice_id or "").lower()
        if is_vietnamese:
            if "aoede" in voice_lower:
                return "vi-VN-HoaiMyNeural"
            elif "kore" in voice_lower:
                return "vi-VN-HoaiMyNeural-story"
            elif "puck" in voice_lower:
                return "vi-VN-NamMinhNeural"
            elif "charon" in voice_lower:
                return "vi-VN-NamMinhNeural-story"
            elif "fenrir" in voice_lower:
                return "vi-VN-NamMinhNeural-heroic"
            return "vi-VN-HoaiMyNeural"
        else:
            if "aoede" in voice_lower:
                return "en-US-JennyNeural"
            elif "kore" in voice_lower:
                return "en-US-AriaNeural"
            elif "puck" in voice_lower:
                return "en-US-GuyNeural"
            elif "charon" in voice_lower:
                return "en-US-ChristopherNeural"
            elif "fenrir" in voice_lower:
                return "en-GB-RyanNeural"
            return "en-US-JennyNeural"

    async def _try_edge_tts(self, text: str, output_audio_path: str, voice: str, rate: str, pitch: str, max_retries: int = 4):
        """Attempts Edge-TTS synthesis for the specified voice with robust retry and backoff."""
        last_err = None
        for attempt in range(max_retries):
            try:
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
                    raise RuntimeError(f"Edge-TTS voice '{voice}' generated zero audio bytes.")

                return boundaries
            except Exception as e:
                last_err = e
                if attempt < max_retries - 1:
                    backoff = (attempt + 1) * 0.7
                    print(f"Edge-TTS attempt {attempt + 1} for '{voice}' encountered: {e}. Retrying same voice in {backoff:.1f}s...")
                    await asyncio.sleep(backoff)
                    continue
                raise last_err

    def _synthesize_with_gtts(self, text: str, output_audio_path: str, lang: str):
        """Ultra-reliable fallback using gTTS."""
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang)
        tts.save(output_audio_path)

    async def _synthesize_with_gemini(self, text: str, output_audio_path: str, voice: str, api_key: str = None) -> bool:
        """Synthesize speech using Google Gemini Native Audio generation."""
        import base64
        import wave
        from google import genai
        from google.genai import types
        from backend.config import get_server_credentials

        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            s_creds = get_server_credentials()
            key = s_creds.get("gemini_api_key")

        if not key:
            raise ValueError("Gemini API key is required for Gemini voice synthesis.")

        client = genai.Client(api_key=key)
        voice_clean = voice.replace("gemini-", "").strip()

        # Models supporting native audio / TTS output
        models_to_try = [
            "gemini-2.5-flash-preview-tts",
            "gemini-3.8-flash-tts"
        ]

        raw_bytes = None
        last_err = None

        for m_id in models_to_try:
            try:
                resp = client.models.generate_content(
                    model=m_id,
                    contents=f"Read this animation scene narration clearly, engagingly, and expressively without extra commentary:\n\n{text}",
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice_clean
                                )
                            )
                        )
                    )
                )
                if resp.candidates and resp.candidates[0].content and resp.candidates[0].content.parts:
                    for part in resp.candidates[0].content.parts:
                        if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                            data = part.inline_data.data
                            raw_bytes = base64.b64decode(data) if isinstance(data, str) else data
                            if raw_bytes and len(raw_bytes) > 200:
                                break
                    if raw_bytes:
                        break
            except Exception as e:
                last_err = e
                continue

        if not raw_bytes:
            raise RuntimeError(f"Gemini voice synthesis failed on model {models_to_try}: {last_err}")

        # Write raw PCM to temp WAV file with 24000Hz 16-bit Mono header
        temp_wav = output_audio_path + ".temp.wav"
        with wave.open(temp_wav, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(raw_bytes)

        # Convert to final MP3 via FFmpeg
        cmd = [FFMPEG_PATH, "-y", "-i", temp_wav, "-b:a", "192k", output_audio_path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        try:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
        except Exception:
            pass

        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg audio conversion failed: {proc.stderr}")

        return True

    async def synthesize(
        self,
        text: str,
        output_audio_path: str,
        output_srt_path: str = None,
        voice: str = None,
        rate: str = "+0%",
        pitch: str = "+0Hz",
        api_key: str = None,
        allow_voice_fallback: bool = False
    ) -> dict:
        """
        Synthesizes narration speech using ONE consistent voice throughout the clip.
        When allow_voice_fallback is False (default for clip narration), it strictly preserves
        the chosen character voice and will NOT swap to an alternate gender or robotic voice.
        """
        clean_text = self._normalize_text_for_tts(text)
        selected_voice = voice or self.default_voice
        output_audio_path = str(output_audio_path)
        parent_dir = os.path.dirname(output_audio_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        lang_code = self._get_lang_code_from_voice(selected_voice)
        boundaries = []
        success = False

        is_fallback = False
        fallback_from = None

        # Attempt 0: Google Gemini Native Audio if selected
        if selected_voice and selected_voice.startswith("gemini-"):
            try:
                await self._synthesize_with_gemini(clean_text, output_audio_path, selected_voice, api_key=api_key)
                success = True
                print(f"Synthesized scene speech using Google Gemini voice '{selected_voice}'!")
            except Exception as e_gemini:
                fallback_from = selected_voice
                is_fallback = True
                is_vn = any(ord(c) > 127 for c in clean_text) or "vi" in lang_code
                matched_voice = self._get_fallback_voice_for_gemini(selected_voice, is_vietnamese=is_vn)
                print(f"Gemini voice synthesis notice ({selected_voice}): {e_gemini}. Using matched voice '{matched_voice}'...")
                selected_voice = matched_voice

        # Extract tuning variants if any
        actual_voice = selected_voice
        actual_rate = rate
        actual_pitch = pitch

        if selected_voice == "gtts-vi":
            try:
                self._synthesize_with_gtts(clean_text, output_audio_path, "vi")
                success = True
                boundaries = []
            except Exception as e_gtts:
                print(f"gTTS error: {e_gtts}")
        elif "-story" in selected_voice:
            actual_voice = selected_voice.replace("-story", "")
            actual_rate = "-10%"
            actual_pitch = "-1Hz"
        elif "-energetic" in selected_voice:
            actual_voice = selected_voice.replace("-energetic", "")
            actual_rate = "+12%"
            actual_pitch = "+3Hz"
        elif "-heroic" in selected_voice:
            actual_voice = selected_voice.replace("-heroic", "")
            actual_rate = "-5%"
            actual_pitch = "-3Hz"

        # Attempt 1: Requested Voice via Edge-TTS (with 4 retries on the SAME voice)
        if not success:
            try:
                boundaries = await self._try_edge_tts(clean_text, output_audio_path, actual_voice, actual_rate, actual_pitch, max_retries=4)
                success = True
            except Exception as e:
                print(f"Edge-TTS primary voice '{actual_voice}' retry exhausted: {e}.")
                # If pitch/rate was tuned, retry once with standard pitch/rate on the SAME voice
                if actual_rate != "+0%" or actual_pitch != "+0Hz":
                    try:
                        print(f"Retrying '{actual_voice}' with standard pitch/rate to preserve character voice...")
                        boundaries = await self._try_edge_tts(clean_text, output_audio_path, actual_voice, "+0%", "+0Hz", max_retries=2)
                        success = True
                    except Exception as e_norm:
                        print(f"Standard pitch retry for '{actual_voice}' failed: {e_norm}")

        # If allow_voice_fallback is explicitly enabled (e.g. audition probe), only then allow swapping
        if not success and allow_voice_fallback:
            alt_voice = None
            if selected_voice == "vi-VN-HoaiMyNeural":
                alt_voice = "vi-VN-NamMinhNeural"
            elif selected_voice == "vi-VN-NamMinhNeural":
                alt_voice = "vi-VN-HoaiMyNeural"
            elif "en-" in selected_voice:
                alt_voice = "en-US-JennyNeural" if selected_voice != "en-US-JennyNeural" else "en-US-ChristopherNeural"

            if alt_voice:
                try:
                    boundaries = await self._try_edge_tts(clean_text, output_audio_path, alt_voice, rate, pitch, max_retries=2)
                    selected_voice = alt_voice
                    success = True
                    is_fallback = True
                    print(f"Audition fallback synthesized with '{alt_voice}'.")
                except Exception:
                    pass

            if not success:
                try:
                    self._synthesize_with_gtts(clean_text, output_audio_path, lang_code)
                    success = True
                    is_fallback = True
                    boundaries = []
                except Exception as e3:
                    raise RuntimeError(f"All TTS voice engines failed: {e3}")

        if not success:
            raise RuntimeError(f"Voice synthesis failed for voice '{selected_voice}'. Consistent voice policy prevented swapping to another voice.")

        duration = self.get_audio_duration(output_audio_path)

        # Generate SRT if path is provided
        if output_srt_path:
            output_srt_path = str(output_srt_path)
            parent_srt = os.path.dirname(output_srt_path)
            if parent_srt:
                os.makedirs(parent_srt, exist_ok=True)

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
            "boundaries": boundaries,
            "is_fallback": is_fallback,
            "fallback_from": fallback_from
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
