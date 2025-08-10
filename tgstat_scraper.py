import time
import os
import json
import random
import socket
from datetime import datetime
from contextlib import suppress

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException

# ===================== КОНФИГ =====================
keywords = ["новости", "технологии"]  # твои ключевые слова

# Карта диапазонов просмотров -> id радиокнопок (проверь id на странице параметров)
view_ranges = {
    "1к-10к": "views1",
    "10к-50к": "views2",
    "50к-100к": "views3",
    "более 100к": "views4"
}

SEARCH_URL     = "https://tgstat.ru/search"
download_dir   = os.path.abspath("downloads")
log_file       = "tgstat_log.txt"
progress_file  = "progress.json"
max_attempts   = 3

# Диапазон дат в формате DD.MM.YYYY
START_DATE = "01.08.2025"
END_DATE   = "07.08.2025"

# Локальный путь к chromedriver (под Mac M1/Homebrew)
CHROMEDRIVER_PATH = "/opt/homebrew/bin/chromedriver"

# Адрес devtools-дебаггера уже запущенного Chrome
DEBUG_ADDRESS = os.environ.get("CHROME_DEBUG_ADDRESS", "127.0.0.1:9222")

# Исключающие слова в поиске
EXCLUDE_BLOCK = (
    "-рецепт -еда -косметика -мода -бренд -скидка -промо -вкус -доставка "
    "-парфюм -футбол -спорт -игра -аниме -фильм -песня -альбом -трек "
    "-развлечения -NFT -бьюти -конкурс -гороскоп -эзотерика"
)

# "Человечные" задержки
HUMAN_DELAY_SHORT = (0.3, 0.8)
HUMAN_DELAY_MED   = (0.8, 1.8)
HUMAN_DELAY_LONG  = (1.5, 3.0)
TYPE_DELAY        = (0.05, 0.18)

# ===================== УТИЛИТЫ =====================
def log(message, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{level}] {ts} - {message}"
    print(line)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def human_sleep(bounds=HUMAN_DELAY_MED):
    time.sleep(random.uniform(*bounds))

def random_scroll_jitter(driver):
    jitter = random.randint(-180, 220)
    driver.execute_script("window.scrollBy(0, arguments[0]);", jitter)

def type_like_human(element, text, delay_range=TYPE_DELAY, clear_first=True):
    if clear_first:
        element.clear()
        human_sleep(HUMAN_DELAY_SHORT)
    for ch in text:
        element.send_keys(ch)
        time.sleep(random.uniform(*delay_range))
    human_sleep(HUMAN_DELAY_SHORT)

def load_progress():
    if not os.path.exists(progress_file):
        return {}
    with open(progress_file, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return {k: {r: True for r in v} if isinstance(v, list) else dict(v) for k, v in data.items()}
        except Exception:
            return {}

def save_progress(progress):
    tmp = progress_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)
    with suppress(Exception):
        os.replace(tmp, progress_file)

def is_done(progress, keyword, range_label):
    return progress.get(keyword, {}).get(range_label, False) is True

def mark_done(progress, keyword, range_label):
    progress.setdefault(keyword, {})
    progress[keyword][range_label] = True
    save_progress(progress)

def _port_open(host, port, timeout=1.0):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        s.close()

# ===================== ПОДКЛЮЧЕНИЕ К CHROME =====================
def connect_to_existing_chrome(debug_address=DEBUG_ADDRESS, retries=15, pause=1.0):
    host, port_str = debug_address.split(":")
    port = int(port_str)
    for attempt in range(1, retries + 1):
        try:
            if not _port_open(host, port):
                time.sleep(pause)
                continue
            opts = webdriver.ChromeOptions()
            opts.add_experimental_option("debuggerAddress", debug_address)
            driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=opts)
            return driver
        except WebDriverException as e:
            log(f"Не удалось подключиться к Chrome (попытка {attempt}/{retries}): {e}", "ERROR")
            time.sleep(pause)
    raise RuntimeError(f"Не удалось подключиться к уже запущенному Chrome по {debug_address}")

# ===================== CLOUDFLARE ГАРД =====================
def wait_for_cloudflare(driver, ping_every_sec: int = 3, post_clear_wait: float = 0.8):
    elapsed = 0
    indicators = (
        "checking your browser",
        "проверка браузера",
        "please wait while we check your browser",
        "ddos protection by cloudflare",
        "cloudflare"
    )
    while True:
        html = driver.page_source.lower()
        url  = driver.current_url.lower()
        challenge = (
            any(ind in html for ind in indicators) or
            "/cdn-cgi/" in url or
            "challenge" in url or
            "captcha" in html
        )
        if challenge:
            if elapsed == 0:
                log("🔒 Обнаружена проверка Cloudflare. Жду ручного прохождения…")
            time.sleep(ping_every_sec)
            elapsed += ping_every_sec
            continue
        time.sleep(post_clear_wait)
        log("🔓 Проверка Cloudflare пройдена. Продолжаю.")
        return

def is_cloudflare_active(driver):
    html = driver.page_source.lower()
    url  = driver.current_url.lower()
    indicators = (
        "checking your browser",
        "проверка браузера",
        "please wait while we check your browser",
        "ddos protection by cloudflare",
        "cloudflare",
        "captcha"
    )
    return any(ind in html for ind in indicators) or "/cdn-cgi/" in url or "challenge" in url

# ======== ВОССТАНОВЛЕНИЕ КОНТЕКСТА ПОСЛЕ CF ПЕРЕБРОСА НА /search ========
def is_on_initial_search_page(driver):
    """Понимаем, что нас вернуло на стартовую /search (без формы параметров)."""
    url_ok = driver.current_url.split("?")[0].rstrip("/") == SEARCH_URL
    has_start = len(driver.find_elements(By.ID, "startdate")) > 0
    has_end   = len(driver.find_elements(By.ID, "enddate")) > 0
    has_iskat = len(driver.find_elements(By.XPATH, "//button[normalize-space()='Искать']")) > 0
    return url_ok and not (has_start or has_end or has_iskat)

def recover_to_params_page(driver, wait, keyword):
    """Если нас выкинуло на /search — повторно вводим запрос и дожидаемся страницы параметров."""
    if is_on_initial_search_page(driver):
        log("↩️ Вернуло на стартовую /search. Повторяю ввод запроса и перехожу к параметрам…")
        search_input = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.NAME, "q")))
        full_query = f"{keyword} {EXCLUDE_BLOCK}"
        type_like_human(search_input, full_query)
        search_input.send_keys(Keys.RETURN)
        wait_for_params_page(driver, wait, timeout=30)

def await_condition_with_cf(driver, cond_fn, timeout=60, poll=0.5, describe="ожидание условия", on_cf_cleared=None):
    """
    Ждёт cond_fn() == True, пережидая Cloudflare; после прохождения CF вызывает on_cf_cleared(),
    чтобы восстановить контекст (например, вернуться со стартовой /search на страницу параметров).
    """
    end = time.time() + timeout
    while True:
        if is_cloudflare_active(driver):
            log(f"🔒 Cloudflare во время {describe}. Жду прохождения…")
            wait_for_cloudflare(driver)
            if on_cf_cleared:
                try:
                    on_cf_cleared()
                except Exception as e:
                    log(f"on_cf_cleared ошибка: {e}", "ERROR")
            end = time.time() + timeout  # дать полный таймаут заново

        try:
            if cond_fn():
                return True
        except Exception:
            pass
        if time.time() > end:
            raise TimeoutError(f"Таймаут: {describe}")
        time.sleep(poll)

# ===================== ЛОГИКА СТРАНИЦЫ =====================
def wait_for_params_page(driver, wait, timeout=30):
    def cond():
        return any([
            len(driver.find_elements(By.XPATH, "//form[.//input[contains(@name, 'facets')]]")) > 0,
            len(driver.find_elements(By.XPATH, "//label[@for='views1' or @for='views2' or @for='views3' or @for='views4']")) > 0,
            len(driver.find_elements(By.CSS_SELECTOR, "button.search-button.btn.btn-dark.btn-block")) > 0,
            len(driver.find_elements(By.XPATH, "//button[normalize-space()='Искать']")) > 0,
            len(driver.find_elements(By.ID, "startdate")) > 0,
            len(driver.find_elements(By.ID, "enddate")) > 0,
        ])
    await_condition_with_cf(
        driver, cond, timeout=timeout,
        describe="загрузки страницы параметров",
        on_cf_cleared=lambda: None  # сюда не нужен keyword
    )

def set_date_range(driver, start_date: str, end_date: str, wait=None, keyword=None):
    # ждём поля; если CF кинет назад — вернёмся
    await_condition_with_cf(
        driver, lambda: len(driver.find_elements(By.ID, "startdate")) > 0,
        timeout=30, describe="поля startdate",
        on_cf_cleared=(lambda: recover_to_params_page(driver, wait, keyword) if (wait and keyword) else None)
    )
    await_condition_with_cf(
        driver, lambda: len(driver.find_elements(By.ID, "enddate")) > 0,
        timeout=30, describe="поля enddate",
        on_cf_cleared=(lambda: recover_to_params_page(driver, wait, keyword) if (wait and keyword) else None)
    )

    start_el = driver.find_element(By.ID, "startdate")
    end_el   = driver.find_element(By.ID, "enddate")

    for el, val in [(start_el, start_date), (end_el, end_date)]:
        driver.execute_script("""
            const el = arguments[0], val = arguments[1];
            el.value = val;
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            """, el, val)
        human_sleep(HUMAN_DELAY_SHORT)
    log(f"Установлен период: {start_date} — {end_date}")

def submit_secondary_search(driver, wait, results_timeout=60, keyword=None):
    locators = [
        (By.CSS_SELECTOR, "form button.search-button.btn.btn-dark.btn-block"),
        (By.XPATH, "//form//button[normalize-space()='Искать']"),
        (By.XPATH, "//form//button[contains(@class,'search-button')]"),
        (By.XPATH, "//form//input[@type='submit' and (contains(@value,'Искать') or contains(@value,'Поиск'))]")
    ]
    btn = None
    for by, sel in locators:
        try:
            btn = WebDriverWait(driver, 15).until(EC.element_to_be_clickable((by, sel)))
            break
        except Exception:
            continue
    if not btn:
        raise RuntimeError("Не нашёл кнопку 'Искать'.")
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
    human_sleep(HUMAN_DELAY_MED)
    btn.click()
    human_sleep(HUMAN_DELAY_SHORT)

    def results_loaded():
        return (
            len(driver.find_elements(By.XPATH, "//a[contains(text(),'Экспорт в Excel')]") ) > 0 or
            len(driver.find_elements(By.XPATH, "//*[contains(@class,'results') or contains(@class,'search-results')]") ) > 0 or
            len(driver.find_elements(By.XPATH, "//*[contains(.,'Ничего не найдено') or contains(.,'ничего не найдено')]") ) > 0
        )
    await_condition_with_cf(
        driver, results_loaded, timeout=results_timeout,
        describe="обновления результатов после 'Искать'",
        on_cf_cleared=(lambda: recover_to_params_page(driver, wait, keyword) if keyword else None)
    )
    log("Нажата кнопка 'Искать', результаты обновились.")

def wait_for_download_to_finish(timeout=90):
    log("Ожидание загрузки...")
    elapsed = 0
    while elapsed < timeout:
        if not any(f.endswith(".crdownload") for f in os.listdir(download_dir)):
            log("Загрузка завершена.")
            return True
        time.sleep(1)
        elapsed += 1
    log("Время ожидания загрузки истекло", "ERROR")
    return False

def select_view_range_by_id(driver, wait, input_id, keyword=None):
    try:
        # ждём label; если CF кинул назад — восстановимся
        await_condition_with_cf(
            driver,
            lambda: len(driver.find_elements(By.XPATH, f"//label[@for='{input_id}']")) > 0,
            timeout=30,
            describe=f"появления фильтра {input_id}",
            on_cf_cleared=(lambda: recover_to_params_page(driver, wait, keyword) if keyword else None)
        )
        label = driver.find_element(By.XPATH, f"//label[@for='{input_id}']")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", label)
        human_sleep(HUMAN_DELAY_SHORT)
        label.click()
        human_sleep(HUMAN_DELAY_SHORT)
        wait_for_cloudflare(driver)
        # на случай переброса — вернёмся
        if keyword:
            recover_to_params_page(driver, wait, keyword)
        log(f"Выбран фильтр: {input_id}")
        return True
    except Exception as e:
        log(f"Не удалось выбрать фильтр {input_id}: {e}", "ERROR")
        return False

def export_and_rename(driver, wait, keyword, range_label):
    try:
        def export_btn_ready():
            return len(driver.find_elements(By.XPATH, "//a[contains(text(), 'Экспорт в Excel')]") ) > 0
        await_condition_with_cf(
            driver, export_btn_ready, timeout=60,
            describe="кнопки 'Экспорт в Excel'",
            on_cf_cleared=(lambda: recover_to_params_page(driver, wait, keyword) if keyword else None)
        )

        export_btn = driver.find_element(By.XPATH, "//a[contains(text(), 'Экспорт в Excel')]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", export_btn)
        human_sleep(HUMAN_DELAY_MED)
        export_btn.click()
        human_sleep(HUMAN_DELAY_SHORT)

        wait_for_cloudflare(driver)
        if keyword:
            recover_to_params_page(driver, wait, keyword)

        log(f"Выгрузка: {keyword} [{range_label}]")
        if wait_for_download_to_finish():
            files = sorted(
                [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.endswith(".xlsx")],
                key=os.path.getmtime, reverse=True
            )
            if not files:
                log("⛔ Excel-файл не найден после завершения загрузки", "ERROR")
                return False
            latest_file = files[0]
            safe_keyword = keyword.strip().replace(" ", "_")
            safe_range = (range_label.strip()
                          .replace(" ", "_")
                          .replace("к", "k").replace("К", "k")
                          .replace("/", "-"))
            new_name = f"{safe_keyword}__{safe_range}.xlsx"
            new_path = os.path.join(download_dir, new_name)
            if os.path.exists(new_path):
                os.remove(new_path)
            os.rename(latest_file, new_path)
            log(f"Сохранён: {new_name}")
            return True
        return False
    except Exception as e:
        log(f"Ошибка экспорта: {e}", "ERROR")
        return False

# ===================== ОСНОВНОЙ ПОТОК =====================
def process_keyword(driver, wait, keyword, progress):
    log(f"Обработка: {keyword}")
    for range_label, input_id in view_ranges.items():
        if is_done(progress, keyword, range_label):
            log(f"Пропуск: уже есть {keyword} [{range_label}]")
            continue
        attempt = 1
        while attempt <= max_attempts:
            try:
                # Первый поиск
                driver.get(SEARCH_URL)
                human_sleep(HUMAN_DELAY_MED)
                wait_for_cloudflare(driver)
                recover_to_params_page(driver, wait, keyword)  # если нас сразу кидает назад

                search_input = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.NAME, "q")))
                full_query = f"{keyword} {EXCLUDE_BLOCK}"
                type_like_human(search_input, full_query)
                search_input.send_keys(Keys.RETURN)

                # Ждём страницу параметров (с авто-восстановлением)
                wait_for_params_page(driver, wait, timeout=30)

                # Устанавливаем даты (с авто-восстановлением)
                set_date_range(driver, START_DATE, END_DATE, wait=wait, keyword=keyword)
                human_sleep(HUMAN_DELAY_MED)

                # Фильтр (с авто-восстановлением)
                if not select_view_range_by_id(driver, wait, input_id, keyword=keyword):
                    raise Exception("Фильтр не выбран")

                human_sleep(HUMAN_DELAY_MED)

                # Второй поиск (с авто-восстановлением) и ждать результатов
                submit_secondary_search(driver, wait, results_timeout=60, keyword=keyword)

                # Экспорт
                if export_and_rename(driver, wait, keyword, range_label):
                    mark_done(progress, keyword, range_label)
                    break
            except Exception as e:
                log(f"Ошибка: {e}", "ERROR")
            attempt += 1
            time.sleep(random.uniform(5, 10))
        human_sleep(HUMAN_DELAY_LONG)

# ===================== MAIN =====================
if __name__ == "__main__":
    os.makedirs(download_dir, exist_ok=True)
    log("=== Старт скрипта ===")
    driver = connect_to_existing_chrome(DEBUG_ADDRESS)
    wait = WebDriverWait(driver, 30)
    progress = load_progress()
    try:
        for kw in keywords:
            process_keyword(driver, wait, kw, progress)
        log("✅ Готово.")
    finally:
        with suppress(Exception):
            driver.quit()
