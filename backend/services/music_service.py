import math
import wave
import struct
import subprocess
from pathlib import Path
from backend.config import FFMPEG_PATH

class MusicService:
    @staticmethod
    def generate_ambient_track(output_path: str, duration: float = 30.0, style: str = "whimsical") -> str:
        """
        Synthesizes a pleasant ambient background track using acoustic chord tones.
        Ensures videos have subtle emotional musical atmosphere without copyright issues.
        """
        output_path = str(output_path)
        wav_path = output_path.replace(".mp3", ".wav")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        sample_rate = 22050
        total_samples = int(sample_rate * duration)

        # Chords defined by frequencies (Hz)
        # Sequence: Cmaj9 -> Am9 -> Fmaj7 -> Gadd9
        chord_progression = [
            [261.63, 329.63, 392.00, 493.88, 587.33], # Cmaj9
            [220.00, 261.63, 329.63, 392.00, 493.88], # Am9
            [174.61, 220.00, 261.63, 329.63, 392.00], # Fmaj7
            [196.00, 246.94, 293.66, 392.00, 440.00], # G6
        ]

        chord_dur = 4.0  # 4 seconds per chord

        with wave.open(wav_path, "w") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)

            raw_data = bytearray()
            for n in range(total_samples):
                t = n / float(sample_rate)
                chord_idx = int(t / chord_dur) % len(chord_progression)
                chord_time = t % chord_dur
                chord = chord_progression[chord_idx]

                sample = 0.0
                # Sum harmonics for a soft bell/celeste timbre
                for freq in chord:
                    # Exponential decay envelope
                    env = math.exp(-1.4 * chord_time) + 0.12 * math.sin(math.pi * (chord_time / chord_dur))
                    # Fundamental + soft octave overtone
                    tone = math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(4 * math.pi * freq * t)
                    sample += tone * env

                # Gentle master normalization and soft limiter
                sample = (sample / len(chord)) * 0.28
                sample = max(-0.95, min(0.95, sample))
                ival = int(sample * 32767.0)
                raw_data.extend(struct.pack("<h", ival))

            wav_file.writeframes(raw_data)

        # Convert WAV to MP3 using FFmpeg
        try:
            cmd = [
                FFMPEG_PATH, "-y", "-i", wav_path,
                "-ac", "2", "-b:a", "128k",
                output_path
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            if Path(wav_path).exists() and wav_path != output_path:
                Path(wav_path).unlink()
        except Exception:
            return wav_path

        return output_path
