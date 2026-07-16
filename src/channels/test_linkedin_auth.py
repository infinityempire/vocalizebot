"""
Temporary script to test LinkedIn authentication using cookies.json.
"""
import json
import time
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from loguru import logger

def test_auth():
    cookies_path = "cookies.json"
    
    # Configure Chrome
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.binary_location = "/data/data/com.termux/files/usr/bin/chromium-browser"
    
    service = Service("/data/data/com.termux/files/usr/bin/chromedriver")
    
    logger.info("Initializing ChromeDriver...")
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        # Load cookies
        logger.info(f"Loading cookies from {cookies_path}...")
        with open(cookies_path, "r") as f:
            cookies = json.load(f)
            
        # Navigate to LinkedIn first
        logger.info("Navigating to LinkedIn home page to set domain context...")
        driver.get("https://www.linkedin.com")
        time.sleep(3)
        
        # Inject cookies
        logger.info("Injecting cookies...")
        for cookie in cookies:
            cookie_dict = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain", ".linkedin.com"),
                "path": cookie.get("path", "/"),
                "secure": cookie.get("secure", True),
            }
            if "expirationDate" in cookie:
                cookie_dict["expiry"] = int(cookie["expirationDate"])
            
            # Filter domain to ensure it's valid for the current page
            # If domain ends with .linkedin.com or www.linkedin.com, keep it
            domain = cookie_dict["domain"]
            if not (domain.endswith("linkedin.com") or domain.endswith("linkedin.com.")):
                continue
                
            try:
                driver.add_cookie(cookie_dict)
            except Exception as e:
                # logger.debug(f"Skipping cookie {cookie['name']}: {e}")
                pass
                
        # Wait a bit
        time.sleep(2)
        
        # Navigate directly to the feed
        logger.info("Navigating to https://www.linkedin.com/feed/...")
        driver.get("https://www.linkedin.com/feed/")
        time.sleep(5)
        
        # Check if we are logged in successfully
        current_url = driver.current_url
        logger.info(f"Current URL: {current_url}")
        
        # Verify the session is active
        # We look for indicators that we're on the feed:
        # - URL contains 'linkedin.com/feed'
        # - Page source contains "feed" elements, or profile details
        # Let's inspect the page title and some page content
        title = driver.title
        logger.info(f"Page Title: {title}")
        
        if "feed" in current_url or "Feed" in title:
            logger.success("Verification successful! Session is active and authenticated.")
        else:
            logger.error("Verification failed! Redirection or login block detected.")
            if "login" in current_url or "signin" in current_url:
                logger.error("Session expired. Please update cookies.json using MacroDroid.")
            else:
                logger.error(f"Unexpected page detected: {current_url}")
                
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    test_auth()
