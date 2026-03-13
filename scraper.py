import logging
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import time

class ReadmooScraper:
    def __init__(self, app):
        logging.info("Initializing ReadmooScraper.")
        self.app = app
        self.driver = webdriver.Edge()
        self.login_url = "https://member.readmoo.com/login"
        self.library_url = "https://read.readmoo.com/#/library/installments"
        logging.info("Browser started.")

    def login(self):
        """
        Opens the login page and waits for the user to log in and
        manually navigate to their library page.
        Returns True if successful, False otherwise.
        """
        logging.info(f"Opening login page: {self.login_url}")
        self.driver.get(self.login_url)
        self.app.update_status("請在瀏覽器中登入，並「手動」導覽至您的書櫃頁面。")

        for i in range(300): # Wait up to 300 seconds (5 minutes)
            try:
                current_url = self.driver.current_url
                logging.debug(f"Waiting for library page. Current URL: {current_url}")
                if "#/library/installments" in current_url:
                    self.app.update_status("偵測到書櫃頁面！")
                    logging.info("Library page detected.")
                    return True
                
                # Update status every 15s to show it's still alive
                if (i > 0) and (i % 15 == 0):
                    self.app.update_status(f"仍在等待您導覽至書櫃... ({i}秒)")
                
                time.sleep(1)
            except Exception as e:
                # This will catch the ConnectionRefusedError if the driver dies
                self.app.update_status(f"與瀏覽器連線中斷，請重啟程式。", error=True)
                logging.error(f"Connection error during login wait: {e}", exc_info=True)
                return False
                
        self.app.update_status("等待您導覽至書櫃頁面超時(5分鐘)。", error=True)
        logging.warning("Timed out waiting for user to navigate to library page.")
        return False

    def get_books(self):
        """
        Assumes driver is already on the library page. It waits for books 
        to load, scrolls down, gets a list of all book URLs, then visits
        each URL in a new tab to scrape the title and author.
        """
        prelim_books = []
        try:
            self.app.update_status("正在等待書櫃資料載入...")
            logging.info("Waiting for book items to be present...")
            wait_selector = ".library-item"
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, wait_selector))
            )
            self.app.update_status("書櫃資料已載入，開始讀取所有書籍...")
            logging.info("Book items found. Starting to scroll.")

            # --- Auto-scroll to load all books ---
            last_height = self.driver.execute_script("return document.body.scrollHeight")
            while True:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                self.app.update_status("正在向下捲動以載入更多書籍...")
                time.sleep(2) 
                new_height = self.driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            self.app.update_status("已載入所有書籍，正在分析書單...")
            logging.info("Finished scrolling. Getting page source.")
            
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, "html.parser")
            
            book_items = soup.select(".library-item")
            logging.info(f"Found {len(book_items)} book items to process.")

            for item in book_items:
                title_element = item.select_one(".title")
                link_element = item.select_one("a.reader-link")

                title = title_element['title'].strip() if title_element and title_element.has_attr('title') else "標題不明"
                url = link_element['href'] if link_element and link_element.has_attr('href') else None
                
                if url:
                    # The link is to the reader API, which can be protected.
                    # Let's transform it into a likely product page URL.
                    if "/api/reader/" in url:
                        url = url.replace("/api/reader/", "/book/")
                        logging.debug(f"Transformed URL to: {url}")

                    # Make sure URL is absolute
                    if url.startswith('/'):
                        url = "https://read.readmoo.com" + url
                    prelim_books.append({"title": title, "url": url})

        except Exception as e:
            self.app.update_status(f"擷取書本列表時發生錯誤: {e}", error=True)
            logging.error(f"An unexpected error occurred in get_books initial phase: {e}", exc_info=True)
            return []

        # --- Get Authors for each book in a new tab ---
        final_books = []
        total_books = len(prelim_books)
        main_window = self.driver.current_window_handle

        for i, book in enumerate(prelim_books):
            self.app.update_status(f"正在擷取作者... ({i+1}/{total_books})")
            author = "作者不明"
            try:
                # Open a new tab
                self.driver.execute_script("window.open('');")
                # Switch to the new tab
                self.driver.switch_to.window(self.driver.window_handles[1])
                self.driver.get(book['url'])
                
                author_selector = "span[itemprop='author']"
                author_element = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, author_selector))
                )
                author = author_element.text.strip()
                logging.info(f"Found author '{author}' for {book['title']}")

            except Exception as e:
                logging.warning(f"Could not get author for {book['title']} at {book['url']}: {e}")
            finally:
                # Close the new tab and switch back to the main window
                if len(self.driver.window_handles) > 1:
                    self.driver.close()
                    self.driver.switch_to.window(main_window)

            final_books.append({"title": book['title'], "author": author})
            
        logging.info(f"Successfully extracted details for {len(final_books)} books.")
        return final_books

    def quit(self):
        """Closes the browser gracefully."""
        self.app.update_status("正在關閉瀏覽器...")
        logging.info("Closing browser.")
        if self.driver:
            try:
                self.driver.quit()
                logging.info("Browser quit successfully.")
            except TimeoutException:
                self.app.update_status("關閉瀏覽器超時。", error=True)
                logging.error("TimeoutException while quitting browser.", exc_info=True)
            except Exception as e:
                # This can happen if the browser was already closed manually.
                self.app.update_status(f"關閉瀏覽器時發生錯誤 (可能已手動關閉)", error=True)
                logging.error(f"Error quitting browser: {e}", exc_info=True)
            finally:
                self.driver = None

if __name__ == '__main__':
    # For testing the scraper independently
    # Note: The app GUI is needed to display status updates.
    # This standalone test will only print to console/log.
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    class MockApp:
        def update_status(self, text, error=False):
            print(f"STATUS: {text}" + (" (ERROR)" if error else ""))

    scraper = ReadmooScraper(MockApp())
    try:
        if scraper.login():
            scraper.get_books()
    finally:
        scraper.quit()
