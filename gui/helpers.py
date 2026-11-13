"""Small functions for the interface"""


def short_text(text, limit):
    """Shorten a long text, such as a path, by leaving out the middle"""
    if len(text) <= limit:
        return text
    head = (limit - 3) // 3
    return text[:head] + "..." + text[-(limit - 3 - head):]
