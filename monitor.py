#!/Users/cehwang/miniconda3/bin/python3
"""
Yes24 가요 LP 신상품 모니터링 스크립트
새 상품이 등록되면 Discord로 알림을 보냅니다.
"""

import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

# 설정
CATEGORY_URL = "https://www.yes24.com/Product/Category/Display/003001033001?pageNumber=1&pageSize=24&sortType=NEW"
DISCORD_WEBHOOK_URL = "https://discordapp.com/api/webhooks/1464577763527889137/crrzuov6ADoIoNcrJ5-jCK723zkXmjaKovNOL5WprbGlTVDjrhIKIJJcvr0RpkqDeOkx"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def load_saved_products():
    """저장된 상품 목록 불러오기"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_products(products):
    """상품 목록 저장"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False, indent=2)


def fetch_products():
    """Yes24에서 상품 목록 가져오기"""
    try:
        response = requests.get(CATEGORY_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        products = {}

        # 상품 목록 파싱 - li[data-goods-no] 선택자 사용
        goods_list = soup.select("li[data-goods-no]")

        for item in goods_list:
            try:
                product_id = item.get("data-goods-no")
                if not product_id:
                    continue

                # 상품명 찾기 - a.gd_name
                title_tag = item.select_one("a.gd_name")
                title = title_tag.get_text(strip=True) if title_tag else ""

                # 가격 찾기 - hidden input의 JSON 데이터에서 추출
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

                # 가격 태그에서도 시도
                if not price:
                    price_tag = item.select_one("em.yes_b")
                    if price_tag:
                        price = price_tag.get_text(strip=True) + "원"

                # 이미지 찾기
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
            except Exception as e:
                continue

        return products
    except Exception as e:
        print(f"[{datetime.now()}] 상품 조회 실패: {e}")
        return None


def send_discord_notification(new_products):
    """Discord로 새 상품 알림 보내기"""
    for product_id, product in new_products.items():
        embed = {
            "embeds": [{
                "title": f"🎵 새 LP 등록!",
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
                print(f"[{datetime.now()}] 알림 전송 완료: {product['title']}")
            else:
                print(f"[{datetime.now()}] 알림 전송 실패: {response.status_code}")
        except Exception as e:
            print(f"[{datetime.now()}] Discord 전송 오류: {e}")


def main():
    print(f"[{datetime.now()}] Yes24 가요 LP 모니터링 시작...")

    # 저장된 상품 목록 불러오기
    saved_products = load_saved_products()

    # 현재 상품 목록 가져오기
    current_products = fetch_products()

    if current_products is None:
        print(f"[{datetime.now()}] 상품 조회에 실패했습니다.")
        return

    print(f"[{datetime.now()}] 조회된 상품: {len(current_products)}개")

    # 첫 실행인 경우
    if not saved_products:
        print(f"[{datetime.now()}] 첫 실행 - 상품 목록 저장 중...")
        save_products(current_products)
        print(f"[{datetime.now()}] {len(current_products)}개 상품 저장 완료")

        # 테스트 메시지 전송
        test_msg = {
            "content": f"✅ Yes24 가요 LP 모니터링이 시작되었습니다!\n현재 {len(current_products)}개의 상품을 추적 중입니다."
        }
        try:
            requests.post(DISCORD_WEBHOOK_URL, json=test_msg, timeout=10)
        except:
            pass
        return

    # 새 상품 찾기
    new_products = {}
    for product_id, product in current_products.items():
        if product_id not in saved_products:
            new_products[product_id] = product

    if new_products:
        print(f"[{datetime.now()}] 새 상품 {len(new_products)}개 발견!")
        send_discord_notification(new_products)

        # 상품 목록 업데이트
        saved_products.update(current_products)
        save_products(saved_products)
    else:
        print(f"[{datetime.now()}] 새 상품 없음")


if __name__ == "__main__":
    main()
