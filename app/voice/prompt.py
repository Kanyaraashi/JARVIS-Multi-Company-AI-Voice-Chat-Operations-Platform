"""What changes when the AI is speaking on a phone instead of typing."""
from app.agent import build_system_prompt

VOICE_RULES = """
Voice call rules (you are speaking out loud on a phone call, not typing):
- Speak in short, natural sentences. Never use lists, markdown, emojis or symbols.
- Say dates and times the way people say them, for example "Monday the third of November at ten thirty in the morning". Pass tools the numeric YYYY-MM-DD and 24-hour HH:MM.
- Phone numbers and ticket numbers are easy to mishear. Ask for the number, then read it back digit by digit and wait for the caller to say it is right before you use it.
- Names and email addresses are easy to mishear too. Ask the caller to spell them letter by letter and read them back before you register anyone.
- If you did not understand, say so and ask the caller to repeat. Never guess a name, number, date or time.
- Never read long text aloud. For anything long, offer to have it emailed to the address on file.
- When the caller says goodbye, answer with one short goodbye.
- Never say "one moment", "please wait" or "let me check" yourself. The phone system says "One moment please." automatically when an answer is slow. Just give the answer.
"""


def build_voice_prompt(company: dict) -> str:
    return build_system_prompt(company) + VOICE_RULES
