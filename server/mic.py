import asyncio
import io
import logging
import wave

import numpy as np

log = logging.getLogger("jarvis.mic")

SAMPLE_RATE   = 16000
SILENCE_RMS   = 350       # below this = silence
SILENCE_SEC   = 1.4       # seconds of silence to stop
MAX_SEC       = 9.0       # max recording time
MIN_SEC       = 0.4       # minimum to count as speech
CHUNK_MS      = 80        # ms per chunk


async def record_command() -> bytes:
    """Record one command from PC mic. Returns WAV bytes or b'' on failure."""
    try:
        import sounddevice as sd
    except ImportError:
        log.error("sounddevice no instalado")
        return b""

    chunk_size    = int(SAMPLE_RATE * CHUNK_MS / 1000)
    max_chunks    = int(MAX_SEC * 1000 / CHUNK_MS)
    silence_limit = int(SILENCE_SEC * 1000 / CHUNK_MS)
    min_chunks    = int(MIN_SEC * 1000 / CHUNK_MS)

    loop = asyncio.get_event_loop()
    q: asyncio.Queue = asyncio.Queue()

    def _cb(indata, frames, t, status):
        loop.call_soon_threadsafe(q.put_nowait, indata.copy())

    chunks:      list = []
    silent_count: int = 0
    recording:   bool = False

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=chunk_size, callback=_cb):
            log.info("PC mic: grabando (max %.0fs)...", MAX_SEC)
            while len(chunks) < max_chunks:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=MAX_SEC)
                except asyncio.TimeoutError:
                    break

                rms = int(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                is_speech = rms > SILENCE_RMS

                if is_speech:
                    recording = True
                    silent_count = 0
                    chunks.append(chunk)
                elif recording:
                    chunks.append(chunk)
                    silent_count += 1
                    if silent_count >= silence_limit:
                        break
    except Exception as e:
        log.error("PC mic error: %s", e)
        return b""

    if len(chunks) < min_chunks:
        log.info("PC mic: audio muy corto, ignorando")
        return b""

    audio = np.concatenate(chunks, axis=0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    log.info("PC mic: %.1fs de audio grabado", len(chunks) * CHUNK_MS / 1000)
    return buf.getvalue()
