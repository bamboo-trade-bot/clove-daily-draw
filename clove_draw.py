"""Clove 白金登入獎勵每日一抽

用法：
  python clove_draw.py --login     第一次使用：開瀏覽器讓你手動登入，登入完關掉視窗
  python clove_draw.py --dry-run   測試：跑到抽卡確認視窗就按「取消」，不會扣點
  python clove_draw.py             正式：抽一次，10,000pt 以下自動兌換點數
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
PROFILE_DIR = BASE / "clove-profile"  # 登入狀態存這裡，不要分享給別人
LOG_DIR = BASE / "logs"
LIST_URL = "https://oripa.clove.jp/zh-TW/oripa/All"
# 以下三項可用指令參數覆蓋，見 --help
POOL = "ログインボーナス(プラチナ)"  # 卡池名稱（網站商品圖的日文名稱）
POOL_NAME = re.compile(re.escape(POOL))
COST = 5000  # 每抽幾點
EXCHANGE_LIMIT = 10000  # 抽中幾點以下自動兌換成點數


def log(msg):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "clove.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def shot(page, name):
    LOG_DIR.mkdir(exist_ok=True)
    path = LOG_DIR / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{name}.png"
    page.screenshot(path=str(path))
    log(f"截圖：{path}")


def to_int(s):
    return int(s.replace(",", ""))


def read_balance(page):
    # 右上角點數連結，例如 href="/zh-TW/point?from=..."，文字是 6,753
    text = page.locator('a[href*="/point"]').first.inner_text(timeout=10000)
    m = re.search(r"[\d,]+", text)
    if not m:
        raise RuntimeError(f"讀不到點數餘額（{text!r}），可能沒登入")
    return to_int(m.group())


def close_popup(page):
    """關掉活動彈窗。彈窗有動畫，點不到就跳過，不要卡住整支腳本。"""
    dismiss_inapp(page)
    try:
        page.keyboard.press("Escape")
    except Exception:  # noqa: BLE001
        pass
    for name in ("關閉", "close", "×"):
        btn = page.get_by_role("button", name=name, exact=True)
        try:
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=3000, force=True)
                return
        except Exception:  # noqa: BLE001
            continue


def dismiss_inapp(page):
    """關掉網站的促銷彈窗（Braze in-app message），它會蓋住按鈕讓點擊失敗。"""
    page.evaluate(
        """() => {
            document.querySelectorAll('.ab-iam-root, .ab-in-app-message').forEach(e => e.remove());
        }"""
    )


def do_login():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(PROFILE_DIR, channel="chrome", headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LIST_URL)
        print("請在開啟的瀏覽器中登入 Clove，登入完成後直接關掉瀏覽器視窗。")
        page.wait_for_event("close", timeout=0)
        ctx.close()


def do_draw(dry_run):
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, channel="chrome", headless=False, viewport={"width": 1400, "height": 900}
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(LIST_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            close_popup(page)

            balance = read_balance(page)
            log(f"點數餘額：{balance:,}")
            if balance < COST:
                log("點數不足，停止")
                return 1

            link = page.get_by_role("link", name=POOL_NAME).first
            try:
                link.wait_for(timeout=15000)
            except PWTimeout:
                shot(page, "pool-not-found")
                # 今天抽過後，這個卡池會從列表消失
                log("列表上找不到白金登入獎勵卡池（今天已經抽過、卡池已結束，或帳號不是白金等級），停止")
                return 1

            card = link.locator("xpath=ancestor::*[.//button[normalize-space()='抽一次']][1]")
            draw_btn = card.get_by_role("button", name="抽一次", exact=True)
            draw_btn.scroll_into_view_if_needed()
            if draw_btn.is_disabled():
                log("抽一次按鈕無法點擊，今天可能已經抽過，停止")
                return 0
            draw_btn.click()

            confirm = page.get_by_role("button", name=f"用{COST:,}pt抽取")
            try:
                confirm.wait_for(timeout=10000)
            except PWTimeout:
                shot(page, "no-confirm-dialog")
                log("沒有出現「用5,000pt抽取」確認視窗（可能今天已抽過），停止")
                return 1

            if dry_run:
                shot(page, "dry-run-confirm")
                page.get_by_role("button", name="取消").click()
                log("dry-run：已看到確認視窗並按取消，沒有扣點")
                return 0

            confirm.click()
            log("已抽卡，等待結果")

            skip = page.get_by_text("跳過", exact=True).first
            try:
                skip.wait_for(timeout=20000)
                skip.click()
            except PWTimeout:
                pass
            page.wait_for_url(re.compile(r"/result"), timeout=60000)
            page.wait_for_timeout(3000)
            dismiss_inapp(page)

            text = page.locator("body").inner_text()
            # 卡名與獎項只用來寫 log，解析不到也不影響兌換
            groups = re.findall(r"(\S+等[奬獎])\s+(\d+)件", text)
            names = re.findall(r"\n\d+等\s*\n+\s*([^\n]+)", text)
            shot(page, "result")

            # 合計點數以「全選」後頁面顯示的數字為準
            dismiss_inapp(page)
            page.get_by_text("全選", exact=True).click(timeout=15000)
            page.wait_for_timeout(1000)
            m = re.search(r"([\d,]+)\s*\n\s*全選", page.locator("body").inner_text())
            if not m:
                shot(page, "result-unparsed")
                log("讀不到勾選後的合計點數，不做兌換，請自己查看")
                return 1
            total = to_int(m.group(1))
            log(f"抽中：{'、'.join(f'{g}×{n}' for g, n in groups) or '（獎項未解析）'}"
                f"｜{'、'.join(s.strip() for s in names) or '（卡名未解析）'}｜合計 {total:,}pt")

            if total > EXCHANGE_LIMIT:
                log(f"超過 {EXCHANGE_LIMIT:,}pt，保留卡片不兌換 🎉")
                return 0

            dismiss_inapp(page)
            page.get_by_role("button", name="兌換點數").click(timeout=15000)
            page.wait_for_timeout(1500)
            # 確認視窗：「兌換成點數 / 所選商品將兌換成點數。可以嗎？ / 2,253 → 7,753 / 決定 / 取消」
            dialog_btn = page.get_by_role("button", name="決定", exact=True)
            try:
                dialog_btn.wait_for(timeout=10000)
            except PWTimeout:
                shot(page, "exchange-dialog-unknown")
                log("找不到兌換確認按鈕「決定」，請看截圖手動處理")
                return 1
            # 箭頭可能是圖示不是文字，所以只取視窗裡最後兩個數字（兌換前 / 兌換後）
            dialog = dialog_btn.locator("xpath=ancestor::*[contains(., '兌換成點數')][1]")
            nums = re.findall(r"\d{1,3}(?:,\d{3})+|\d+", dialog.inner_text())
            before, after = (to_int(nums[-2]), to_int(nums[-1])) if len(nums) >= 2 else (0, 0)
            if after - before != total:
                shot(page, "exchange-dialog-mismatch")
                log(f"兌換視窗的點數變化對不上（視窗數字：{nums}，預期 +{total:,}），不兌換")
                return 1
            log(f"兌換視窗：{before:,} → {after:,}")
            dialog_btn.click()
            page.wait_for_timeout(3000)
            shot(page, "exchanged")
            page.goto(LIST_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            log(f"已兌換 {total:,}pt，目前餘額：{read_balance(page):,}")
            return 0
        except Exception as e:  # noqa: BLE001
            shot(page, "error")
            log(f"發生錯誤：{e}")
            return 1
        finally:
            ctx.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Clove 每日限定一抽")
    ap.add_argument("--login", action="store_true", help="開瀏覽器手動登入，登入後關掉視窗")
    ap.add_argument("--dry-run", action="store_true", help="跑到確認視窗就取消，不會扣點")
    ap.add_argument("--cost", type=int, default=COST, help=f"每抽幾點（預設 {COST}）")
    ap.add_argument("--pool", default=POOL, help=f"卡池名稱（預設 {POOL}）")
    ap.add_argument("--limit", type=int, default=EXCHANGE_LIMIT,
                    help=f"抽中幾點以下自動兌換（預設 {EXCHANGE_LIMIT}；設 0 代表都不兌換）")
    args = ap.parse_args()
    COST = args.cost
    POOL = args.pool
    POOL_NAME = re.compile(re.escape(POOL))
    EXCHANGE_LIMIT = args.limit
    if args.login:
        do_login()
    else:
        sys.exit(do_draw(args.dry_run))
