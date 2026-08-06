import os
import re
import time
import math
import pickle
import requests
import shutil

from selenium import webdriver
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==========================================
# 1. ユーティリティ
# ==========================================
def sanitize_filename(name):
    if not name: return ""
    table = str.maketrans({'/': '／', ':': '：', '*': '＊', '?': '？', '<': '＜', '>': '＞', '|': '｜'})
    name = name.translate(table)
    name = re.sub(r'[\\"\x00-\x1f\x7f]', '', name)
    name = name.replace('\n', ' ').replace('\r', '').replace('\t', ' ')
    return re.sub(r'\s+', ' ', name).strip().rstrip('.')

def format_date(s):
    if not s: return ""
    m = re.search(r"\d{4}/\d{2}/\d{2}", s)
    if m: return m.group(0).replace("/", "")
    m = re.search(r"\d{8}", s)
    if m: return m.group(0)
    m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", s)
    if m: return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return ""

def clean_title(title):
    if not title: return ""
    patterns = [r'\b[Vv]er\.?\s*[0-9]+(?:\.[0-9]+)*[a-zA-Z]?\b', r'\bv[-_]?\s*[0-9]+(?:\.[0-9]+)*[a-zA-Z]?\b']
    for p in patterns: title = re.sub(p, '', title)
    title = re.sub(r"^【[^】]*[%％]\s*OFF[^】]*】\s*", "", title, flags=re.IGNORECASE)
    return title.strip()

def get_dlsite_direct_thumb(cid):
    # RJやVJなどのアルファベット部分と、数字部分を分けて抽出
    m = re.match(r'([a-zA-Z]+)(\d+)', cid)
    if not m: return ""
    
    prefix = m.group(1).upper() # RJ や VJ
    num_str = m.group(2)
    folder_num = math.ceil(int(num_str) / 1000) * 1000
    
    folder_str = f"{prefix}{str(folder_num).zfill(len(num_str))}"
    return f"https://img.dlsite.jp/modpub/images2/work/doujin/{folder_str}/{cid.upper()}_img_main.jpg"

def download_image(url, save_path):
    if not url: return
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(r.content)
            # 🌟 成功したことが一目でわかるようにログを追加
            print(f"  🖼 画像保存完了: {os.path.basename(save_path)}")
        else:
            print(f"  ❌ 画像DL失敗: サーバーエラー (ステータスコード {r.status_code}) - {url}")
    except Exception as e:
        print(f"  ❌ 画像DL失敗: {e}")

# Cookie処理
def load_cookies(driver):
    if not os.path.exists("cookies.pkl"): return False
    with open("cookies.pkl", "rb") as f:
        cookies = pickle.load(f)
    for c in cookies:
        try: driver.add_cookie(c)
        except: pass
    return True

def save_cookies(driver):
    with open("cookies.pkl", "wb") as f:
        pickle.dump(driver.get_cookies(), f)

# ==========================================
# 2. スクレイパー群
# ==========================================
def fetch_fanza(driver, cid):
    print(f"🌐 FETCH FANZA: {cid}")
    url = f"https://www.dmm.co.jp/dc/doujin/-/detail/=/cid={cid}/"
    driver.get(url)
    time.sleep(2)

    data = {"cid": cid, "url": url, "circle": "", "title": "", "format": "", "release_date": "", "update_date": "", "version": "", "thumb": ""}

    try: data["title"] = driver.find_element(By.TAG_NAME, "h1").text
    except: pass
    try: data["circle"] = driver.find_element(By.CSS_SELECTOR, ".circleName__txt").get_attribute("textContent").strip()
    except: pass
    try: data["format"] = driver.find_element(By.CSS_SELECTOR, ".c_icon_productGenre").text.strip()
    except: pass

    try:
        for b in driver.find_elements(By.CSS_SELECTOR, "dl.informationList"):
            try:
                dt = b.find_element(By.CSS_SELECTOR, ".informationList__ttl").text
                dd = b.find_element(By.CSS_SELECTOR, ".informationList__txt").text.split("\n")[0].strip()
                if "配信開始日" in dt: data["release_date"] = dd
                elif "最終更新日" in dt: data["update_date"] = dd
            except: continue
    except: pass

    try:
        ver_text = driver.find_element(By.CSS_SELECTOR, ".updateInfo-item .version").text
        m = re.search(r'([0-9]+(?:\.[0-9]+)*[a-zA-Z]?)', ver_text)
        if m: data["version"] = f"Ver{m.group(1)}"
    except:
        m = re.search(r'[Vv]er\.?\s*([0-9]+(?:\.[0-9]+)*[a-zA-Z]?)', data["title"])
        if m: data["version"] = f"Ver{m.group(1)}"

    try:
        html = driver.page_source
        m = re.search(r'https://doujin-assets\.dmm\.co\.jp/[^"]+?pr\.jpg', html)
        if not m: m = re.search(r'https://doujin-assets\.dmm\.co\.jp/[^"]+?jp-\d+\.jpg', html)
        if m: data["thumb"] = m.group(0)
    except: pass

    return data

def fetch_dlsite(driver, cid):
    print(f"🌐 FETCH DLsite: {cid}")
    url = f"https://www.dlsite.com/maniax/work/=/product_id/{cid}.html"
    driver.get(url)
    time.sleep(2)

    # 年齢確認の再チェック（念のため）
    if "error/age" in driver.current_url or "age_check" in driver.current_url:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn_yes, .btn-yes")))
            btn.click()
            time.sleep(2)
        except: pass

    if "error" in driver.current_url and "age" not in driver.current_url:
        print(f"   -> 🔒 アクセス制限/404です。サムネイル直接取得に切り替えます。")
        return {"cid": cid, "url": url, "circle": "不明", "title": "限定・販売終了作品", "format": "", "release_date": "", "update_date": "", "version": "", "thumb": get_dlsite_direct_thumb(cid)}

    data = {"cid": cid, "url": url, "circle": "", "title": "", "format": "", "release_date": "", "update_date": "", "version": "", "thumb": ""}

    try: data["title"] = driver.find_element(By.ID, "work_name").text
    except: pass
    try: data["circle"] = driver.find_element(By.CSS_SELECTOR, ".maker_name a").text
    except: pass

    # ID直撃で作品形式を取得
    try:
        elem = driver.find_element(By.ID, "category_type")
        data["format"] = elem.text.split()[0] # 最初のブロックのみ
    except: pass

    # テーブルから日付を取得
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "#work_outline tr")
        for row in rows:
            try:
                th = row.find_element(By.TAG_NAME, "th").text
                td = row.find_element(By.TAG_NAME, "td").text
                if "販売日" in th:
                    m = re.search(r'\d{4}年\d{2}月\d{2}日', td)
                    if m: data["release_date"] = m.group(0)
                elif "更新情報" in th or "更新日" in th:
                    m = re.search(r'\d{4}年\d{2}月\d{2}日', td)
                    if m: data["update_date"] = m.group(0)
                    else: data["update_date"] = td.replace("\n", " ").strip()
            except: continue
    except: pass

    m = re.search(r'[Vv]er\.?\s*([0-9]+(?:\.[0-9]+)*[a-zA-Z]?)', data["title"])
    if m: data["version"] = f"Ver{m.group(1)}"

	# ==========================================
    # 🌟 サムネイル取得（OGPメタタグ対応版）
    # ==========================================
    try:
        # 最優先: OGPタグ（共有用メタタグ）から取得。webp等にも確実に対応
        og_image = driver.find_element(By.CSS_SELECTOR, 'meta[property="og:image"]')
        data["thumb"] = og_image.get_attribute("content")
    except:
        try:
            # 予備: 従来のDOMからの取得
            thumb_elem = driver.find_element(By.CSS_SELECTOR, ".product-slider-data div[data-src]")
            thumb_url = thumb_elem.get_attribute("data-src")
            if thumb_url.startswith("//"): thumb_url = "https:" + thumb_url
            data["thumb"] = thumb_url
        except: 
            # 最終手段: URL直接生成
            data["thumb"] = get_dlsite_direct_thumb(cid)

    return data
    return data

def get_metadata(driver, cid):
    cid_upper = cid.upper()
    # RJ または VJ で始まる場合はDLsiteへ
    if cid_upper.startswith("RJ") or cid_upper.startswith("VJ"):
        return fetch_dlsite(driver, cid_upper)
    elif cid.startswith("d_") or re.match(r'^[a-z]+', cid):
        return fetch_fanza(driver, cid)
    return None

# ==========================================
# 3. フォルダ/ファイル名生成ロジック
# ==========================================
def build_base_name(data):
    """拡張子抜きのベースとなるファイル/フォルダ名を生成"""
    clean_circle = sanitize_filename(data.get("circle", ""))
    clean_title_str = clean_title(sanitize_filename(data.get("title", "")))
    fmt = data.get("format", "")
    rel_date = format_date(data.get("release_date", ""))
    
    ver_suffix = data.get("version", "")
    if not ver_suffix and data.get("update_date"):
        up_date = format_date(data.get("update_date", ""))
        if up_date:
            ver_suffix = f"Update_{up_date}"

    name = f"[{clean_circle}][{data['cid']}]"
    if fmt: name += f"[{fmt}]"
    if rel_date: name += f"[{rel_date}]"
    name += f" {clean_title_str}"
    if ver_suffix: name += f" {ver_suffix}"
    
    return sanitize_filename(name)

# ==========================================
# 4. メイン処理
# ==========================================
def main():
    base_dir = "targets"
    os.makedirs(base_dir, exist_ok=True)
    url_file = os.path.join(base_dir, "url.txt")

    url_cids = []
    if os.path.exists(url_file):
        with open(url_file, encoding="utf-8") as f:
            url_cids = [line.strip() for line in f if line.strip()]

	# 【修正前】
    # files = [f for f in os.listdir(base_dir) if os.path.isfile(os.path.join(base_dir, f)) and f != "url.txt"]
    # ...
    # for file in files:

    # ==========================================
    # 🌟 【修正後】ファイルもフォルダも両方拾う
    # ==========================================
    items = [f for f in os.listdir(base_dir) if f != "url.txt"]

    # 処理対象の全CIDを抽出
    target_cids = set(url_cids)
    file_targets = [] # (元の名前, CID) のリスト

    for item in items:
        # RJ, VJ, d_ を含む名前ならファイルでもフォルダでも検知
        m = re.search(r'(d_\d+|RJ\d+|VJ\d+)', item, flags=re.IGNORECASE)
        if m:
            cid = m.group(1)
            target_cids.add(cid)
            file_targets.append((item, cid))

    if not target_cids:
        print("📁 処理対象のCIDやファイルが見つかりません。")
        input("Enterで終了...")
        return

    # --- ブラウザ初期化 ---
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless=new")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    needs_dlsite = any(c.upper().startswith("RJ") or c.upper().startswith("VJ") for c in target_cids)
    needs_fanza = any(c.startswith("d_") or re.match(r'^[a-z]+', c) for c in target_cids)

    print("🔧 ブラウザの初期セットアップを実行中...")
    if needs_dlsite:
        driver.get("https://www.dlsite.com/maniax/")
        time.sleep(2)
        try:
            btn = driver.find_element(By.CSS_SELECTOR, ".btn_yes, .btn-yes, .work_welcome")
            btn.click()
            print("  -> DLsite 年齢確認を突破しました。画面遷移を待機します...")
            time.sleep(4) # 👈 ここが先ほどのエラーの特効薬です！
        except: pass

    if needs_fanza:
        driver.get("https://www.dmm.co.jp/")
        time.sleep(2)
        if load_cookies(driver):
            driver.refresh()
        else:
            try:
                btn = driver.find_element(By.XPATH, "//a[contains(text(),'はい')]")
                btn.click()
                time.sleep(2)
                save_cookies(driver)
            except: pass

    # --- 情報収集ループ ---
    print("\n🚀 情報取得を開始します...")
    data_map = {}
    for cid in target_cids:
        data = get_metadata(driver, cid)
        if data:
            data_map[cid] = data
            print("  ✅ 取得完了")

    # 全て取り終わったのでブラウザは閉じてOK
    driver.quit()
    print("\n✅ スクレイピング完了。ブラウザを閉じました。")

# ==========================================
    # 🌟 ファイル/フォルダのローカル操作
    # ==========================================
    print("\n📦 フォルダ作成・ファイルリネームを開始します...")

    # 1. url.txt由来のCID -> フォルダ作成
    for cid in url_cids:
        if cid in data_map:
            base_name = build_base_name(data_map[cid])
            folder_path = os.path.join(base_dir, base_name)
            os.makedirs(folder_path, exist_ok=True)
            print(f"  📁 フォルダ作成: {base_name}")
            
            # サムネ保存 (.webp対応)
            thumb_url = data_map[cid].get("thumb")
            if thumb_url:
                img_ext = ".webp" if ".webp" in thumb_url.lower() else ".jpg"
                img_path = os.path.join(base_dir, base_name + img_ext)
                if not os.path.exists(img_path):
                    download_image(thumb_url, img_path)

    # 2. ファイル/既存フォルダ -> リネーム処理
    for item, cid in file_targets:
        if cid in data_map:
            src = os.path.join(base_dir, item)
            
            if not os.path.exists(src):
                continue
                
            is_dir = os.path.isdir(src)

            base_name = build_base_name(data_map[cid])
            
            if is_dir:
                new_filename = base_name
            else:
                ext = os.path.splitext(item)[1]
                new_filename = base_name + ext
            
            dst = os.path.join(base_dir, new_filename)
            
            # 💡 サムネ保存 (.webp対応)
            thumb_url = data_map[cid].get("thumb")
            if thumb_url:
                img_ext = ".webp" if ".webp" in thumb_url.lower() else ".jpg"
                img_path = os.path.join(base_dir, base_name + img_ext)
                if not os.path.exists(img_path):
                    download_image(thumb_url, img_path)
            
            # 既に完璧な名前にリネーム済みの場合はスキップ
            if src == dst:
                continue
            
            try:
                os.rename(src, dst)
                if is_dir:
                    print(f"  📁 フォルダリネーム完了: {item} -> {new_filename}")
                else:
                    print(f"  📝 ファイルリネーム完了: {item} -> {new_filename}")
            except Exception as e:
                print(f"  ❌ リネーム失敗 ({item}): {e}")

    # ==========================================
    # 🌟 url.txt の更新（成功したCIDの削除）
    # ==========================================
    if os.path.exists(url_file) and url_cids:
        # 取得成功(data_mapに存在する)していないCIDだけをリストに残す
        remaining_cids = [cid for cid in url_cids if cid not in data_map]
        
        # 減っている場合のみ上書き保存を実行
        if len(remaining_cids) < len(url_cids):
            with open(url_file, "w", encoding="utf-8") as f:
                for cid in remaining_cids:
                    f.write(cid + "\n")
            print(f"\n📝 url.txt を更新しました（成功した {len(url_cids) - len(remaining_cids)} 件を削除しました）")

    print("\n🏁 全ての処理が完了しました！")
    input("Enterキーを押すと画面を閉じます...")

if __name__ == "__main__":
    main()