import logging
import time
from typing import Any, Dict, List

import requests
from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.common.exceptions import WebDriverException


class ReadmooScraper:
    def __init__(self, app, driver_path: str = None):
        logging.info("Initializing ReadmooScraper.")
        self.app = app
        self.driver_path = driver_path
        self.driver = None
        self.id_token = None

        self.session = requests.Session()
        self.login_url = "https://member.readmoo.com/login/"
        self.session.headers.update({
            "User-Agent": "ReadmooChecker/1.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        })

    def _sync_cookies_to_session(self):
        if not self.driver:
            return

        jar = requests.cookies.RequestsCookieJar()
        for c in self.driver.get_cookies():
            jar.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path"))
        self.session.cookies = jar

    def check_login(self) -> bool:
        """Check if login is successful by testing API access."""
        try:
            # Extract id_token if available
            id_token = None
            id_token_cookie_name = 'CognitoIdentityServiceProvider.1vo6drk6c6ma7htam496pnrkdr.b724da08-2091-70f4-914c-4dc4806a1e1e.idToken'
            for c in self.driver.get_cookies():
                if c["name"] == id_token_cookie_name:
                    id_token = c["value"]
                    break

            headers = self.session.headers.copy()
            if id_token:
                headers['Authorization'] = f'Bearer {id_token}'

            test_url = "https://new-read.readmoo.com/api/me/readings?page=1&per_page=1"
            res = requests.get(test_url, headers=headers, cookies=self.session.cookies, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if 'included' in data and len(data['included']) > 0:
                    return True
        except Exception as e:
            logging.debug(f"Login check failed: {e}")
        return False

    def login(self) -> bool:
        """Use a browser to let the user login (QR/Passkey), then copy cookies into requests.Session."""
        self.app.update_status("正在啟動瀏覽器，請完成登入（可掃 QR / 使用 Passkey）。")
        logging.info("Starting browser for login...")

        try:
            options = Options()
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)

            driver_path = r"d:\Development\ReadmooChecker\msedgedriver.exe"
            service = Service(driver_path)
            self.driver = webdriver.Edge(service=service, options=options)
        except WebDriverException as e:
            logging.error("Failed to start Edge WebDriver.", exc_info=True)
            self.app.update_status("啟動瀏覽器失敗，請確認 msedgedriver.exe 位於專案目錄。", error=True)
            return False

        try:
            self.driver.get(self.login_url)

            for i in range(300):  # wait up to 5 minutes
                try:
                    # Sync cookies periodically so we can use them for API checks
                    self._sync_cookies_to_session()
                    if self.check_login():
                        self.app.update_status("登入成功！正在取得書單...")
                        # Extract idToken before quitting browser
                        id_token_cookie_name = 'CognitoIdentityServiceProvider.1vo6drk6c6ma7htam496pnrkdr.b724da08-2091-70f4-914c-4dc4806a1e1e.idToken'
                        for c in self.driver.get_cookies():
                            if c["name"] == id_token_cookie_name:
                                self.id_token = c["value"]
                                logging.info("Extracted idToken from browser cookies.")
                                break
                        # Close browser immediately after successful login
                        self.driver.quit()
                        self.driver = None
                        return True

                    current_url = self.driver.current_url
                    if "#/library" in current_url or "/library" in current_url:
                        # sometimes the URL changes after login even though cookies are not yet valid
                        self._sync_cookies_to_session()
                        if self.check_login():
                            self.app.update_status("登入成功！正在取得書單...")
                            # Extract idToken
                            id_token_cookie_name = 'CognitoIdentityServiceProvider.1vo6drk6c6ma7htam496pnrkdr.b724da08-2091-70f4-914c-4dc4806a1e1e.idToken'
                            for c in self.driver.get_cookies():
                                if c["name"] == id_token_cookie_name:
                                    self.id_token = c["value"]
                                    logging.info("Extracted idToken from browser cookies.")
                                    break
                            # Close browser
                            self.driver.quit()
                            self.driver = None
                            return True

                    if (i > 0) and (i % 15 == 0):
                        self.app.update_status(f"請完成登入（QR/Passkey），等待中... ({i}秒)")

                    time.sleep(1)
                except WebDriverException as e:
                    logging.error(f"WebDriver error during login wait: {e}", exc_info=True)
                    self.app.update_status("瀏覽器已中斷，請重啟程式。", error=True)
                    return False

            self.app.update_status("登入超時（5 分鐘），請再試一次。", error=True)
            logging.warning("Login timeout after waiting for user to complete authentication.")
            return False
        finally:
            # Close browser once cookies are captured (or on failure)
            self.quit()

    def check_login(self) -> bool:
        try:
            res = self.session.get(self.readings_url, timeout=20)
            if res.status_code != 200:
                return False

            data = res.json()
            if isinstance(data, dict) and data.get("status") == "error_login":
                return False
            return True
        except Exception:
            return False

    def get_books(self) -> List[Dict[str, str]]:
        self.app.update_status("正在取得已購書清單...")
        logging.info("Fetching readings API...")

        # Add Authorization header with idToken
        if self.id_token:
            self.session.headers['Authorization'] = f'Bearer {self.id_token}'
            logging.info("Added Authorization header with idToken.")
        else:
            logging.warning("idToken not available.")

        books: List[Dict[str, str]] = []
        page = 1
        per_page = 100

        while True:
            url = f"https://new-read.readmoo.com/api/me/readings?page={page}&per_page={per_page}"
            logging.info(f"Fetching page {page}...")

            try:
                res = self.session.get(url, timeout=20)
                logging.info(f"API response status: {res.status_code}")
                res.raise_for_status()
                data = res.json()
                logging.info(f"Parsed data for page {page}: {data}")
            except Exception as e:
                logging.error(f"Failed to fetch readings page {page}: {e}", exc_info=True)
                self.app.update_status("無法取得書單，請稍後再試。", error=True)
                return books  # Return what we have so far

            # Parse included
            if 'data' in data and 'included' in data:
                included = data.get("included") or []
            elif 'included' in data:
                included = data.get("included") or []
            elif isinstance(data, list):
                included = data
            else:
                included = []

            logging.info(f"Page {page}: found {len(included)} items")

            for item in included:
                item_type = item.get("type", "")
                if "book" not in item_type:
                    continue
                title = item.get("title", "標題不明").strip()
                author = item.get("author", "作者不明").strip()
                books.append({"title": title, "author": author})

            # If less than per_page, no more pages
            if len(included) < per_page:
                break
            page += 1

        logging.info(f"Total books extracted: {len(books)}")
        return books

    def quit(self):
        """Closes the browser gracefully (if it was opened)."""
        if self.driver:
            try:
                self.app.update_status("正在關閉瀏覽器...")
                logging.info("Closing browser.")
                self.driver.quit()
            except Exception as e:
                logging.error(f"Error quitting browser: {e}", exc_info=True)
            finally:
                self.driver = None


if __name__ == '__main__':
    # For testing the scraper independently
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    class MockApp:
        def update_status(self, text, error=False):
            print(f"STATUS: {text}" + (" (ERROR)" if error else ""))

    scraper = ReadmooScraper(MockApp())
    try:
        if scraper.login():
            books = scraper.get_books()
            print(books)
    finally:
        scraper.quit()
