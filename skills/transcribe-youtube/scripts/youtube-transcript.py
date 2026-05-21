import argparse
import os
import re
import tempfile
from urllib.parse import parse_qs, urlparse

import yt_dlp
from openai import OpenAI
from pydub import AudioSegment
from youtube_transcript_api import YouTubeTranscriptApi

# Whisper API accepts up to 25MB; use 24MB as a safe threshold
_MAX_CHUNK_BYTES = 24 * 1024 * 1024


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    if parsed.hostname in ("www.youtube.com", "youtube.com"):
        if parsed.path.startswith("/watch"):
            return parse_qs(parsed.query)["v"][0]
        if parsed.path.startswith(("/embed/", "/shorts/")):
            return parsed.path.split("/")[2]
    raise ValueError(f"Cannot extract video ID from URL: {url}")


def _download_audio(url: str, out_dir: str) -> str:
    out_path = os.path.join(out_dir, "audio")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    return out_path + ".mp3"


def _split_audio(file_path: str, tmp_dir: str) -> list:
    """Split an audio file into chunks that fit within the Whisper API size limit."""
    file_size = os.path.getsize(file_path)
    if file_size <= _MAX_CHUNK_BYTES:
        return [file_path]

    audio = AudioSegment.from_mp3(file_path)
    total_ms = len(audio)
    num_chunks = (file_size // _MAX_CHUNK_BYTES) + 1
    chunk_ms = total_ms // num_chunks

    chunk_paths = []
    for i in range(num_chunks):
        start = i * chunk_ms
        end = min((i + 1) * chunk_ms, total_ms)
        chunk = audio[start:end]
        chunk_path = os.path.join(tmp_dir, f"chunk_{i}.mp3")
        chunk.export(chunk_path, format="mp3")
        chunk_paths.append(chunk_path)

    return chunk_paths


def _transcribe_with_whisper(file_path: str) -> str:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    with open(file_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=f,
            response_format="text",
        )
    return transcript


def get_transcript(video_id: str, use_youtube_transcript: bool = False) -> str:
    if use_youtube_transcript:
        ytt_api = YouTubeTranscriptApi()
        segments = ytt_api.fetch(video_id)
        return "\n".join(s.text for s in segments)

    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = _download_audio(url=url, out_dir=tmp_dir)
        chunk_paths = _split_audio(file_path=audio_path, tmp_dir=tmp_dir)
        if len(chunk_paths) > 1:
            print(f"Audio is {os.path.getsize(audio_path) / 1024 / 1024:.1f}MB, split into {len(chunk_paths)} chunks")
        parts = [_transcribe_with_whisper(file_path=p) for p in chunk_paths]
        return " ".join(parts)


def _get_video_title(url: str) -> str:
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        return info["title"]


def _sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]', "", name)
    sanitized = sanitized.strip(". ")
    return sanitized[:200] if sanitized else "transcript"


def main():
    parser = argparse.ArgumentParser(description="Transcribe a YouTube video to markdown")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output-dir", default="transcripts", help="Output directory (default: transcripts/)")
    parser.add_argument("--use-youtube-transcript", action="store_true", help="Use YouTube's built-in transcript instead of OpenAI Whisper")
    args = parser.parse_args()

    video_id = _extract_video_id(args.url)
    title = _get_video_title(args.url)
    transcript = get_transcript(video_id=video_id, use_youtube_transcript=args.use_youtube_transcript)

    os.makedirs(args.output_dir, exist_ok=True)

    filename = _sanitize_filename(title) + ".md"
    output_path = os.path.join(args.output_dir, filename)

    with open(output_path, "w") as f:
        f.write(f"# {title}\n\n")
        f.write(f"Source: {args.url}\n\n")
        f.write("---\n\n")
        f.write(transcript)
        f.write("\n")

    print(output_path)


if __name__ == "__main__":
    main()
