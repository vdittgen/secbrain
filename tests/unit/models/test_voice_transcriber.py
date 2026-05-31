"""Unit tests for VoiceTranscriber.

Tests cover the dual-backend transcriber API (Qwen3-ASR + faster-whisper
fallback), lazy loading, graceful degradation, and the CLI command for
audio transcription.
"""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# is_available() / is_qwen_asr_available() / is_whisper_available()
# ---------------------------------------------------------------------------


def test_is_available_qwen_only():
    """is_available returns True when only mlx-qwen3-asr is installed."""
    with patch.dict("sys.modules", {"mlx_qwen3_asr": MagicMock()}):
        from src.models.voice_transcriber import is_available
        assert is_available() is True


def test_is_available_whisper_only():
    """is_available returns True when only faster-whisper is installed."""
    with (
        patch.dict("sys.modules", {"mlx_qwen3_asr": None}),
        patch.dict("sys.modules", {"faster_whisper": MagicMock()}),
    ):
        from src.models.voice_transcriber import is_available
        assert is_available() is True


def test_is_available_neither():
    """is_available returns False when no backend is installed."""
    with (
        patch.dict("sys.modules", {"mlx_qwen3_asr": None}),
        patch.dict("sys.modules", {"faster_whisper": None}),
    ):
        from src.models.voice_transcriber import is_available
        assert is_available() is False


def test_is_qwen_asr_available_true():
    """is_qwen_asr_available returns True when mlx-qwen3-asr is installed."""
    with patch.dict("sys.modules", {"mlx_qwen3_asr": MagicMock()}):
        from src.models.voice_transcriber import is_qwen_asr_available
        assert is_qwen_asr_available() is True


def test_is_qwen_asr_available_false():
    """is_qwen_asr_available returns False when not installed."""
    with patch.dict("sys.modules", {"mlx_qwen3_asr": None}):
        from src.models.voice_transcriber import is_qwen_asr_available
        assert is_qwen_asr_available() is False


def test_is_whisper_available_true():
    """is_whisper_available returns True when faster-whisper is installed."""
    with patch.dict("sys.modules", {"faster_whisper": MagicMock()}):
        from src.models.voice_transcriber import is_whisper_available
        assert is_whisper_available() is True


def test_is_whisper_available_false():
    """is_whisper_available returns False when not installed."""
    with patch.dict("sys.modules", {"faster_whisper": None}):
        from src.models.voice_transcriber import is_whisper_available
        assert is_whisper_available() is False


# ---------------------------------------------------------------------------
# VoiceTranscriber
# ---------------------------------------------------------------------------


class TestVoiceTranscriber:
    """Tests for VoiceTranscriber class."""

    def test_init_defaults(self):
        """Default model size is 'base' with int8 compute."""
        from src.models.voice_transcriber import VoiceTranscriber
        t = VoiceTranscriber()
        assert t._model_size == "base"
        assert t._compute_type == "int8"
        assert t._model is None
        assert t._session is None
        assert t._backend is None

    def test_init_custom_params(self):
        """Custom model size and compute type are stored."""
        from src.models.voice_transcriber import VoiceTranscriber
        t = VoiceTranscriber(model_size="tiny", compute_type="float32")
        assert t._model_size == "tiny"
        assert t._compute_type == "float32"

    def test_transcribe_file_not_found(self):
        """transcribe raises FileNotFoundError for missing files."""
        from src.models.voice_transcriber import VoiceTranscriber
        t = VoiceTranscriber()
        with pytest.raises(FileNotFoundError):
            t.transcribe("/nonexistent/audio.wav")

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_qwen_backend(self, mock_ensure):
        """transcribe routes to Qwen backend when available."""
        from src.models.voice_transcriber import (
            BACKEND_QWEN,
            TranscriptionResult,
            VoiceTranscriber,
        )

        mock_result = MagicMock()
        mock_result.text = " Hello world "
        mock_result.language = "en"
        mock_result.segments = None
        mock_result.duration = 1.5

        mock_session = MagicMock()
        mock_session.transcribe.return_value = mock_result
        mock_ensure.return_value = mock_session

        t = VoiceTranscriber()
        t._backend = BACKEND_QWEN
        t._session = mock_session

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake audio data")
            tmp_path = f.name

        try:
            result = t.transcribe(tmp_path)
            assert isinstance(result, TranscriptionResult)
            assert result.text == "Hello world"
            assert result.language == "en"
            assert result.duration == 1.5
            assert len(result.segments) == 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_qwen_with_segments(self, mock_ensure):
        """Qwen backend correctly maps segments when available."""
        from src.models.voice_transcriber import (
            BACKEND_QWEN,
            VoiceTranscriber,
        )

        seg1 = MagicMock(start=0.0, end=1.0, text=" Hello ")
        seg2 = MagicMock(start=1.0, end=2.5, text=" world ")

        mock_result = MagicMock()
        mock_result.text = " Hello world "
        mock_result.language = "pt"
        mock_result.segments = [seg1, seg2]

        mock_session = MagicMock()
        mock_session.transcribe.return_value = mock_result
        mock_ensure.return_value = mock_session

        t = VoiceTranscriber()
        t._backend = BACKEND_QWEN
        t._session = mock_session

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            result = t.transcribe(tmp_path)
            assert result.text == "Hello world"
            assert result.language == "pt"
            assert result.duration == 2.5
            assert len(result.segments) == 2
            assert result.segments[0].text == "Hello"
            assert result.segments[1].text == "world"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_qwen_list_result(self, mock_ensure):
        """Qwen backend handles list result (batch API)."""
        from src.models.voice_transcriber import (
            BACKEND_QWEN,
            VoiceTranscriber,
        )

        mock_result = MagicMock()
        mock_result.text = "Test"
        mock_result.language = "en"
        mock_result.segments = None
        mock_result.duration = 0.5

        mock_session = MagicMock()
        mock_session.transcribe.return_value = [mock_result]
        mock_ensure.return_value = mock_session

        t = VoiceTranscriber()
        t._backend = BACKEND_QWEN
        t._session = mock_session

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            result = t.transcribe(tmp_path)
            assert result.text == "Test"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_whisper_fallback(self, mock_ensure):
        """transcribe routes to Whisper backend as fallback."""
        from src.models.voice_transcriber import (
            BACKEND_WHISPER,
            TranscriptionResult,
            TranscriptionSegment,
            VoiceTranscriber,
        )

        mock_seg = MagicMock()
        mock_seg.start = 0.0
        mock_seg.end = 1.5
        mock_seg.text = " Hello world "

        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.duration = 1.5

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_seg]), mock_info)
        mock_ensure.return_value = mock_model

        t = VoiceTranscriber()
        t._backend = BACKEND_WHISPER
        t._model = mock_model

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake audio data")
            tmp_path = f.name

        try:
            result = t.transcribe(tmp_path)
            assert isinstance(result, TranscriptionResult)
            assert result.text == "Hello world"
            assert result.language == "en"
            assert result.duration == 1.5
            assert len(result.segments) == 1
            seg = result.segments[0]
            assert isinstance(seg, TranscriptionSegment)
            assert seg.text == "Hello world"
            assert seg.start == 0.0
            assert seg.end == 1.5
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_multiple_segments_whisper(self, mock_ensure):
        """Whisper fallback joins multiple segments with spaces."""
        from src.models.voice_transcriber import (
            BACKEND_WHISPER,
            VoiceTranscriber,
        )

        seg1 = MagicMock(start=0.0, end=1.0, text=" Hello ")
        seg2 = MagicMock(start=1.0, end=2.5, text=" world ")

        mock_info = MagicMock(language="pt", duration=2.5)
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([seg1, seg2]), mock_info)
        mock_ensure.return_value = mock_model

        t = VoiceTranscriber()
        t._backend = BACKEND_WHISPER
        t._model = mock_model

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            result = t.transcribe(tmp_path)
            assert result.text == "Hello world"
            assert result.language == "pt"
            assert len(result.segments) == 2
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_whisper_forwards_language(self, mock_ensure):
        """Whisper backend forwards the optional language hint."""
        from src.models.voice_transcriber import (
            BACKEND_WHISPER,
            VoiceTranscriber,
        )

        mock_seg = MagicMock(start=0.0, end=1.0, text=" hola ")
        mock_info = MagicMock(language="es", duration=1.0)
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_seg]), mock_info)
        mock_ensure.return_value = mock_model

        t = VoiceTranscriber()
        t._backend = BACKEND_WHISPER
        t._model = mock_model

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            t.transcribe(tmp_path, language="es")
            mock_model.transcribe.assert_called_once()
            _, kwargs = mock_model.transcribe.call_args
            assert kwargs.get("language") == "es"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_whisper_no_language_omits_kwarg(self, mock_ensure):
        """Whisper backend omits language kwarg when None (auto-detect)."""
        from src.models.voice_transcriber import (
            BACKEND_WHISPER,
            VoiceTranscriber,
        )

        mock_seg = MagicMock(start=0.0, end=1.0, text=" hi ")
        mock_info = MagicMock(language="en", duration=1.0)
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_seg]), mock_info)
        mock_ensure.return_value = mock_model

        t = VoiceTranscriber()
        t._backend = BACKEND_WHISPER
        t._model = mock_model

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            t.transcribe(tmp_path)
            _, kwargs = mock_model.transcribe.call_args
            assert "language" not in kwargs
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_qwen_forwards_language(self, mock_ensure):
        """Qwen backend forwards the language hint when accepted."""
        from src.models.voice_transcriber import (
            BACKEND_QWEN,
            VoiceTranscriber,
        )

        mock_result = MagicMock()
        mock_result.text = "hola"
        mock_result.language = "es"
        mock_result.segments = None
        mock_result.duration = 0.5

        mock_session = MagicMock()
        mock_session.transcribe.return_value = mock_result
        mock_ensure.return_value = mock_session

        t = VoiceTranscriber()
        t._backend = BACKEND_QWEN
        t._session = mock_session

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            t.transcribe(tmp_path, language="es")
            mock_session.transcribe.assert_called_once()
            _, kwargs = mock_session.transcribe.call_args
            assert kwargs.get("language") == "es"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_qwen_handles_unsupported_language_kwarg(
        self, mock_ensure
    ):
        """Qwen backend falls back to no-hint if the session rejects the kwarg."""
        from src.models.voice_transcriber import (
            BACKEND_QWEN,
            VoiceTranscriber,
        )

        mock_result = MagicMock()
        mock_result.text = "hi"
        mock_result.language = "en"
        mock_result.segments = None
        mock_result.duration = 0.5

        def fake_transcribe(path, **kwargs):
            if "language" in kwargs:
                raise TypeError("unexpected keyword argument 'language'")
            return mock_result

        mock_session = MagicMock()
        mock_session.transcribe.side_effect = fake_transcribe
        mock_ensure.return_value = mock_session

        t = VoiceTranscriber()
        t._backend = BACKEND_QWEN
        t._session = mock_session

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            result = t.transcribe(tmp_path, language="es")
            assert result.text == "hi"
            assert mock_session.transcribe.call_count == 2
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.VoiceTranscriber._ensure_model")
    def test_transcribe_bytes(self, mock_ensure):
        """transcribe_bytes writes to temp file and transcribes."""
        from src.models.voice_transcriber import (
            BACKEND_WHISPER,
            VoiceTranscriber,
        )

        mock_seg = MagicMock(start=0.0, end=1.0, text=" Test ")
        mock_info = MagicMock(language="en", duration=1.0)
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_seg]), mock_info)
        mock_ensure.return_value = mock_model

        t = VoiceTranscriber()
        t._backend = BACKEND_WHISPER
        t._model = mock_model
        result = t.transcribe_bytes(b"fake audio bytes")
        assert result.text == "Test"
        assert result.language == "en"

    def test_ensure_model_no_backend_raises(self):
        """_ensure_model raises RuntimeError when no backend is available."""
        from src.models.voice_transcriber import VoiceTranscriber
        t = VoiceTranscriber()

        with (
            patch(
                "src.models.voice_transcriber.is_qwen_asr_available",
                return_value=False,
            ),
            patch(
                "src.models.voice_transcriber.is_whisper_available",
                return_value=False,
            ),
        ):
            with pytest.raises(RuntimeError, match="No ASR backend"):
                t._ensure_model()

    def test_ensure_model_prefers_qwen(self):
        """_ensure_model prefers Qwen when both backends are available."""
        from src.models.voice_transcriber import BACKEND_QWEN, VoiceTranscriber

        mock_session = MagicMock()
        mock_session_cls = MagicMock(return_value=mock_session)

        with (
            patch(
                "src.models.voice_transcriber.is_qwen_asr_available",
                return_value=True,
            ),
            patch(
                "src.models.voice_transcriber.is_whisper_available",
                return_value=True,
            ),
            patch.dict(
                "sys.modules",
                {"mlx_qwen3_asr": MagicMock(Session=mock_session_cls)},
            ),
        ):
            t = VoiceTranscriber()
            t._ensure_model()
            assert t._backend == BACKEND_QWEN
            assert t._session is not None
            assert t._model is None

    def test_ensure_model_falls_back_to_whisper(self):
        """_ensure_model falls back to Whisper when Qwen is unavailable."""
        from src.models.voice_transcriber import (
            BACKEND_WHISPER,
            VoiceTranscriber,
        )

        mock_whisper_model = MagicMock()
        mock_whisper_cls = MagicMock(return_value=mock_whisper_model)

        with (
            patch(
                "src.models.voice_transcriber.is_qwen_asr_available",
                return_value=False,
            ),
            patch(
                "src.models.voice_transcriber.is_whisper_available",
                return_value=True,
            ),
            patch.dict(
                "sys.modules",
                {"faster_whisper": MagicMock(WhisperModel=mock_whisper_cls)},
            ),
        ):
            t = VoiceTranscriber()
            t._ensure_model()
            assert t._backend == BACKEND_WHISPER
            assert t._model is not None
            assert t._session is None

    def test_lazy_model_loading(self):
        """Model is not loaded until first transcribe call."""
        from src.models.voice_transcriber import VoiceTranscriber
        t = VoiceTranscriber()
        assert t._model is None
        assert t._session is None
        assert t._backend is None


# ---------------------------------------------------------------------------
# TranscriptionResult and TranscriptionSegment
# ---------------------------------------------------------------------------


class TestDataClasses:
    """Tests for frozen dataclasses."""

    def test_transcription_segment_frozen(self):
        from src.models.voice_transcriber import TranscriptionSegment
        seg = TranscriptionSegment(start=0.0, end=1.5, text="hello")
        with pytest.raises(AttributeError):
            seg.text = "modified"  # type: ignore[misc]

    def test_transcription_result_frozen(self):
        from src.models.voice_transcriber import TranscriptionResult
        result = TranscriptionResult(
            text="hello",
            language="en",
            duration=1.5,
            segments=[],
        )
        with pytest.raises(AttributeError):
            result.text = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CLI command: transcribe-audio
# ---------------------------------------------------------------------------


class TestCLITranscribeAudio:
    """Tests for cmd_transcribe_audio CLI command."""

    @patch("src.models.voice_transcriber.is_available", return_value=False)
    def test_unavailable_returns_error(self, _mock):
        """CLI returns 1 when no ASR backend is installed."""
        from src.core.cli import cmd_transcribe_audio
        code = cmd_transcribe_audio("dummy_input")
        assert code == 1

    @patch("src.models.voice_transcriber.is_available", return_value=True)
    @patch("src.models.voice_transcriber.VoiceTranscriber.transcribe")
    def test_file_path_input(self, mock_transcribe, _mock_avail, capsys):
        """CLI handles file path input correctly."""
        from src.models.voice_transcriber import (
            TranscriptionResult,
            TranscriptionSegment,
        )
        mock_transcribe.return_value = TranscriptionResult(
            text="hello world",
            language="en",
            duration=1.5,
            segments=[TranscriptionSegment(start=0.0, end=1.5, text="hello world")],
        )

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(b"fake audio")
            tmp_path = f.name

        try:
            from src.core.cli import cmd_transcribe_audio
            code = cmd_transcribe_audio(tmp_path)
            assert code == 0
            output = json.loads(capsys.readouterr().out)
            assert output["text"] == "hello world"
            assert output["language"] == "en"
            assert output["duration"] == 1.5
            assert len(output["segments"]) == 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @patch("src.models.voice_transcriber.is_available", return_value=True)
    @patch("src.models.voice_transcriber.VoiceTranscriber.transcribe_bytes")
    def test_base64_input(self, mock_transcribe, _mock_avail, capsys):
        """CLI handles base64 input correctly."""
        from src.models.voice_transcriber import TranscriptionResult
        mock_transcribe.return_value = TranscriptionResult(
            text="test",
            language="pt",
            duration=0.8,
            segments=[],
        )

        audio_b64 = base64.b64encode(b"fake audio data").decode()
        from src.core.cli import cmd_transcribe_audio
        code = cmd_transcribe_audio(audio_b64)
        assert code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["text"] == "test"
        assert output["language"] == "pt"

    @patch("src.models.voice_transcriber.is_available", return_value=True)
    def test_invalid_input_returns_error(self, _mock_avail):
        """CLI returns 1 for invalid input (not a file, not base64)."""
        from src.core.cli import cmd_transcribe_audio
        code = cmd_transcribe_audio("not-a-file-and-not-base64!!!")
        assert code == 1

    @patch("src.models.voice_transcriber.is_available", return_value=True)
    @patch("src.models.voice_transcriber.VoiceTranscriber.transcribe")
    def test_language_hint_forwarded_to_transcriber(
        self, mock_transcribe, _mock_avail
    ):
        """CLI forwards --language down to VoiceTranscriber.transcribe."""
        from src.models.voice_transcriber import (
            TranscriptionResult,
        )
        mock_transcribe.return_value = TranscriptionResult(
            text="hola", language="es", duration=0.5, segments=[],
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake")
            tmp_path = f.name

        try:
            from src.core.cli import cmd_transcribe_audio
            code = cmd_transcribe_audio(tmp_path, language="es")
            assert code == 0
            mock_transcribe.assert_called_once()
            _, kwargs = mock_transcribe.call_args
            assert kwargs.get("language") == "es"
        finally:
            Path(tmp_path).unlink(missing_ok=True)
