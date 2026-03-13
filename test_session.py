import logging
import time
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from webdriver_manager.microsoft import EdgeChromiumDriverManager
import requests

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_session():
    # Edge options
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # Start Edge
    driver_path = r"d:\Development\ReadmooChecker\msedgedriver.exe"
    service = Service(driver_path)
    driver = webdriver.Edge(service=service, options=options)

    try:
        # Open login page
        login_url = "https://member.readmoo.com/login/"
        driver.get(login_url)
        logging.info("Browser opened. Please complete login (QR/Passkey).")

        # Wait for login completion (check for redirect or element)
        timeout = 300  # 5 minutes
        for i in range(timeout):
            cookies = driver.get_cookies()
            id_token = None
            for c in cookies:
                if c["name"] == "id_token":
                    id_token = c["value"]
                    break
            if id_token:
                logging.info("Login detected via id_token.")
                break
            if i % 15 == 0:
                logging.info(f"Waiting for login... ({i}s)")
            time.sleep(1)
        else:
            logging.error("Login timeout.")
            return

        # Sync cookies
        session = requests.Session()
        jar = requests.cookies.RequestsCookieJar()
        for c in driver.get_cookies():
            jar.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path"))
        session.cookies = jar

        # Extract id_token
        id_token = None
        for c in driver.get_cookies():
            if c["name"] == "id_token":
                id_token = c["value"]
                break

        # Set headers
        session.headers.update({
            "User-Agent": "ReadmooChecker/1.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
        })

        # Add Authorization if id_token
        if id_token:
            session.headers['Authorization'] = f'Bearer {id_token}'
            logging.info("Added Authorization header.")

        # API request for 1 book
        readings_url = "https://new-read.readmoo.com/api/me/readings?page=1&per_page=1"
        res = session.get(readings_url, timeout=20)
        logging.info(f"API status: {res.status_code}")
        logging.info(f"Response text: {res.text}")

        if res.status_code == 200:
            data = res.json()
            logging.info(f"Parsed data: {data}")

            # Parse one book
            if 'data' in data and 'included' in data:
                included = data.get("included") or []
            elif 'included' in data:
                included = data.get("included") or []
            elif isinstance(data, list):
                included = data
            else:
                included = []

            if included:
                item = included[0]
                title = item.get("title", "unknown")
                author = item.get("author", "unknown")
                logging.info(f"First book: Title='{title}', Author='{author}'")
            else:
                logging.info("No books found.")
        else:
            logging.error("API request failed.")

    finally:
        driver.quit()
        logging.info("Browser closed.")

if __name__ == "__main__":
    test_session()