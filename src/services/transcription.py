"""
Voice Transcription Service using Google AI Studio (Gemini API).

This service handles audio-to-text conversion for voice messages
received from Telegram, utilizing Google's Gemini models for
high-quality transcription.
"""

import io
import httpx
import asyncio
from typing import Optional
from loguru import logger

from src.config import settings
from src.models import TranscriptionResult


class TranscriptionService:
    """
    Service for transcribing voice messages using Google AI Studio.
    
    This service downloads audio files from Telegram, converts them
    to the appropriate format, and sends them to Google AI Studio's
    Gemini API for transcription.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the transcription service.
        
        Args:
            api_key: Google AI API key. If not provided, uses settings.
        """
        self.api_key = api_key or settings.GOOGLE_AI_API_KEY
        self.model = settings.GOOGLE_AI_MODEL
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        
    async def transcribe_audio(
        self,
        audio_data: bytes,
        filename: str = "voice.ogg",
        language: Optional[str] = None
    ) -> TranscriptionResult:
        """
        Transcribe audio data to text.
        
        Args:
            audio_data: Raw audio bytes (OGG format from Telegram)
            filename: Original filename for content type detection
            language: Optional language hint (e.g., "he" for Hebrew)
            
        Returns:
            TranscriptionResult with transcribed text and metadata
            
        Raises:
            TranscriptionError: If transcription fails
        """
        if not self.api_key:
            raise TranscriptionError("Google AI API key not configured")
            
        logger.info(f"Starting transcription for {filename}, size: {len(audio_data)} bytes")
        
        try:
            # For Gemini API, we need to use the vision/multimodal endpoint
            # with audio support. As of now, Gemini supports audio input.
            result = await self._transcribe_with_gemini(audio_data, language)
            logger.info(f"Transcription completed: {len(result.text)} characters")
            return result
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise TranscriptionError(f"Failed to transcribe audio: {e}")
    
    async def _transcribe_with_gemini(
        self,
        audio_data: bytes,
        language: Optional[str] = None
    ) -> TranscriptionResult:
        """
        Internal method to call Gemini API for transcription.
        
        Gemini models can process audio files directly. We convert the
        audio to base64 and send it to the API with retry logic and
        robust error handling.
        """
        import base64
        import time
        import random
        
        # Convert audio to base64
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        
        # Build prompt for transcription
        prompt_text = self._build_transcription_prompt(language)
        
        # Gemini expects inline data with mime type
        inline_data = {
            "mime_type": "audio/ogg",  # Telegram voice messages are OGG
            "data": audio_b64
        }
        
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt_text},
                    {"inline_data": inline_data}
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,  # Low temperature for factual transcription
                "maxOutputTokens": 2048,
            }
        }
        
        url = f"{self.base_url}/models/{self.model}:generateContent?key={self.api_key}"
        
        max_retries = 3
        backoff_factor = 2.0
        
        for attempt in range(max_retries):
            start_time = time.time()
            try:
                logger.debug(f"Sending request to Gemini API (Attempt {attempt + 1}/{max_retries})")
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(url, json=payload)
                
                duration = time.time() - start_time
                logger.debug(f"Gemini API request took {duration:.2f}s, status: {response.status_code}")
                
                # Check for rate limit (429) or temporary server errors (5xx)
                if response.status_code in (429, 500, 502, 503, 504):
                    try:
                        err_json = response.json()
                        err_msg = err_json.get("error", {}).get("message", "Unknown error")
                        err_status = err_json.get("error", {}).get("status", "Unknown status")
                        logger.warning(
                            f"Gemini API returned transient status {response.status_code}: {err_status} - {err_msg}"
                        )
                    except Exception:
                        logger.warning(f"Gemini API returned transient status {response.status_code}")
                    
                    if attempt == max_retries - 1:
                        raise TranscriptionError(
                            f"Gemini API error (Status {response.status_code}) after {max_retries} attempts"
                        )
                    
                    sleep_time = (backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                    logger.info(f"Retrying in {sleep_time:.2f}s...")
                    await asyncio.sleep(sleep_time)
                    continue
                
                # For other non-200 status codes (such as 400, 401, 403) - do not retry
                if response.status_code != 200:
                    try:
                        err_json = response.json()
                        err_msg = err_json.get("error", {}).get("message", "No details")
                        err_status = err_json.get("error", {}).get("status", "No status")
                        logger.error(f"Gemini API Client Error {response.status_code}: [{err_status}] {err_msg}")
                        raise TranscriptionError(f"Gemini API Authentication/Configuration Error: {err_msg}")
                    except ValueError:
                        logger.error(f"Gemini API Client Error {response.status_code}: {response.text}")
                        raise TranscriptionError(f"Gemini API returned client error {response.status_code}")
                
                # Parse JSON response
                try:
                    result = response.json()
                except ValueError as e:
                    logger.error(f"Failed to parse Gemini response as JSON: {response.text[:500]}")
                    raise TranscriptionError(f"Invalid JSON response from Gemini API: {e}")
                
                # Extract transcription from response
                if "candidates" in result and len(result["candidates"]) > 0:
                    candidate = result["candidates"][0]
                    
                    # Check finish reason
                    finish_reason = candidate.get("finishReason")
                    if finish_reason and finish_reason != "STOP":
                        logger.warning(f"Gemini generation did not finish with STOP. Reason: {finish_reason}")
                        if finish_reason == "SAFETY":
                            raise TranscriptionError("Transcription blocked due to safety content filtering")
                        elif finish_reason == "RECITATION":
                            raise TranscriptionError("Transcription blocked due to recitation check")
                    
                    if "content" in candidate and "parts" in candidate["content"]:
                        parts = candidate["content"]["parts"]
                        transcribed_text = ""
                        for part in parts:
                            if "text" in part:
                                transcribed_text += part["text"]
                        
                        return TranscriptionResult(
                            text=transcribed_text.strip(),
                            confidence=0.95,  # Gemini doesn't provide confidence, estimate
                            language=language or "auto",
                            model_used=self.model
                        )
                
                # If we get here, response is valid JSON but has unexpected structure
                # Check for prompt feedback block
                prompt_feedback = result.get("promptFeedback", {})
                if prompt_feedback and "blockReason" in prompt_feedback:
                    reason = prompt_feedback.get("blockReason")
                    logger.error(f"Gemini API blocked the transcription prompt. Reason: {reason}")
                    raise TranscriptionError(f"Prompt blocked by safety filters: {reason}")
                
                logger.error(f"Unexpected Gemini API response structure: {list(result.keys())}")
                raise TranscriptionError("No transcription candidate returned by Gemini API")
                
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.warning(f"Network error calling Gemini API (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise TranscriptionError(f"Network timeout/connectivity error calling Gemini API: {e}")
                
                sleep_time = (backoff_factor ** attempt) + random.uniform(0.1, 0.5)
                await asyncio.sleep(sleep_time)
                continue
                
            except Exception as e:
                if isinstance(e, TranscriptionError):
                    raise
                logger.exception(f"Unexpected error in Gemini API call: {e}")
                raise TranscriptionError(f"Unexpected error in Gemini API call: {e}")
    
    def _build_transcription_prompt(self, language: Optional[str] = None) -> str:
        """
        Build a prompt for the transcription task.
        
        Args:
            language: Optional language code (ISO 639-1)
            
        Returns:
            Formatted prompt string
        """
        if language == "he":
            return """אתה מתמלל מקצועי. תמלל את ההודעה הקולית בדיוק מקסימלי.
החזר רק את הטקסט המתומלל ללא הערות או הסברים נוספים.
אם אינך יכול לשמוע בבירור, החזר [לא ברור]."""
        
        return f"""You are a professional transcription service. Transcribe the audio message exactly.
Return ONLY the transcribed text without any additional comments.
The audio is in language: {language or 'auto-detect'}.
If you cannot hear clearly, return [unclear]."""
    
    async def transcribe_from_url(
        self,
        file_url: str,
        language: Optional[str] = None
    ) -> TranscriptionResult:
        """
        Download audio from URL and transcribe.
        
        Args:
            file_url: Direct URL to audio file
            language: Optional language hint
            
        Returns:
            TranscriptionResult
        """
        logger.info(f"Downloading audio from {file_url}")
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(file_url)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to download audio from URL: Status {e.response.status_code} - {file_url}")
            raise TranscriptionError(f"Failed to download audio from source URL (Status {e.response.status_code})")
        except httpx.HTTPError as e:
            logger.error(f"Network error downloading audio from {file_url}: {e}")
            raise TranscriptionError(f"Network error downloading audio file: {e}")
            
        content_type = response.headers.get("content-type", "audio/ogg")
        filename = f"audio.{content_type.split('/')[-1]}"
        
        return await self.transcribe_audio(
            response.content,
            filename=filename,
            language=language
        )


class TranscriptionError(Exception):
    """Custom exception for transcription errors."""
    pass


# Singleton instance
_transcription_service: Optional[TranscriptionService] = None


def get_transcription_service() -> TranscriptionService:
    """Get or create the global transcription service instance."""
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service