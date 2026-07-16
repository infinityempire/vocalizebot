"""
ReplyQ AI Agent - LinkedIn Automation Channel
Integrated Selenium-based autonomous LinkedIn message poll and response.
"""
import os
import json
import time
import random
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from loguru import logger
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from config.settings import get_settings
from src.agents.core import get_agent
from src.database.connection import get_db_context
from src.database.models import Customer, Conversation, Message, MessageDirection, MessageType, CustomerSegment, BlackoutStatus

settings = get_settings()

class LinkedInAutomationAgent:
    """
    Autonomous LinkedIn Automation Agent for ReplyQ.
    Uses Selenium with pre-authenticated session cookies to safely read and reply to messages.
    """

    def __init__(self, cookies_path: str = "cookies.json"):
        self.cookies_path = cookies_path
        self.driver: Optional[webdriver.Chrome] = None
        self.settings = settings
        self.agent = get_agent()

    def _get_random_delay(self, min_sec: float = 5.0, max_sec: float = 15.0) -> float:
        """Generate a human-like delay between min_sec and max_sec."""
        return random.uniform(min_sec, max_sec)

    def _human_delay(self, min_sec: float = 5.0, max_sec: float = 15.0):
        """Sleep for a random human-like delay."""
        delay = self._get_random_delay(min_sec, max_sec)
        logger.debug(f"Adding human-like delay of {delay:.2f} seconds...")
        time.sleep(delay)

    def setup_driver(self) -> webdriver.Chrome:
        """Set up and configure Chrome WebDriver for Termux/headless environment."""
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1200,800")
        
        # Point to Termux-installed Chromium and ChromeDriver binaries
        options.binary_location = "/data/data/com.termux/files/usr/bin/chromium-browser"
        service = Service("/data/data/com.termux/files/usr/bin/chromedriver")
        
        logger.info("Initializing Chromium WebDriver...")
        self.driver = webdriver.Chrome(service=service, options=options)
        return self.driver

    def inject_cookies(self) -> bool:
        """Load and inject authentication cookies from cookies.json."""
        if not os.path.exists(self.cookies_path):
            logger.error(f"Cookies file not found at: {self.cookies_path}")
            return False

        try:
            with open(self.cookies_path, "r") as f:
                cookies = json.load(f)
        except Exception as e:
            logger.error(f"Failed to parse cookies.json: {e}")
            return False

        logger.info("Navigating to LinkedIn to establish domain context...")
        self.driver.get("https://www.linkedin.com")
        self._human_delay(3.0, 5.0)

        logger.info(f"Injecting {len(cookies)} cookies from cookies.json into the browser context...")
        li_at_found = False
        jsessionid_found = False

        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if name == "li_at":
                li_at_found = True
            if name == "JSESSIONID":
                jsessionid_found = True

            cookie_dict = {
                "name": name,
                "value": value,
                "domain": cookie.get("domain", ".linkedin.com"),
                "path": cookie.get("path", "/"),
                "secure": cookie.get("secure", True),
            }
            if "expirationDate" in cookie:
                cookie_dict["expiry"] = int(cookie["expirationDate"])

            # Filter out non-LinkedIn domains to avoid driver errors
            domain = cookie_dict["domain"]
            if not (domain.endswith("linkedin.com") or domain.endswith("linkedin.com.")):
                continue

            try:
                self.driver.add_cookie(cookie_dict)
            except Exception as e:
                # Silently ignore individual cookie errors (such as domain mismatch warnings)
                pass

        if not li_at_found or not jsessionid_found:
            logger.warning("Both 'li_at' and 'JSESSIONID' auth cookies should be present in cookies.json.")
        
        logger.info("Cookies successfully injected.")
        return True

    def verify_session(self) -> bool:
        """Verify if the LinkedIn session is active by navigating directly to feed."""
        logger.info("Verifying session by navigating directly to https://www.linkedin.com/feed/...")
        self.driver.get("https://www.linkedin.com/feed/")
        self._human_delay(5.0, 10.0)

        current_url = self.driver.current_url
        title = self.driver.title
        logger.info(f"Current URL: {current_url}")
        logger.info(f"Page Title: {title}")

        # Check for expired/redirected state
        if "login" in current_url or "signin" in current_url or "checkpoint" in current_url:
            logger.error("Session expired. Please update cookies.json using MacroDroid.")
            return False

        # Check if page looks authenticated (contains feed indicators, home, search, messaging, etc.)
        page_source_lower = self.driver.page_source.lower()
        if "feed" in current_url or "feed" in page_source_lower or "messaging" in page_source_lower:
            logger.success("LinkedIn session is active and verified! Authentication successful.")
            return True
        
        logger.error("Session verification failed. Unable to find feed elements.")
        logger.error("Session expired. Please update cookies.json using MacroDroid.")
        return False

    async def get_or_create_customer(self, linkedin_id: str, full_name: str) -> Customer:
        """Get existing customer or create a new one from LinkedIn connection."""
        async with get_db_context() as session:
            from sqlalchemy import select
            import hashlib
            
            # Find existing customer by linkedin_handle or ID
            stmt = select(Customer).where(Customer.instagram_handle == f"li_{linkedin_id}")
            result = await session.execute(stmt)
            customer = result.scalar_one_or_none()
            
            if not customer:
                # Create new customer
                customer = Customer(
                    id=f"li_{hashlib.md5(linkedin_id.encode()).hexdigest()[:12]}",
                    name=full_name,
                    instagram_handle=f"li_{linkedin_id}",  # Reusing handle fields for tracking
                    segment=CustomerSegment.B2B,  # LinkedIn defaults to B2B
                    lead_score=self.settings.initial_lead_score
                )
                session.add(customer)
                await session.commit()
                await session.refresh(customer)
                logger.info(f"Created new B2B customer profile for: {full_name}")
            
            return customer

    async def get_or_create_conversation(self, customer: Customer, conversation_id: str) -> Conversation:
        """Get active conversation or create new one."""
        async with get_db_context() as session:
            from sqlalchemy import select
            import hashlib
            
            # Find active conversation
            stmt = select(Conversation).where(
                Conversation.customer_id == customer.id,
                Conversation.channel == "linkedin",
                Conversation.is_active == True
            )
            result = await session.execute(stmt)
            conversation = result.scalar_one_or_none()
            
            if not conversation:
                conversation = Conversation(
                    id=f"conv_li_{hashlib.md5(conversation_id.encode()).hexdigest()[:12]}",
                    customer_id=customer.id,
                    channel="linkedin",
                    channel_id=conversation_id
                )
                session.add(conversation)
                await session.commit()
                await session.refresh(conversation)
                logger.info(f"Started new LinkedIn conversation flow for {customer.name}")
            
            return conversation

    async def store_message(
        self,
        conversation_id: str,
        direction: MessageDirection,
        message_type: MessageType,
        content: str,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
        ai_response: Optional[str] = None
    ) -> Message:
        """Store a message in the database."""
        async with get_db_context() as session:
            import hashlib
            message = Message(
                id=f"msg_li_{hashlib.md5((content + str(time.time())).encode()).hexdigest()[:12]}",
                conversation_id=conversation_id,
                direction=direction,
                message_type=message_type,
                content=content,
                intent_detected=intent,
                confidence=confidence,
                ai_response=ai_response
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return message

    def poll_and_respond(self) -> int:
        """
        Poll the LinkedIn messaging system for unread messages and reply.
        Returns the count of processed/replied messages.
        """
        logger.info("Navigating to LinkedIn Messaging...")
        self.driver.get("https://www.linkedin.com/messaging/")
        self._human_delay(5.0, 10.0)

        # Check if we are blocked/redirected
        if "login" in self.driver.current_url or "signin" in self.driver.current_url:
            logger.error("Session expired. Please update cookies.json using MacroDroid.")
            return 0

        # Try to locate message list elements
        try:
            # Wait for conversation list to load
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.CLASS_NAME, "msg-conversations-container__conversations-list"))
            )
        except Exception:
            logger.warning("Could not find messaging container. It might be empty or in a different layout.")
            return 0

        # Find all unread conversation threads
        # LinkedIn marks unread conversations with a bold class or indicator e.g. "msg-conversation-card--unread"
        unread_cards = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'msg-conversation-card--unread')]")
        if not unread_cards:
            logger.info("No unread LinkedIn messages found.")
            return 0

        logger.info(f"Found {len(unread_cards)} unread conversation thread(s).")
        replies_sent = 0

        for card in unread_cards:
            try:
                # Highlight and click card to select the conversation thread
                self.driver.execute_script("arguments[0].scrollIntoView(true);", card)
                self._human_delay(1.0, 3.0)
                card.click()
                logger.info("Clicked on unread conversation card.")
                self._human_delay(3.0, 6.0)

                # Get Connection Name
                name_element = card.find_element(By.CLASS_NAME, "msg-conversation-card__participant-names")
                connection_name = name_element.text.strip()
                logger.info(f"Active conversation connection: {connection_name}")

                # Extract conversation ID or thread ID from URL or attributes
                current_url = self.driver.current_url
                # URL structure is usually like https://www.linkedin.com/messaging/thread/2-YmFiNDZi...
                thread_id = "unknown_thread"
                if "/thread/" in current_url:
                    thread_id = current_url.split("/thread/")[-1].split("/")[0]
                logger.info(f"Thread ID detected: {thread_id}")

                # Get the last incoming message
                # Find the message bubble elements
                message_bubbles = self.driver.find_elements(By.CLASS_NAME, "msg-s-event-listitem__body")
                if not message_bubbles:
                    logger.warning("No message bubbles found in this thread.")
                    continue

                last_message_text = message_bubbles[-1].text.strip()
                logger.info(f"Last received message: '{last_message_text}'")

                # Process the message through our AI Agent asynchronously
                # Since poll_and_respond is run in a synchronous loop, we'll run the async db operations & AI agent inside it
                loop = asyncio.get_event_loop()
                customer = loop.run_until_complete(self.get_or_create_customer(thread_id, connection_name))
                conversation = loop.run_until_complete(self.get_or_create_conversation(customer, thread_id))

                # Store incoming message in DB
                loop.run_until_complete(self.store_message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.INBOUND,
                    message_type=MessageType.TEXT,
                    content=last_message_text
                ))

                # Update customer interaction
                async def update_customer_db():
                    async with get_db_context() as session:
                        from sqlalchemy import select
                        stmt = select(Customer).where(Customer.id == customer.id)
                        res = await session.execute(stmt)
                        db_cust = res.scalar_one_or_none()
                        if db_cust:
                            db_cust.last_interaction = datetime.utcnow()
                            db_cust.blackout_count = 0
                            db_cust.blackout_status = BlackoutStatus.NORMAL
                            await session.commit()
                loop.run_until_complete(update_customer_db())

                # Query AI Response
                logger.info("Consulting omni-intent AIAgent for response...")
                context = {
                    "customer_name": customer.name or connection_name,
                    "customer_id": customer.id,
                    "segment": customer.segment.value,
                    "lead_score": customer.lead_score,
                    "channel": "linkedin"
                }

                ai_result = loop.run_until_complete(self.agent.get_ai_response(
                    message=last_message_text,
                    customer_id=customer.id,
                    context=context
                ))

                response_text = ai_result["message"]
                logger.info(f"AI generated response: '{response_text}'")

                # Store Outbound response in DB
                loop.run_until_complete(self.store_message(
                    conversation_id=conversation.id,
                    direction=MessageDirection.OUTBOUND,
                    message_type=MessageType.TEXT,
                    content=response_text,
                    intent=ai_result.get("intent"),
                    confidence=ai_result.get("confidence"),
                    ai_response=response_text
                ))

                # Locate the reply text area and type the response
                # On LinkedIn, the message box can be located by class msg-form__contenteditable
                logger.info("Locating the message box and typing the response...")
                reply_box = self.driver.find_element(By.CLASS_NAME, "msg-form__contenteditable")
                reply_box.click()
                self._human_delay(1.0, 2.0)
                
                # Clear and send keys
                reply_box.send_keys(response_text)
                self._human_delay(2.0, 4.0)

                # Find the Send button
                # The send button is typically msg-form__send-button or button with type 'submit'
                send_button = self.driver.find_element(By.XPATH, "//button[contains(@class, 'msg-form__send-button')]")
                
                # Verify we aren't clicking Log In/Sign In buttons
                if "Log In" in send_button.text or "Sign In" in send_button.text:
                    logger.error("Safety constraint triggered: Refusing to click authentication button.")
                    continue

                logger.info("Clicking the Send button...")
                send_button.click()
                replies_sent += 1
                logger.success(f"Successfully sent reply to {connection_name}.")

                # Add a safe random interval between distinct conversation responses
                self._human_delay(5.0, 15.0)

            except Exception as ex:
                logger.error(f"Error processing card/thread: {ex}")
                continue

        return replies_sent

    def run_once(self) -> bool:
        """Run a single execution loop of the LinkedIn Automation Agent."""
        try:
            self.setup_driver()
            if not self.inject_cookies():
                return False

            if not self.verify_session():
                return False

            # Success, perform the messaging polling and automated replying action
            replies = self.poll_and_respond()
            logger.info(f"Completed run. Autonomously sent {replies} reply/replies.")
            return True
        except Exception as e:
            logger.exception(f"Automation execution run failed: {e}")
            return False
        finally:
            if self.driver:
                logger.info("Closing Chrome browser driver safely...")
                self.driver.quit()

if __name__ == "__main__":
    # Quick CLI invocation of the automation agent
    agent = LinkedInAutomationAgent()
    agent.run_once()
