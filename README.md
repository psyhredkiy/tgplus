# tgplus

Python scraper that automates exporting Telegram channel statistics. The script uses Selenium to control an existing Chrome session and downloads search results as Excel files.

## Features
- Connects to a running Chrome instance via the DevTools protocol
- Searches for configurable keywords
- Applies view range filters and date ranges
- Exports results to Excel and renames downloads automatically
- Saves progress and resumes incomplete runs

## Requirements
- Python 3.10+
- [Selenium](https://pypi.org/project/selenium/)
- Chrome with [remote debugging](https://chromedevtools.github.io/devtools-protocol/#how-do-i-access-the-protocol) enabled
- Matching `chromedriver`

Install dependencies:

```bash
pip install selenium
```

## Usage
1. Launch Chrome with remote debugging, e.g.:
   ```bash
   /path/to/chrome --remote-debugging-port=9222
   ```
2. Adjust configuration values at the top of `tgstat_scraper.py` (keywords, date range, etc.).
3. Optionally set the `CHROME_DEBUG_ADDRESS` environment variable to point at the debugging port.
4. Run the scraper:
   ```bash
   python tgstat_scraper.py
   ```

Downloaded Excel files will be stored in `downloads/` with a descriptive name. Log output is written to `tgstat_log.txt` and progress is stored in `progress.json` to avoid repeating completed tasks.

## Disclaimer
The script interacts with third‑party services. Ensure your usage complies with tgstat.ru's terms and any applicable laws.

