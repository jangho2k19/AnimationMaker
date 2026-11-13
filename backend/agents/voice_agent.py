import os
import re
import shutil
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
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
        - Sanitizes XML/SSML sensitive chars (&, <, >) that trigger WebSocket disconnections.
        - Replaces em-dashes and quotes with natural punctuation pauses.
        - Ensures first letter is capitalized and terminal punctuation exists.
        """
        t = text.strip() if text else ""
        if not t:
            return "..."
        # Replace XML/SSML and prosody-breaking characters that trigger WebSocket disconnections on vi-VN neural voices
        is_vn = any(ord(c) > 127 for c in t)
        t = t.replace("&", " và " if is_vn else " and ")
        t = re.sub(r'[<>]', '', t)
        t = re.sub(r'[*_`#]', '', t)
        t = re.sub(r'[—–]', ', ', t)
        t = re.sub(r'["“”„\'‘’]', ' ', t)
        t = re.sub(r'\s*[:;]\s*', ', ', t)
        t = re.sub(r'…+|\.{2,}', '. ', t)
        t = re.sub(r',\s*,+', ', ', t)
        t = re.sub(r'\.\s*\.+', '. ', t)
        t = re.sub(r'\s+', ' ', t).strip()
        if t and t[0].isalpha() and t[0].islower():
            t = t[0].upper() + t[1:]
        if t and not t.endswith(('.', '!', '?')):
            t = t.rstrip(',;:') + "."
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
            elif "leda" in voice_lower:
                return "vi-VN-HoaiMyNeural-sweet"
            elif "zephyr" in voice_lower:
                return "vi-VN-HoaiMyNeural-energetic"
            elif "callirrhoe" in voice_lower:
                return "vi-VN-HoaiMyNeural-drama"
            elif "puck" in voice_lower:
                return "vi-VN-NamMinhNeural-energetic"
            elif "charon" in voice_lower:
                return "vi-VN-NamMinhNeural-story"
            elif "fenrir" in voice_lower:
                return "vi-VN-NamMinhNeural-heroic"
            elif "orus" in voice_lower:
                return "vi-VN-NamMinhNeural-documentary"
            elif "enceladus" in voice_lower:
                return "vi-VN-NamMinhNeural"
            return "vi-VN-HoaiMyNeural"
        else:
            if "aoede" in voice_lower:
                return "en-US-JennyNeural"
            elif "kore" in voice_lower or "leda" in voice_lower or "callirrhoe" in voice_lower:
                return "en-US-AriaNeural"
            elif "zephyr" in voice_lower:
                return "en-GB-SoniaNeural"
            elif "puck" in voice_lower:
                return "en-US-GuyNeural"
            elif "charon" in voice_lower or "orus" in voice_lower or "enceladus" in voice_lower:
                return "en-US-ChristopherNeural"
            elif "fenrir" in voice_lower:
                return "en-GB-RyanNeural"
            return "en-US-JennyNeural"

    def _apply_voice_persona_dsp(self, audio_path: str, persona_suffix: str, boundaries: list) -> None:
        """
        Applies high-precision FFmpeg acoustic formant/pitch/tempo shaping (`asetrate` + `aresample` + `atempo`)
        after synthesis so each Vietnamese voice persona (-story, -energetic, -heroic, -sweet, -drama,
        -documentary, -commercial, -elder, -fast) has a distinct, natural vocal timbre and pacing
        without triggering Microsoft SSML prosody rejections.
        """
        if not persona_suffix or not os.path.exists(audio_path):
            return

        # Define pitch_ratio (1.0 = original pitch) and speed_ratio (1.0 = original speed)
        # In FFmpeg: asetrate=24000*pitch_ratio shifts pitch AND speed by pitch_ratio;
        # then atempo=speed_ratio/pitch_ratio restores/sets exact final speaking tempo!
        profiles = {
            "-story":       {"pitch": 0.965, "speed": 0.96, "eq": "bass=g=2.5:f=140"},
            "-energetic":   {"pitch": 1.055, "speed": 1.00, "eq": "treble=g=2.0:f=3500"},
            "-heroic":      {"pitch": 0.915, "speed": 0.96, "eq": "bass=g=4.0:f=120"},
            "-sweet":       {"pitch": 1.040, "speed": 0.98, "eq": "treble=g=2.5:f=4000"},
            "-drama":       {"pitch": 0.945, "speed": 0.96, "eq": "bass=g=3.0:f=130"},
            "-documentary": {"pitch": 0.950, "speed": 0.98, "eq": "bass=g=2.0:f=150,treble=g=1.5:f=3500"},
            "-commercial":  {"pitch": 1.015, "speed": 1.00, "eq": "treble=g=2.5:f=3200"},
            "-elder":       {"pitch": 0.895, "speed": 0.93, "eq": "bass=g=3.5:f=130"},
            "-fast":        {"pitch": 1.010, "speed": 1.05, "eq": "treble=g=1.5:f=3500"},
        }
        prof = profiles.get(persona_suffix)
        if not prof:
            return

        pitch_r = prof["pitch"]
        speed_r = prof["speed"]
        atempo_r = round(speed_r / pitch_r, 4)
        atempo_r = max(0.5, min(2.0, atempo_r))
        new_srate = int(24000 * pitch_r)
        af_chain = f"asetrate={new_srate},aresample=24000,atempo={atempo_r}"
        if prof.get("eq"):
            af_chain += f",{prof['eq']}"

        dsp_out = f"{audio_path}.persona.mp3"
        cmd = [
            FFMPEG_PATH, "-y",
            "-i", str(audio_path),
            "-filter:a", af_chain,
            "-ar", "24000",
            "-ac", "1",
            "-b:a", "48k",
            str(dsp_out)
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and os.path.exists(dsp_out) and os.path.getsize(dsp_out) > 500:
            shutil.move(dsp_out, audio_path)
            if boundaries and abs(speed_r - 1.0) > 0.005:
                for b in boundaries:
                    b["start"] = round(b["start"] / speed_r, 2)
                    b["end"] = round(b["end"] / speed_r, 2)
        else:
            if os.path.exists(dsp_out):
                try:
                    os.remove(dsp_out)
                except Exception:
                    pass

    async def _try_edge_tts(self, text: str, output_audio_path: str, voice: str, rate: str, pitch: str, max_retries: int = 5):
        """Attempts Edge-TTS synthesis for the specified voice with robust retry, backoff, and pitch normalization."""
        last_err = None
        is_vi = "vi-" in (voice or "").lower()
        effective_rate = "+0%" if is_vi else rate
        effective_pitch = "+0Hz" if is_vi else pitch

        for attempt in range(max_retries):
            # Clean partial or corrupt audio file before attempt
            if os.path.exists(output_audio_path):
                try:
                    os.remove(output_audio_path)
                except Exception:
                    pass

            try:
                # If earlier attempts failed with custom pitch/rate, fallback to neutral pitch/rate on same voice
                use_rate = effective_rate if attempt < 2 else "+0%"
                use_pitch = effective_pitch if attempt < 2 else "+0Hz"
                comm = edge_tts.Communicate(text, voice, rate=use_rate, pitch=use_pitch, connect_timeout=15, receive_timeout=60)
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
                if os.path.exists(output_audio_path):
                    try:
                        os.remove(output_audio_path)
                    except Exception:
                        pass
                if attempt < max_retries - 1:
                    backoff = (attempt + 1) * 1.5
                    print(f"Edge-TTS attempt {attempt + 1} for '{voice}' encountered temporary network/server notice: {e}. Retrying same voice in {backoff:.1f}s...")
                    await asyncio.sleep(backoff)
                    continue
                raise last_err

    async def _synthesize_by_sentences(self, text: str, output_audio_path: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz") -> list:
        """
        Splits text into individual sentences (or clauses) and synthesizes each separately
        on the EXACT SAME voice, then stitches them using FFmpeg.
        Resolves buffer drops on long narration paragraphs while guaranteeing 100% voice consistency.
        """
        raw_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
        if len(raw_sentences) <= 1:
            # Also split on commas if it's a single multi-clause sentence
            raw_sentences = [s.strip() for s in re.split(r',\s+', text) if s.strip()]
            if len(raw_sentences) <= 1:
                return []

        temp_files = []
        all_boundaries = []
        cumulative_time = 0.0

        try:
            for s_idx, sent in enumerate(raw_sentences):
                if not sent.endswith(('.', '!', '?')):
                    sent = sent.rstrip(',;:') + "."
                temp_s_path = f"{output_audio_path}.part_{s_idx}.mp3"
                temp_files.append(temp_s_path)
                s_bounds = await self._try_edge_tts(sent, temp_s_path, voice, rate, pitch, max_retries=6)
                sent_dur = self.get_audio_duration(temp_s_path)
                for b in s_bounds:
                    all_boundaries.append({
                        "start": round(b["start"] + cumulative_time, 2),
                        "end": round(b["end"] + cumulative_time, 2),
                        "text": b["text"]
                    })
                cumulative_time += sent_dur
                await asyncio.sleep(0.3)

            norm_clauses = [f"[{i}:a]aformat=sample_rates=24000:channel_layouts=mono[a{i}]" for i in range(len(temp_files))]
            filter_inputs = "".join(f"[a{i}]" for i in range(len(temp_files)))
            filter_str = ";".join(norm_clauses) + f";{filter_inputs}concat=n={len(temp_files)}:v=0:a=1[outa]"
            cmd = [FFMPEG_PATH, "-y"]
            for tf in temp_files:
                cmd.extend(["-i", tf])
            cmd.extend(["-filter_complex", filter_str, "-map", "[outa]", "-b:a", "192k", output_audio_path])
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0 or not os.path.exists(output_audio_path) or os.path.getsize(output_audio_path) == 0:
                raise RuntimeError(f"FFmpeg sentence concat failed: {proc.stderr}")
            return all_boundaries
        finally:
            for tf in temp_files:
                if os.path.exists(tf):
                    try:
                        os.remove(tf)
                    except Exception:
                        pass

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
                    contents=f"Read this animation scene narration clearly, naturally, and at a steady normal speaking speed (never rushed) without extra commentary:\n\n{text}",
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

    async def synthesize_multivoice(
        self,
        dialogues: Optional[List[Dict[str, Any]]] = None,
        narration: str = "",
        character_voices: Optional[Dict[str, str]] = None,
        output_audio_path: str = "scene.mp3",
        output_srt_path: Optional[str] = None,
        default_voice: Optional[str] = None,
        api_key: Optional[str] = None,
        max_duration: Optional[float] = None,
        pause_gap: float = 0.25,
        include_narrator: bool = True
    ) -> dict:
        """
        Synthesizes multi-voice character dialogues for a scene.
        Each speaker segment is voiced by their assigned character voice persona,
        concatenated with natural speech pauses (pause_gap), and merged into
        a single cohesive scene audio track with synchronized rhythmic subtitles.
        """
        output_audio_path = str(output_audio_path)
        parent_dir = os.path.dirname(output_audio_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        def_voice = default_voice or self.default_voice
        char_voices = dict(character_voices or {})

        # Resolve dialogue segments
        segments = []
        if dialogues and isinstance(dialogues, list):
            for d in dialogues:
                if isinstance(d, dict) and d.get("text", "").strip():
                    segments.append({
                        "speaker": d.get("speaker", "Narrator").strip(),
                        "text": d.get("text", "").strip()
                    })

        if not segments and narration:
            try:
                from backend.agents.script_agent import ScriptAgent
                segments = ScriptAgent.extract_scene_dialogue_segments(
                    narration,
                    characters=list(char_voices.keys()),
                    narrator_name="Narrator"
                )
            except Exception:
                segments = [{"speaker": "Narrator", "text": narration.strip()}]

        if not segments:
            segments = [{"speaker": "Narrator", "text": narration.strip() or "Scene action."}]

        all_segments = list(segments)
        if not include_narrator:
            segments = [
                s for s in segments
                if (s.get("speaker") or "").strip().lower() not in ("narrator", "người kể chuyện", "none", "")
            ]
            if not segments:
                # Scene has no character dialogue (only narrator description): generate clean silent audio
                sil_dur = 4.0
                subprocess.run([
                    FFMPEG_PATH, "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", str(sil_dur),
                    "-c:a", "libmp3lame", "-q:a", "4",
                    output_audio_path
                ], capture_output=True)
                if output_srt_path:
                    with open(output_srt_path, "w", encoding="utf-8") as srt_f:
                        srt_f.write("")
                return {
                    "audio_path": output_audio_path,
                    "srt_path": output_srt_path,
                    "duration": sil_dur,
                    "voice": def_voice,
                    "character_voices": char_voices,
                    "dialogues": all_segments,
                    "is_multivoice": True,
                    "dialogue_only_silent": True
                }

        # Voice resolver
        def get_voice_for_speaker(speaker_name: str) -> str:
            spk = (speaker_name or "").strip()
            if not char_voices:
                return def_voice
            if spk in char_voices:
                return char_voices[spk]
            low_spk = spk.lower()
            for k, v in char_voices.items():
                if k.lower() == low_spk:
                    return v
            for k, v in char_voices.items():
                if k.lower() in low_spk or low_spk in k.lower():
                    return v
            if low_spk == "character":
                named = [v for k, v in char_voices.items() if k.lower() not in ("narrator", "người kể chuyện", "character")]
                if named:
                    return named[0]
            return char_voices.get("Narrator") or def_voice

        # Check if single speaker / single voice needed
        voices_needed = [get_voice_for_speaker(s["speaker"]) for s in segments]
        distinct_voices = set(voices_needed)

        if len(segments) == 1 or len(distinct_voices) <= 1:
            chosen_single_voice = voices_needed[0] if voices_needed else def_voice
            combined_text = " ".join(s["text"] for s in segments) if len(segments) > 1 else segments[0]["text"]
            res = await self.synthesize(
                text=combined_text,
                output_audio_path=output_audio_path,
                output_srt_path=output_srt_path,
                voice=chosen_single_voice,
                api_key=api_key,
                allow_voice_fallback=True,
                max_duration=max_duration,
                enable_multivoice=False
            )
            res["dialogues"] = all_segments
            res["character_voices"] = char_voices
            res["is_multivoice"] = False
            return res

        # Multi-voice synthesis flow
        temp_dir = f"{output_audio_path}.multivoice_temp"
        os.makedirs(temp_dir, exist_ok=True)
        temp_files = []
        sil_file = os.path.join(temp_dir, "speech_gap.mp3")

        try:
            # Generate silence gap matching 24kHz mono speech streams
            if pause_gap > 0:
                subprocess.run([
                    FFMPEG_PATH, "-y",
                    "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", str(pause_gap),
                    "-c:a", "libmp3lame", "-b:a", "192k",
                    sil_file
                ], capture_output=True)

            all_cues = []
            current_time = 0.0

            for idx, seg in enumerate(segments):
                seg_spk = seg["speaker"]
                seg_text = seg["text"]
                seg_voice = get_voice_for_speaker(seg_spk)
                part_audio = os.path.join(temp_dir, f"part_{idx}.mp3")
                part_srt = os.path.join(temp_dir, f"part_{idx}.srt")

                # Synthesize individual segment
                res = await self.synthesize(
                    text=seg_text,
                    output_audio_path=part_audio,
                    output_srt_path=part_srt,
                    voice=seg_voice,
                    api_key=api_key,
                    allow_voice_fallback=True,
                    enable_multivoice=False
                )
                part_dur = res.get("duration") or self.get_audio_duration(part_audio)

                # Subtitle cues with exact time offset
                cues = self._chunk_text_into_rhythmic_cues(seg_text, current_time, current_time + part_dur)
                all_cues.extend(cues)

                temp_files.append(part_audio)
                current_time += part_dur

                if idx < len(segments) - 1 and pause_gap > 0 and os.path.exists(sil_file):
                    temp_files.append(sil_file)
                    current_time += pause_gap

                # Pacing between Edge-TTS requests
                await asyncio.sleep(0.4)

            # Concatenate with FFmpeg (normalize sample rate & channels across all parts and gaps)
            inputs = []
            for tf in temp_files:
                inputs.extend(["-i", str(tf)])
            norm_clauses = [f"[{i}:a]aformat=sample_rates=24000:channel_layouts=mono[a{i}]" for i in range(len(temp_files))]
            filter_inputs = "".join(f"[a{i}]" for i in range(len(temp_files)))
            filter_complex = ";".join(norm_clauses) + f";{filter_inputs}concat=n={len(temp_files)}:v=0:a=1[aout]"

            concat_cmd = [
                FFMPEG_PATH, "-y",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "[aout]",
                "-b:a", "192k",
                output_audio_path
            ]
            proc = subprocess.run(concat_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                raise RuntimeError(f"Multi-voice audio concat failed: {proc.stderr}")

            duration = self.get_audio_duration(output_audio_path)

            # Write combined SRT
            if output_srt_path:
                output_srt_path = str(output_srt_path)
                parent_srt = os.path.dirname(output_srt_path)
                if parent_srt:
                    os.makedirs(parent_srt, exist_ok=True)
                with open(output_srt_path, "w", encoding="utf-8") as srt_file:
                    for c_idx, cue in enumerate(all_cues, 1):
                        s_str = self._format_srt_timestamp(cue["start"])
                        e_str = self._format_srt_timestamp(cue["end"])
                        srt_file.write(f"{c_idx}\n{s_str} --> {e_str}\n{cue['text']}\n\n")

            return {
                "audio_path": output_audio_path,
                "srt_path": output_srt_path,
                "duration": duration,
                "voice": def_voice,
                "character_voices": char_voices,
                "dialogues": all_segments,
                "is_multivoice": True
            }

        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    async def synthesize(
        self,
        text: str,
        output_audio_path: str,
        output_srt_path: str = None,
        voice: str = None,
        rate: str = "+0%",
        pitch: str = "+0Hz",
        api_key: str = None,
        allow_voice_fallback: bool = False,
        max_duration: Optional[float] = None,
        dialogues: Optional[List[Dict[str, Any]]] = None,
        character_voices: Optional[Dict[str, str]] = None,
        enable_multivoice: bool = False,
        include_narrator: bool = True
    ) -> dict:
        """
        Synthesizes scene audio and subtitles.
        When enable_multivoice is True, routes to synthesize_multivoice() to voice
        each character with distinct personas (and optionally skip Narrator when include_narrator=False).
        When single-voice narration is desired, synthesizes using ONE consistent voice.
        """
        if enable_multivoice or not include_narrator:
            return await self.synthesize_multivoice(
                dialogues=dialogues,
                narration=text,
                character_voices=character_voices,
                output_audio_path=output_audio_path,
                output_srt_path=output_srt_path,
                default_voice=voice or self.default_voice,
                api_key=api_key,
                max_duration=max_duration,
                include_narrator=include_narrator
            )

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

        # Extract tuning variants / Vietnamese persona suffixes if any
        actual_voice = selected_voice
        actual_rate = rate
        actual_pitch = pitch
        persona_suffix = None

        if selected_voice in ("gtts-vi", "gtts-vi-fast"):
            try:
                self._synthesize_with_gtts(clean_text, output_audio_path, "vi")
                if selected_voice == "gtts-vi-fast":
                    persona_suffix = "-fast"
                success = True
                boundaries = []
            except Exception as e_gtts:
                print(f"gTTS error: {e_gtts}")
        else:
            for sfx in ("-story", "-energetic", "-heroic", "-sweet", "-drama", "-documentary", "-commercial", "-elder"):
                if selected_voice and selected_voice.endswith(sfx):
                    actual_voice = selected_voice[:-len(sfx)]
                    persona_suffix = sfx
                    break

        # Vietnamese neural voices (vi-VN-*) do not support custom pitch or rate modifications
        # on Microsoft's servers and will fail with "No audio was received".
        # Enforce neutral rate and pitch for Vietnamese during Edge-TTS streaming,
        # then apply acoustic persona DSP shaping post-synthesis.
        if "vi-" in actual_voice.lower():
            actual_rate = "+0%"
            actual_pitch = "+0Hz"

        # Attempt 1: Requested Voice via Edge-TTS (with robust retries on the SAME voice)
        if not success:
            try:
                boundaries = await self._try_edge_tts(clean_text, output_audio_path, actual_voice, actual_rate, actual_pitch, max_retries=8)
                success = True
            except Exception as e:
                print(f"Edge-TTS primary voice '{actual_voice}' full text retry exhausted: {e}.")
                # Attempt 1b: Try sentence/clause synthesis on the exact SAME voice
                try:
                    print(f"Attempting sentence-by-sentence synthesis on '{actual_voice}' to preserve character voice...")
                    boundaries = await self._synthesize_by_sentences(clean_text, output_audio_path, actual_voice, actual_rate, actual_pitch)
                    if boundaries or (os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0):
                        success = True
                        print(f"Sentence-by-sentence synthesis on '{actual_voice}' succeeded!")
                except Exception as e_sent:
                    print(f"Sentence-by-sentence synthesis failed: {e_sent}")

        # Attempt 1c: Cooldown retry on the EXACT SAME voice (never switch to an alternate gender/robotic voice during scene narration!)
        if not success:
            try:
                await asyncio.sleep(2.0)
                boundaries = await self._try_edge_tts(clean_text, output_audio_path, actual_voice, "+0%", "+0Hz", max_retries=6)
                success = True
            except Exception as e_cooldown:
                print(f"Cooldown retry on '{actual_voice}' failed: {e_cooldown}")

        # If allow_voice_fallback is explicitly enabled (e.g. audition probe only)
        if not success and allow_voice_fallback:
            alt_voice = None
            voice_lower = selected_voice.lower()
            if "hoaimy" in voice_lower:
                alt_voice = "vi-VN-NamMinhNeural"
            elif "namminh" in voice_lower:
                alt_voice = "vi-VN-HoaiMyNeural"
            elif "vi-" in voice_lower:
                alt_voice = "gtts-vi"
            elif "en-" in voice_lower:
                alt_voice = "en-US-JennyNeural" if "jenny" not in voice_lower else "en-US-ChristopherNeural"

            if alt_voice:
                try:
                    boundaries = await self._try_edge_tts(clean_text, output_audio_path, alt_voice, "+0%", "+0Hz", max_retries=3)
                    selected_voice = alt_voice
                    success = True
                    is_fallback = True
                    print(f"Audition fallback synthesized with '{alt_voice}'.")
                except Exception as e_alt:
                    print(f"Alt voice '{alt_voice}' failed: {e_alt}")

            if not success:
                try:
                    self._synthesize_with_gtts(clean_text, output_audio_path, lang_code)
                    selected_voice = f"gtts-{lang_code}"
                    success = True
                    is_fallback = True
                    boundaries = []
                    print(f"Safety fallback synthesized with Google TTS ({lang_code}).")
                except Exception as e3:
                    raise RuntimeError(f"All TTS voice engines failed: {e3}")

        if not success:
            raise RuntimeError(f"Voice synthesis failed for voice '{selected_voice}' after all retries.")

        # Apply acoustic persona DSP shaping if a persona variant (-story, -energetic, -heroic, -sweet, -elder, etc.) was selected
        if persona_suffix:
            self._apply_voice_persona_dsp(output_audio_path, persona_suffix, boundaries)

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
