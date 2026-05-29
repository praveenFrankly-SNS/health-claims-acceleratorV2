import re

def sanitize_document_text(text: str, max_length: int = 4000) -> str:
    """
    Sanitize document text to prevent prompt injection.
    Strips control sequences, JSON-breaking characters, and truncates to max_length.
    Wraps the result in <document> tags.
    """
    if not text:
        return "<document></document>"
    
    # Remove known prompt-control sequences
    text = re.sub(r'(?i)ignore previous instructions', '', text)
    text = re.sub(r'(?i)system prompt', '', text)
    text = re.sub(r'(?i)you are an ai', '', text)
    
    # Escape braces to prevent JSON injection in prompts that expect JSON output
    text = text.replace('{', '(').replace('}', ')')
    text = text.replace('\\', '\\\\')
    text = text.replace('"', '\\"')
    
    # Truncate to limit context window and prevent overflow attacks
    text = text[:max_length]
    
    return f"<document>\n{text}\n</document>"
