import unicodedata
import re
from src.config import settings

class SanitizationError(Exception):
    pass

class InputSanitizer:
    # Categories to strip: Control (Cc), Format (Cf), Surrogate (Cs), Private Use (Co)
    STRIP_CATEGORIES = {'Cc', 'Cf', 'Cs', 'Co'}
    
    # Explicit blocklist for dangerous invisible chars
    DANGEROUS_CHARS = {
        '\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
        '\u202a', '\u202b', '\u202c', '\u202d', '\u202e', '\ufeff',
    }

    @classmethod
    def sanitize(cls, raw_input: str) -> tuple[str, list[str]]:
        """
        Cleans input and returns (clean_text, list_of_tokens).
        Raises SanitizationError if input is too long.
        """
        if not isinstance(raw_input, str):
            raise SanitizationError("Input must be a string")

        # 1. Raw Length Check
        if len(raw_input) > settings.MAX_RAW_LENGTH:
            raise SanitizationError("Raw input too long")

        # 2. Unicode Normalization (NFKC)
        text = unicodedata.normalize('NFKC', raw_input)

        # 3. Strip Dangerous Characters
        cleaned_chars = []
        for char in text:
            cat = unicodedata.category(char)
            if cat in cls.STRIP_CATEGORIES:
                continue
            if char in cls.DANGEROUS_CHARS:
                continue
            if char.isprintable() or char in [' ', '\n', '\t']:
                cleaned_chars.append(char)
        
        text = "".join(cleaned_chars)

        # 4. Whitespace Normalization
        text = re.sub(r'\s+', ' ', text).strip()

        # 5. Post-Sanitization Length Check
        if len(text) > settings.MAX_INPUT_LENGTH:
             raise SanitizationError("Sanitized input too long")

        # 6. Tokenization (Simple split for P1 exact matching)
        tokens = text.lower().split()

        return text, tokens

    @classmethod
    def sanitize_output(cls, model_output: str) -> str:
        """Strips ANSI escape codes from AI output to prevent terminal hacks."""
        if not isinstance(model_output, str):
            return ""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', model_output)