import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(
        timeout=20000,
        retry_options=types.HttpRetryOptions(attempts=1),
    ),
)

names = []
for model in client.models.list():
    name = model.name.replace("models/", "")
    actions = getattr(model, "supported_actions", None) or ["generateContent"]
    if "gemini" in name and "flash" in name and "generateContent" in actions:
        if not any(word in name for word in ("image", "live", "tts", "audio", "embedding")):
            names.append(name)

names = names[:8]
print(f"Testing {len(names)} models (each gets 20 seconds)...\n")

for name in names:
    start = time.time()
    try:
        reply = client.models.generate_content(
            model=name, contents="Say hello in three words."
        )
        text = (reply.text or "").strip()[:30]
        print(f"OK      {name:40} {time.time() - start:5.1f}s  {text!r}")
    except errors.APIError as exc:
        print(f"FAILED  {name:40} {time.time() - start:5.1f}s  error {getattr(exc, 'code', '?')}")
    except Exception as exc:
        print(f"FAILED  {name:40} {time.time() - start:5.1f}s  {type(exc).__name__}")
    time.sleep(6)  # stay under the free-tier requests-per-minute limit