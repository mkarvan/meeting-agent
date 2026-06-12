"""Tests for the audio capture module with mocked subprocess."""
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
from src.audio.capture import AudioCapture


class TestAudioCapture:
    """Tests for AudioCapture class."""

    @pytest.fixture
    def capture(self):
        with patch("src.audio.capture.subprocess") as mock_subprocess:
            instance = AudioCapture()
            instance._subprocess_mock = mock_subprocess
            instance.chunk_dir = Path("/tmp/test-chunks")
            instance.chunk_dir.mkdir(parents=True, exist_ok=True)
            yield instance
            # Cleanup
            if instance.chunk_dir.exists():
                import shutil
                shutil.rmtree(instance.chunk_dir, ignore_errors=True)

    def test_init_creates_chunk_dir(self):
        """Init should create the audio chunk directory."""
        with patch("src.audio.capture.subprocess"):
            with patch("src.audio.capture.settings") as mock_settings:
                mock_settings.audio_dir = Path("/tmp/test-audio-capture")
                mock_settings.sample_rate = 16000
                mock_settings.chunk_duration = 30

                cap = AudioCapture()
                assert cap.chunk_dir.exists()
                assert cap._current_chunk == 0
                assert cap._process is None

                # Cleanup
                import shutil
                shutil.rmtree(cap.chunk_dir, ignore_errors=True)

    def test_monitor_source(self, capture):
        """monitor_source should return the configured device."""
        with patch("src.audio.capture.settings") as mock_settings:
            mock_settings.audio_device = "test-sink.monitor"
            assert capture.monitor_source == "test-sink.monitor"

    def test_start_launches_ffmpeg(self, capture):
        """Start should spawn an FFmpeg subprocess."""
        mock_popen = capture._subprocess_mock.Popen
        capture.start()
        mock_popen.assert_called_once()

        # Check ffmpeg command args
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-f" in cmd
        assert "pulse" in cmd
        assert "-ac" in cmd
        assert "1" in cmd  # mono
        assert "-ar" in cmd
        assert "16000" in cmd  # sample rate

    def test_start_uses_segment_output(self, capture):
        """FFmpeg should use segment muxer for chunked output."""
        mock_popen = capture._subprocess_mock.Popen
        capture.start()
        cmd = mock_popen.call_args[0][0]
        # Find the *second* "-f" which should be followed by "segment"
        indices = [i for i, v in enumerate(cmd) if v == "-f"]
        assert len(indices) >= 2, f"Expected at least 2 '-f' flags, got: {cmd}"
        segment_idx = indices[1] + 1
        assert cmd[segment_idx] == "segment"

    def test_get_new_chunks_waits_for_files(self, capture):
        """get_new_chunks should yield files as they appear."""
        # Create a test chunk file
        chunk_file = capture.chunk_dir / "chunk_00000.wav"
        chunk_file.write_text("fake wav data")

        # Stop after first chunk by breaking the loop manually
        gen = capture.get_new_chunks()
        first_chunk = next(gen)
        assert first_chunk == chunk_file
        assert capture._current_chunk == 1

    def test_get_new_chunks_sequential(self, capture):
        """Multiple chunks should be yielded in order."""
        chunk0 = capture.chunk_dir / "chunk_00000.wav"
        chunk0.write_text("chunk 0")
        chunk1 = capture.chunk_dir / "chunk_00001.wav"
        chunk1.write_text("chunk 1")

        gen = capture.get_new_chunks()
        assert next(gen) == chunk0
        assert capture._current_chunk == 1
        assert next(gen) == chunk1
        assert capture._current_chunk == 2

    def test_cleanup_chunk_deletes_file(self, capture):
        """cleanup_chunk should delete the WAV file."""
        chunk_file = capture.chunk_dir / "test.wav"
        chunk_file.write_text("data")

        with patch("src.audio.capture.settings") as mock_settings:
            mock_settings.keep_audio = False
            capture.cleanup_chunk(chunk_file)
            assert not chunk_file.exists()

    def test_cleanup_chunk_respects_keep_audio(self, capture):
        """cleanup_chunk should NOT delete if keep_audio is True."""
        chunk_file = capture.chunk_dir / "test_keep.wav"
        chunk_file.write_text("data")

        with patch("src.audio.capture.settings") as mock_settings:
            mock_settings.keep_audio = True
            capture.cleanup_chunk(chunk_file)
            assert chunk_file.exists()

        # Cleanup manually
        chunk_file.unlink()

    def test_cleanup_chunk_handles_missing_file(self, capture):
        """cleanup_chunk should not raise for missing files."""
        missing_file = capture.chunk_dir / "does_not_exist.wav"
        # Should not raise
        capture.cleanup_chunk(missing_file)

    def test_cleanup_all_removes_directory(self, capture):
        """cleanup_all should remove the entire chunk directory."""
        test_dir = Path("/tmp/test-cleanup-dir")
        test_dir.mkdir(exist_ok=True)
        (test_dir / "test.wav").write_text("data")
        capture.chunk_dir = test_dir

        with patch("src.audio.capture.settings") as mock_settings:
            mock_settings.keep_audio = False
            capture.cleanup_all()
            assert not test_dir.exists()

    def test_cleanup_all_respects_keep_audio(self, capture):
        """cleanup_all should NOT remove directory if keep_audio is True."""
        test_dir = Path("/tmp/test-keep-dir")
        test_dir.mkdir(exist_ok=True)
        (test_dir / "test.wav").write_text("data")
        capture.chunk_dir = test_dir

        with patch("src.audio.capture.settings") as mock_settings:
            mock_settings.keep_audio = True
            capture.cleanup_all()
            assert test_dir.exists()

        # Cleanup manually
        import shutil
        shutil.rmtree(test_dir, ignore_errors=True)

    def test_stop_terminates_process(self, capture):
        """Stop should terminate the FFmpeg process."""
        mock_process = MagicMock()
        capture._process = mock_process

        capture.stop()

        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once()
        assert capture._process is None

    def test_stop_handles_no_process(self, capture):
        """Stop should not crash if no process is running."""
        capture._process = None
        capture.stop()  # Should not raise
