#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import argparse
import requests
from openai import OpenAI


# ==========================================
# 1. 飞书 API 数据拉取模块
# ==========================================

def get_feishu_tenant_access_token(app_id, app_secret):
    """获取飞书 API 调用凭证 (tenant_access_token)"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    payload = {
        "app_id": app_id,
        "app_secret": app_secret
    }
    
    response = requests.post(url, headers=headers, json=payload)
    data = response.json()
    if data.get("code") == 0:
        return data.get("tenant_access_token")
    else:
        print(f"❌ 获取飞书 Token 失败: {data.get('msg')}")
        return None

def fetch_feishu_bitable_records(token, app_token, table_id):
    """从飞书多维表格读取所有记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8"
    }
    
    records = []
    page_token = None
    
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
            
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        
        if data.get("code") != 0:
            print(f"❌ 读取飞书表格失败: {data.get('msg')}")
            break
            
        items = data.get("data", {}).get("items", [])
        for item in items:
            fields = item.get("fields", {})
            records.append(fields)
            
        has_more = data.get("data", {}).get("has_more", False)
        page_token = data.get("data", {}).get("page_token")
        
        if not has_more:
            break
            
    return records

def process_and_save_jsonl(records, output_file="family_data.jsonl"):
    """
    将飞书数据清洗转换为标准的 n.s.f.m.sp.info 基础结构并保存为 JSONL
    n: 姓名/ID
    s: 性别
    f: 父亲
    m: 母亲
    sp: 配偶
    info: 生卒日及备注
    """
    cleaned_records = []
    
    for r in records:
        # 读取并规范化各个字段
        name = str(r.get("姓名", r.get("n", ""))).strip()
        if not name:
            continue  # 无效记录跳过
            
        sex = str(r.get("性别", r.get("s", ""))).strip()
        father = str(r.get("父亲", r.get("f", ""))).strip()
        mother = str(r.get("母亲", r.get("m", ""))).strip()
        
        # 配偶字段处理（支持字符串或列表格式）
        spouse_raw = r.get("配偶", r.get("sp", ""))
        if isinstance(spouse_raw, list):
            spouse = [str(item).strip() for item in spouse_raw if str(item).strip()]
        elif isinstance(spouse_raw, str) and spouse_raw.strip():
            spouse = [s.strip() for s in spouse_raw.split(",") if s.strip()]
        else:
            spouse = ""

        info = str(r.get("生卒及备注", r.get("info", ""))).strip()

        node = {
            "n": name,
            "s": sex,
            "f": father,
            "m": mother,
            "sp": spouse,
            "info": info
        }
        cleaned_records.append(node)

    # 写入 JSONL 文件
    with open(output_file, "w", encoding="utf-8") as f:
        for item in cleaned_records:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
    print(f"✅ 数据清洗完成，共生成 {len(cleaned_records)} 条成员记录存入 {output_file}")
    return cleaned_records


# ==========================================
# 2. DeepSeek AI Agent 智能校验与 RAG 模块
# ==========================================

def init_deepseek_agent():
    """初始化 DeepSeek API 客户端"""
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    
    if not api_key:
        print("⚠️ 未检测到 LLM_API_KEY，跳过 AI Agent 校验。")
        return None
        
    return OpenAI(api_key=api_key, base_url=base_url)

def agent_audit_family_tree(jsonl_file_path="family_data.jsonl"):
    """
    调用 DeepSeek Agent 对家族逻辑树（n.s.f.m.sp.info）进行拓扑逻辑诊断
    """
    client = init_deepseek_agent()
    if not client:
        return

    records = []
    if os.path.exists(jsonl_file_path):
        with open(jsonl_file_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except:
                        pass

    if not records:
        print("ℹ️ 家族数据为空，无需 Agent 校验。")
        return

    prompt = f"""
你是一位严谨的家族档案 AI 专家。以下是家族树成员 JSONL 数据，结构字段定义为：
- n: 姓名/ID
- s: 性别
- f: 父亲姓名
- m: 母亲姓名
- sp: 配偶
- info: 生卒日及备注信息

家族数据内容如下：
{json.dumps(records, ensure_ascii=False, indent=2)}

请对这份家族关系链进行深度逻辑诊断，输出一份简明的分析报告：
1. 【关系链检查】：是否存在找不到父母节点的断层、逻辑倒错或性别冲突？
2. 【族谱概要】：简要总结当前家族的数据规模与世代特点。
"""

    try:
        print("🤖 DeepSeek Agent 正在对家族关系网进行智能校验...")
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        report = response.choices[0].message.content
        print("\n==== 📋 DeepSeek AI Agent 诊断报告 ====")
        print(report)
        print("======================================\n")
        
        # 将诊断结果保存为 agent_report.md
        with open("agent_report.md", "w", encoding="utf-8") as f:
            f.write("# 🤖 家族关系网 AI Agent 诊断报告\n\n" + report)
            
    except Exception as e:
        print(f"❌ DeepSeek Agent 执行失败: {e}")


# ==========================================
# 3. 主程序入口
# ==========================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="家族档案数据同步与 AI Agent 校验引擎")
    parser.add_argument("--enable-agent", action="store_true", help="是否启动 DeepSeek Agent 校验")
    args = parser.parse_args()

    # 从 GitHub Secrets / 环境变量中读取飞书凭证
    feishu_app_id = os.environ.get("FEISHU_APP_ID")
    feishu_app_secret = os.environ.get("FEISHU_APP_SECRET")
    feishu_app_token = os.environ.get("FEISHU_APP_TOKEN")
    feishu_table_id = os.environ.get("FEISHU_TABLE_ID")

    if feishu_app_id and feishu_app_secret and feishu_app_token and feishu_table_id:
        print("🔄 开始从飞书拉取最新的家族档案数据...")
        token = get_feishu_tenant_access_token(feishu_app_id, feishu_app_secret)
        if token:
            raw_records = fetch_feishu_bitable_records(token, feishu_app_token, feishu_table_id)
            process_and_save_jsonl(raw_records)
    else:
        print("ℹ️ 未检测到完整的飞书 API 环境变量，跳过飞书拉取，直接使用本地 family_data.jsonl 文件。")

    # 执行 DeepSeek Agent 智能分析
    if args.enable_agent:
        agent_audit_family_tree()
