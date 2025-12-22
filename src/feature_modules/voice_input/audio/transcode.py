import os
import shutil
import subprocess

def _ffmpeg_bin() -> str:
    exe = os.getenv("FFMPEG_BIN", "ffmpeg")
    if not shutil.which(exe):
        raise RuntimeError("ffmpeg not found on PATH. Install ffmpeg or set FFMPEG_BIN to the full path.")
    return exe

def to_wav_16k_mono(audio_bytes: bytes) -> bytes:
    """
    Optional fallback: use ffmpeg to ensure WAV PCM s16le 16kHz mono.
    Only used if STT_FORCE_WAV=true or if OpenAI rejects the original.
    """
    exe = _ffmpeg_bin()
    proc = subprocess.run(
        [
            exe, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",
            "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", "-f", "wav", "pipe:1",
        ],
        input=audio_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        err = (proc.stderr or b"").decode(errors="ignore")[:300]
        raise RuntimeError(f"ffmpeg failed to transcode audio. {err}")
    return proc.stdout
