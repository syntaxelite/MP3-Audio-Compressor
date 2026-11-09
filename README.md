# MP3 Audio Compression System

A terminal-based MP3 re-encoding tool for an Information Theory and Coding assignment. It uses FFmpeg's `libmp3lame` encoder, reports measurements from the files it actually creates, compares supported bitrates, and plays MP3 files with FFplay.

## Requirements

- Python 3.10 or newer
- FFmpeg compiled with the `libmp3lame` encoder
- FFplay for playback (usually distributed with FFmpeg)
- On Windows, a Python installation that includes `tkinter` for the native File Explorer file picker

The Python application uses only the standard library. FFmpeg and FFplay are separate programs; this project does **not** download, install, or reinstall them.

## Project layout

```text
Audio-compression/
|-- compressor.py
|-- input/       Starting folder for source MP3 file selection
|-- output/      Generated and selectable MP3 files
|-- requirements.txt
|-- tests/
|   `-- test_compressor.py
`-- README.md
```

## Setup

1. Install FFmpeg yourself using a trusted source for your operating system. Choose a build that includes `libmp3lame`, and make `ffmpeg` and `ffplay` available on `PATH` if possible.
2. Verify the encoder is present:

   ```powershell
   ffmpeg -hide_banner -encoders
   ```

   Look for `libmp3lame` in the output.
3. Place MP3 files in `input\` or navigate to their location using the native file picker.
4. No Python packages need to be installed. `requirements.txt` documents this; it is safe to run `python -m pip install -r requirements.txt` if desired.

If FFmpeg is not on `PATH`, provide its executable path on launch:

```powershell
python .\compressor.py --ffmpeg "C:\path\to\ffmpeg.exe" --ffplay "C:\path\to\ffplay.exe"
```

Or configure environment variables for the current PowerShell session:

```powershell
$env:AUDIO_COMPRESSOR_FFMPEG = "C:\path\to\ffmpeg.exe"
$env:AUDIO_COMPRESSOR_FFPLAY = "C:\path\to\ffplay.exe"
python .\compressor.py
```

The CLI also accepts `--input-dir` and `--output-dir`. These control the initial source-picking directory and the output folder (also the initial directory for selecting compressed MP3s). A picker opens whenever a menu option needs a file. It filters to `.mp3` files, and the application rejects a different extension even if typed into the dialog. Cancel closes that operation and returns to the menu.

## Run

From the project directory:

```powershell
python .\compressor.py
```

The menu can re-encode one selected MP3 at a chosen bitrate, compare the selected MP3 at all five bitrates, play a selected source MP3, or play a selected MP3 from `output\`. The available bitrates are **96, 128, 192, 256, and 320 kbps**. Outputs are named `<source>_<bitrate>kbps.mp3`.

The selected source MP3 is only read and is never modified. Existing outputs are also never overwritten; move or rename an output before repeating that bitrate. Compression re-encodes MP3 audio using `libmp3lame`, so it is lossy again and can reduce audio quality further.

## Measurements

- **Original size** and **compressed size** are measured from the selected MP3 and the generated MP3 files in bytes.
- **Compression ratio** is `original size / compressed size`, displayed as `x:1`. A value over 1 means the new file is smaller.
- **Space saved** is `(1 - compressed size / original size) * 100`. If re-encoding produces a larger MP3, the result is negative rather than hidden.
- The comparison contains only successful encodes and prints a specific error for each bitrate that fails. No predicted or fabricated results are shown.

## Compression concepts

- **MP3 is lossy.** Encoding discards or coarsens some audio information, so decoding cannot recreate the exact original signal. Re-encoding an MP3 is lossy-to-lossy conversion; it does not restore details discarded during the first encode.
- **Psychoacoustic modelling** estimates which sounds are less audible in context, including sounds masked by nearby louder components. The encoder uses this model to guide bit allocation and quantization; discarded information is not guaranteed to be inaudible.
- **Perceptual coding** uses hearing-related analysis to represent audio with fewer bits while aiming to keep audible distortion low. Lower bitrates generally require more aggressive trade-offs; the perceived result also depends on the source and listener.
- **Quantization** maps transformed audio values to a finite set of representable values. Coarser quantization introduces quantization noise and is a source of MP3's irreversible loss.
- **Bitrate** is the encoded data rate, measured here in kilobits per second (kbps). For a fixed duration, a higher bitrate generally uses more storage and can allow less aggressive quantization. It does not by itself guarantee a particular quality or file size.
- **Entropy coding** in MP3 (including Huffman coding of quantized spectral values and related data) is lossless coding of the already-quantized representation. It reduces redundancy; it is not the lossy step and cannot restore information removed during quantization.

## Tests

Run the standard-library unit tests:

```powershell
python -m unittest discover -s tests -v
```

The tests cover MP3-only validation, picker filtering and cancellation, source preservation, bitrate selection, and FFmpeg command construction. The real FFmpeg integration test runs only when `ffmpeg` is already available on `PATH`; otherwise it is skipped. The app reports missing FFmpeg or a missing `libmp3lame` encoder when compression is requested.
