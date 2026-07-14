"""
VocalizeBot - Core AI Agent Implementation
"""
import json
import re
from typing import Optional, Dict, Any, List
from datetime import datetime
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from loguru import logger
from config.settings import get_settings
from src.agents.prompts import (
    SYSTEM_PROMPT,
    INTENT_CLASSIFICATION_PROMPT,
    LEAD_QUALIFICATION_PROMPT,
    OBJECTION_HANDLING_PROMPT,
    COMPLAINT_HANDLETING_PROMPT,
    PAYMENT_GENERATION_PROMPT,
    SALES_CLOSING_PROMPT,
    BLACKOUT_DETECTION_PROMPT,
    format_prompt
)
from src.database.models import CustomerSegment, LeadStatus, BlackoutStatus

settings = get_settings()


class AIAgent:
    """Main AI Agent for VocalizeBot."""

    def __init__(self):
        self.settings = settings
        self.openai_client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        self.anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key) if settings.anthropic_api_key else None
        self.conversation_history: Dict[str, List[Dict]] = {}
        self.blackout_counter: Dict[str, int] = {}

    async def get_ai_response(
        self,
        message: str,
        customer_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Main method to process a customer message and get AI response.
        """
        # Get or initialize conversation history
        if customer_id not in self.conversation_history:
            self.conversation_history[customer_id] = []

        # Add user message to history
        self.conversation_history[customer_id].append({
            "role": "user",
            "content": message,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Detect intent
        intent_result = await self.classify_intent(message, customer_id, context)

        # Check for blackout mode
        if intent_result.get("blackout_suspected"):
            await self.handle_blackout_mode(customer_id)

        # Generate response
        response = await self.generate_response(message, customer_id, intent_result, context)

        # Update blackout counter if successful
        if customer_id in self.blackout_counter:
            self.blackout_counter[customer_id] = 0

        # Add AI response to history
        self.conversation_history[customer_id].append({
            "role": "assistant",
            "content": response["message"],
            "timestamp": datetime.utcnow().isoformat(),
            "intent": intent_result.get("primary_intent")
        })

        return {
            "message": response["message"],
            "intent": intent_result.get("primary_intent"),
            "confidence": intent_result.get("confidence"),
            "lead_score_impact": intent_result.get("lead_score_impact"),
            "detected_segment": intent_result.get("detected_segment"),
            "requires_action": intent_result.get("requires_immediate_action"),
            "escalation": intent_result.get("escalation_recommended"),
            "actions": response.get("actions", [])
        }

    async def classify_intent(
        self,
        message: str,
        customer_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Classify the intent of the customer message."""
        # Get conversation history context
        history_context = self._get_recent_history(customer_id, last_n=5)

        prompt = format_prompt(
            INTENT_CLASSIFICATION_PROMPT,
            message=message,
            context=history_context or "No previous context"
        )

        try:
            result = await self._call_ai(
                prompt,
                system=INTENT_CLASSIFICATION_PROMPT
            )
            return json.loads(result)
        except json.JSONDecodeError:
            logger.warning("Failed to parse intent classification response")
            return {
                "primary_intent": "unknown",
                "secondary_intent": None,
                "confidence": 0.0,
                "lead_score_impact": 0,
                "detected_segment": "unknown",
                "emotional_tone": "neutral",
                "requires_immediate_action": False,
                "blackout_suspected": False,
                "escalation_recommended": False
            }
        except Exception as e:
            logger.error(f"Error in intent classification: {e}")
            return {
                "primary_intent": "error",
                "confidence": 0.0,
                "blackout_suspected": True,
                "escalation_recommended": True
            }

    async def generate_response(
        self,
        message: str,
        customer_id: str,
        intent_result: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Generate the AI response based on intent."""
        intent = intent_result.get("primary_intent", "unknown")
        segment = intent_result.get("detected_segment", "b2c")
        
        # Build conversation context
        history_context = self._get_conversation_for_ai(customer_id)
        customer_segment = context.get("segment", segment) if context else segment

        # Build system prompt based on segment
        system_prompt = self._build_system_prompt(customer_segment, intent)

        # Build user message with context
        user_message = self._build_user_message(message, intent_result, context)

        try:
            response_text = await self._call_ai(
                user_message,
                system=system_prompt,
                history=history_context
            )

            # Parse response for actions
            actions = self._extract_actions(response_text, intent, context)

            return {
                "message": response_text,
                "actions": actions
            }
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return {
                "message": "Desculpe, estou tendo dificuldades para processar sua mensagem. Um momento, por favor.",
                "actions": []
            }

    async def _call_ai(
        self,
        user_message: str,
        system: Optional[str] = None,
        history: Optional[List[Dict]] = None
    ) -> str:
        """Make an AI API call."""
        if self.settings.default_ai_provider == "openai" and self.openai_client:
            return await self._call_openai(user_message, system, history)
        elif self.anthropic_client:
            return await self._call_anthropic(user_message, system, history)
        else:
            raise Exception("No AI provider configured")

    async def _call_openai(
        self,
        user_message: str,
        system: Optional[str] = None,
        history: Optional[List[Dict]] = None
    ) -> str:
        """Call OpenAI API."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        response = await self.openai_client.chat.completions.create(
            model=self.settings.ai_model,
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content

    async def _call_anthropic(
        self,
        user_message: str,
        system: Optional[str] = None,
        history: Optional[List[Dict]] = None
    ) -> str:
        """Call Anthropic API."""
        messages = []
        if history:
            for msg in history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        messages.append({"role": "user", "content": user_message})

        response = await self.anthropic_client.messages.create(
            model="claude-3-sonnet-20240229",
            system=system or "",
            messages=messages,
            max_tokens=1000
        )
        return response.content[0].text

    def _get_recent_history(self, customer_id: str, last_n: int = 5) -> str:
        """Get recent conversation history as a string."""
        history = self.conversation_history.get(customer_id, [])
        recent = history[-last_n:] if len(history) > last_n else history
        
        formatted = []
        for msg in recent:
            role = "Customer" if msg["role"] == "user" else "Agent"
            formatted.append(f"{role}: {msg['content']}")
        
        return "\n".join(formatted) if formatted else ""

    def _get_conversation_for_ai(self, customer_id: str) -> List[Dict]:
        """Get conversation history formatted for AI API."""
        return self.conversation_history.get(customer_id, [])[-10:]  # Last 10 messages

    def _build_system_prompt(self, segment: str, intent: str) -> str:
        """Build customized system prompt based on segment and intent."""
        prompt = SYSTEM_PROMPT
        
        # Add segment-specific instructions
        if segment == "b2b":
            prompt += "\n\n[B2B MODE] Focus on business value, ROI, and professional communication."
        elif segment == "b2c":
            prompt += "\n\n[B2C MODE] Be friendly and approachable. Focus on personal benefits."
        else:
            prompt += "\n\n[EXISTING CUSTOMER MODE] Show appreciation. Focus on loyalty and upsells."
        
        return prompt

    def _build_user_message(
        self,
        message: str,
        intent_result: Dict,
        context: Optional[Dict[str, Any]]
    ) -> str:
        """Build the user message with context."""
        msg = f"Customer Message: {message}\n\n"
        msg += f"Detected Intent: {intent_result.get('primary_intent')}\n"
        msg += f"Confidence: {intent_result.get('confidence')}\n"
        msg += f"Emotional Tone: {intent_result.get('emotional_tone')}\n"
        
        if context:
            if context.get("customer_name"):
                msg += f"Customer Name: {context['customer_name']}\n"
            if context.get("lead_score"):
                msg += f"Current Lead Score: {context['lead_score']}\n"
        
        return msg

    def _extract_actions(
        self,
        response: str,
        intent: str,
        context: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract actionable items from the response."""
        actions = []
        
        # Check for payment-related keywords
        if any(word in response.lower() for word in ["payment", "pagamento", "pagar", "link", "stripe"]):
            actions.append({"type": "payment", "status": "pending"})

        # Check for follow-up keywords
        if any(word in response.lower() for word in ["follow up", "lembrete", "reminder"]):
            actions.append({"type": "follow_up", "status": "scheduled"})

        # Check for escalation keywords
        if any(word in response.lower() for word in ["escalate", "human", "manager", "supervisor"]):
            actions.append({"type": "escalation", "status": "required"})

        return actions

    async def handle_blackout_mode(self, customer_id: str):
        """Handle blackout mode when AI is suspected of confusion."""
        self.blackout_counter[customer_id] = self.blackout_counter.get(customer_id, 0) + 1
        
        if self.blackout_counter[customer_id] >= self.settings.blackout_mode_threshold:
            logger.warning(f"Blackout mode triggered for customer {customer_id}")
            
            if self.settings.blackout_mode_escalation_enabled:
                # Signal escalation
                self.conversation_history[customer_id].append({
                    "role": "system",
                    "content": "⚠️ ESCALATION: AI blackout detected. Routing to human agent.",
                    "timestamp": datetime.utcnow().isoformat()
                })

    async def qualify_lead(
        self,
        customer_id: str,
        segment: str,
        current_score: int,
        status: str
    ) -> Dict[str, Any]:
        """Qualify and score a lead."""
        history = self._get_recent_history(customer_id, last_n=10)
        
        prompt = format_prompt(
            LEAD_QUALIFICATION_PROMPT,
            conversation_history=history,
            segment=segment,
            current_score=current_score,
            status=status
        )

        try:
            result = await self._call_ai(prompt, system=LEAD_QUALIFICATION_PROMPT)
            return json.loads(result)
        except Exception as e:
            logger.error(f"Error in lead qualification: {e}")
            return {
                "qualified": False,
                "score": current_score,
                "status": status,
                "error": str(e)
            }

    async def handle_objection(
        self,
        objection: str,
        segment: str,
        product_info: str
    ) -> str:
        """Handle customer objection."""
        prompt = format_prompt(
            OBJECTION_HANDLING_PROMPT,
            objection=objection,
            product_info=product_info,
            segment=segment
        )

        try:
            return await self._call_ai(prompt, system=OBJECTION_HANDLING_PROMPT)
        except Exception as e:
            logger.error(f"Error handling objection: {e}")
            return "Agradeço seu feedback. Vou verificar essa questão e retorno em breve."

    async def handle_complaint(
        self,
        complaint: str,
        customer_name: str,
        segment: str,
        product_info: str
    ) -> Dict[str, Any]:
        """Handle customer complaint."""
        prompt = format_prompt(
            COMPLAINT_HANDLETING_PROMPT,
            complaint=complaint,
            customer_name=customer_name,
            segment=segment,
            product_info=product_info
        )

        try:
            response = await self._call_ai(prompt, system=COMPLAINT_HANDLETING_PROMPT)
            return {
                "response": response,
                "requires_refund": "refund" in response.lower(),
                "requires_follow_up": True,
                "priority": "high"
            }
        except Exception as e:
            logger.error(f"Error handling complaint: {e}")
            return {
                "response": "Lamentamos o transtorno. Nossa equipe entrará em contato em breve.",
                "requires_refund": False,
                "requires_follow_up": True,
                "priority": "high"
            }

    async def generate_payment_request(
        self,
        customer_name: str,
        amount: float,
        currency: str,
        description: str
    ) -> Dict[str, Any]:
        """Generate payment link request."""
        prompt = format_prompt(
            PAYMENT_GENERATION_PROMPT,
            customer_name=customer_name,
            amount=amount,
            currency=currency,
            description=description
        )

        try:
            result = await self._call_ai(prompt, system=PAYMENT_GENERATION_PROMPT)
            parsed = json.loads(result)
            return {
                "action": "generate_payment_link",
                "data": parsed,
                "success_message": parsed.get("success_message", "Link de pagamento criado com sucesso!")
            }
        except Exception as e:
            logger.error(f"Error generating payment request: {e}")
            return {
                "action": "generate_payment_link",
                "error": str(e)
            }

    async def get_closing_recommendation(
        self,
        interest_level: str,
        objections_addressed: List[str],
        product_interest: str,
        segment: str
    ) -> Dict[str, Any]:
        """Get sales closing recommendation."""
        prompt = format_prompt(
            SALES_CLOSING_PROMPT,
            interest_level=interest_level,
            objections_addressed=", ".join(objections_addressed),
            product_interest=product_interest,
            segment=segment
        )

        try:
            result = await self._call_ai(prompt, system=SALES_CLOSING_PROMPT)
            return {
                "recommendation": result,
                "technique": self._extract_closing_technique(result),
                "next_steps": self._extract_next_steps(result)
            }
        except Exception as e:
            logger.error(f"Error getting closing recommendation: {e}")
            return {
                "recommendation": None,
                "technique": "direct_close",
                "next_steps": ["Send payment link", "Confirm receipt"]
            }

    def _extract_closing_technique(self, text: str) -> str:
        """Extract the closing technique from AI response."""
        techniques = ["direct_close", "assumptive_close", "trial_close", "consultative_close"]
        for technique in techniques:
            if technique.replace("_", " ") in text.lower():
                return technique
        return "direct_close"

    def _extract_next_steps(self, text: str) -> List[str]:
        """Extract next steps from AI response."""
        # Simple extraction - look for numbered items or bullet points
        steps = re.findall(r'\d+\.\s*([^\n]+)', text)
        return steps if steps else ["Confirm interest", "Send payment link"]

    def clear_conversation(self, customer_id: str):
        """Clear conversation history for a customer."""
        if customer_id in self.conversation_history:
            self.conversation_history[customer_id] = []
        if customer_id in self.blackout_counter:
            self.blackout_counter[customer_id] = 0


# Singleton instance
_agent_instance: Optional[AIAgent] = None


def get_agent() -> AIAgent:
    """Get the singleton AI agent instance."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = AIAgent()
    return _agent_instance
