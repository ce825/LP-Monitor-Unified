#!/Users/cehwang/miniconda3/bin/python3
"""
LP 신상품 모니터링 스크립트 (Yes24 + Aladin + Ktown4u)
새 상품이 등록되면 Discord로 알림을 보냅니다.
Selenium을 사용하여 실제 브라우저처럼 동작합니다.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime, timezone
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# 설정
SITES = {
    "yes24": {
        "name": "Yes24",
        "url": "https://www.yes24.com/Product/Category/Display/003001033001",
        "color": 0x00D4AA,  # 초록색
    },
    "aladin": {
        "name": "알라딘",
        "url": "https://www.aladin.co.kr/shop/wbrowse.aspx?BrowseTarget=List&ViewRowsCount=25&ViewType=Detail&PublishMonth=0&SortOrder=6&page=1&Stockstatus=1&PublishDay=84&CID=86800&SearchOption=",
        "color": 0xFFD700,  # 노란색 (골드)
    },
    "ktown4u": {
        "name": "Ktown4u",
        "url": "https://kr.ktown4u.com/searchList?goodsTextSearch=lp&goodsSearch=newgoods",
        "color": 0xFF6B6B,  # 빨간색
    },
}

DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1464577763527889137/crrzuov6ADoIoNcrJ5-jCK723zkXmjaKovNOL5WprbGlTVDjrhIKIJJcvr0RpkqDeOkx"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products.json")


def load_saved_products():
    """저장된 상품 목록 불러오기"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 기존 형식 -> 새 형식으로 마이그레이션
            if data and not any(key in data for key in SITES.keys()):
                print(f"[{datetime.now()}] 데이터 형식 마이그레이션 중...")
                return {"yes24": data, "aladin": {}, "ktown4u": {}}
            # 새 사이트 추가 시 키 초기화
            for site_key in SITES.keys():
                if site_key not in data:
                    data[site_key] = {}
            return data
    return {site: {} for site in SITES.keys()}


def save_products(products):
    """상품 목록 저장"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def create_driver():
    """Chrome WebDriver 생성"""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # navigator.webdriver 숨기기
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'},
    )

    return driver


def fetch_yes24_products(driver, saved_products, is_first_run):
    """Yes24에서 상품 목록 가져오기 (신상품순 + 등록일순) - 즉시 알림"""
    products = {}
    site_saved = saved_products.get("yes24", {})

    def parse_and_notify():
        """현재 페이지에서 상품 파싱 및 즉시 알림"""
        soup = BeautifulSoup(driver.page_source, "html.parser")
        page_products = {}

        for item in soup.select("li[data-goods-no]"):
            try:
                product_id = item.get("data-goods-no")
                if not product_id:
                    continue

                title_tag = item.select_one("a.gd_name")
                title = title_tag.get_text(strip=True) if title_tag else ""

                price = ""
                price_input = item.select_one("input[name='ORD_GOODS_OPT']")
                if price_input:
                    try:
                        price_data = json.loads(price_input.get("value", "{}"))
                        sale_price = price_data.get("salePrice", 0)
                        if sale_price:
                            price = f"{int(sale_price):,}원"
                    except:
                        pass

                if not price:
                    price_tag = item.select_one("em.yes_b")
                    if price_tag:
                        price = price_tag.get_text(strip=True) + "원"

                img_tag = item.select_one("img")
                img_url = ""
                if img_tag:
                    img_url = img_tag.get("data-original") or img_tag.get("src", "")
                    if img_url.startswith("//"):
                        img_url = "https:" + img_url

                # 품절 여부 확인
                item_text = item.get_text()
                item_html = str(item).lower()
                is_soldout = (
                    "품절" in item_text
                    or "soldout" in item_html
                    or item.select_one('[class*="soldout"]') is not None
                )

                if product_id and title:
                    product = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.yes24.com/Product/Goods/{product_id}",
                        "image": img_url,
                        "soldout": is_soldout,
                    }
                    page_products[product_id] = product

                    # 신상품이면 즉시 알림
                    if product_id not in site_saved and product_id not in products:
                        if not is_first_run:
                            print(f"[{datetime.now()}] [Yes24] 신상품 발견! 즉시 알림: {title[:50]}")
                            send_discord_notification("yes24", {product_id: product})
            except:
                continue

        return page_products

    try:
        url = SITES["yes24"]["url"]
        print(f"[{datetime.now()}] [Yes24] 페이지 로드 중...")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-goods-no]"))
        )

        # 1. 신상품순 정렬
        print(f"[{datetime.now()}] [Yes24] 신상품순 정렬 클릭...")
        sort_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a[data-search-value='RECENT']"))
        )
        sort_button.click()

        time.sleep(2)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-goods-no]"))
        )

        recent_products = parse_and_notify()
        print(f"[{datetime.now()}] [Yes24] 신상품순: {len(recent_products)}개")
        products.update(recent_products)

        # 2. 등록일순 정렬
        print(f"[{datetime.now()}] [Yes24] 등록일순 정렬 클릭...")
        sort_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a[data-search-value='REG_DTS']"))
        )
        sort_button.click()

        time.sleep(2)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-goods-no]"))
        )

        new_products = parse_and_notify()
        print(f"[{datetime.now()}] [Yes24] 등록일순: {len(new_products)}개")

        # 등록일순에서 새로 발견된 상품 추가
        for pid, prod in new_products.items():
            if pid not in products:
                products[pid] = prod

        return products

    except Exception as e:
        print(f"[{datetime.now()}] [Yes24] 상품 조회 실패: {e}")
        return None


def fetch_aladin_products(saved_products, is_first_run):
    """알라딘에서 상품 목록 가져오기 (출시일순 + 등록일순) - requests 사용으로 빠른 조회"""
    products = {}
    site_saved = saved_products.get("aladin", {})

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9',
    }

    def parse_and_notify(html):
        """HTML에서 상품 파싱 및 즉시 알림"""
        soup = BeautifulSoup(html, "html.parser")
        page_products = {}

        for box in soup.select("div.ss_book_box"):
            try:
                title_link = box.select_one("a.bo3")
                if not title_link:
                    title_link = box.select_one('a[href*="ItemId="]')

                if not title_link:
                    continue

                href = title_link.get("href", "")
                match = re.search(r"ItemId=(\d+)", href)
                if not match:
                    continue

                product_id = match.group(1)
                title = title_link.get_text(strip=True)

                price_tag = box.select_one("span.ss_p2")
                price = price_tag.get_text(strip=True) if price_tag else ""

                img_tag = box.select_one('img[src*="image.aladin.co.kr"]')
                img_url = ""
                if img_tag:
                    img_url = img_tag.get("src", "")
                    img_url = img_url.replace("coversum", "cover200")

                # 품절 여부 확인
                box_text = box.get_text()
                is_soldout = "품절" in box_text or "절판" in box_text

                if product_id and title:
                    product = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={product_id}",
                        "image": img_url,
                        "soldout": is_soldout,
                    }
                    page_products[product_id] = product

                    # 신상품이면 즉시 알림
                    if product_id not in site_saved and product_id not in products:
                        if not is_first_run:
                            print(f"[{datetime.now()}] [알라딘] 신상품 발견! 즉시 알림: {title[:50]}")
                            send_discord_notification("aladin", {product_id: product})
            except:
                continue

        return page_products

    try:
        base_url = "https://www.aladin.co.kr/shop/wbrowse.aspx?BrowseTarget=List&ViewRowsCount=25&ViewType=Detail&PublishMonth=0&page=1&Stockstatus=1&PublishDay=84&CID=86800&SearchOption="

        # 1. 출시일순 (SortOrder=5)
        print(f"[{datetime.now()}] [알라딘] 출시일순 조회 중...")
        response = requests.get(base_url + "&SortOrder=5", headers=headers, timeout=10)
        release_products = parse_and_notify(response.text)
        print(f"[{datetime.now()}] [알라딘] 출시일순: {len(release_products)}개")
        products.update(release_products)

        # 2. 등록일순 (SortOrder=6)
        print(f"[{datetime.now()}] [알라딘] 등록일순 조회 중...")
        response = requests.get(base_url + "&SortOrder=6", headers=headers, timeout=10)
        register_products = parse_and_notify(response.text)
        print(f"[{datetime.now()}] [알라딘] 등록일순: {len(register_products)}개")

        # 등록일순에서 새로 발견된 상품 추가
        for pid, prod in register_products.items():
            if pid not in products:
                products[pid] = prod

        return products

    except Exception as e:
        print(f"[{datetime.now()}] [알라딘] 상품 조회 실패: {e}")
        return None


def fetch_ktown4u_products(driver, saved_products, is_first_run):
    """Ktown4u에서 상품 목록 가져오기 - 즉시 알림 (최적화)"""
    site_saved = saved_products.get("ktown4u", {})

    try:
        url = SITES["ktown4u"]["url"]
        print(f"[{datetime.now()}] [Ktown4u] 페이지 로드 중...")
        driver.get(url)

        # 상품이 로드될 때까지 대기 (최대 10초)
        WebDriverWait(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, 'a[href*="/iteminfo?"]')) > 5
        )

        # 스크롤해서 더 많은 상품 로드 (최적화: 3회로 축소, 대기 시간 단축)
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.8)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        products = {}

        # 상품 링크 찾기
        product_links = soup.select('a[href*="/iteminfo?"]')

        for link in product_links:
            try:
                href = link.get("href", "")
                match = re.search(r"goods_no=(\d+)", href)
                if not match:
                    continue

                product_id = match.group(1)
                if product_id in products:
                    continue

                # 이미지와 제목 찾기
                img = link.select_one("img")
                if not img:
                    continue

                title = img.get("alt", "")
                if not title or "LP" not in title.upper():
                    continue

                img_url = img.get("src", "")

                # 가격 찾기
                link_text = link.get_text()
                price_match = re.search(r"KRW\s*([\d,]+)", link_text)
                price = ""
                if price_match:
                    price = price_match.group(1) + "원"

                # 품절 여부 확인
                is_soldout = "품절" in link_text

                product = {
                    "title": title[:100],
                    "price": price,
                    "url": f"https://kr.ktown4u.com/iteminfo?goods_no={product_id}",
                    "image": img_url.replace("/thumbnail/", "/detail/") if img_url else "",
                    "soldout": is_soldout,
                }
                products[product_id] = product

                # 신상품이면 즉시 알림
                if product_id not in site_saved:
                    if not is_first_run:
                        print(f"[{datetime.now()}] [Ktown4u] 신상품 발견! 즉시 알림: {title[:50]}")
                        send_discord_notification("ktown4u", {product_id: product})
            except:
                continue

        return products

    except Exception as e:
        print(f"[{datetime.now()}] [Ktown4u] 상품 조회 실패: {e}")
        return None


def send_discord_notification(site_key, new_products):
    """Discord로 새 상품 알림 보내기"""
    site = SITES[site_key]

    for product_id, product in new_products.items():
        # 품절 여부에 따라 타이틀 변경
        is_soldout = product.get("soldout", False)
        title_prefix = "🎵 새 LP 등록!"
        if is_soldout:
            title_prefix = "🎵 새 LP 등록! [품절]"

        embed = {
            "embeds": [
                {
                    "title": f"{title_prefix} [{site['name']}]",
                    "description": product["title"],
                    "url": product["url"],
                    "color": 0x808080 if is_soldout else site["color"],  # 품절이면 회색
                    "fields": [],
                    "footer": {"text": f"{site['name']} LP"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        }

        if product["price"]:
            price_display = product["price"]
            if is_soldout:
                price_display = f"~~{product['price']}~~ (품절)"
            embed["embeds"][0]["fields"].append(
                {"name": "가격", "value": price_display, "inline": True}
            )

        if product["image"]:
            embed["embeds"][0]["thumbnail"] = {"url": product["image"]}

        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=embed, timeout=10)
            if response.status_code == 204:
                print(f"[{datetime.now()}] [{site['name']}] 알림 전송 완료: {product['title']}")
            else:
                print(f"[{datetime.now()}] [{site['name']}] 알림 전송 실패: {response.status_code}")
            time.sleep(0.5)
        except Exception as e:
            print(f"[{datetime.now()}] [{site['name']}] Discord 전송 오류: {e}")


def main():
    print(f"[{datetime.now()}] LP 모니터링 시작 (Yes24 + 알라딘 + Ktown4u)...")
    start_time = time.time()

    saved_products = load_saved_products()
    is_first_run = all(not saved_products.get(site, {}) for site in SITES.keys())

    results = {}
    driver = None

    try:
        # 병렬 실행: 알라딘(requests)과 Selenium 작업 동시 실행
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 알라딘은 requests로 별도 스레드에서 실행
            aladin_future = executor.submit(fetch_aladin_products, saved_products, is_first_run)

            # Selenium 작업 (Yes24 + Ktown4u)는 메인 스레드에서 순차 실행
            driver = create_driver()

            # Yes24 조회
            yes24_products = fetch_yes24_products(driver, saved_products, is_first_run)
            if yes24_products:
                results["yes24"] = yes24_products
                print(f"[{datetime.now()}] [Yes24] 조회된 상품: {len(yes24_products)}개")

            # Ktown4u 조회
            ktown4u_products = fetch_ktown4u_products(driver, saved_products, is_first_run)
            if ktown4u_products:
                results["ktown4u"] = ktown4u_products
                print(f"[{datetime.now()}] [Ktown4u] 조회된 상품: {len(ktown4u_products)}개")

            # 알라딘 결과 수집
            aladin_products = aladin_future.result()
            if aladin_products:
                results["aladin"] = aladin_products
                print(f"[{datetime.now()}] [알라딘] 조회된 상품: {len(aladin_products)}개")

        # 결과 저장
        for site_key, current_products in results.items():
            site_saved = saved_products.get(site_key, {})
            saved_products[site_key] = {**site_saved, **current_products}

        save_products(saved_products)

        elapsed = time.time() - start_time
        print(f"[{datetime.now()}] 총 소요 시간: {elapsed:.1f}초")

        if is_first_run:
            print(f"[{datetime.now()}] 첫 실행 - 상품 목록 저장 완료")
            total_count = sum(len(saved_products.get(s, {})) for s in SITES.keys())
            test_msg = {
                "content": f"✅ LP 모니터링이 시작되었습니다! (Yes24 + 알라딘 + Ktown4u)\n현재 총 {total_count}개의 상품을 추적 중입니다."
            }
            try:
                requests.post(DISCORD_WEBHOOK_URL, json=test_msg, timeout=10)
            except:
                pass

    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
