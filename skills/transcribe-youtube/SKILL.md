---
name: transcribe-youtube
description: Use when the user asks to transcribe a YouTube video, get a YouTube transcript, or download/save a transcript from a YouTube URL.
---

# Transcribe YouTube Video

Transcribes a YouTube video and saves the result as a markdown file.

## How to Run

```bash
python ~/.claude/skills/transcribe-youtube/scripts/youtube-transcript.py <URL> [--output-dir <dir>] [--use-youtube-transcript]
```

- `<URL>` — YouTube video URL (supports watch, shorts, youtu.be, embed formats)
- `--output-dir` — where to save the markdown file (default: `transcripts/` in cwd)
- `--use-youtube-transcript` — use YouTube's built-in transcript instead of OpenAI Whisper (faster but lower quality)

## Steps

1. Run the script with the user's YouTube URL. If the user specified a custom output directory, pass `--output-dir`.
2. The script prints the path of the saved markdown file to stdout.
3. Report that path to the user.

## Requirements

- `OPENAI_API_KEY` must be set in the environment (for the default Whisper path)
- Python packages: `yt-dlp`, `openai`, `youtube-transcript-api`
