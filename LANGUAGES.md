# Indian languages (Hindi, Telugu, Tamil and more)

Supported: en-IN hi-IN te-IN ta-IN kn-IN ml-IN mr-IN bn-IN gu-IN pa-IN od-IN.

## Web chat (works with Gemini, no Sarvam needed)
Customers see language buttons. The AI answers in the chosen language.
Choose buttons in .env:  CHAT_LANGUAGES=en-IN,hi-IN,te-IN,ta-IN
Screen text is translated for Hindi, Telugu, Tamil only; other languages show English labels
but the AI still replies in that language. Ask a native speaker to review the translations.

## Phone calls (needs Sarvam)
1. Create a key at https://dashboard.sarvam.ai (free starter credit), then in .env:
   VOICE_STACK=sarvam
   SARVAM_API_KEY=your_key
   VOICE_LANGUAGE=en-IN
   VOICE_LANGUAGES=hi-IN,te-IN,ta-IN
2. Test the voice:   python -m app.voice.sarvam_check --languages te-IN,hi-IN,ta-IN
   It saves sarvam_test\<code>.wav files. Play them. [OK] = key and credit work.
3. Check settings:   python -m app.voice.preflight
4. Run the worker:   python voice_agent.py dev
The call starts in VOICE_LANGUAGE. If the caller speaks Telugu, the AI switches the voice with
its switch_language tool.

## Not verified yet (be honest with buyers)
- Not tested against live Sarvam audio. Run step 2 and make a real call first.
- If realtime listening is refused on your plan, set SARVAM_STT_MODE=standard.
- Sarvam pricing is pay-as-you-go after free credit.
