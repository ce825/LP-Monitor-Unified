#!/usr/bin/env python3
"""
LP 통합 모니터링 스크립트 (GitHub Actions용)
신상품 + 재입고를 한 번에 모니터링합니다.
Yes24 + Aladin + Ktown4u
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import re
import random
from datetime import datetime, timezone
import time
from concurrent.futures import ThreadPoolExecutor

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

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
        "color": 0xFFD700,
    },
    "ktown4u": {
        "name": "Ktown4u",
        "url": "https://kr.ktown4u.com/searchList?goodsTextSearch=lp&goodsSearch=newgoods",
        "color": 0xFF6B6B,
    },
}

# Discord Webhooks (신상품/재입고 분리)
DISCORD_WEBHOOK_NEW = os.environ.get("DISCORD_WEBHOOK_NEW", "")
DISCORD_WEBHOOK_RESTOCK = os.environ.get("DISCORD_WEBHOOK_RESTOCK", "")
DATA_FILE = "products.json"

# 재입고 알림 제외 상품 (상품 ID 또는 제목 키워드)
RESTOCK_EXCLUDE = {
    "ids": {
        "153151430",  # Yes24 - 브라운 아이드 소울 Soul Tricycle 블루 컬러 2LP
        "167465825",  # Yes24 - 브라운 아이드 소울 Soul Tricycle 2LP
        "378968965",  # Aladin - 브라운 아이드 소울 Soul Tricycle 2LP
        "152687",     # Ktown4u - 브라운 아이드 소울 Soul Tricycle 2LP
        "154936022",  # Yes24 - Mark Tuan Silhouette LP
        "373080976",  # Aladin - Mark Tuan Silhouette LP
        "148039",     # Ktown4u - Mark Tuan Silhouette LP
        "386044574",  # Aladin - 터치드 TOUCHED GSI Edition LP
        "386043641",  # Aladin - 김수영 Antiguo Trunk LP
        "384368363",  # Aladin - 김현철 VOL.1 LP
        "384368953",  # Aladin - 김현철 VOL.1 골드 마블 컬러 LP
        "386060891",  # Aladin - 권나무 삶의 향기 2LP
    },
    "keywords": [
        "브라운 아이드 소울",
        "Brown Eyed Soul",
        "Soul Tricycle",
        "Mark Tuan",
        "Silhouette",
        "GSI Edition",  # GSI 에디션 LP (품절 감지 문제)
    ]
}


def load_saved_products():
    """저장된 상품 목록 불러오기"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
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

    driver = webdriver.Chrome(options=chrome_options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'},
    )
    return driver


def get_first_product_id(driver):
    """현재 페이지의 첫 번째 상품 ID 가져오기"""
    try:
        first_item = driver.find_element(By.CSS_SELECTOR, "li[data-goods-no]")
        return first_item.get_attribute("data-goods-no")
    except:
        return None


def click_sort_and_wait(driver, sort_value, sort_name, max_wait=10):
    """정렬 버튼 클릭 후 페이지 변경 대기"""
    try:
        # 현재 첫 번째 상품 ID 저장
        old_first_id = get_first_product_id(driver)
        print(f"[Yes24] {sort_name} 정렬 클릭 (현재 첫 상품: {old_first_id})")

        # JavaScript로 정렬 버튼 클릭
        driver.execute_script(f"""
            var btn = document.querySelector("a[data-search-value='{sort_value}']");
            if (btn) btn.click();
        """)

        # 페이지 내용이 변경될 때까지 대기
        start_time = time.time()
        while time.time() - start_time < max_wait:
            time.sleep(0.5)
            new_first_id = get_first_product_id(driver)
            if new_first_id and new_first_id != old_first_id:
                print(f"[Yes24] {sort_name} 페이지 변경 감지 (새 첫 상품: {new_first_id})")
                time.sleep(1)  # 추가 안정화 대기
                return True

        # 변경 안 되면 그냥 대기 후 진행
        print(f"[Yes24] {sort_name} 페이지 변경 감지 실패, 5초 대기 후 진행")
        time.sleep(5)
        return True

    except Exception as e:
        print(f"[Yes24] {sort_name} 정렬 실패: {e}")
        return False


def fetch_yes24_products(driver, saved_products, is_first_run):
    """Yes24에서 상품 목록 가져오기 (신상품순 + 등록일순 + 판매량순)"""
    products = {}
    site_key = "yes24"
    site_saved = saved_products.get(site_key, {})

    def parse_products_from_page():
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
                    page_products[product_id] = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.yes24.com/Product/Goods/{product_id}",
                        "image": img_url,
                        "soldout": is_soldout,
                    }
            except:
                continue

        return page_products

    def process_products(page_products, label):
        """상품 처리 및 알림 전송"""
        print(f"[Yes24] {label}: {len(page_products)}개")

        if not is_first_run:
            for pid, prod in page_products.items():
                if pid not in site_saved and pid not in products:
                    send_new_product_notification(site_key, {pid: prod})
                elif pid in site_saved and site_saved[pid].get("soldout") and not prod.get("soldout"):
                    send_restock_notification(site_key, {pid: prod})

        for pid, prod in page_products.items():
            if pid not in products:
                products[pid] = prod

    try:
        url = SITES["yes24"]["url"]
        print(f"[Yes24] 페이지 로드 중...")
        driver.get(url)

        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "li[data-goods-no]"))
        )
        time.sleep(2)

        # 1. 신상품순 정렬
        if click_sort_and_wait(driver, "RECENT", "신상품순"):
            recent_products = parse_products_from_page()
            process_products(recent_products, "신상품순")

        # 2. 등록일순 정렬
        if click_sort_and_wait(driver, "REG_DTS", "등록일순"):
            # 스크롤해서 더 많은 상품 로드
            for _ in range(3):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
            new_products = parse_products_from_page()
            process_products(new_products, "등록일순")

        # 3. 판매량순 정렬 (재입고 체크용)
        if click_sort_and_wait(driver, "SALE_SCO", "판매량순"):
            sale_products = parse_products_from_page()
            process_products(sale_products, "판매량순")

        return products

    except Exception as e:
        print(f"[Yes24] 상품 조회 실패: {e}")
        return products if products else None


def fetch_aladin_products(saved_products, is_first_run):
    """알라딘에서 상품 목록 가져오기 (출시일순 + 등록일순 + 리뷰순 2페이지)"""
    products = {}
    site_key = "aladin"
    site_saved = saved_products.get(site_key, {})

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9',
    }

    def parse_products_from_html(html):
        soup = BeautifulSoup(html, "html.parser")
        page_products = {}

        # 방법 1: ss_book_box (책 카테고리)
        boxes = soup.select("div.ss_book_box")

        # 방법 2: ss_book_box가 없으면 ItemId 링크를 기준으로 파싱 (음악 카테고리)
        if not boxes:
            # 모든 ItemId 링크를 찾아서 부모 요소를 box로 사용
            item_links = soup.select('a[href*="ItemId="]')
            seen_ids = set()
            for link in item_links:
                href = link.get("href", "")
                match = re.search(r"ItemId=(\d+)", href)
                if match and match.group(1) not in seen_ids:
                    seen_ids.add(match.group(1))
                    # 부모를 3-5단계 올라가서 상품 컨테이너 찾기
                    parent = link
                    for _ in range(5):
                        if parent.parent:
                            parent = parent.parent
                            # 텍스트가 충분히 많으면 상품 컨테이너로 간주
                            if len(parent.get_text()) > 50:
                                break
                    boxes.append(parent)

        for box in boxes:
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
                if product_id in page_products:
                    continue

                title = title_link.get_text(strip=True)

                price_tag = box.select_one("span.ss_p2")
                price = price_tag.get_text(strip=True) if price_tag else ""
                # 가격이 없으면 다른 방식으로 찾기
                if not price:
                    price_match = re.search(r"(\d{1,3}(?:,\d{3})*)\s*원", box.get_text())
                    if price_match:
                        price = price_match.group(1) + "원"

                img_tag = box.select_one('img[src*="image.aladin.co.kr"]')
                img_url = ""
                if img_tag:
                    img_url = img_tag.get("src", "")
                    img_url = img_url.replace("coversum", "cover200")

                # 품절 여부 확인 (다양한 방식으로 체크)
                box_text = box.get_text()
                box_html = str(box).lower()
                is_soldout = (
                    "품절" in box_text
                    or "절판" in box_text
                    or "일시품절" in box_text
                    or "구매불가" in box_text
                    or "재입고 알림" in box_text  # 재입고 알림 버튼이 있으면 품절
                    or "유통이 중단" in box_text  # 유통 중단 메시지
                    or "soldout" in box_html
                    or "sold_out" in box_html
                    or "sold-out" in box_html
                    or box.select_one('[class*="soldout"]') is not None
                    or box.select_one('[class*="품절"]') is not None
                    or box.select_one('img[alt*="품절"]') is not None
                    or box.select_one('img[src*="soldout"]') is not None
                )

                if product_id and title:
                    page_products[product_id] = {
                        "title": title[:100],
                        "price": price,
                        "url": f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={product_id}",
                        "image": img_url,
                        "soldout": is_soldout,
                    }
            except:
                continue

        return page_products

    def safe_request(url):
        """Rate limit을 고려한 안전한 요청"""
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 429:
                print(f"[알라딘] Rate limit 감지, 5초 대기...")
                time.sleep(5)
                response = requests.get(url, headers=headers, timeout=10)
            return response
        except Exception as e:
            print(f"[알라딘] 요청 실패: {e}")
            return None

    try:
        base_url = "https://www.aladin.co.kr/shop/wbrowse.aspx?BrowseTarget=List&ViewRowsCount=25&ViewType=Detail&PublishMonth=0&page=1&PublishDay=84&CID=86800&SearchOption="

        # 1. 출시일순 (SortOrder=5)
        print(f"[알라딘] 출시일순 조회...")
        response = safe_request(base_url + "&SortOrder=5")
        if response:
            release_products = parse_products_from_html(response.text)
            print(f"[알라딘] 출시일순: {len(release_products)}개")

            # 즉시 알림
            if not is_first_run:
                for pid, prod in release_products.items():
                    if pid not in site_saved and pid not in products:
                        send_new_product_notification(site_key, {pid: prod})
                    elif pid in site_saved and site_saved[pid].get("soldout") and not prod.get("soldout"):
                        print(f"[알라딘] 재입고 감지: {prod['title'][:30]} (저장: soldout=True, 현재: soldout=False)")
                        send_restock_notification(site_key, {pid: prod})

            products.update(release_products)

        time.sleep(1)  # 요청 간 딜레이

        # 2. 등록일순 (SortOrder=6)
        print(f"[알라딘] 등록일순 조회...")
        response = safe_request(base_url + "&SortOrder=6")
        if response:
            register_products = parse_products_from_html(response.text)
            print(f"[알라딘] 등록일순: {len(register_products)}개")

            # 즉시 알림
            if not is_first_run:
                for pid, prod in register_products.items():
                    if pid not in site_saved and pid not in products:
                        send_new_product_notification(site_key, {pid: prod})
                    elif pid in site_saved and site_saved[pid].get("soldout") and not prod.get("soldout"):
                        print(f"[알라딘] 재입고 감지: {prod['title'][:30]} (저장: soldout=True, 현재: soldout=False)")
                        send_restock_notification(site_key, {pid: prod})

            for pid, prod in register_products.items():
                if pid not in products:
                    products[pid] = prod

        time.sleep(1)  # 요청 간 딜레이

        # 3. 리뷰순 (SortOrder=4) - 날짜 필터 없이 2페이지까지 (재입고 체크용)
        review_base = "https://www.aladin.co.kr/shop/wbrowse.aspx?BrowseTarget=List&ViewRowsCount=25&ViewType=Detail&CID=86800&SortOrder=4"

        for page in [1, 2]:
            print(f"[알라딘] 리뷰순 {page}페이지 조회...")
            response = safe_request(f"{review_base}&page={page}")
            if response:
                review_products = parse_products_from_html(response.text)
                print(f"[알라딘] 리뷰순 {page}페이지: {len(review_products)}개")

                # 즉시 알림 (재입고용)
                if not is_first_run:
                    for pid, prod in review_products.items():
                        if pid not in site_saved and pid not in products:
                            send_new_product_notification(site_key, {pid: prod})
                        elif pid in site_saved and site_saved[pid].get("soldout") and not prod.get("soldout"):
                            print(f"[알라딘] 재입고 감지: {prod['title'][:30]} (저장: soldout=True, 현재: soldout=False)")
                            send_restock_notification(site_key, {pid: prod})

                for pid, prod in review_products.items():
                    if pid not in products:
                        products[pid] = prod
            time.sleep(1)  # 요청 간 딜레이

        return products

    except Exception as e:
        print(f"[알라딘] 상품 조회 실패: {e}")
        return None


def fetch_ktown4u_products(driver, saved_products, is_first_run):
    """Ktown4u에서 상품 목록 가져오기"""
    site_key = "ktown4u"
    site_saved = saved_products.get(site_key, {})

    try:
        url = SITES["ktown4u"]["url"]
        print(f"[Ktown4u] 페이지 로드 중...")
        driver.get(url)

        WebDriverWait(driver, 10).until(
            lambda d: len(d.find_elements(By.CSS_SELECTOR, 'a[href*="/iteminfo?"]')) > 5
        )

        # 스크롤해서 더 많은 상품 로드
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.8)

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

                is_soldout = "품절" in link_text

                prod = {
                    "title": title[:100],
                    "price": price,
                    "url": f"https://kr.ktown4u.com/iteminfo?goods_no={product_id}",
                    "image": img_url.replace("/thumbnail/", "/detail/") if img_url else "",
                    "soldout": is_soldout,
                }

                # 즉시 알림
                if not is_first_run:
                    if product_id not in site_saved:
                        send_new_product_notification(site_key, {product_id: prod})
                    elif site_saved[product_id].get("soldout") and not is_soldout:
                        send_restock_notification(site_key, {product_id: prod})

                products[product_id] = prod
            except:
                continue

        return products

    except Exception as e:
        print(f"[Ktown4u] 상품 조회 실패: {e}")
        return None


def send_new_product_notification(site_key, new_products):
    """신상품 알림 전송"""
    if not DISCORD_WEBHOOK_NEW:
        print("신상품 Discord webhook URL이 설정되지 않았습니다.")
        return

    site = SITES[site_key]

    for product_id, product in new_products.items():
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
                    "color": 0x808080 if is_soldout else site["color"],
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
            response = requests.post(DISCORD_WEBHOOK_NEW, json=embed, timeout=10)
            if response.status_code == 204:
                print(f"[{site['name']}] 신상품 알림 전송: {product['title'][:50]}")
            else:
                print(f"[{site['name']}] 알림 전송 실패: {response.status_code}")
            time.sleep(0.5)
        except Exception as e:
            print(f"[{site['name']}] Discord 전송 오류: {e}")


def is_restock_excluded(product_id, title):
    """재입고 알림 제외 대상인지 확인"""
    if product_id in RESTOCK_EXCLUDE["ids"]:
        return True
    for keyword in RESTOCK_EXCLUDE["keywords"]:
        if keyword.lower() in title.lower():
            return True
    return False


def send_restock_notification(site_key, restocked_products):
    """재입고 알림 전송"""
    if not DISCORD_WEBHOOK_RESTOCK:
        print("재입고 Discord webhook URL이 설정되지 않았습니다.")
        return

    site = SITES[site_key]

    for product_id, product in restocked_products.items():
        # 제외 대상 확인
        if is_restock_excluded(product_id, product.get("title", "")):
            print(f"[{site['name']}] 재입고 알림 제외: {product['title'][:50]}")
            continue

        embed = {
            "embeds": [
                {
                    "title": f"🎉 LP 재입고! [{site['name']}]",
                    "description": product["title"],
                    "url": product["url"],
                    "color": site["color"],
                    "fields": [],
                    "footer": {"text": f"{site['name']} LP 재입고"},
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
            response = requests.post(DISCORD_WEBHOOK_RESTOCK, json=embed, timeout=10)
            if response.status_code == 204:
                print(f"[{site['name']}] 재입고 알림 전송: {product['title'][:50]}")
            else:
                print(f"[{site['name']}] 알림 전송 실패: {response.status_code}")
            time.sleep(0.5)
        except Exception as e:
            print(f"[{site['name']}] Discord 전송 오류: {e}")


def main():
    # 랜덤 딜레이 (0~15초) - 봇 패턴 회피
    delay = random.randint(0, 15)
    print(f"[{datetime.now()}] 랜덤 딜레이: {delay}초")
    time.sleep(delay)

    print(f"[{datetime.now()}] LP 통합 모니터링 시작 (신상품 + 재입고)...")
    start_time = time.time()

    saved_products = load_saved_products()
    is_first_run = all(not saved_products.get(site, {}) for site in SITES.keys())

    if is_first_run:
        print("첫 실행 - 상품 목록만 저장하고 알림은 보내지 않습니다.")

    results = {}
    driver = None

    try:
        # 병렬 실행: 알라딘(requests)과 Selenium 작업 동시 실행
        with ThreadPoolExecutor(max_workers=2) as executor:
            # 알라딘은 requests로 별도 스레드에서 실행
            aladin_future = executor.submit(fetch_aladin_products, saved_products, is_first_run)

            # Selenium 작업 (Yes24 + Ktown4u)
            driver = create_driver()

            yes24_products = fetch_yes24_products(driver, saved_products, is_first_run)
            if yes24_products:
                results["yes24"] = yes24_products

            ktown4u_products = fetch_ktown4u_products(driver, saved_products, is_first_run)
            if ktown4u_products:
                results["ktown4u"] = ktown4u_products

            # 알라딘 결과 수집
            aladin_products = aladin_future.result()
            if aladin_products:
                results["aladin"] = aladin_products

        # 결과 집계 (알림은 이미 즉시 전송됨)
        for site_key, current_products in results.items():
            site = SITES[site_key]
            site_saved = saved_products.get(site_key, {})

            print(f"[{site['name']}] 조회 완료: {len(current_products)}개")

            # 상품 데이터 업데이트
            for pid, prod in current_products.items():
                site_saved[pid] = prod
            saved_products[site_key] = site_saved

        # 저장
        save_products(saved_products)

        elapsed = time.time() - start_time
        print(f"[{datetime.now()}] 완료 - 소요시간: {elapsed:.1f}초")

    finally:
        if driver:
            driver.quit()


if __name__ == "__main__":
    main()
