import logging
import wave, threading, re, time
from pathlib import Path
import numpy as np, sounddevice as sd
from .config import load, save, APP_DIR
log=logging.getLogger("himari.voice")
_UNSET = object()
_MINECRAFT_LAUNCHER_COMMAND = re.compile(
    r"\b(?:please\s+)?(?:open|launch|start)\s*(?:the\s*)?"
    r"(?:minecraft|mine\s*craft|miner\s*craft|mainer\s*craft)\s*launcher\b",
    re.IGNORECASE,
)


def correct_known_voice_commands(text):
    return _MINECRAFT_LAUNCHER_COMMAND.sub("Open Minecraft Launcher", text)


def _cached_stt_model(name):
    local_path = Path(name).expanduser()
    if local_path.is_dir():
        return str(local_path.resolve())
    bundled_path = Path(__file__).resolve().parents[1] / "models" / name
    if (bundled_path / "model.bin").is_file() and (bundled_path / "config.json").is_file():
        return str(bundled_path)
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return None

    snapshots = Path(HF_HUB_CACHE) / f"models--Systran--faster-whisper-{name}" / "snapshots"
    if not snapshots.is_dir():
        return None
    for snapshot in sorted(snapshots.iterdir(), reverse=True):
        if snapshot.is_dir() and (snapshot / "model.bin").is_file():
            return name
    return None


def _preferred_stt_model():
    cfg = load()["voice"]
    preferred = str(cfg.get("stt_model") or "large-v3").strip() or "large-v3"
    language = str(cfg.get("recognition_language") or cfg.get("language") or "en").lower()
    preferred_path = Path(preferred).expanduser()
    candidates = [
        preferred if preferred_path.is_dir() else "large-v3-turbo",
        "large-v3", "distil-large-v3",
        preferred,
        "large", "medium", "small", "base.en", "base", "tiny.en", "tiny",
    ]
    if language in {"", "auto"} and preferred.lower().endswith(".en"):
        candidates = [name for name in candidates if not name.lower().endswith(".en")]
        candidates.append(preferred)
    seen = set()
    for candidate in candidates:
        if candidate.lower() in seen:
            continue
        seen.add(candidate.lower())
        if (
            language not in {"", "auto"}
            and not language.startswith("en")
            and candidate.lower().endswith(".en")
        ):
            continue
        available_model = _cached_stt_model(candidate)
        if available_model:
            return available_model
    language_name = "English" if language.startswith("en") else "multilingual"
    raise RuntimeError(
        f"No {language_name} faster-whisper model is available locally. "
        "Prepare a compatible model before using speech recognition."
    )


def normalize_audio(audio):
    if audio is None:
        return np.zeros(0, dtype=np.float32)
    arr = np.asarray(audio, dtype=np.float32).reshape(-1)
    if arr.size == 0:
        return arr
    arr = np.nan_to_num(arr, copy=False)
    arr = arr - np.mean(arr, dtype=np.float64)
    peak = float(np.max(np.abs(arr)))
    if peak < 1e-5:
        return np.zeros_like(arr)
    arr *= min(0.9 / peak, 20.0)
    return np.ascontiguousarray(np.clip(arr, -1.0, 1.0), dtype=np.float32)


class STT:
    def __init__(self):
        from faster_whisper import WhisperModel
        cfg=load()["voice"]
        model_name = _preferred_stt_model()
        self.model_name = model_name
        self.model=WhisperModel(
            model_name,device="cpu",compute_type="int8",local_files_only=True)
        self.lang = str(cfg.get("recognition_language") or cfg.get("language") or "en").lower()
        if self.lang.startswith("ru"):
            self.lang = "ru"
        elif self.lang.startswith("en"):
            self.lang = "en"
        elif self.lang in {"auto",""}:
            self.lang = "auto"
    def transcribe(self,audio,sr=16000):
        audio = normalize_audio(audio)
        if audio.size == 0:
            return ""
        language = self.lang if self.lang != "auto" else None
        options = {
            "language": language,
            "beam_size": 5,
            "best_of": 5,
            "condition_on_previous_text": False,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 700, "speech_pad_ms": 500},
            "hallucination_silence_threshold": 2.0,
            "hotwords": "Himari, Minecraft Launcher, Minecraft, Windows, Spotify, Steam, Discord",
        }
        segs,info=self.model.transcribe(audio, **options)
        return " ".join(s.text.strip() for s in segs).strip()
class WakeWordMonitor:
    def __init__(self, on_detect=None, on_error=None):
        self.on_detect = on_detect
        self.on_error = on_error
        self.monitoring = False
        self.stream = None
        self.thread = None
        self._lock = threading.Lock()
        self._buffer = []
        self._last_trigger = 0.0
        self._wake_word = "Himari"
        self._stt = None
        self._energy_threshold = 0.01

    def start(self):
        if self.monitoring:
            return
        cfg = load()["voice"]
        self._wake_word = str(cfg.get("wake_word") or "Himari").strip() or "Himari"
        sensitivity = max(0.1, min(1.0, float(cfg.get("sensitivity", 0.75))))
        self._energy_threshold = max(0.003, (1.0 - sensitivity) * 0.04)
        self._stt = STT()
        self._last_trigger = 0.0
        stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype="float32",
            device=cfg.get("microphone_device"),
            callback=self._callback,
        )
        try:
            stream.start()
        except Exception:
            stream.close()
            self._stt = None
            raise
        self.stream = stream
        self.monitoring = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.monitoring = False
        if self.stream is not None:
            try:
                self.stream.stop(); self.stream.close()
            except Exception:
                pass
            self.stream = None
        self.thread = None

    def _callback(self, indata, frames, time_info, status):
        if not self.monitoring:
            return
        if status:
            return
        samples = np.asarray(indata[:, 0], dtype=np.float32)
        if samples.size == 0:
            return
        rms = float(np.sqrt(np.mean(np.square(samples))))
        if rms < self._energy_threshold:
            return
        with self._lock:
            self._buffer.append(samples)
            while len(self._buffer) > 12:
                self._buffer.pop(0)

    def _run(self):
        while self.monitoring:
            try:
                time.sleep(0.25)
                with self._lock:
                    if not self._buffer:
                        continue
                    chunk = np.concatenate(self._buffer)
                    self._buffer.clear()
                if chunk.size < 1600:
                    continue
                if self._stt is None:
                    self._stt = STT()
                text = self._stt.transcribe(chunk, sr=16000)
                if not text:
                    continue
                if re.search(rf"\b{re.escape(self._wake_word)}\b", text, flags=re.IGNORECASE):
                    now = time.monotonic()
                    if now - self._last_trigger > 4.0:
                        self._last_trigger = now
                        if self.on_detect:
                            self.on_detect(self._wake_word)
            except Exception as exc:
                if self.on_error:
                    self.on_error(f"Wake-word monitoring error: {exc}")
                break


class TTS:
    def __init__(self, on_error=None, on_finished=None):
        self._stop=threading.Event(); self._thread=None
        self._play_lock=threading.Lock(); self._synthesis_lock=threading.Lock()
        self._voice=None; self._voice_path=None
        self._on_error=on_error; self._on_finished=on_finished

    def available_voices(self):
        voices = APP_DIR / "voices"
        voices.mkdir(parents=True, exist_ok=True)
        return sorted(p.stem for p in voices.glob("*.onnx"))

    def _resolve_voice_path(self, lang=None):
        cfg=load()["voice"]
        voices_dir=APP_DIR/"voices"; voices_dir.mkdir(parents=True, exist_ok=True)
        lang_value = (lang or str(cfg.get("recognition_language") or cfg.get("language") or "en")).lower()
        available = self.available_voices()
        if not available:
            return None
        if lang_value.startswith("ru"):
            preferred = [name for name in available if "ru" in name.lower()]
        else:
            preferred = [name for name in available if "en" in name.lower()]
        if preferred:
            return voices_dir / f"{preferred[0]}.onnx"

        requested = str(cfg.get("tts_voice") or "").strip()
        if requested:
            candidate = voices_dir / f"{requested}.onnx"
            if candidate.exists():
                return candidate
        return voices_dir / f"{available[0]}.onnx"

    def speak(self,text):
        self.stop()
        stop_event=threading.Event()
        self._stop=stop_event
        self._thread=threading.Thread(target=self._run,args=(text,stop_event),daemon=True)
        self._thread.start()
    def _sentences(self,text):
        parts=re.split(r'(?<=[.!?])\s+',text.strip())
        return [p for p in parts if p.strip()]
    def _run(self,text,stop_event):
        cfg=load()["voice"]; voices=APP_DIR/"voices"; voices.mkdir(exist_ok=True)
        model = self._resolve_voice_path(cfg.get("recognition_language") or cfg.get("language") or "en")
        if model is None or not model.exists():
            available = self.available_voices()
            requested = str(cfg.get("tts_voice") or "").strip()
            if available:
                chosen = available[0]
                cfg["tts_voice"] = chosen
                save(cfg)
                model = voices / f"{chosen}.onnx"
            else:
                missing = requested or "configured voice"
                self._report_error(f"Piper voice '{missing}.onnx' not found in {voices}. Download a local English or Russian voice into that folder before speaking.")
                return
        wav=APP_DIR/f"tts_out_{threading.get_ident()}.wav"
        failed=False
        try:
            for sent in self._sentences(text):
                if stop_event.is_set(): return
                with self._synthesis_lock:
                    if stop_event.is_set(): return
                    if self._voice is None or self._voice_path != model:
                        from piper import PiperVoice
                        self._voice=PiperVoice.load(model)
                        self._voice_path=model
                    with wave.open(str(wav),"wb") as output:
                        self._voice.synthesize_wav(sent,output)
                self._play(str(wav),stop_event)
        except Exception as e:
            failed=True
            log.exception("Text-to-speech failed")
            self._report_error(str(e))
        finally:
            try: wav.unlink(missing_ok=True)
            except OSError: log.warning("Could not remove temporary speech file: %s",wav)
            if not failed and self._stop is stop_event and self._on_finished:
                self._on_finished()
    def _report_error(self,message):
        if self._on_error:
            self._on_error(message)
    def _play(self,path,stop_event):
        with wave.open(path,"rb") as w:
            sr=w.getframerate(); ch=w.getnchannels(); sw=w.getsampwidth()
            if sw==1:
                data=(np.frombuffer(w.readframes(w.getnframes()),dtype=np.uint8).astype(np.float32)-128)/128
            elif sw==2:
                data=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768
            elif sw==4:
                data=np.frombuffer(w.readframes(w.getnframes()),dtype=np.int32).astype(np.float32)/2147483648
            else:
                raise RuntimeError(f"Unsupported Piper WAV sample width: {sw} bytes")
        if ch>1: data=data.reshape(-1,ch).mean(axis=1)
        vol=max(0.0,min(1.0,float(load()["voice"].get("volume",1.0))))
        with self._play_lock:
            if stop_event.is_set(): return
            sd.play(data*vol,sr)
            while not stop_event.is_set():
                try:
                    sd.wait(timeout=50)
                    stream_getter = getattr(sd, "get_stream", None)
                    if stream_getter is not None:
                        if stream_getter() is None:
                            break
                except Exception:
                    break
            if stop_event.is_set():
                try: sd.stop()
                except Exception: pass
    def stop(self):
        self._stop.set()
        try: sd.stop()
        except Exception: pass
class Mic:
    def __init__(self, on_silence=None):
        self.rec=False; self.buf=[]; self.stream=None
        self._lock = threading.Lock()
        self._silence_samples = 0
        self._silence_notified = False
        self._on_silence = on_silence
        self._speech_started = False
        self._silence_threshold = 0.01
        self._silence_limit_samples = 24000

    def start(self, on_silence=_UNSET):
        if self.rec:
            return
        if on_silence is not _UNSET:
            self._on_silence = on_silence
        settings = load()["voice"]
        device = settings.get("microphone_device")
        with self._lock:
            self.buf = []
            self._silence_samples = 0
            self._silence_notified = False
            self._speech_started = False
            self.rec = True
        stream = None
        try:
            stream=sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                callback=self._cb,
                device=device,
            )
            self.stream = stream
            stream.start()
        except Exception:
            with self._lock:
                self.rec = False
                self.stream = None
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    log.exception("Could not close the microphone after startup failed")
            raise

    def _cb(self,ind,frames,t,status):
        samples = np.asarray(ind[:, 0], dtype=np.float32)
        if status:
            log.warning("Microphone stream reported an audio status: %s", status)
        notify = None
        with self._lock:
            if not self.rec:
                return
            self.buf.append(samples.copy())
            rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
            if rms >= self._silence_threshold:
                self._speech_started = True
                self._silence_samples = 0
            elif self._speech_started and self._on_silence is not None:
                self._silence_samples += samples.size
                if self._silence_samples >= self._silence_limit_samples and not self._silence_notified:
                    self._silence_notified = True
                    notify = self._on_silence
        if notify is not None:
            try:
                notify()
            except Exception:
                log.exception("Microphone silence callback failed")

    def stop(self):
        with self._lock:
            if not self.rec:
                return np.zeros(0, dtype=np.float32)
            self.rec = False
            stream = self.stream
            self.stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                log.exception("Could not stop the microphone stream cleanly")
            try:
                stream.close()
            except Exception:
                log.exception("Could not close the microphone stream cleanly")
        with self._lock:
            chunks, self.buf = self.buf, []
        if not chunks:
            return np.zeros(0,dtype=np.float32)
        data = np.concatenate(chunks)
        return normalize_audio(data)
