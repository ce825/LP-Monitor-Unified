#!/Users/cehwang/miniconda3/bin/python3
"""
LP 신상품 모니터링 스크립트 (Yes24 + Aladin)
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
        "color": 0x8B4513,  # 갈색
    },
}

DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1464577763527889137/crrzuov6ADoIoNcrJ5-jCK723zkXmjaKovNOL5WprbGlTVDjrhIKIJJcvr0RpkqDeOkx"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products.json")


def load_saved_products():
    """저장된 상품 목록 불러오기"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 기존 형식(사이트 구분 없음) -> 새 형식으로 마이그레이션
            if data and not any(key in data for key in SITES.keys()):
                print(f"[{datetime.now()}] 데이터 형식 마이그레이션 중...")
                return {"yes24": data, "aladin": {}}
            return data
    return {site: {} for site in SITES.keys()}


def save_products(products):
    """상품 목록 저장"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def create_driver():
    """Chrome WebDriver 생성"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


def fetch_yes24_products(driver):
    """Yes24에서 상품 목록 가져오기"""
    try:
        url = SITES["yes24"]["url"]
        print(f"[{datetime.now()}] [Yes24] 페이지 로드 중...")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-goods-no]"))
        )

        # 신상품순 정렬
        print(f"[{datetime.now()}] [Yes24] 신상품순 정렬 클릭...")
        sort_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a[data-search-value='RECENT']"))
        )
        sort_button.click()

        time.sleep(2)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-goods-no]"))
        )

        soup = BeautifulSoup(driver.page_source, "html.parser")
        products = {}

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

                if product_id and title:
                    products[product_id] = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.yes24.com/Product/Goods/{product_id}",
                        "image": img_url,
                    }
            except:
                continue

        return products

    except Exception as e:
        print(f"[{datetime.now()}] [Yes24] 상품 조회 실패: {e}")
        return None


def fetch_aladin_products(driver):
    """알라딘에서 상품 목록 가져오기"""
    try:
        url = SITES["aladin"]["url"]
        print(f"[{datetime.now()}] [알라딘] 페이지 로드 중...")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ss_book_box"))
        )

        soup = BeautifulSoup(driver.page_source, "html.parser")
        products = {}

        for box in soup.select("div.ss_book_box"):
            try:
                # 상품 링크에서 ID와 제목 추출
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

                # 가격 추출
                price_tag = box.select_one("span.ss_p2")
                price = price_tag.get_text(strip=True) if price_tag else ""

                # 이미지 추출
                img_tag = box.select_one('img[src*="image.aladin.co.kr"]')
                img_url = ""
                if img_tag:
                    img_url = img_tag.get("src", "")
                    img_url = img_url.replace("coversum", "cover200")

                if product_id and title:
                    products[product_id] = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={product_id}",
                        "image": img_url,
                    }
            except:
                continue

        return products

    except Exception as e:
        print(f"[{datetime.now()}] [알라딘] 상품 조회 실패: {e}")
        return None


def send_discord_notification(site_key, new_products):
    """Discord로 새 상품 알림 보내기"""
    site = SITES[site_key]

    for product_id, product in new_products.items():
        embed = {
            "embeds": [
                {
                    "title": f"🎵 새 LP 등록! [{site['name']}]",
                    "description": product["title"],
                    "url": product["url"],
                    "color": site["color"],
                    "fields": [],
                    "footer": {"text": f"{site['name']} LP"},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        }

        if product["price"]:
            embed["embeds"][0]["fields"].append(
                {"name": "가격", "value": product["price"], "inline": True}
            )

        if product["image"]:
            embed["embeds"][0]["thumbnail"] = {"url": product["image"]}

        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=embed, timeout=10)
            if response.status_code == 204:
                print(f"[{datetime.now()}] [{site['name']}] 알림 전송 완료: {product['title']}")
            else:
                print(f"[{datetime.now()}] [{site['name']}] 알림 전송 실패: {response.status_code}")
            time.sleep(0.5)  # Rate limit 방지
        except Exception as e:
            print(f"[{datetime.now()}] [{site['name']}] Discord 전송 오류: {e}")


def main():
    print(f"[{datetime.now()}] LP 모니터링 시작 (Yes24 + 알라딘)...")

    saved_products = load_saved_products()
    driver = None

    try:
        driver = create_driver()

        # 각 사이트별로 처리
        fetch_functions = {
            "yes24": fetch_yes24_products,
            "aladin": fetch_aladin_products,
        }

        is_first_run = all(not saved_products.get(site, {}) for site in SITES.keys())
        total_new = 0

        for site_key, fetch_func in fetch_functions.items():
            site = SITES[site_key]
            current_products = fetch_func(driver)

            if current_products is None:
                print(f"[{datetime.now()}] [{site['name']}] 상품 조회 실패")
                continue

            print(f"[{datetime.now()}] [{site['name']}] 조회된 상품: {len(current_products)}개")

            site_saved = saved_products.get(site_key, {})

            # 새 상품 찾기
            new_products = {
                pid: prod
                for pid, prod in current_products.items()
                if pid not in site_saved
            }

            if new_products:
                print(f"[{datetime.now()}] [{site['name']}] 새 상품 {len(new_products)}개 발견!")
                if not is_first_run:
                    send_discord_notification(site_key, new_products)
                total_new += len(new_products)

            # 상품 목록 업데이트
            saved_products[site_key] = {**site_saved, **current_products}

        # 저장
        save_products(saved_products)

        if is_first_run:
            print(f"[{datetime.now()}] 첫 실행 - 상품 목록 저장 완료")
            # 테스트 메시지 전송
            total_count = sum(len(saved_products.get(s, {})) for s in SITES.keys())
            test_msg = {
                "content": f"✅ LP 모니터링이 시작되었습니다! (Yes24 + 알라딘)\n현재 총 {total_count}개의 상품을 추적 중입니다."
            }
            try:
                requests.post(DISCORD_WEBHOOK_URL, json=test_msg, timeout=10)
            except:
                pass
        elif total_new == 0:
            print(f"[{datetime.now()}] 새 상품 없음")

    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
