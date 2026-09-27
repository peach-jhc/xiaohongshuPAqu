"""抓取指定小红书账号的作品，并下载无水印原视频；不生成 Excel。"""

from configparser import ConfigParser
from pathlib import Path
from urllib.parse import urlencode
import json
import re
import time

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PROGRESS_PATH = HERE / "下载进度.json"
EXTRACTOR_VERSION = 2


def is_yes(value):
    return value.strip().lower() in {"是", "true", "1", "yes", "y"}


def settings():
    cfg = ConfigParser()
    cfg.read(HERE / "config.txt", encoding="utf-8-sig")
    s = cfg["下载无水印原视频"]
    folder = s.get("保存目录", "").strip()
    return {
        "account": s.get("小红书账号", "").strip(),
        "profile": s.get("账号主页地址", "").strip(),
        "parser": s.get("解析地址", "").strip(),
        "limit": max(0, s.getint("导出数量", fallback=0)),
        "refresh": is_yes(s.get("重新扫描作品", "否")),
        "headless": not is_yes(s.get("显示浏览器", "是")),
        "wait_login": is_yes(s.get("等待登录确认", "是")),
        "skip": is_yes(s.get("跳过已有视频", "是")),
        "folder": Path(folder) if folder else HERE / "无水印原视频",
    }


def find_profile(page, account):
    if not account:
        raise ValueError("请在 config.txt 填写小红书账号或账号主页地址。")
    url = "https://www.xiaohongshu.com/search_result?" + urlencode(
        {"keyword": account, "source": "web_search_result_notes", "type": "user"}
    )
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    links = page.locator('a[href*="/user/profile/"]')
    for i in range(min(links.count(), 100)):
        item = links.nth(i)
        href, text = item.get_attribute("href") or "", (item.inner_text() or "").strip()
        if account.lower() in text.lower():
            return href if href.startswith("http") else "https://www.xiaohongshu.com" + href
    if links.count():
        href = links.first.get_attribute("href") or ""
        return href if href.startswith("http") else "https://www.xiaohongshu.com" + href
    raise RuntimeError("没有搜索到账号，请在配置中直接填写账号主页地址。")


def collect_links(page, profile, limit):
    """综合接口、页面初始状态、HTML 和 DOM 获取作品链接。"""
    notes, order = {}, []

    def add(note_id, token=""):
        note_id = str(note_id or "").strip()
        if not note_id:
            return
        if note_id not in notes:
            notes[note_id] = str(token or "")
            order.append(note_id)
        elif token and not notes[note_id]:
            notes[note_id] = str(token)

    def walk(obj):
        if isinstance(obj, dict):
            note_id = obj.get("note_id") or obj.get("noteId")
            token = obj.get("xsec_token") or obj.get("xsecToken") or ""
            if note_id:
                add(note_id, token)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    def response_handler(response):
        if "/api/sns/web/v1/user_posted" in response.url:
            try:
                walk(response.json())
            except Exception:
                pass

    def extract_initial_state():
        """补充首屏中未经过 XHR 的 note_id 和 xsec_token。"""
        before = len(notes)
        try:
            initial_data = page.evaluate("""
                () => {
                    const candidates = [
                        window.__INITIAL_STATE__,
                        window.__INITIAL_SSR_STATE__,
                        window.__NUXT__,
                        window.__NEXT_DATA__
                    ];
                    for (const item of candidates) {
                        if (!item) continue;
                        try { return JSON.parse(JSON.stringify(item)); }
                        catch (e) {}
                    }
                    return null;
                }
            """)
            if initial_data:
                walk(initial_data)
        except Exception:
            pass
        added = len(notes) - before
        if added:
            print(f"页面初始状态补充 {added} 个作品")

    def extract_html():
        """页面状态不可序列化时，从 HTML 中兜底匹配 token。"""
        before = len(notes)
        try:
            html = page.content()
        except Exception:
            return
        forward = re.compile(
            r'"(?:note_id|noteId|id)"\s*:\s*"([0-9a-f]{16,})"'
            r'.{0,1500}?"(?:xsec_token|xsecToken)"\s*:\s*"([^"]+)"', re.S
        )
        reverse = re.compile(
            r'"(?:xsec_token|xsecToken)"\s*:\s*"([^"]+)"'
            r'.{0,1500}?"(?:note_id|noteId|id)"\s*:\s*"([0-9a-f]{16,})"', re.S
        )
        for match in forward.finditer(html):
            add(match.group(1), match.group(2))
        for match in reverse.finditer(html):
            add(match.group(2), match.group(1))
        added = len(notes) - before
        if added:
            print(f"页面 HTML 补充 {added} 个作品")

    page.on("response", response_handler)
    page.goto(profile, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    extract_initial_state()
    extract_html()
    previous, stable = -1, 0
    for round_no in range(1, 201):
        anchors = page.locator('a[href*="/explore/"], a[href*="/discovery/item/"]')
        for i in range(anchors.count()):
            href = anchors.nth(i).get_attribute("href") or ""
            match = re.search(r"/(?:explore|discovery/item)/([^/?#]+)", href)
            token = re.search(r"[?&]xsec_token=([^&#]+)", href)
            if match:
                add(match.group(1), token.group(1) if token else "")
        print(f"扫描第 {round_no} 轮：已发现 {len(order)} 个作品")
        if limit and len(order) >= limit:
            break
        stable = stable + 1 if len(order) == previous else 0
        previous = len(order)
        if stable >= 6:
            break
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1200)

    # 最后一页的接口或页面状态可能稍晚返回，再做一次完整兜底。
    page.wait_for_timeout(1500)
    extract_initial_state()
    extract_html()

    result = []
    for note_id in order[:limit or None]:
        query = {"xsec_source": "pc_user"}
        if notes[note_id]:
            query["xsec_token"] = notes[note_id]
        result.append(f"https://www.xiaohongshu.com/explore/{note_id}?{urlencode(query)}")
    return result


def valid_video(path):
    return path.exists() and path.stat().st_size >= 20_000


def page_is_blocked(page):
    """识别解析站常见的 403 拦截页面。"""
    try:
        text = page.locator("body").inner_text(timeout=2000)
        return "403" in text and ("请求被阻止" in text or "禁忌" in text or "forbidden" in text.lower())
    except Exception:
        return False


def load_progress(profile):
    """读取链接和处理状态，避免每次启动都重新扫描账号主页。"""
    if not PROGRESS_PATH.exists():
        return {"profile": profile, "links": [], "status": {}, "extractor_version": 0}
    try:
        data = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
        if data.get("profile") == profile:
            return data
    except Exception:
        pass
    return {"profile": profile, "links": [], "status": {}, "extractor_version": 0}


def save_progress(data):
    temporary = PROGRESS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PROGRESS_PATH)


def download_one(page, context, parser, xhs_url, target):
    response = page.goto(parser, wait_until="domcontentloaded", timeout=45000)
    if response and response.status == 403:
        return "blocked"
    if page_is_blocked(page):
        return "blocked"
    box = page.locator('input[type="text"], input:not([type]), textarea').first
    box.wait_for(state="visible", timeout=15000)
    box.fill(xhs_url)
    page.get_by_role("button", name=re.compile("开始解析|解析")).first.click()
    try:
        page.get_by_text("解析结果", exact=True).wait_for(state="visible", timeout=30000)
    except Exception:
        if page_is_blocked(page):
            return "blocked"
        raise
    page.wait_for_timeout(1500)

    video = page.locator("video").first
    if video.count():
        src = video.evaluate("node => node.currentSrc || node.src || ''")
        if src and not src.startswith("blob:"):
            reply = context.request.get(src, headers={"Referer": page.url}, timeout=60000)
            if reply.status == 403:
                return "blocked"
            if reply.ok:
                target.write_bytes(reply.body())
                if valid_video(target):
                    return "success"

    choices = page.locator('a[download], a[href*=".mp4"], button:has-text("下载")')
    for i in range(choices.count()):
        item = choices.nth(i)
        try:
            href = item.get_attribute("href") or ""
            if href and not href.startswith("blob:"):
                reply = context.request.get(href, headers={"Referer": page.url}, timeout=60000)
                if reply.status == 403:
                    return "blocked"
                if reply.ok:
                    target.write_bytes(reply.body())
                    if valid_video(target):
                        return "success"
            with page.expect_download(timeout=15000) as event:
                item.click()
            event.value.save_as(target)
            if valid_video(target):
                return "success"
        except Exception:
            continue

    # 解析结果含图片但没有视频时，属于图文作品，不计入解析失败。
    images = page.locator(
        'a[download] img, a[href*=".jpg"], a[href*=".jpeg"], '
        'a[href*=".png"], a[href*=".webp"]'
    )
    if images.count():
        return "non_video"
    return "failed"


def main():
    s = settings()
    s["folder"].mkdir(parents=True, exist_ok=True)
    print(f"无水印原视频保存位置：{s['folder']}")
    print("导出数量：全部" if s["limit"] == 0 else f"导出数量：{s['limit']}")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(HERE / "浏览器登录数据"), headless=s["headless"],
            accept_downloads=True, viewport={"width": 1400, "height": 900}
        )
        page = context.pages[0] if context.pages else context.new_page()
        if s["wait_login"]:
            page.goto("https://www.xiaohongshu.com/", wait_until="domcontentloaded", timeout=60000)
            input("确认小红书已经登录后，按 Enter 继续：")
        profile = s["profile"] or find_profile(page, s["account"])
        progress = load_progress(profile)
        cached_links = progress.get("links", [])
        # 缓存数量够用时直接复用；导出全部时仍重新扫描，以发现账号新增作品。
        cache_is_current = progress.get("extractor_version") == EXTRACTOR_VERSION
        if cached_links and not s["refresh"] and cache_is_current:
            links = cached_links[:s["limit"] or None]
            print(f"复用进度文件中的 {len(links)} 个作品链接，不重新扫描主页。")
        else:
            if cached_links and not cache_is_current:
                print("提取逻辑已升级，本次自动重新扫描主页并更新链接缓存。")
            links = collect_links(page, profile, s["limit"])
            progress["links"] = links
            progress["extractor_version"] = EXTRACTOR_VERSION
            save_progress(progress)
        print(f"取得 {len(links)} 个作品链接，不生成 Excel。")
        ok = skipped = non_video = failed = 0
        for index, link in enumerate(links, 1):
            target = s["folder"] / f"{index}.mp4"
            print(f"[{index}/{len(links)}] {target.name}")
            if s["skip"] and valid_video(target):
                skipped += 1
                progress.setdefault("status", {})[link] = "success"
                continue
            if progress.get("status", {}).get(link) == "non_video":
                print("  已确认是图文作品，跳过")
                non_video += 1
                continue
            if target.exists():
                target.unlink()
            try:
                result = download_one(page, context, s["parser"], link, target)
                if result == "success":
                    ok += 1
                    progress.setdefault("status", {})[link] = "success"
                elif result == "non_video":
                    print("  图文/非视频作品，跳过")
                    non_video += 1
                    progress.setdefault("status", {})[link] = "non_video"
                elif result == "blocked":
                    print("  检测到 403，立即停止，避免继续触发限制。更换VPN后可续跑。")
                    progress.setdefault("status", {})[link] = "blocked"
                    save_progress(progress)
                    break
                else:
                    failed += 1
                    progress.setdefault("status", {})[link] = "failed"
            except Exception as exc:
                print(f"  失败：{exc}")
                failed += 1
                progress.setdefault("status", {})[link] = "failed"
            save_progress(progress)
            time.sleep(0.5)
        context.close()
    print(f"下载完成：成功 {ok}，已有跳过 {skipped}，图文跳过 {non_video}，失败 {failed}")


if __name__ == "__main__":
    main()
