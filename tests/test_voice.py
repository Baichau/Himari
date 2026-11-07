import threading
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from himari import voice
from himari.voice import Mic, TTS


def test_microphone_start_failure_does_not_leave_recording_enabled(monkeypatch):
    def fail_to_open(**kwargs):
        raise RuntimeError("no microphone")

    monkeypatch.setattr(voice.sd, "InputStream", fail_to_open)
    mic = Mic()
    try:
        mic.start()
    except RuntimeError as error:
        assert str(error) == "no microphone"
    else:
        raise AssertionError("microphone start should fail")
    assert not mic.rec


def test_microphone_uses_configured_device(monkeypatch):
    stream = Mock()
    load_config = Mock(return_value={
        "voice": {"microphone_device": 3},
    })
    monkeypatch.setattr(voice, "load", load_config)
    input_stream = Mock(return_value=stream)
    monkeypatch.setattr(voice.sd, "InputStream", input_stream)
    mic = Mic()
    mic.start()
    assert input_stream.call_args.kwargs["device"] == 3
    assert mic.rec
    mic._cb(np.zeros((1600, 1), dtype="float32"), 1600, None, None)
    assert load_config.call_count == 1
    mic.stop()


def test_microphone_auto_stop_callback_fires_only_once():
    on_silence = Mock()
    mic = Mic(on_silence=on_silence)
    mic.rec = True
    speech = np.full((1600, 1), 0.1, dtype="float32")
    silence = np.zeros((1600, 1), dtype="float32")

    mic._cb(speech, len(speech), None, None)
    for _ in range(mic._silence_limit_samples // len(silence) + 5):
        mic._cb(silence, len(silence), None, None)

    assert on_silence.call_count == 1


def test_push_to_talk_keeps_recording_through_pauses(monkeypatch):
    on_silence = Mock()
    stream = Mock()
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"microphone_device": None},
    })
    monkeypatch.setattr(voice.sd, "InputStream", Mock(return_value=stream))
    mic = Mic(on_silence=on_silence)
    mic.start(on_silence=None)
    speech = np.full((1600, 1), 0.1, dtype="float32")
    silence = np.zeros((1600, 1), dtype="float32")

    mic._cb(speech, len(speech), None, None)
    for _ in range(mic._silence_limit_samples // len(silence) + 5):
        mic._cb(silence, len(silence), None, None)

    assert mic.rec
    assert len(mic.buf) > 1
    assert on_silence.call_count == 0
    mic.stop()


def test_wake_word_audio_callback_uses_cached_threshold(monkeypatch):
    monitor = voice.WakeWordMonitor()
    monitor.monitoring = True
    monkeypatch.setattr(voice, "load", Mock(side_effect=AssertionError("callback read config")))
    monitor._callback(np.full((1600, 1), 0.02, dtype="float32"), 1600, None, None)

    assert len(monitor._buffer) == 1


def test_stt_loads_only_models_already_available_locally(monkeypatch):
    loader = Mock()
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=loader))
    monkeypatch.setattr(voice, "_cached_stt_model", lambda name: name)
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"stt_model": "base.en", "language": "en"},
    })
    voice.STT()
    assert loader.call_args.kwargs["local_files_only"] is True


def test_stt_finds_bundled_model_and_prefers_it_to_the_english_fallback(tmp_path, monkeypatch):
    module_dir = tmp_path / "himari"
    module_dir.mkdir()
    model_dir = tmp_path / "models" / "large-v3-turbo"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").touch()
    (model_dir / "config.json").touch()
    monkeypatch.setattr(voice, "__file__", str(module_dir / "voice.py"))
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"stt_model": "large-v3", "recognition_language": "auto"},
    })

    assert voice._cached_stt_model("large-v3-turbo") == str(model_dir)
    assert voice._preferred_stt_model() == str(model_dir)


def test_stt_prefers_bundled_multilingual_model_over_saved_english_model(tmp_path, monkeypatch):
    module_dir = tmp_path / "himari"
    module_dir.mkdir()
    model_dir = tmp_path / "models" / "large-v3-turbo"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").touch()
    (model_dir / "config.json").touch()
    monkeypatch.setattr(voice, "__file__", str(module_dir / "voice.py"))
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"stt_model": "base.en", "recognition_language": "en"},
    })

    assert voice._preferred_stt_model() == str(model_dir)


def test_tts_reports_missing_voice_without_crashing(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "APP_DIR", tmp_path)
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"tts_voice": "missing-voice", "volume": 1.0},
    })
    errors = []
    TTS(on_error=errors.append)._run("Hello.", threading.Event())
    assert len(errors) == 1
    assert "missing-voice.onnx" in errors[0]


def test_stt_prefers_multilingual_local_model(monkeypatch):
    monkeypatch.setattr(voice, "load", lambda: {"voice": {"stt_model": "base.en", "recognition_language": "ru"}})
    monkeypatch.setattr(
        voice,
        "_cached_stt_model",
        lambda name: name if name in {"large-v3", "distil-large-v3"} else None,
    )
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(
        WhisperModel=lambda *args, **kwargs: object(),
    ))
    stt = voice.STT()
    assert stt.model_name == "large-v3"
    assert stt.lang == "ru"


def test_stt_uses_cached_english_model_when_preferred_model_is_missing(monkeypatch):
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"stt_model": "large-v3", "recognition_language": "en"},
    })
    monkeypatch.setattr(
        voice,
        "_cached_stt_model",
        lambda name: "base.en" if name == "base.en" else None,
    )
    assert voice._preferred_stt_model() == "base.en"


def test_stt_reports_missing_multilingual_model_for_russian(monkeypatch):
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"stt_model": "large-v3", "recognition_language": "ru"},
    })
    monkeypatch.setattr(voice, "_cached_stt_model", lambda name: None)
    with pytest.raises(RuntimeError, match="No multilingual faster-whisper model"):
        voice._preferred_stt_model()


def test_stt_uses_automatic_language_detection_and_accuracy_options(monkeypatch):
    transcribe = Mock(return_value=([SimpleNamespace(text="recognized words")], None))
    model = SimpleNamespace(transcribe=transcribe)
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"stt_model": "base.en", "recognition_language": "auto"},
    })
    monkeypatch.setattr(
        voice,
        "_cached_stt_model",
        lambda name: name if name in {"large-v3", "base.en"} else None,
    )
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(
        WhisperModel=lambda *args, **kwargs: model,
    ))

    stt = voice.STT()
    assert stt.model_name == "large-v3"
    assert stt.lang == "auto"
    audio = np.sin(np.linspace(0, 20, 1600, dtype=np.float32)) * 0.1
    assert stt.transcribe(audio) == "recognized words"
    transcribed_audio = transcribe.call_args.args[0]
    assert isinstance(transcribed_audio, np.ndarray)
    assert transcribed_audio.dtype == np.float32
    assert transcribe.call_args.kwargs == {
        "language": None,
        "beam_size": 5,
        "best_of": 5,
        "condition_on_previous_text": False,
        "vad_filter": True,
        "vad_parameters": {"min_silence_duration_ms": 700, "speech_pad_ms": 500},
        "hallucination_silence_threshold": 2.0,
        "hotwords": "Himari, Minecraft Launcher, Minecraft, Windows, Spotify, Steam, Discord",
    }


def test_auto_language_uses_english_fallback_only_when_no_multilingual_model_is_cached(monkeypatch):
    monkeypatch.setattr(voice, "load", lambda: {
        "voice": {"stt_model": "large-v3", "recognition_language": "auto"},
    })
    monkeypatch.setattr(
        voice,
        "_cached_stt_model",
        lambda name: "base.en" if name == "base.en" else None,
    )

    assert voice._preferred_stt_model() == "base.en"


def test_normalize_audio_removes_dc_offset_and_amplifies_quiet_speech():
    audio = np.linspace(-0.02, 0.02, 1600, dtype=np.float32) + 0.25

    normalized = voice.normalize_audio(audio)

    assert normalized.dtype == np.float32
    assert normalized.flags.c_contiguous
    assert abs(float(np.mean(normalized))) < 1e-5
    assert np.max(np.abs(normalized)) == pytest.approx(0.4)
    assert np.max(np.abs(voice.normalize_audio(np.full(100, 0.25)))) == 0


@pytest.mark.parametrize(
    "recognized",
    [
        "Open Minecraft Launcher",
        "OpenMainerCraft Launcher",
        "OpenMinerCraftLauncher",
        "Please open the miner craft launcher",
    ],
)
def test_corrects_minecraft_launcher_voice_transcription(recognized):
    assert voice.correct_known_voice_commands(recognized) == "Open Minecraft Launcher"


def test_tts_prefers_language_matching_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(voice, "APP_DIR", tmp_path)
    monkeypatch.setattr(voice, "load", lambda: {"voice": {"tts_voice": "en_US-lessac-medium", "recognition_language": "ru"}})
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "ru_RU-irina-medium.onnx").write_bytes(b"x")
    (voices / "en_US-lessac-medium.onnx").write_bytes(b"x")
    tts = TTS()
    assert tts._resolve_voice_path("ru").name.startswith("ru")
