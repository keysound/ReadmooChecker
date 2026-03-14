# ReadmooChecker

A small GUI tool to fetch your purchased books from Readmoo using Readmoo's hidden API.

## Features

- Opens a browser for you to login (supports QR code / Passkey)
- After login, fetches purchased book list and displays title + author
- Uses Readmoo internal endpoints (`/api/me/readings`)

## Requirements

- Python 3.10+
- Dependencies:
  - `requests`
  - `selenium`
  - `beautifulsoup4` (kept for compatibility, but not strictly required)
  - `pytest` (for unit tests)

## Setup

```sh
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

Run the GUI:

```sh
python main.py
```

Click **開始擷取書單** and complete the login in the browser window.

## Testing

Run all unit tests:

```sh
pytest -q tests
```

Run scraper-only tests:

```sh
pytest -q tests/test_scraper_unit.py
```

Detailed testing guide:
- `TESTING.md`

## Notes

This tool relies on Readmoo's private API endpoints and may stop working if Readmoo changes their backend.
