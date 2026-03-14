# ReadmooChecker 程式流程說明

## 整體架構

```
main.py  (GUI 層)
  └── ReadmooCheckerApp   ← Tkinter 主視窗
        └── ReadmooScraper  ← 核心爬蟲 (scraper.py)
```

使用者操作 GUI → 背景執行緒執行爬蟲 → 結果回傳 GUI 顯示。

---

## 一、GUI 啟動 (`main.py`)

```
程式進入點
  │
  └─ ReadmooCheckerApp.__init__()
       ├─ 建立主視窗（800×600）
       ├─ 控制列：「開始擷取書單」按鈕、排序選單、狀態列
       └─ 結果區：Treeview（序號 / 書名 / 作者）+ 捲軸
```

---

## 二、使用者點擊「開始擷取書單」

```
fetch_books()
  ├─ 停用按鈕（防止重複點擊）
  ├─ 清空 Treeview
  └─ 開新背景執行緒 → _scrape_data()
```

---

## 三、背景執行緒：`_scrape_data()`

```
_scrape_data()
  ├─ 建立 ReadmooScraper 實例
  ├─ 呼叫 scraper.login()
  │     ├─ 成功 → 繼續
  │     └─ 失敗 → 顯示錯誤訊息，結束
  ├─ 呼叫 scraper.get_books()  → 取得書單 list
  ├─ 依使用者選擇排序（書名 / 作者）
  ├─ 呼叫 populate_tree(books) → 顯示結果
  └─ [finally] scraper.quit()，重新啟用按鈕
```

---

## 四、登入流程：`ReadmooScraper.login()`

```
login()
  │
  ├─ _resolve_driver_path()          ← 決定 msedgedriver 路徑
  │     優先順序：
  │       1. 建構子傳入的 driver_path
  │       2. 專案目錄下的 msedgedriver.exe（自動偵測）
  │       3. None → 交由 Selenium Manager 自動處理
  │
  ├─ 啟動 Microsoft Edge（Selenium WebDriver）
  ├─ 開啟登入頁 https://member.readmoo.com/login/
  │
  └─ 輪詢迴圈（最多等待 5 分鐘）
        ├─ _sync_cookies_to_session()   ← 把瀏覽器 cookies 同步到 requests.Session
        ├─ check_login()                ← 判斷目前 URL 是否已完成登入
        │     ├─ 解析 URL（含 hash fragment，避免 #/auth/… 被忽略）
        │     ├─ URL 含 "library"           → 登入成功 ✔
        │     ├─ 是 readmoo.com 且非 auth 頁 → 登入成功 ✔
        │     └─ 其他                       → 繼續等待
        │
        ├─ 登入成功時
        │     ├─ 從 cookies 取出 idToken（Cognito JWT）
        │     ├─ 設定 login_succeeded = True
        │     └─ return True
        │
        └─ [finally] 若 login_succeeded == False → quit()（關閉瀏覽器）
              （成功時瀏覽器保持開啟，供後續 in-browser fetch 使用）
```

---

## 五、取書流程：`ReadmooScraper.get_books()`

`get_books()` 有兩條路徑，優先走**瀏覽器路徑**，失敗則退回 **requests 路徑**。

### 5-A 瀏覽器路徑（browser-context fetch）

```
get_books()  [driver 存在]
  │
  ├─ _detect_browser_paging_strategy(per_page=1000)
  │     ├─ 逐一嘗試 5 種 paging 策略：
  │     │     page_per_page / page_limit /
  │     │     offset_per_page / offset_limit / start_limit
  │     ├─ 對每種策略呼叫 _browser_fetch_payload(params)
  │     │     └─ 在瀏覽器頁面內執行 fetch()（攜帶 session cookies）
  │     ├─ 比對第 1 頁與第 2 頁的 book ID 是否不同
  │     └─ 回傳第一個「第 2 頁有新書」的策略 + 第 1 頁 payload
  │
  └─ 分頁累積迴圈（最多 100 頁）
        ├─ 第 1 頁：使用 detect 時已取好的 payload（省一次請求）
        ├─ 第 2 頁起：呼叫 _browser_fetch_payload(builder(page))
        ├─ _extract_included_items(payload)  ← 將 payload 拍平成 item list
        ├─ 過濾出 type 含 "book" 的項目，排除重複 ID
        ├─ update_fetch_status(page, count, total_hint)  ← 更新 GUI 狀態列
        └─ 停止條件（滿足任一即停）：
              • 已累積數量 ≥ payload 中的 total 欄位
              • 本頁沒有新書
              • 本頁書數 < per_page（最後一頁）
```

### 5-B requests 路徑（fallback）

```
get_books()  [driver 不存在，或瀏覽器路徑失敗]
  │
  └─ 分頁 while 迴圈（最多 50 頁）
        ├─ 以 requests.Session 呼叫 readings API（帶 Authorization: Bearer idToken）
        ├─ _extract_included_items(data)  ← 拍平 item list
        ├─ 過濾 book，排除重複 ID
        ├─ 讀取 pagination 元資料，支援以下格式：
        │     next_page / next / page+total_pages / offset+limit+total
        ├─ update_fetch_status(page, count, total_hint)
        └─ 停止條件：
              • 連續 3 頁無新書（重複頁偵測）
              • pagination 顯示無下一頁
              • 本頁書數 < per_page
              • 超過 50 頁上限
```

---

## 六、結果顯示

```
populate_tree(books)
  └─ 透過 tk.after(0, ...) 在主執行緒插入每一列
       └─ (序號, 書名, 作者)
```

---

## 七、結束流程

```
quit()  /  on_closing()
  ├─ driver.quit()   ← 關閉 Edge 瀏覽器
  └─ Tkinter destroy()  ← 關閉視窗（on_closing 時）
```

---

## 資料流圖

```
使用者點擊按鈕
      │
      ▼
_scrape_data() [背景執行緒]
      │
      ├──► login() ──► Edge 瀏覽器 ──► 使用者手動登入（QR / Passkey）
      │         └── cookies 同步到 requests.Session；idToken 儲存
      │
      ├──► get_books()
      │         ├── [有 driver] in-browser fetch → JSON payload → 書單 list
      │         └── [無 driver] requests.get → JSON payload → 書單 list
      │
      └──► populate_tree() ──► Treeview 顯示結果
```

---

## 主要設定值

| 參數 | 值 | 說明 |
|------|----|------|
| `browser_per_page` | 1000 | 瀏覽器路徑每頁請求筆數 |
| `max_pages`（browser） | 100 | 瀏覽器路徑最大頁數 |
| `per_page`（requests） | 1000 | requests 路徑每頁請求筆數 |
| `max_pages`（requests） | 50 | requests 路徑最大頁數 |
| 登入等待上限 | 300 秒（5 分鐘） | 超時後顯示錯誤 |
| 連續重複頁停止閾值 | 3 頁 | 連續無新書時中止 |
