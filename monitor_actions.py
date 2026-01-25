#!/usr/bin/env python3
"""
LP 신상품 모니터링 스크립트 (GitHub Actions용)
Yes24 + Aladin + Ktown4u를 모니터링합니다.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
from datetime import datetime, timezone
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 설정
SITES = {
    "yes24": {
        "name": "Yes24",
        "url": "https://www.yes24.com/Product/Category/Display/003001033001",
        "color": 0x00D4AA,
    },
    "aladin": {
        "name": "알라딘",
        "url": "https://www.aladin.co.kr/shop/wbrowse.aspx?BrowseTarget=List&ViewRowsCount=25&ViewType=Detail&PublishMonth=0&SortOrder=6&page=1&Stockstatus=1&PublishDay=84&CID=86800&SearchOption=",
        "color": 0x8B4513,
    },
    "ktown4u": {
        "name": "Ktown4u",
        "url": "https://kr.ktown4u.com/searchList?goodsTextSearch=lp&goodsSearch=newgoods",
        "color": 0xFF6B6B,
    },
}

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DATA_FILE = "products.json"


def load_saved_products():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data and not any(key in data for key in SITES.keys()):
                print("데이터 형식 마이그레이션 중...")
                return {"yes24": data, "aladin": {}, "ktown4u": {}}
            for site_key in SITES.keys():
                if site_key not in data:
                    data[site_key] = {}
            return data
    return {site: {} for site in SITES.keys()}


def save_products(products):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def create_driver():
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

    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'},
    )
    return driver


def fetch_yes24_products(driver):
    try:
        url = SITES["yes24"]["url"]
        print(f"[Yes24] 페이지 로드 중...")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-goods-no]"))
        )

        print(f"[Yes24] 신상품순 정렬 클릭...")
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

                # 품절 여부 확인
                item_text = item.get_text()
                item_html = str(item).lower()
                is_soldout = (
                    "품절" in item_text
                    or "soldout" in item_html
                    or item.select_one('[class*="soldout"]') is not None
                )

                if product_id and title:
                    products[product_id] = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.yes24.com/Product/Goods/{product_id}",
                        "image": img_url,
                        "soldout": is_soldout,
                    }
            except:
                continue

        return products

    except Exception as e:
        print(f"[Yes24] 상품 조회 실패: {e}")
        return None


def fetch_aladin_products(driver):
    try:
        url = SITES["aladin"]["url"]
        print(f"[알라딘] 페이지 로드 중...")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.ss_book_box"))
        )

        soup = BeautifulSoup(driver.page_source, "html.parser")
        products = {}

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
                    products[product_id] = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={product_id}",
                        "image": img_url,
                        "soldout": is_soldout,
                    }
            except:
                continue

        return products

    except Exception as e:
        print(f"[알라딘] 상품 조회 실패: {e}")
        return None


def fetch_ktown4u_products(driver):
    try:
        url = SITES["ktown4u"]["url"]
        print(f"[Ktown4u] 페이지 로드 중...")
        driver.get(url)

        time.sleep(8)

        for _ in range(5):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)

        soup = BeautifulSoup(driver.page_source, "html.parser")
        products = {}

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

                img = link.select_one("img")
                if not img:
                    continue

                title = img.get("alt", "")
                if not title or "LP" not in title.upper():
                    continue

                img_url = img.get("src", "")

                link_text = link.get_text()
                price_match = re.search(r"KRW\s*([\d,]+)", link_text)
                price = ""
                if price_match:
                    price = price_match.group(1) + "원"

                # 품절 여부 확인
                is_soldout = "품절" in link_text

                products[product_id] = {
                    "title": title[:100],
                    "price": price,
                    "url": f"https://kr.ktown4u.com/iteminfo?goods_no={product_id}",
                    "image": img_url.replace("/thumbnail/", "/detail/") if img_url else "",
                    "soldout": is_soldout,
                }
            except:
                continue

        return products

    except Exception as e:
        print(f"[Ktown4u] 상품 조회 실패: {e}")
        return None


def send_discord_notification(site_key, new_products):
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL이 설정되지 않았습니다.")
        return

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
                print(f"[{site['name']}] 알림 전송 완료: {product['title']}")
            else:
                print(f"[{site['name']}] 알림 전송 실패: {response.status_code}")
            time.sleep(0.5)
        except Exception as e:
            print(f"[{site['name']}] Discord 전송 오류: {e}")


def main():
    print(f"[{datetime.now()}] LP 모니터링 (Yes24 + 알라딘 + Ktown4u)...")

    saved_products = load_saved_products()
    driver = None

    try:
        driver = create_driver()

        fetch_functions = {
            "yes24": fetch_yes24_products,
            "aladin": fetch_aladin_products,
            "ktown4u": fetch_ktown4u_products,
        }

        is_first_run = all(not saved_products.get(site, {}) for site in SITES.keys())
        total_new = 0

        for site_key, fetch_func in fetch_functions.items():
            site = SITES[site_key]
            current_products = fetch_func(driver)

            if current_products is None:
                print(f"[{site['name']}] 상품 조회 실패")
                continue

            print(f"[{site['name']}] 조회된 상품: {len(current_products)}개")

            site_saved = saved_products.get(site_key, {})

            new_products = {
                pid: prod
                for pid, prod in current_products.items()
                if pid not in site_saved
            }

            if new_products:
                print(f"[{site['name']}] 새 상품 {len(new_products)}개 발견!")
                if not is_first_run:
                    send_discord_notification(site_key, new_products)
                total_new += len(new_products)

            saved_products[site_key] = {**site_saved, **current_products}

        save_products(saved_products)

        if is_first_run:
            print("첫 실행 - 상품 목록 저장 완료")
        elif total_new == 0:
            print("새 상품 없음")

    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
