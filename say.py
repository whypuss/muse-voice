#!/usr/bin/env python3
import sys
import os
import json
import base64
import subprocess
import requests

DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
FALLBACK_MODELS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview"]

def get_api_key():
    # 1. Environment variable
    key = os.environ.get("GEMINI_API_KEY")
    if key and key.strip():
        return key.strip()

    # 2. Key file (.gemini_key in script dir or home)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(script_dir, ".gemini_key"),
        os.path.expanduser("~/.gemini_key"),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return content
            except Exception:
                pass

    # 3. config.json in script dir
    cfg_candidates = [
        os.path.join(script_dir, "config.json"),
        os.path.join(os.getcwd(), "config.json"),
    ]
    for cfg_path in cfg_candidates:
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    val = cfg.get("gemini_api_key")
                    if val and isinstance(val, str) and val.strip() and "YOUR_" not in val:
                        return val.strip()
            except Exception:
                pass

    raise RuntimeError("Gemini API key not found in env GEMINI_API_KEY, .gemini_key, or config.json")

def synthesize_with_model(model, text, voice, api_key, proxies):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key,
    }

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": text
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {
                        "voiceName": voice
                    }
                }
            }
        }
    }

    session = requests.Session()
    session.trust_env = False

    resp = session.post(url, headers=headers, json=payload, proxies=proxies, timeout=90)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")

    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"No candidates returned: {data}")

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason")
    parts = candidate.get("content", {}).get("parts", [])

    pcm_b64 = None
    for part in parts:
        inline_data = part.get("inlineData")
        if inline_data and "data" in inline_data:
            pcm_b64 = inline_data["data"]
            break

    if not pcm_b64:
        raise RuntimeError(f"No audio data found in candidate (finishReason={finish_reason}): {data}")

    return base64.b64decode(pcm_b64)

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python3 say.py <text> [voice] [output.mp3]")
        sys.exit(1)

    text = sys.argv[1]
    voice = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else "Laomedeia"
    output_path = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else "output.mp3"
    primary_model = os.environ.get("GEMINI_TTS_MODEL", DEFAULT_MODEL)

    api_key = get_api_key()

    proxies = {
        "http": "http://127.0.0.1:1080",
        "https": "http://127.0.0.1:1080",
    }

    models_to_try = [primary_model]
    for fb in FALLBACK_MODELS:
        if fb not in models_to_try:
            models_to_try.append(fb)

    pcm_bytes = None
    used_model = None
    errors = []

    for m in models_to_try:
        try:
            pcm_bytes = synthesize_with_model(m, text, voice, api_key, proxies)
            used_model = m
            break
        except Exception as e:
            errors.append((m, str(e)))
            if "GEMINI_TTS_MODEL" in os.environ and os.environ["GEMINI_TTS_MODEL"] != DEFAULT_MODEL:
                raise

    if not pcm_bytes:
        err_msg = "\n".join(f"- {m}: {err}" for m, err in errors)
        raise RuntimeError(f"Failed to synthesize speech across available models:\n{err_msg}")

    output_dir = os.path.dirname(os.path.abspath(output_path))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "s16le",
        "-ar", "24000",
        "-ac", "1",
        "-i", "pipe:0",
        "-codec:a", "libmp3lame",
        "-b:a", "128k",
        output_path
    ]

    proc = subprocess.run(cmd, input=pcm_bytes, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr.decode()}")

    file_size = os.path.getsize(output_path)
    print(f"Generated {output_path} ({file_size} bytes, voice={voice}, model={used_model})")

if __name__ == "__main__":
    main()
