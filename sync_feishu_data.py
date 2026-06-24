#!/usr/bin/env python3
import os
import sys
import json
import requests
import random
import re
from pypinyin import pinyin, Style

# ==================== 1. 从 GitHub 保险柜读取参数 ====================
APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
TABLE_ID = os.getenv("FEISHU_TABLE_ID")
PWD_TABLE_ID = os.getenv("FEISHU_PWD_TABLE_ID")
FAMILY_NAME_TAG = os.getenv("FAMILY_NAME_TAG")

if not all([APP_ID, APP_SECRET, APP_TOKEN, TABLE_ID, PWD_TABLE_ID]):
    sys.exit("❌ 云端保险柜缺少配置，请检查 Settings->Secrets")

JSONL_PATH = "family_data.jsonl"
ROOT_MEDIA_DIR = "资料"

# ==================== 2. 密码生成 ====================
def generate_pinyin_password(name):
    if not name:
        return str(random.randint(100, 999))
    letters = pinyin(name, style=Style.FIRST_LETTER)
    pinyin_head = "".join([item[0] for item in letters if item]).upper()
    pinyin_head = re.sub(r'[^A-Z]', '', pinyin_head)
    if not pinyin_head:
        pinyin_head = "FENG"
    return f"{pinyin_head}{random.randint(100, 999)}"

# ==================== 3. 飞书鉴权 ====================
def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10).json()
        if res.get("code") == 0:
            return res.get("tenant_access_token")
        return None
    except Exception:
        return None

# ==================== 4. 下载多媒体文件 ====================
def download_from_url(url, save_path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        res = requests.get(url, headers=headers, stream=True, timeout=30)
        if res.status_code == 200:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"   ➔ 💾 [下载成功] {save_path}")
            return True
        return False
    except Exception:
        return False

# ==================== 5. 写入密码基础表 ====================
def push_to_pwd_base_table(token, name, password):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{PWD_TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        payload = {"fields": {"姓名": name, "密码": password}}
        res = requests.post(url, headers=headers, json=payload, timeout=10).json()
        return res.get("code") == 0
    except Exception:
        return False

# ==================== 6. 本地 JSONL 读写 ====================
def load_family_data():
    if not os.path.exists(JSONL_PATH):
        return {}
    data = {}
    with open(JSONL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    item = json.loads(line.strip())
                    if "n" in item:
                        data[item["n"]] = item
                except Exception:
                    continue
    return data

def save_family_data(data):
    with open(JSONL_PATH, "w", encoding="utf-8") as f:
        for item in data.values():
            clean_item = {
                "n": item.get("n", ""),
                "s": item.get("s", ""),
                "f": item.get("f", ""),
                "m": item.get("m", ""),
                "sp": item.get("sp", ""),
                "info": item.get("info", "")
            }
            f.write(json.dumps(clean_item, ensure_ascii=False) + "\n")
    print(f"💾 [本地落盘] {JSONL_PATH} 已更新。")

# ==================== 7. 飞书数据清洗 ====================
def clean_feishu_value(val):
    if val is None:
        return ""
    if isinstance(val, list):
        if not val:
            return ""
        return clean_feishu_value(val[0])
    if isinstance(val, dict):
        for key in ["text", "name", "value", "id"]:
            if key in val and val[key]:
                return clean_feishu_value(val[key])
        return clean_feishu_value(list(val.values())[0]) if val else ""
    res = str(val).strip()
    return "" if res.upper() == "NONE" else res

# ==================== 8. 主引擎逻辑 ====================
def run_local_sync_data():
    print("🚀 [同步引擎启动]（修复版）")
    family_tree = load_family_data()

    token = get_tenant_access_token()
    if not token:
        print("🛑 无法获取飞书 token，终止同步")
        return

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # 1. 加载现有的密码池
        print("📡 正在同步远程【密码表】档案...")
        pwd_pool = {}
        pwd_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{PWD_TABLE_ID}/records?page_size=500"
        pwd_res = requests.get(pwd_url, headers=headers, timeout=15).json()
        
        if pwd_res.get("code") == 0:
            # 【核心安全重构：拆写短句，规避手机长行截断问题】
            pwd_data = pwd_res.get("data", {}) or {}
            pwd_items = pwd_data.get("items") or []
            for item in pwd_items:
                f = item.get("fields") or {}
                if f.get("姓名") and f.get("密码"):
                    raw_n = clean_feishu_value(f["姓名"])
                    raw_p = clean_feishu_value(f["密码"])
                    if raw_n:
                        pwd_pool[raw_n] = raw_p
        print(f"   ➔ 密码表共载入 {len(pwd_pool)} 条比对记录")

        # 2. 拉取主多维表数据
        main_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records?page_size=500"
        main_res = requests.get(main_url, headers=headers, timeout=15).json()
        if main_res.get("code") != 0:
            print(f"❌ 读取主表失败: {main_res.get('msg')}")
            return

        records = main_res.get("data", {}).get("items") or []
        print(f"📡 成功捕获飞书主数据表 {len(records)} 条历史记录\n")

        # ======== 轨道 A：资料录入与文件抓取 ========
        print("====== 轨道 A：资料录入 ======")
        for record in records:
            fields = record.get("fields") or {}
            operator_name = clean_feishu_value(fields.get("本人姓名"))
            if not operator_name or operator_name == "未命名记录":
                continue

            user_pwd = clean_feishu_value(fields.get("你的密码"))
            correct_pwd = clean_feishu_value(fields.get("对比密码") or fields.get("供对比密码"))
            if not user_pwd or user_pwd != correct_pwd:
                continue

            need_process = clean_feishu_value(fields.get("处理基本信息吗"))
            target_name = clean_feishu_value(fields.get("被编辑者姓名"))

            gender = clean_feishu_value(fields.get("性别"))
            father = clean_feishu_value(fields.get("父亲姓名"))
            mother = clean_feishu_value(fields.get("母亲姓名"))
            spouse = clean_feishu_value(fields.get("配偶姓名"))
            lifespan = clean_feishu_value(fields.get("生卒时间"))

            if "需要" in need_process and target_name:
                current_subject = target_name
                print(f"   ➕ [新成员/修改] 主体【{current_subject}】")
                if current_subject not in family_tree:
                    family_tree[current_subject] = {
                        "n": current_subject,
                        "s": gender,
                        "f": father,
                        "m": mother,
                        "sp": spouse,
                        "info": lifespan
                    }
                else:
                    if gender: family_tree[current_subject]["s"] = gender
                    if father: family_tree[current_subject]["f"] = father
                    if mother: family_tree[current_subject]["m"] = mother
                    if spouse: family_tree[current_subject]["sp"] = spouse
                    if lifespan: family_tree[current_subject]["info"] = lifespan

                if current_subject not in pwd_pool:
                    new_pwd = generate_pinyin_password(current_subject)
                    if push_to_pwd_base_table(token, current_subject, new_pwd):
                        pwd_pool[current_subject] = new_pwd
                        record_id = record.get("id")
                        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
                        requests.put(update_url, headers=headers, json={"fields": {"新人密码": new_pwd}})
                        print(f"      ✨ 新密码【{new_pwd}】已回写飞书")
            else:
                current_subject = operator_name
                print(f"   📂 [个人资料补充] 归属【{operator_name}】")

            user_folder = os.path.join(ROOT_MEDIA_DIR, current_subject)
            os.makedirs(user_folder, exist_ok=True)

            # --- 下图 1 ---
            image_list_1 = fields.get("从图库选入图片视频")
            if image_list_1:
                print(f"   🔍 发现 {len(image_list_1)} 个选入图片/视频")
                for idx, img in enumerate(image_list_1):
                    filename = img.get("name", f"photo_{idx}.jpg")
                    save_path = os.path.join(user_folder, filename)
                    download_url = img.get("url")
                    if download_url:
                        if not os.path.exists(save_path):
                            download_from_url(download_url, save_path, token)
                        else:
                            print(f"   ⏭️ 文件已存在: {filename}")

            # --- 下图 2 ---
            image_list_2 = fields.get("从图库上传图片视频")
            if image_list_2:
                print(f"   🔍 发现 {len(image_list_2)} 个上传图片/视频")
                for idx, img in enumerate(image_list_2):
                    filename = img.get("name", f"photo_up_{idx}.jpg")
                    save_path = os.path.join(user_folder, filename)
                    download_url = img.get("url")
                    if download_url:
                        if not os.path.exists(save_path):
                            download_from_url(download_url, save_path, token)
                        else:
                            print(f"   ⏭️ 文件已存在: {filename}")

            if not image_list_1 and not image_list_2:
                print(f"   ℹ️ 该记录无图片/视频")

            # --- 下音频 1 ---
            audio_list_1 = fields.get("从录音选入音频")
            if audio_list_1:
                print(f"   🔍 发现 {len(audio_list_1)} 个选入音频")
                for idx, audio in enumerate(audio_list_1):
                    filename = audio.get("name", f"audio_{idx}.mp3")
                    save_path = os.path.join(user_folder, filename)
                    download_url = audio.get("url")
                    if download_url:
                        if not os.path.exists(save_path):
                            download_from_url(download_url, save_path, token)
                        else:
                            print(f"   ⏭️ 音频已存在: {filename}")

            # --- 下音频 2 ---
            audio_list_2 = fields.get("从录音上传音频")
            if audio_list_2:
                print(f"   🔍 发现 {len(audio_list_2)} 个上传音频")
                for idx, audio in enumerate(audio_list_2):
                    filename = audio.get("name", f"audio_up_{idx}.mp3")
                    save_path = os.path.join(user_folder, filename)
                    download_url = audio.get("url")
                    if download_url:
                        if not os.path.exists(save_path):
                            download_from_url(download_url, save_path, token)
                        else:
                            print(f"   ⏭️ 音频已存在: {filename}")

            if not audio_list_1 and not audio_list_2:
                print(f"   ℹ️ 该记录无音频")

            # --- 处理文献文章 ---
            article_content = str(fields.get("输入粘贴文章", "") or fields.get("输入/粘贴文章", "")).strip()
            if article_content and article_content.upper() != "NONE":
                articles = [a.strip() for a in article_content.split("===") if a.strip()]
                for single_article in articles:
                    lines = [line.strip() for line in single_article.splitlines() if line.strip()]
                    if lines:
                        title = "未命名文献"
                        for candidate in lines:
                            if "http" in candidate or "feishu.cn" in candidate:
                                continue
                            title = candidate
                            break
                        for c in ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '&', '=']:
                            title = title.replace(c, "_")
                        if len(title) > 50:
                            title = title[:50]
                        txt_path = os.path.join(user_folder, f"{title}.txt")
                        if not os.path.exists(txt_path):
                            with open(txt_path, "w", encoding="utf-8") as f:
                                f.write(single_article)
                            print(f"   📝 [文章] 已落盘: {txt_path}")

        # ======== 轨道 B：密码查询与反哺 ========
        print("\n====== 轨道 B：密码查询 ======")
        for record in records:
            fields = record.get("fields") or {}
            record_id = record.get("id")
            operator_name = clean_feishu_value(fields.get("本人姓名"))
            if not operator_name:
                continue
            user_pwd = clean_feishu_value(fields.get("你的密码"))
            correct_pwd = clean_feishu_value(fields.get("对比密码") or fields.get("供对比密码"))
            if not user_pwd or user_pwd != correct_pwd:
                continue
            need_process = clean_feishu_value(fields.get("处理基本信息吗"))
            target_name = clean_feishu_value(fields.get("被编辑者姓名"))
            if "需要" not in need_process and target_name:
                already = clean_feishu_value(fields.get("新人密码"))
                if not already:
                    found = pwd_pool.get(target_name)
                    if found:
                        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{record_id}"
                        requests.put(update_url, headers=headers, json={"fields": {"新人密码": found}})
                        print(f"   🔑 已反哺密码给【{target_name}】")

        save_family_data(family_tree)

        # ==================== 9. 可视化清单 manifest.json 生成 ====================
        def generate_manifest(media_root):
            manifest = {}
            if not os.path.exists(media_root):
                return manifest
            for person_name in os.listdir(media_root):
                person_dir = os.path.join(media_root, person_name)
                if os.path.isdir(person_dir):
                    files = [f for f in os.listdir(person_dir) if os.path.isfile(os.path.join(person_dir, f))]
                    if files:
                        manifest[person_name] = files
            return manifest

        manifest_data = generate_manifest(ROOT_MEDIA_DIR)
        with open("manifest.json", "w", encoding="utf-8") as mf:
            json.dump(manifest_data, mf, ensure_ascii=False, indent=2)
        print(f"📋 [清单生成] manifest.json 已更新。")

        print("\n🎉 [云端同步大获全胜]")

    except Exception as e:
        print(f"❌ 运行错误: {e}")

if __name__ == "__main__":
    run_local_sync_data()
