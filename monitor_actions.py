#!/usr/bin/env python3
"""
Yes24 가요 LP 신상품 모니터링 스크립트 (GitHub Actions용)
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

# 설정
CATEGORY_URL = "https://www.yes24.com/Product/Category/Display/003001033001?pageNumber=1&pageSize=24&sortType=NEW"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DATA_FILE = "products.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def load_saved_products():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_products(products):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def fetch_products():
    try:
        response = requests.get(CATEGORY_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        products = {}
        goods_list = soup.select("li[data-goods-no]")

        for item in goods_list:
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
                        "image": img_url
                    }
            except:
                continue

        return products
    except Exception as e:
        print(f"상품 조회 실패: {e}")
        return None


def send_discord_notification(new_products):
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL이 설정되지 않았습니다.")
        return

    for product_id, product in new_products.items():
        embed = {
            "embeds": [{
                "title": "🎵 새 LP 등록!",
                "description": product["title"],
                "url": product["url"],
                "color": 0x00D4AA,
                "fields": [],
                "footer": {"text": "Yes24 가요 LP"},
                "timestamp": datetime.utcnow().isoformat()
            }]
        }

        if product["price"]:
            embed["embeds"][0]["fields"].append({
                "name": "가격",
                "value": product["price"],
                "inline": True
            })

        if product["image"]:
            embed["embeds"][0]["thumbnail"] = {"url": product["image"]}

        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=embed, timeout=10)
            if response.status_code == 204:
                print(f"알림 전송 완료: {product['title']}")
            else:
                print(f"알림 전송 실패: {response.status_code}")
        except Exception as e:
            print(f"Discord 전송 오류: {e}")


def main():
    print(f"[{datetime.now()}] Yes24 가요 LP 모니터링...")

    saved_products = load_saved_products()
    current_products = fetch_products()

    if current_products is None:
        print("상품 조회 실패")
        return

    print(f"조회된 상품: {len(current_products)}개")

    if not saved_products:
        print("첫 실행 - 상품 목록 저장")
        save_products(current_products)
        return

    new_products = {
        pid: prod for pid, prod in current_products.items()
        if pid not in saved_products
    }

    if new_products:
        print(f"새 상품 {len(new_products)}개 발견!")
        send_discord_notification(new_products)
        saved_products.update(current_products)
        save_products(saved_products)
    else:
        print("새 상품 없음")


if __name__ == "__main__":
    main()
