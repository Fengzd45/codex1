#!/usr/bin/env python3
import os
import sys
import json
import requests
import random
import re
from pypinyin import pinyin, Style

# ==================== 1. 从 GitHub 秘密保险柜安全读取 6 个核心参数 ====================
APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
APP_TOKEN = os.getenv("FEISHU_APP_TOKEN")

TABLE_ID = os.getenv("FEISHU_TABLE_ID")
PWD_TABLE_ID = os.getenv("FEISHU_PWD_TABLE_ID")
FAMILY_NAME_TAG = os.getenv("FAMILY_NAME_TAG")

# 容错安全锁：如果保险柜钥匙没对上，直接报错拦截，防止空跑
if not all([APP_ID, APP_SECRET, APP_TOKEN, TABLE_ID, PWD_TABLE_ID]):
    missing = []
    if not APP_ID: missing.append("FEISHU_APP_ID")
    if not APP_SECRET: missing.append("FEISHU_APP_SECRET")
    if not APP_TOKEN: missing.append("FEISHU_APP_TOKEN")
    if not TABLE_ID: missing.append("FEISHU_TABLE_ID")
    if not PWD_TABLE_ID: missing.append("FEISHU_PWD_TABLE_ID")
    sys.exit(f"❌ 云端保险柜缺少以下关键配置，请检查 Settings->Secrets: {', '.join(missing)}")

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
        else:
            print(f"❌ 获取 token 失败: {res.get('msg')}")
            return None
    except Exception as e:
        print(f"⚠️ 鉴权异常: {e}")
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
        else:
            print(f"   ➔ ❌ 下载失败，状态码 {res.status_code}")
            return False
    except Exception as e:
        print(f"   ➔ ❌ 下载异常: {e}")
        return False

# ==================== 5. 写入密码基础表 ====================
def push_to_pwd_base_table(token, name, password):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{PWD_TABLE_ID}/records"
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

# ==================== 8. 主引擎逻辑（100% 继承 mmb.py） ====================
def run_local_sync_data():
    print("🚀 [同步引擎启动]（继承本地 mmb 纯正血统版本）")
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
            for item in pwd_res.get("data", {}).get("items") or
