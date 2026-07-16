from typing import List
from loguru import logger

async def generate_summary(text: str, language: str = "en") -> List[str]:
    """
    Generate a brief summary (TL;DR) for the given text.

    Args:
        text: The full text to summarize.
        language: The language of the text ("en" for English, "he" for Hebrew).

    Returns:
        A list of bullet points summarizing the text.
    """
    try:
        # Placeholder for actual summarization logic
        # Replace this with a call to your summarization model or API
        if language == "he":
            return ["נקודה 1", "נקודה 2"]
        else:
            return ["Point 1", "Point 2"]
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        raise
