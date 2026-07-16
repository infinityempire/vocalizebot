"""
ReplyQ AI Agent - LinkedIn Integration Unit Tests
"""
import pytest
import json
from unittest.mock import MagicMock, patch, mock_open, AsyncMock
from selenium import webdriver

from src.channels.linkedin import LinkedInAutomationAgent
from src.database.models import Customer, Conversation, Message, MessageDirection, MessageType, CustomerSegment

# Set up test environment variables
import os
os.environ["ALLOWED_ORIGINS"] = '["*"]'

class TestLinkedInAutomationAgent:
    """Tests for the LinkedInAutomationAgent."""

    @patch("src.channels.linkedin.webdriver.Chrome")
    @patch("src.channels.linkedin.Service")
    def test_setup_driver(self, mock_service, mock_chrome):
        """Test that ChromeDriver is initialized with proper headless options."""
        agent = LinkedInAutomationAgent()
        driver = agent.setup_driver()
        
        assert driver is not None
        mock_chrome.assert_called_once()
        
        # Verify chrome options are passed correctly
        called_args, called_kwargs = mock_chrome.call_args
        options = called_kwargs.get("options") or called_args[1]
        assert "--headless" in options.arguments
        assert "--no-sandbox" in options.arguments
        assert "--disable-dev-shm-usage" in options.arguments

    @patch("src.channels.linkedin.os.path.exists")
    @patch("src.channels.linkedin.webdriver.Chrome")
    def test_inject_cookies(self, mock_chrome, mock_exists):
        """Test cookie loading and browser injection logic."""
        mock_exists.return_value = True
        
        cookie_data = [
            {"name": "li_at", "value": "test_li_at", "domain": ".linkedin.com"},
            {"name": "JSESSIONID", "value": "test_jsessionid", "domain": ".linkedin.com"},
            {"name": "other_cookie", "value": "val", "domain": ".other.com"}
        ]
        
        with patch("builtins.open", mock_open(read_data=json.dumps(cookie_data))):
            agent = LinkedInAutomationAgent()
            agent.driver = mock_chrome
            
            success = agent.inject_cookies()
            assert success is True
            
            # Should first navigate to linkedin
            mock_chrome.get.assert_any_call("https://www.linkedin.com")
            
            # Should call add_cookie for linkedin cookies but skip other domains
            assert mock_chrome.add_cookie.call_count >= 2
            
            # Verify details of injected cookies
            added_cookie_names = [call.args[0]["name"] for call in mock_chrome.add_cookie.call_args_list]
            assert "li_at" in added_cookie_names
            assert "JSESSIONID" in added_cookie_names
            assert "other_cookie" not in added_cookie_names  # domain is not linkedin.com

    @patch("src.channels.linkedin.webdriver.Chrome")
    def test_verify_session_success(self, mock_chrome):
        """Test successful session verification when on feed page."""
        agent = LinkedInAutomationAgent()
        agent.driver = mock_chrome
        
        mock_chrome.current_url = "https://www.linkedin.com/feed/"
        mock_chrome.title = "Feed | LinkedIn"
        mock_chrome.page_source = "<html><body><div id='feed-container'>Feed posts</div></body></html>"
        
        assert agent.verify_session() is True

    @patch("src.channels.linkedin.webdriver.Chrome")
    def test_verify_session_expired(self, mock_chrome):
        """Test failed session verification when redirected to login page."""
        agent = LinkedInAutomationAgent()
        agent.driver = mock_chrome
        
        mock_chrome.current_url = "https://www.linkedin.com/login"
        mock_chrome.title = "LinkedIn: Log In or Sign Up"
        mock_chrome.page_source = "<html><body>Sign In to LinkedIn</body></html>"
        
        assert agent.verify_session() is False

    @pytest.mark.anyio
    @patch("src.channels.linkedin.get_db_context")
    async def test_get_or_create_customer(self, mock_db_context):
        """Test retrieval or creation of a customer object."""
        # Setup mock db session
        mock_session = AsyncMock()
        mock_db_context.return_value.__aenter__.return_value = mock_session
        
        # Mocking sqlalchemy scalar_one_or_none
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Force new customer creation
        mock_session.execute.return_value = mock_result
        
        agent = LinkedInAutomationAgent()
        customer = await agent.get_or_create_customer("test_user_123", "John Doe")
        
        assert customer is not None
        assert customer.name == "John Doe"
        assert customer.instagram_handle == "li_test_user_123"
        assert customer.segment == CustomerSegment.B2B
        
        # Verify it added the customer to the session
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()
