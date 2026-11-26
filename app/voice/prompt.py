"""What changes when the AI is speaking on a phone instead of typing."""
from app import languages
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


LANGUAGE_RULES = """
Languages on this phone line: {listed}.
- Every call starts in {start}.
- Always answer in the language the caller is speaking. When the caller speaks, or asks for, another language from the list, call switch_language with its code BEFORE you say anything else, then carry on in that language.
- If the caller uses a language that is not on the list, say so briefly in {start} and ask which listed language they prefer.
- The voice reads your words in the call's current language, so write every reply in that language's own script (for Telugu, Telugu script), never in English letters.
- Tool arguments always stay in the usual form: dates as YYYY-MM-DD, times as HH:MM, phone numbers and ticket numbers as digits, email addresses in English letters.
- Ask the caller to spell names and email addresses in English letters, one letter at a time, and read them back.
- Read phone numbers and ticket numbers back one digit at a time.
"""


def build_voice_prompt(company: dict, allowed=None) -> str:
    """allowed: the languages of this phone line (the first is where calls start). One English-only line adds nothing."""
    prompt = build_system_prompt(company) + VOICE_RULES
    if allowed and (len(allowed) > 1 or allowed[0] != "en-IN"):
        prompt += LANGUAGE_RULES.format(listed=languages.list_for_prompt(allowed), start=languages.english_name(allowed[0]))
    return prompt
