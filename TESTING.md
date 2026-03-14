# ReadmooChecker 測試說明文件

## 1. 目標與範圍

本文件說明目前 ReadmooChecker 的自動化測試設計、覆蓋範圍、執行方式與持續整合流程。

目前測試重點放在：
- Scraper 核心邏輯（資料解析、分頁策略判斷、登入判斷、cookie 同步）
- 主要流程分支（瀏覽器路徑成功、fallback 至 requests、重複頁停止條件）
- GUI 的可測單元（序號欄插入、狀態顏色更新）

目前不在單元測試範圍：
- Selenium 真實瀏覽器互動流程（例如 QR 登入）
- 對 Readmoo 真實 API 的端對端網路測試

---

## 2. 測試結構

測試檔案：
- [tests/test_scraper_unit.py](tests/test_scraper_unit.py)
- [tests/test_main_unit.py](tests/test_main_unit.py)

CI 設定：
- [.github/workflows/pytest.yml](.github/workflows/pytest.yml)

依賴設定：
- [requirements.txt](requirements.txt)

---

## 3. 測試案例說明

### 3.1 Scraper 測試

檔案：[tests/test_scraper_unit.py](tests/test_scraper_unit.py)

已覆蓋內容：

1. included 資料抽取
- 驗證支援多種 payload 結構：
  - dict.included
  - dict.data.included
  - dict.data(list)
  - raw list
- 驗證非 dict 項目會被過濾

2. 書籍 id 抽取
- 只抽取 type 包含 book 且有 id 的項目
- 自動轉為字串 id

3. 分頁策略生成
- 驗證策略名稱列表
- 驗證 page 與 offset 參數生成正確

4. 分頁策略偵測
- 驗證可以挑選出第 2 頁有新書 id 的策略
- 驗證所有策略皆重複時回傳 None

5. API 登入狀態判斷
- 200 + 非 error_login 回傳 True
- error_login / 非 200 / 例外回傳 False

6. URL 登入判斷
- library URL 視為成功
- readmoo.com 且非 auth 視為成功
- auth 頁面視為失敗
- driver 例外視為失敗

7. Cookie 同步
- 驗證 driver cookies 能正確同步到 requests session

8. get_books 主流程
- 瀏覽器路徑成功並依 total hint 收斂停止
- 瀏覽器策略失敗時 fallback 至 requests
- requests 路徑遇連續重複頁會觸發保護停止

### 3.2 Main 視窗測試

檔案：[tests/test_main_unit.py](tests/test_main_unit.py)

已覆蓋內容：

1. 清單插入
- 驗證 populate_tree 會插入序號、書名、作者三欄

2. 狀態文字更新
- error=False 時顏色為 black
- error=True 時顏色為 red

---

## 4. 本機執行方式

### 4.1 安裝依賴

```powershell
pip install -r requirements.txt
```

### 4.2 執行全部測試

```powershell
pytest -q tests
```

### 4.3 只執行 scraper 測試

```powershell
pytest -q tests/test_scraper_unit.py
```

### 4.4 只執行 main 測試

```powershell
pytest -q tests/test_main_unit.py
```

---

## 5. CI（GitHub Actions）

Workflow 檔案：[.github/workflows/pytest.yml](.github/workflows/pytest.yml)

觸發條件：
- push 到任意分支
- pull request

流程：
1. checkout 原始碼
2. 安裝 Python 3.12
3. 安裝 requirements
4. 執行 pytest

---

## 6. 已知限制與後續建議

已知限制：
- 目前單元測試大量使用 mock，無法涵蓋真實瀏覽器與真實 Readmoo API 行為差異
- Selenium 互動登入流程尚未做整合測試

建議後續：
1. 增加一個可選的整合測試模式（手動觸發，不納入 CI）
2. 為 get_books 再拆分更小函式，降低 mock 複雜度並提升可讀性
3. 針對錯誤情境（timeout、API schema 改變）增加更多回歸測試
