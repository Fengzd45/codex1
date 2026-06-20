#!/usr/bin/env python3
import os
import sys
import json
import requests
import random
import re
from pypinyin import pinyin, Style

# ==================== 所有飞书参数从环境变量读取（均以 FEISHU_ 开头） ====================
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")
FEISHU_TABLE_ID = os.getenv("FEISHU_TABLE_ID")
FEISHU_PWD_TABLE_ID = os.getenv("FEISHU_PWD_TABLE_ID")

if not all([FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_APP_TOKEN, FEISHU_TABLE_ID, FEISHU_PWD_TABLE_ID]):
    missing = []
    if not FEISHU_APP_ID: missing.append("FEISHU_APP_ID")
    if not FEISHU_APP_SECRET: missing.append("FEISHU_APP_SECRET")
    if not FEISHU_APP_TOKEN: missing.append("FEISHU_APP_TOKEN")
    if not FEISHU_TABLE_ID: missing.append("FEISHU_TABLE_ID")
    if not FEISHU_PWD_TABLE_ID: missing.append("FEISHU_PWD_TABLE_ID")
    sys.exit(f"❌ 缺少环境变量: {', '.join(missing)}。请在 GitHub Secrets 或本地环境中设置。")

JSONL_PATH = "family_data.jsonl"
ROOT_MEDIA_DIR = "资料"

# ==================== 密码生成 ====================
def generate_pinyin_password(name):
    if not name:
        return str(random.randint(100, 999))
    letters = pinyin(name, style=Style.FIRST_LETTER)
    pinyin_head = "".join([item[0] for item in letters if item]).upper()
    pinyin_head = re.sub(r'[^A-Z]', '', pinyin_head)
    if not pinyin_head:
        pinyin_head = "FENG"
    return f"{pinyin_head}{random.randint(100, 999)}"

# ==================== 飞书鉴权 ====================
def get_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10).json()
        if res.get("code") == 0:
            return res.get("tenant_access_token")
        else:
            print(f"❌ 获取 token 失败: {res.get('msg')}")
            return None
    except Exception as e:
        print(f"⚠️ 鉴权异常: {e}")
        return None

# ==================== 下载文件（使用附件自带的 url） ====================
def download_from_url(url, save_path):
    try:
        res = requests.get(url, stream=True, timeout=30)
        if res.status_code == 200:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"   ➔ 💾 [下载成功] {save_path}")
            return True
        else:
            print(f"   ➔ ❌ 下载失败，状态码 {res.status_code}")
            return False
    except Exception as e:
        print(f"   ➔ ❌ 下载异常: {e}")
        return False

# ==================== 写入密码表 ====================
def push_to_pwd_base_table(token, name, password):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_PWD_TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        payload = {"fields": {"姓名": name, "密码": password}}
        res = requests.post(url, headers=headers, json=payload, timeout=10).json()
        if res.get("code") == 0:
            print(f"   🚀 密码【{password}】已录入密码表")
            return True
        else:
            print(f"   ⚠️ 写入密码表失败: {res.get('msg')}")
            return False
    except Exception as e:
        print(f"   ⚠️ 写入密码表异常: {e}")
        return False

# ==================== JSONL 读写 ====================
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

# ==================== 飞书字段清洗 ====================
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

# ==================== 主引擎 ====================
def run_local_sync_data():
    print("🚀 [同步引擎启动]")
    family_tree = load_family_data()

    token = get_tenant_access_token()
    if not token:
        print("🛑 无法获取飞书 token，终止同步")
        return

    headers = {"Authorization": f"Bearer {token}"}

    try:
        # 加载密码表
        print("📡 正在加载密码表...")
        pwd_pool = {}
        pwd_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_PWD_TABLE_ID}/records?page_size=500"
        pwd_res = requests.get(pwd_url, headers=headers, timeout=15).json()
        if pwd_res.get("code") == 0:
            for item in pwd_res.get("data", {}).get("items") or []:
                f = item.get("fields", {})
                if f.get("姓名") and f.get("密码"):
                    raw_n = clean_feishu_value(f["姓名"])
                    raw_p = clean_feishu_value(f["密码"])
                    if raw_n:
                        pwd_pool[raw_n] = raw_p
        print(f"   ➔ 密码表装载 {len(pwd_pool)} 人")

        # 拉取主表
        main_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records?page_size=500"
        main_res = requests.get(main_url, headers=headers, timeout=15).json()
        if main_res.get("code") != 0:
            print(f"❌ 读取主表失败: {main_res.get('msg')}")
            return

        records = main_res.get("data", {}).get("items") or []
        print(f"📡 捕获 {len(records)} 条记录\n")

        # ======== 轨道 A ========
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
                        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/{record_id}"
                        requests.put(update_url, headers=headers, json={"fields": {"新人密码": new_pwd}})
                        print(f"      ✨ 新密码【{new_pwd}】已回写")
            else:
                current_subject = operator_name
                print(f"   📂 [个人资料补充] 归属【{operator_name}】")

            # 创建文件夹
            user_folder = os.path.join(ROOT_MEDIA_DIR, current_subject)
            os.makedirs(user_folder, exist_ok=True)

            # 下载图片/视频
            image_list = fields.get("从图库选入图片视频") or fields.get("从图库上传图片视频")
            if image_list:
                print(f"   🔍 发现 {len(image_list)} 个图片/视频文件")
                for img in image_list:
                    filename = img.get("name", "photo.jpg")
                    save_path = os.path.join(user_folder, filename)
                    download_url = img.get("url")
                    if download_url:
                        if not os.path.exists(save_path):
                            download_from_url(download_url, save_path)
                        else:
                            print(f"   ⏭️ 文件已存在: {filename}")
                    else:
                        print(f"   ⚠️ 附件无下载链接，跳过: {filename}")
            else:
                print(f"   ℹ️ 该记录无图片/视频")

            # 下载音频
            audio_list = fields.get("从录音选入音频") or fields.get("从录音上传音频")
            if audio_list:
                print(f"   🔍 发现 {len(audio_list)} 个音频文件")
                for audio in audio_list:
                    filename = audio.get("name", "audio.mp3")
                    save_path = os.path.join(user_folder, filename)
                    download_url = audio.get("url")
                    if download_url:
                        if not os.path.exists(save_path):
                            download_from_url(download_url, save_path)
                        else:
                            print(f"   ⏭️ 音频已存在: {filename}")
                    else:
                        print(f"   ⚠️ 附件无下载链接，跳过: {filename}")
            else:
                print(f"   ℹ️ 该记录无音频")

            # 处理文章
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

        # ======== 轨道 B ========
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
                        update_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/{record_id}"
                        requests.put(update_url, headers=headers, json={"fields": {"新人密码": found}})
                        print(f"   🔑 已反哺密码给【{target_name}】")

        # 保存账本
        save_family_data(family_tree)

        # ==================== 生成 manifest.json ====================
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
        print(f"📋 [清单生成] manifest.json 已更新，包含 {len(manifest_data)} 位人物的资料索引。")

        print("\n🎉 [同步完成]")

    except Exception as e:
        print(f"❌ 运行错误: {e}")

if __name__ == "__main__":
    run_local_sync_data()