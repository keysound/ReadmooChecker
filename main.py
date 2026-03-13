import tkinter as tk
from tkinter import ttk
import threading
import logging
from scraper import ReadmooScraper

# --- Logging Setup ---
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='debug.log',
    filemode='w' # 'w' to overwrite the log file on each run
)

class ReadmooCheckerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Readmoo 已購書單擷取工具")
        self.geometry("800x600")
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.scraper_instance = None

        # --- Main Frame ---
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Control Frame ---
        control_frame = ttk.LabelFrame(main_frame, text="控制", padding="10")
        control_frame.pack(fill=tk.X, pady=5)

        self.fetch_button = ttk.Button(control_frame, text="開始擷取書單", command=self.fetch_books)
        self.fetch_button.pack(side=tk.LEFT, padx=5)

        # Sort option
        ttk.Label(control_frame, text="排序方式:").pack(side=tk.LEFT, padx=5)
        self.sort_var = tk.StringVar(value="title")
        self.sort_combo = ttk.Combobox(control_frame, textvariable=self.sort_var, values=["書名", "作者"], state="readonly", width=10)
        self.sort_combo.pack(side=tk.LEFT, padx=5)

        self.status_label = ttk.Label(control_frame, text="點擊按鈕後會開啟瀏覽器讓您登入（支援 QR/Passkey）")
        self.status_label.pack(side=tk.LEFT, padx=5)

        # --- Results Frame ---
        results_frame = ttk.LabelFrame(main_frame, text="已購書單", padding="10")
        results_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        self.tree = ttk.Treeview(results_frame, columns=("title", "author"), show="headings")
        self.tree.heading("title", text="書名")
        self.tree.heading("author", text="作者")
        self.tree.column("title", width=500)
        self.tree.column("author", width=200)

        # Scrollbar
        scrollbar = ttk.Scrollbar(results_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
    def fetch_books(self):
        # Disable button and clear tree
        self.fetch_button.config(state=tk.DISABLED)
        for i in self.tree.get_children():
            self.tree.delete(i)

        # Run scraping in a separate thread
        thread = threading.Thread(target=self._scrape_data)
        thread.start()

    def _scrape_data(self):
        self.update_status("正在啟動瀏覽器並登入 Readmoo...")
        logging.info("Starting scrape process...")

        try:
            self.scraper_instance = ReadmooScraper(self)

            if self.scraper_instance.login():
                logging.info("Login successful, getting books.")
                books = self.scraper_instance.get_books()

                # Sort the books based on user selection
                sort_key = "title" if self.sort_var.get() == "書名" else "author"
                self.update_status("正在排序書單...")
                logging.info(f"Sorting books by {sort_key}.")
                books.sort(key=lambda book: book[sort_key])

                self.update_status(f"擷取完成！共找到 {len(books)} 本書。")
                self.populate_tree(books)
            else:
                logging.warning("Login failed or timed out.")
        except Exception as e:
            logging.error(f"An unexpected error occurred in _scrape_data: {e}", exc_info=True)
            self.update_status(f"發生未預期的錯誤: {e}", error=True)
        finally:
            logging.info("Scrape process finished.")
            if self.scraper_instance:
                self.scraper_instance.quit()
                self.scraper_instance = None
            # Re-enable button
            self.after(0, lambda: self.fetch_button.config(state=tk.NORMAL))

    def populate_tree(self, books):
        # This needs to be called from the main thread
        def _insert():
            logging.info(f"DEBUG: Populating tree with {len(books)} books.")
            logging.info(f"Populating tree with {len(books)} books.")
            for book in books:
                logging.info(f"DEBUG: Inserting book: {book}")
                self.tree.insert("", tk.END, values=(book['title'], book['author']))
        self.after(0, _insert)

    def update_status(self, text, error=False):
        # This needs to be called from the main thread
        def _update():
            color = "red" if error else "black"
            self.status_label.config(text=text, foreground=color)
        self.after(0, _update)

    def on_closing(self):
        # Ensure browser closes if the GUI window is closed
        logging.info("Closing application.")
        if self.scraper_instance:
            self.scraper_instance.quit()
        self.destroy()

if __name__ == "__main__":
    logging.info("Application start.")
    app = ReadmooCheckerApp()
    app.mainloop()
    logging.info("Application end.")
