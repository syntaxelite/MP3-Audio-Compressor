from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import compressor


def create_test_mp3(path: Path) -> None:
    path.write_bytes(b"test MP3 data")


class AudioCompressorTests(unittest.TestCase):
    def test_validate_mp3_accepts_case_insensitive_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "tone.MP3"
            create_test_mp3(source)

            compressor.validate_mp3(source)

    def test_rejects_non_mp3_and_empty_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            non_mp3_file = root / "notes.txt"
            non_mp3_file.write_bytes(b"not an MP3")
            empty_mp3 = root / "empty.mp3"
            empty_mp3.touch()

            with self.assertRaisesRegex(compressor.AudioCompressorError, "Only .mp3"):
                compressor.validate_mp3(non_mp3_file)
            with self.assertRaisesRegex(compressor.AudioCompressorError, "empty"):
                compressor.validate_mp3(empty_mp3)

    def test_picker_filters_to_mp3_and_returns_selected_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory) / "tone.mp3"
            create_test_mp3(source)
            root = unittest.mock.MagicMock()

            with patch("tkinter.Tk", return_value=root):
                with patch(
                    "tkinter.filedialog.askopenfilename", return_value=str(source)
                ) as picker:
                    selected = compressor.select_mp3_file(
                        Path(temporary_directory), "Select an MP3"
                    )

            self.assertEqual(selected, source)
            self.assertEqual(
                picker.call_args.kwargs["filetypes"],
                (("MP3 audio files", "*.mp3"),),
            )
            root.withdraw.assert_called_once()
            root.destroy.assert_called_once()

    def test_picker_cancellation_returns_none(self) -> None:
        root = unittest.mock.MagicMock()
        with patch("tkinter.Tk", return_value=root):
            with patch("tkinter.filedialog.askopenfilename", return_value=""):
                self.assertIsNone(
                    compressor.select_mp3_file(Path("."), "Select an MP3")
                )

    def test_picker_rejects_manually_entered_non_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            non_mp3_file = Path(temporary_directory) / "notes.txt"
            non_mp3_file.write_bytes(b"not an MP3")
            with patch("tkinter.Tk", return_value=unittest.mock.MagicMock()):
                with patch(
                    "tkinter.filedialog.askopenfilename",
                    return_value=str(non_mp3_file),
                ):
                    with self.assertRaisesRegex(
                        compressor.AudioCompressorError, "Only .mp3"
                    ):
                        compressor.select_mp3_file(Path(temporary_directory), "Select")

    def test_metrics_use_the_measured_file_sizes(self) -> None:
        result = compressor.calculate_result(
            source=Path("source.mp3"),
            output=Path("source_128kbps.mp3"),
            bitrate_kbps=128,
            original_size=1000,
            compressed_size=400,
        )

        self.assertEqual(result.compression_ratio, 2.5)
        self.assertAlmostEqual(result.space_saved_percent, 60.0)

    def test_rejects_existing_output_before_encoding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "tone.mp3"
            output_dir = root / "output"
            output_dir.mkdir()
            existing_output = output_dir / "tone_128kbps.mp3"
            create_test_mp3(source)
            existing_output.write_bytes(b"keep this file")

            with patch("compressor.resolve_ffmpeg") as resolve_ffmpeg:
                with self.assertRaisesRegex(compressor.AudioCompressorError, "already exists"):
                    compressor.compress_mp3(source, output_dir, 128, "ffmpeg")

            self.assertEqual(source.read_bytes(), b"test MP3 data")
            self.assertEqual(existing_output.read_bytes(), b"keep this file")
            resolve_ffmpeg.assert_not_called()

    def test_reencoding_uses_lame_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "tone.mp3"
            output_dir = root / "output"
            create_test_mp3(source)
            original_data = source.read_bytes()

            def fake_run(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                self.assertEqual(
                    kwargs,
                    {"capture_output": True, "text": True, "check": False},
                )
                if "-encoders" in command:
                    return subprocess.CompletedProcess(
                        command, 0, stdout="A..... libmp3lame", stderr=""
                    )
                Path(command[-1]).write_bytes(b"re-encoded MP3 data")
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            with patch("compressor.resolve_ffmpeg", return_value="ffmpeg"):
                with patch("compressor.subprocess.run", side_effect=fake_run) as run:
                    result = compressor.compress_mp3(source, output_dir, 192, "ffmpeg")

            encode_command = run.call_args_list[1].args[0]
            self.assertIn("libmp3lame", encode_command)
            self.assertIn("192k", encode_command)
            self.assertIn("-n", encode_command)
            self.assertEqual(result.compressed_size, len(b"re-encoded MP3 data"))
            self.assertEqual(source.read_bytes(), original_data)
            self.assertTrue(result.output.name.endswith(".mp3"))

    def test_invalid_mp3_is_reported_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "invalid.mp3"
            output_dir = root / "output"
            create_test_mp3(source)
            original_data = source.read_bytes()

            def reject_input(
                command: list[str], **kwargs: object
            ) -> subprocess.CompletedProcess[str]:
                self.assertEqual(
                    kwargs,
                    {"capture_output": True, "text": True, "check": False},
                )
                if "-encoders" in command:
                    return subprocess.CompletedProcess(
                        command, 0, stdout="A..... libmp3lame", stderr=""
                    )
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr="Invalid data found when processing input"
                )

            with patch("compressor.resolve_ffmpeg", return_value="ffmpeg"):
                with patch("compressor.subprocess.run", side_effect=reject_input):
                    with self.assertRaisesRegex(
                        compressor.AudioCompressorError, "Invalid data found"
                    ):
                        compressor.compress_mp3(source, output_dir, 128, "ffmpeg")

            self.assertEqual(source.read_bytes(), original_data)
            self.assertFalse((output_dir / "invalid_128kbps.mp3").exists())

    def test_play_audio_uses_ffplay_and_rejects_non_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            audio_file = root / "sample.mp3"
            create_test_mp3(audio_file)
            completed = subprocess.CompletedProcess(["ffplay"], 0, stderr="")

            with patch("compressor.resolve_ffplay", return_value="ffplay"):
                with patch("compressor.subprocess.run", return_value=completed) as run:
                    compressor.play_audio(audio_file, "ffplay")

            command = run.call_args.args[0]
            self.assertIn("-nodisp", command)
            self.assertIn("-autoexit", command)
            self.assertNotIn("-xerror", command)
            self.assertEqual(command[-1], str(audio_file))

            non_mp3_file = root / "notes.txt"
            non_mp3_file.write_bytes(b"not an MP3")
            with self.assertRaisesRegex(compressor.AudioCompressorError, "Only .mp3"):
                compressor.play_audio(non_mp3_file, "ffplay")

    def test_source_and_compressed_menu_playback_use_ffplay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mp3"
            compressed = root / "output" / "source_128kbps.mp3"
            compressed.parent.mkdir()
            create_test_mp3(source)
            create_test_mp3(compressed)
            output = io.StringIO()
            completed = subprocess.CompletedProcess(["ffplay"], 0, stderr="")

            with patch("builtins.input", side_effect=("3", "4", "5")):
                with patch(
                    "compressor.select_mp3_file", side_effect=(source, compressed)
                ) as picker:
                    with patch("compressor.resolve_ffplay", return_value="ffplay.exe"):
                        with patch(
                            "compressor.subprocess.run", return_value=completed
                        ) as run:
                            with contextlib.redirect_stdout(output):
                                compressor.run_menu(
                                    root / "input",
                                    compressed.parent,
                                    None,
                                    None,
                                )

            self.assertEqual(picker.call_count, 2)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(
                [call.args[0][-1] for call in run.call_args_list],
                [str(source), str(compressed)],
            )
            for call in run.call_args_list:
                command = call.args[0]
                self.assertEqual(command[0], "ffplay.exe")
                self.assertIn("-nodisp", command)
                self.assertIn("-autoexit", command)
                self.assertNotIn("-xerror", command)
            self.assertEqual(output.getvalue().count("Playback finished."), 2)

    def test_source_and_compressed_playback_errors_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.mp3"
            compressed = root / "output" / "source_128kbps.mp3"
            compressed.parent.mkdir()
            create_test_mp3(source)
            create_test_mp3(compressed)
            output = io.StringIO()
            failed = subprocess.CompletedProcess(
                ["ffplay"], 1, stderr="Audio device unavailable"
            )

            with patch("builtins.input", side_effect=("3", "4", "5")):
                with patch(
                    "compressor.select_mp3_file", side_effect=(source, compressed)
                ):
                    with patch("compressor.resolve_ffplay", return_value="ffplay.exe"):
                        with patch("compressor.subprocess.run", return_value=failed):
                            with contextlib.redirect_stdout(output):
                                compressor.run_menu(
                                    root / "input",
                                    compressed.parent,
                                    None,
                                    None,
                                )

            self.assertEqual(output.getvalue().count("Playback failed: Audio device unavailable"), 2)

    def test_menu_uses_picker_and_handles_cancellation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = io.StringIO()
            with patch("builtins.input", side_effect=("1", "2", "3", "4", "5")):
                with patch(
                    "compressor.select_mp3_file", return_value=None
                ) as picker:
                    with contextlib.redirect_stdout(output):
                        compressor.run_menu(
                            root / "input",
                            root / "output",
                            None,
                            None,
                        )

            self.assertEqual(picker.call_count, 4)
            self.assertEqual(
                [call.args[0] for call in picker.call_args_list],
                [root / "input", root / "input", root / "input", root / "output"],
            )
            self.assertEqual(output.getvalue().count("File selection cancelled."), 4)

    def test_comparison_menu_encodes_every_supported_bitrate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "tone.mp3"
            create_test_mp3(source)

            def fake_compress(
                selected_source: Path,
                output_dir: Path,
                bitrate_kbps: int,
                _ffmpeg_executable: str | None,
            ) -> compressor.CompressionResult:
                self.assertIsNone(_ffmpeg_executable)
                return compressor.CompressionResult(
                    source=selected_source,
                    output=output_dir / f"tone_{bitrate_kbps}kbps.mp3",
                    bitrate_kbps=bitrate_kbps,
                    original_size=1000,
                    compressed_size=bitrate_kbps,
                )

            output = io.StringIO()
            with patch("builtins.input", side_effect=("2", "5")):
                with patch("compressor.select_mp3_file", return_value=source):
                    with patch("compressor.compress_mp3", side_effect=fake_compress) as encode:
                        with contextlib.redirect_stdout(output):
                            compressor.run_menu(
                                root / "input",
                                root / "output",
                                None,
                                None,
                            )

            self.assertEqual(
                [call.args[2] for call in encode.call_args_list],
                list(compressor.BITRATES),
            )
            self.assertIn("Measured comparison", output.getvalue())

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed on PATH")
    def test_real_ffmpeg_reencodes_generated_mp3(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "tone.mp3"
            output_dir = root / "output"
            generated = subprocess.run(
                [
                    shutil.which("ffmpeg") or "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=1",
                    "-codec:a",
                    "libmp3lame",
                    "-b:a",
                    "128k",
                    str(source),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            original_data = source.read_bytes()

            result = compressor.compress_mp3(source, output_dir, 192)

            self.assertGreater(result.compressed_size, 0)
            self.assertTrue(result.output.is_file())
            self.assertEqual(source.read_bytes(), original_data)


if __name__ == "__main__":
    unittest.main()
