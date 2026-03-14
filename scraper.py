import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, cast

import requests
from selenium.webdriver.edge.webdriver import WebDriver as Edge
from requests.cookies import RequestsCookieJar
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.common.exceptions import WebDriverException
from urllib.parse import urlparse


class ReadmooScraper:
    def __init__(self, app, driver_path: Optional[str] = None):
        """Initialise the scraper.

        Args:
            app: The GUI application object; must expose ``update_status(text, error=False)``.
            driver_path: Optional explicit path to ``msedgedriver.exe``. When *None* the
                driver is located automatically via :meth:`_resolve_driver_path`.
        """
        logging.info("Initializing ReadmooScraper.")
        self.app = app
        self.driver_path = driver_path
        self.driver: Any = None
        self.id_token: Optional[str] = None

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
        # API endpoint used to verify login and to fetch the book list.
        self.readings_url = "https://new-read.readmoo.com/api/me/readings"

    def _resolve_driver_path(self) -> Optional[str]:
        """Resolve Edge driver path.

        Priority:
        1. User-provided driver_path
        2. msedgedriver.exe in project directory (same folder as this file)
        3. None (let Selenium Manager handle it)
        """
        if self.driver_path:
            return self.driver_path

        local_driver = Path(__file__).resolve().parent / "msedgedriver.exe"
        if local_driver.exists():
            return str(local_driver)

        return None

    def _extract_included_items(self, data: Any) -> List[Dict[str, Any]]:
        """Normalise a raw API payload into a flat list of item dicts.

        Handles the various response shapes returned by the Readmoo API
        (top-level ``included``, nested ``data.included``, plain ``data`` list,
        and bare lists).
        """
        included: List[Dict[str, Any]] = []
        if isinstance(data, dict):
            raw_included = data.get("included")
            raw_data = data.get("data")
            if isinstance(raw_included, list):
                included = cast(List[Dict[str, Any]], raw_included)
            elif isinstance(raw_data, dict):
                nested_included = raw_data.get("included")
                if isinstance(nested_included, list):
                    included = cast(List[Dict[str, Any]], nested_included)
            elif isinstance(raw_data, list):
                included = cast(List[Dict[str, Any]], raw_data)
        elif isinstance(data, list):
            included = [item for item in data if isinstance(item, dict)]
        return [item for item in included if isinstance(item, dict)]

    def _extract_book_ids(self, data: Any) -> List[str]:
        """Return the string IDs of all book-type items found in a raw API payload."""
        book_ids: List[str] = []
        for item in self._extract_included_items(data):
            item_type = item.get("type", "")
            item_id = item.get("id")
            if "book" in item_type and item_id:
                book_ids.append(str(item_id))
        return book_ids

    def _browser_fetch_payload(self, params: Dict[str, Any]) -> Any:
        """Execute a credentialed ``fetch()`` inside the live browser page and return the JSON payload.

        Uses ``execute_async_script`` so the browser's own session cookies are included
        automatically, bypassing CORS restrictions that would block a plain ``requests`` call.

        Args:
            params: Query parameters to append to :attr:`readings_url`.

        Returns:
            The parsed JSON response body.

        Raises:
            RuntimeError: If the browser driver is unavailable or the HTTP request fails.
        """
        if not self.driver:
            raise RuntimeError("Browser driver is not available for in-page fetch.")

        script = """
const url = arguments[0];
const params = arguments[1];
const done = arguments[arguments.length - 1];
const search = new URLSearchParams();
for (const [key, value] of Object.entries(params || {})) {
  if (value !== undefined && value !== null) {
    search.set(key, String(value));
  }
}
const requestUrl = search.toString() ? `${url}?${search.toString()}` : url;
fetch(requestUrl, {
  credentials: 'include',
  headers: {
    'Accept': 'application/json, text/plain, */*'
  }
}).then(async (response) => {
  const text = await response.text();
  try {
    done({ ok: response.ok, status: response.status, data: JSON.parse(text) });
  } catch (error) {
    done({ ok: response.ok, status: response.status, text });
  }
}).catch((error) => {
  done({ ok: false, status: 0, error: String(error) });
});
"""

        result = self.driver.execute_async_script(script, self.readings_url, params)
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected browser fetch result: {type(result)}")
        if not result.get("ok"):
            raise RuntimeError(
                f"Browser fetch failed (status={result.get('status')}): "
                f"{result.get('error') or result.get('text') or 'unknown error'}"
            )
        return result.get("data")

    def _build_browser_paging_strategies(self, per_page: int) -> List[Tuple[str, Callable[[int], Dict[str, Any]]]]:
        """Return a list of candidate paging strategies as ``(name, param_builder)`` tuples.

        Each ``param_builder`` is a callable that accepts a 1-based page number and returns
        the corresponding query-parameter dict for :attr:`readings_url`.
        """
        return [
            ("page_per_page", lambda page_number: {"page": page_number, "per_page": per_page}),
            ("page_limit", lambda page_number: {"page": page_number, "limit": per_page}),
            ("offset_per_page", lambda page_number: {"offset": (page_number - 1) * per_page, "per_page": per_page}),
            ("offset_limit", lambda page_number: {"offset": (page_number - 1) * per_page, "limit": per_page}),
            ("start_limit", lambda page_number: {"start": (page_number - 1) * per_page, "limit": per_page}),
        ]

    def _detect_browser_paging_strategy(self, per_page: int) -> Optional[Tuple[str, Callable[[int], Dict[str, Any]], Any]]:
        """Probe the API to discover which pagination strategy it supports.

        Fetches pages 1 and 2 with each candidate strategy and picks the first one
        that returns distinct, non-empty results on each page.

        Returns:
            A ``(strategy_name, param_builder, first_page_payload)`` tuple when a
            working strategy is found, or *None* if all strategies fail.
        """
        strategies = self._build_browser_paging_strategies(per_page)
        for strategy_name, builder in strategies:
            try:
                first_payload = self._browser_fetch_payload(builder(1))
                second_payload = self._browser_fetch_payload(builder(2))
            except Exception as exc:
                logging.debug(f"Browser strategy {strategy_name} failed during probe: {exc}")
                continue

            first_ids = self._extract_book_ids(first_payload)
            second_ids = self._extract_book_ids(second_payload)
            if not first_ids or not second_ids:
                logging.debug(f"Browser strategy {strategy_name} returned no book ids during probe.")
                continue

            if set(second_ids) - set(first_ids):
                logging.info(f"Using browser paging strategy: {strategy_name}")
                return strategy_name, builder, first_payload

            logging.debug(f"Browser strategy {strategy_name} returned duplicate page 2 during probe.")

        return None

    def _sync_cookies_to_session(self):
        """Copy the current browser cookies into :attr:`session` so requests can reuse the authenticated state."""
        if not self.driver:
            return

        jar = RequestsCookieJar()
        for c in self.driver.get_cookies():
            jar.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path"))
        self.session.cookies = jar

    def check_login(self) -> bool:
        """Check if login is successful by checking URL for library or completion."""
        try:
            current_url = self.driver.current_url
            logging.info(f"check_login: current_url={current_url}")
            parsed = urlparse(current_url)
            host = parsed.hostname or ""
            path = parsed.path or ""
            fragment = parsed.fragment or ""
            route_text = f"{path}#{fragment}" if fragment else path
            is_readmoo_host = host == "readmoo.com" or host.endswith(".readmoo.com")
            has_library_in_path = "library" in route_text
            on_auth_path = "auth" in route_text
            if has_library_in_path or (is_readmoo_host and not on_auth_path):
                logging.info("Login successful, URL indicates completion.")
                return True
            logging.debug("Login not detected, still on auth page.")
            return False
        except Exception as e:
            logging.error(f"Error in check_login: {e}")
            return False

    def login(self) -> bool:
        """Use a browser to let the user login (QR/Passkey), then copy cookies into requests.Session."""
        self.app.update_status("正在啟動瀏覽器，請完成登入（可掃 QR / 使用 Passkey）。")
        logging.info("Starting browser for login...")
        login_succeeded = False

        try:
            options = Options()
            # Show the "controlled by automated test software" banner so it's clear
            # the browser is being driven by Selenium.
            # (Removing the automation-hiding flags can help debugging login flow.)
            driver_path = self._resolve_driver_path()
            if driver_path:
                logging.info(f"Using configured Edge driver path: {driver_path}")
                service = Service(driver_path)
                self.driver = Edge(service=service, options=options)
            else:
                logging.info("No explicit Edge driver path found; using Selenium Manager.")
                self.driver = Edge(options=options)
        except WebDriverException as e:
            logging.error("Failed to start Edge WebDriver.", exc_info=True)
            self.app.update_status("啟動瀏覽器失敗，請確認 Edge WebDriver 可用（專案內 msedgedriver.exe 或 Selenium Manager）。", error=True)
            return False

        try:
            self.driver.get(self.login_url)

            for i in range(300):  # wait up to 5 minutes
                try:
                    # Sync cookies periodically so we can use them for API checks
                    self._sync_cookies_to_session()
                    logging.info(f"Login check iteration {i}, checking login...")
                    if self.check_login():
                        logging.info("Login detected, proceeding to close browser.")
                        self.app.update_status("登入成功！正在取得書單...")
                        # Extract idToken before quitting browser
                        id_token_cookie_name = 'CognitoIdentityServiceProvider.1vo6drk6c6ma7htam496pnrkdr.b724da08-2091-70f4-914c-4dc4806a1e1e.idToken'
                        for c in self.driver.get_cookies():
                            if c["name"] == id_token_cookie_name:
                                self.id_token = c["value"]
                                logging.info("Extracted idToken from browser cookies.")
                                break
                        login_succeeded = True
                        return True

                    current_url = self.driver.current_url
                    logging.info(f"Current URL: {current_url}")
                    if "#/library" in current_url or "/library" in current_url:
                        # sometimes the URL changes after login even though cookies are not yet valid
                        self._sync_cookies_to_session()
                        if self.check_login():
                            logging.info("Login detected via library URL.")
                            self.app.update_status("登入成功！正在取得書單...")
                            # Extract idToken
                            id_token_cookie_name = 'CognitoIdentityServiceProvider.1vo6drk6c6ma7htam496pnrkdr.b724da08-2091-70f4-914c-4dc4806a1e1e.idToken'
                            for c in self.driver.get_cookies():
                                if c["name"] == id_token_cookie_name:
                                    self.id_token = c["value"]
                                    logging.info("Extracted idToken from browser cookies.")
                                    break
                            login_succeeded = True
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
            # Keep the browser alive after a successful login so we can reuse the
            # authenticated page context for in-browser fetch pagination.
            if not login_succeeded:
                self.quit()

    def _is_logged_in_api(self) -> bool:
        """Check if the current session can access the readings API (i.e., cookies are authenticated)."""
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
        """Fetch the user's entire purchased-book list from the Readmoo API.

        Tries the browser-context path first (using the live authenticated browser session),
        then falls back to ``requests`` if the browser is unavailable or encounters an error.

        Returns:
            A list of ``{"title": str, "author": str}`` dicts, one entry per book.
        """
        self.app.update_status("正在取得已購書清單...")
        logging.info("Fetching readings API...")

        # Add Authorization header with idToken
        if self.id_token:
            self.session.headers['Authorization'] = f'Bearer {self.id_token}'
            logging.info("Added Authorization header with idToken.")
        else:
            logging.warning("idToken not available.")

        # The browser endpoint currently returns up to 1000 items even when a
        # smaller per_page is requested. Using 1000 here avoids 900-item overlap
        # windows that would otherwise turn a 4-page fetch into ~25 pages.
        browser_per_page = 1000
        max_pages = 100

        def update_fetch_status(page_number: int, current_count: int, total_hint: Optional[int] = None):
            if total_hint is not None:
                self.app.update_status(
                    f"正在取得已購書清單（第 {page_number} 頁，已累積 {current_count}/{total_hint} 本）..."
                )
            else:
                self.app.update_status(
                    f"正在取得已購書清單（第 {page_number} 頁，已累積 {current_count} 本）..."
                )

        if self.driver:
            try:
                self.app.update_status("正在透過瀏覽器工作階段取得書單...")
                detected = self._detect_browser_paging_strategy(browser_per_page)
                if detected:
                    strategy_name, builder, first_payload = detected
                    books: List[Dict[str, str]] = []
                    seen_ids: set[str] = set()

                    for page in range(1, max_pages + 1):
                        payload = first_payload if page == 1 else self._browser_fetch_payload(builder(page))
                        included = self._extract_included_items(payload)
                        total_hint = payload.get("total") if isinstance(payload, dict) and isinstance(payload.get("total"), int) else None
                        logging.info(
                            f"Browser fetch page {page} using {strategy_name}: discovered {len(included)} items"
                        )

                        page_new_books = 0
                        for item in included:
                            item_type = item.get("type", "")
                            if "book" not in item_type:
                                continue

                            item_id = item.get("id")
                            if item_id and item_id in seen_ids:
                                continue
                            if item_id:
                                seen_ids.add(item_id)

                            title = item.get("title", "標題不明") or "標題不明"
                            author = item.get("author", "作者不明") or "作者不明"
                            books.append({"title": title.strip(), "author": author.strip()})
                            page_new_books += 1

                        if total_hint is not None:
                            logging.info(f"Browser payload total hint: {total_hint}")
                        update_fetch_status(page, len(books), total_hint)
                        if total_hint is not None:
                            if len(books) >= total_hint:
                                logging.info("Collected all books based on browser payload total count.")
                                break

                        if page_new_books == 0:
                            logging.info("Browser pagination produced no new books; stopping.")
                            break

                        if page_new_books < browser_per_page:
                            logging.info("Browser pagination returned a short page; assuming end of list.")
                            break

                    logging.info(f"Total books extracted via browser context: {len(books)}")
                    if books:
                        return books
                else:
                    logging.warning("Could not detect a working browser paging strategy; falling back to requests.")
            except Exception as exc:
                logging.error(f"Browser-context fetch failed; falling back to requests: {exc}", exc_info=True)
        else:
            logging.warning("Browser driver is unavailable during get_books; browser-context fetch was skipped.")

        books = []
        page = 1
        per_page = 1000  # Fetch as many as possible per request to reduce the number of calls
        seen_ids: set[str] = set()

        # Some API endpoints use cursor/offset-style pagination instead of page numbers.
        # We'll detect those patterns and switch to offset-based fetching if needed.
        offset = 0
        use_offset = False
        consecutive_duplicate_pages = 0

        logging.info(f"Starting book fetch (id_token set: {bool(self.id_token)})")

        while page <= 50:
            prev_total_books = len(books)

            params = {"per_page": per_page}
            if use_offset:
                params["offset"] = offset
            else:
                params["page"] = page

            logging.info(f"Fetching page {page}... (params={params})")

            try:
                # Use a connect+read timeout tuple to avoid hanging indefinitely
                res = self.session.get(self.readings_url, params=params, timeout=(10, 20))
                logging.info(f"API response status: {res.status_code}")
                res.raise_for_status()
                data = res.json()
                # Avoid logging huge payloads (contains full book metadata)
                if isinstance(data, dict):
                    logging.debug(f"Parsed data for page {page}: keys={list(data.keys())}")
                    pagination = data.get("pagination")
                    logging.debug(f"Pagination info: {pagination!r}")
                else:
                    logging.debug(f"Parsed data for page {page}: type={type(data)}")
            except Exception as e:
                logging.error(f"Failed to fetch readings page {page}: {e}", exc_info=True)
                self.app.update_status("無法取得書單，請稍後再試。", error=True)
                return books  # Return what we have so far

            included = self._extract_included_items(data)

            total_hint = data.get("total") if isinstance(data, dict) and isinstance(data.get("total"), int) else None
            logging.info(f"Page {page}: discovered {len(included)} items")

            # Extract books from the API item list
            for item in included:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type", "")
                if "book" not in item_type:
                    continue

                item_id = item.get("id")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)

                title = item.get("title", "標題不明") or "標題不明"
                author = item.get("author", "作者不明") or "作者不明"
                books.append({"title": title.strip(), "author": author.strip()})

            update_fetch_status(page, len(books), total_hint)

            # Detect if we got any new books this page
            new_books = len(books) - prev_total_books
            if new_books == 0:
                consecutive_duplicate_pages += 1
                logging.info("No new books found on this page (possible duplicate pagination).")
                if consecutive_duplicate_pages >= 3:
                    logging.warning("Multiple consecutive duplicate pages detected; stopping to avoid infinite loop.")
                    break
            else:
                consecutive_duplicate_pages = 0

            # Determine next page or offset using pagination metadata (if available)
            next_page = None
            next_offset = None
            if isinstance(data, dict):
                pag = data.get("pagination") or {}
                if isinstance(pag, dict):
                    # Log pagination metadata on first page to help debug API behavior
                    if page == 1:
                        logging.info(f"Pagination metadata (page 1): {pag!r}")

                    # Common patterns:
                    # - next_page / next
                    # - page / total_pages
                    # - offset / limit / total
                    if isinstance(pag.get("next_page"), int):
                        next_page = cast(int, pag.get("next_page"))
                    elif isinstance(pag.get("next"), int):
                        next_page = cast(int, pag.get("next"))
                    elif isinstance(pag.get("page"), int) and isinstance(pag.get("total_pages"), int):
                        current = cast(int, pag.get("page"))
                        total_pages = cast(int, pag.get("total_pages"))
                        if current < total_pages:
                            next_page = current + 1
                    elif isinstance(pag.get("offset"), int) and isinstance(pag.get("limit"), int):
                        use_offset = True
                        current_offset = cast(int, pag.get("offset"))
                        limit = cast(int, pag.get("limit"))
                        total = pag.get("total") if isinstance(pag.get("total"), int) else None
                        # If total is available and we've already collected everything, stop.
                        if total is not None and len(books) >= total:
                            logging.info("Collected all books based on pagination total count.")
                            break
                        if total is not None and current_offset + limit < total:
                            next_offset = current_offset + limit

            if next_offset is not None:
                if next_offset == offset:
                    logging.warning("Pagination offset did not advance; stopping to avoid infinite loop.")
                    break
                offset = next_offset
                use_offset = True
                page += 1
                consecutive_duplicate_pages = 0
                continue

            if next_page is not None:
                if next_page == page:
                    logging.warning("Pagination did not advance; stopping to avoid infinite loop.")
                    break
                page = next_page
                consecutive_duplicate_pages = 0
                continue

            # Fallback: if fewer items returned than requested, we are at the end
            if len(included) < per_page:
                logging.info("Reached end of pages (received fewer items than per_page).")
                break

            page += 1

        if page > 50:
            logging.warning("Reached maximum page limit while fetching books; stopping to prevent infinite loop.")

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
