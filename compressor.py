"""Terminal-based MP3 re-encoder using FFmpeg's LAME encoder."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


BITRATES = (96, 128, 192, 256, 320)
PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = PROJECT_DIR / "input"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output"


class AudioCompressorError(Exception):
    """An expected input, configuration, or audio-processing error."""


@dataclass(frozen=True)
class CompressionResult:
    source: Path
    output: Path
    bitrate_kbps: int
    original_size: int
    compressed_size: int

    @property
    def compression_ratio(self) -> float:
        """Return the original-to-compressed size ratio."""
        return self.original_size / self.compressed_size

    @property
    def space_saved_percent(self) -> float:
        """Return measured space saved; this can be negative."""
        return (1 - self.compressed_size / self.original_size) * 100


def validate_mp3(source: Path) -> None:
    """Check that the selected source is an existing, non-empty MP3 file."""
    if source.suffix.lower() != ".mp3":
        raise AudioCompressorError(f"Only .mp3 files are supported: {source.name}")
    if not source.is_file():
        raise AudioCompressorError(f"MP3 file does not exist: {source}")
    try:
        if source.stat().st_size == 0:
            raise AudioCompressorError(f"MP3 file is empty: {source.name}")
    except OSError as exc:
        raise AudioCompressorError(f"Cannot read '{source.name}': {exc}") from exc


def calculate_result(
    source: Path,
    output: Path,
    bitrate_kbps: int,
    original_size: int,
    compressed_size: int,
) -> CompressionResult:
    """Build measured size metrics, rejecting unusable values."""
    if original_size <= 0 or compressed_size <= 0:
        raise AudioCompressorError("Original and compressed files must both have non-zero size.")
    return CompressionResult(
        source=source,
        output=output,
        bitrate_kbps=bitrate_kbps,
        original_size=original_size,
        compressed_size=compressed_size,
    )


def resolve_executable(configured: str | None, name: str) -> str:
    """Resolve an explicitly configured executable or one available on PATH."""
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        raise AudioCompressorError(
            f"Configured {name} executable was not found: {configured}"
        )
    resolved = shutil.which(name)
    if not resolved:
        raise AudioCompressorError(
            f"{name} was not found on PATH. Install FFmpeg manually or pass its path "
            f"with --{name} / AUDIO_COMPRESSOR_{name.upper()}."
        )
    return resolved


def resolve_ffmpeg(configured: str | None = None) -> str:
    """Find FFmpeg, honoring the CLI value and environment variable."""
    return resolve_executable(
        configured or os.environ.get("AUDIO_COMPRESSOR_FFMPEG"),
        "ffmpeg",
    )


def ensure_lame_encoder(ffmpeg: str) -> None:
    """Verify that the selected FFmpeg build provides libmp3lame."""
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AudioCompressorError(f"Could not run FFmpeg at '{ffmpeg}': {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "FFmpeg returned an error while listing encoders."
        raise AudioCompressorError(detail)
    if "libmp3lame" not in result.stdout:
        raise AudioCompressorError(
            "This FFmpeg build does not provide the libmp3lame encoder. "
            "Use an FFmpeg build compiled with LAME support."
        )


def compress_mp3(
    source: Path,
    output_dir: Path,
    bitrate_kbps: int,
    ffmpeg_executable: str | None = None,
) -> CompressionResult:
    """Re-encode one MP3 without overwriting its source or another output."""
    if bitrate_kbps not in BITRATES:
        allowed = ", ".join(str(rate) for rate in BITRATES)
        raise AudioCompressorError(f"Unsupported bitrate. Choose one of: {allowed} kbps.")

    source = source.expanduser()
    output_dir = output_dir.expanduser()
    validate_mp3(source)
    output = output_dir / f"{source.stem}_{bitrate_kbps}kbps.mp3"
    if output.resolve() == source.resolve():
        raise AudioCompressorError("Output path matches the selected MP3; source was not changed.")
    if output.exists():
        raise AudioCompressorError(
            f"Output already exists and was left unchanged: {output}. "
            "Move or rename it before compressing again."
        )
    ffmpeg = resolve_ffmpeg(ffmpeg_executable)
    ensure_lame_encoder(ffmpeg)

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        process = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-n",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-map_metadata",
                "0",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                f"{bitrate_kbps}k",
                str(output),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AudioCompressorError(f"Could not start FFmpeg: {exc}") from exc

    if process.returncode != 0:
        detail = process.stderr.strip() or f"FFmpeg exited with status {process.returncode}."
        raise AudioCompressorError(f"Compression failed: {detail}")
    if not output.is_file() or output.stat().st_size == 0:
        raise AudioCompressorError("FFmpeg reported success but did not create a non-empty MP3.")

    return calculate_result(
        source=source,
        output=output,
        bitrate_kbps=bitrate_kbps,
        original_size=source.stat().st_size,
        compressed_size=output.stat().st_size,
    )


def format_size(size_bytes: int) -> str:
    """Format a file size using binary units while retaining exact bytes."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    size = float(size_bytes)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        size /= 1024
        if size < 1024 or unit == "TiB":
            return f"{size:.2f} {unit} ({size_bytes:,} B)"
    return f"{size_bytes:,} B"


def display_result(result: CompressionResult) -> None:
    print(f"\nCompressed file: {result.output}")
    print(f"Bitrate:         {result.bitrate_kbps} kbps")
    print(f"Original size:   {format_size(result.original_size)}")
    print(f"Compressed size: {format_size(result.compressed_size)}")
    print(f"Compression ratio (original / compressed): {result.compression_ratio:.2f}:1")
    print(f"Space saved:     {result.space_saved_percent:.2f}%")


def display_comparison(results: Sequence[CompressionResult]) -> None:
    if not results:
        print("No compression results are available to compare.")
        return
    print("\nMeasured comparison")
    print(
        f"{'Bitrate':>8}  {'MP3 size':>18}  {'Ratio':>10}  "
        f"{'Space saved':>12}  Output"
    )
    for result in sorted(results, key=lambda item: item.bitrate_kbps):
        print(
            f"{result.bitrate_kbps:>5} kbps  "
            f"{format_size(result.compressed_size):>18}  "
            f"{result.compression_ratio:>8.2f}:1  "
            f"{result.space_saved_percent:>10.2f}%  "
            f"{result.output.name}"
        )


def select_mp3_file(initial_dir: Path, title: str) -> Path | None:
    """Open the native file picker, filtered to MP3 files; return None if cancelled."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise AudioCompressorError(
            "The native file picker is unavailable because tkinter is missing."
        ) from exc

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            parent=root,
            title=title,
            initialdir=str(initial_dir),
            filetypes=(("MP3 audio files", "*.mp3"),),
        )
    except tk.TclError as exc:
        raise AudioCompressorError(f"Could not open the native file picker: {exc}") from exc
    finally:
        if root is not None:
            root.destroy()

    if not selected:
        return None
    source = Path(selected)
    validate_mp3(source)
    return source


def choose_bitrate() -> int | None:
    print("Available bitrates: " + ", ".join(f"{rate} kbps" for rate in BITRATES))
    try:
        choice = input("Enter bitrate (or press Enter to cancel): ").strip()
    except EOFError:
        print("\nInput closed.")
        return None
    if not choice:
        return None
    try:
        bitrate = int(choice)
    except ValueError:
        print("Please enter a bitrate from the list.")
        return None
    if bitrate not in BITRATES:
        print("Please choose one of the listed bitrates.")
        return None
    return bitrate


def resolve_ffplay(configured: str | None, ffmpeg: str | None = None) -> str:
    """Find FFplay from configuration, beside FFmpeg, or on PATH."""
    configured = configured or os.environ.get("AUDIO_COMPRESSOR_FFPLAY")
    if configured:
        return resolve_executable(configured, "ffplay")
    if ffmpeg:
        ffplay_name = "ffplay.exe" if os.name == "nt" else "ffplay"
        sibling = Path(ffmpeg).with_name(ffplay_name)
        if sibling.is_file():
            return str(sibling)
    return resolve_executable(None, "ffplay")


def play_audio(
    audio_file: Path,
    ffplay_executable: str | None = None,
    ffmpeg_executable: str | None = None,
) -> None:
    """Play an MP3 using FFplay's audio-only playback mode."""
    validate_mp3(audio_file)
    ffmpeg_hint = ffmpeg_executable or os.environ.get("AUDIO_COMPRESSOR_FFMPEG")
    ffplay = resolve_ffplay(ffplay_executable, ffmpeg_hint)
    try:
        process = subprocess.run(
            [
                ffplay,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nodisp",
                "-autoexit",
                str(audio_file),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AudioCompressorError(f"Could not start FFplay: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.strip() or f"FFplay exited with status {process.returncode}."
        raise AudioCompressorError(f"Playback failed: {detail}")


def run_menu(
    input_dir: Path,
    output_dir: Path,
    ffmpeg_executable: str | None,
    ffplay_executable: str | None,
) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    while True:
        print(
            "\n=== MP3 Audio Compression System ===\n"
            "1. Compress one MP3 file\n"
            "2. Compare all supported bitrates\n"
            "3. Play a source MP3 file\n"
            "4. Play a compressed MP3 file\n"
            "5. Exit"
        )
        try:
            selection = input("Choose an option: ").strip()
        except EOFError:
            print("\nExiting.")
            return

        if selection == "5":
            print("Goodbye.")
            return
        if selection == "1":
            try:
                source = select_mp3_file(input_dir, "Select an MP3 file to compress")
            except AudioCompressorError as exc:
                print(f"Error: {exc}")
                continue
            if source is None:
                print("File selection cancelled.")
                continue
            bitrate = choose_bitrate()
            if bitrate is None:
                continue
            try:
                result = compress_mp3(source, output_dir, bitrate, ffmpeg_executable)
            except AudioCompressorError as exc:
                print(f"Error: {exc}")
            else:
                display_result(result)
        elif selection == "2":
            try:
                source = select_mp3_file(input_dir, "Select an MP3 file to compare")
            except AudioCompressorError as exc:
                print(f"Error: {exc}")
                continue
            if source is None:
                print("File selection cancelled.")
                continue
            results: list[CompressionResult] = []
            for bitrate in BITRATES:
                try:
                    result = compress_mp3(source, output_dir, bitrate, ffmpeg_executable)
                except AudioCompressorError as exc:
                    print(f"{bitrate} kbps: {exc}")
                else:
                    results.append(result)
            display_comparison(results)
        elif selection == "3":
            try:
                source = select_mp3_file(input_dir, "Select a source MP3 file to play")
            except AudioCompressorError as exc:
                print(f"Error: {exc}")
                continue
            if source is None:
                print("File selection cancelled.")
                continue
            try:
                play_audio(source, ffplay_executable, ffmpeg_executable)
            except AudioCompressorError as exc:
                print(f"Error: {exc}")
            else:
                print("Playback finished.")
        elif selection == "4":
            try:
                audio_file = select_mp3_file(
                    output_dir, "Select a compressed MP3 file to play"
                )
            except AudioCompressorError as exc:
                print(f"Error: {exc}")
                continue
            if audio_file is None:
                print("File selection cancelled.")
                continue
            try:
                play_audio(audio_file, ffplay_executable, ffmpeg_executable)
            except AudioCompressorError as exc:
                print(f"Error: {exc}")
            else:
                print("Playback finished.")
        else:
            print("Please choose an option from 1 to 5.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-encode MP3 files with FFmpeg's libmp3lame encoder."
    )
    parser.add_argument(
        "--ffmpeg",
        help="FFmpeg executable path (or set AUDIO_COMPRESSOR_FFMPEG).",
    )
    parser.add_argument(
        "--ffplay",
        help="FFplay executable path (or set AUDIO_COMPRESSOR_FFPLAY).",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"folder used to start MP3 selection (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"folder for MP3 files (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args(argv)
    try:
        run_menu(args.input_dir, args.output_dir, args.ffmpeg, args.ffplay)
    except (AudioCompressorError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())