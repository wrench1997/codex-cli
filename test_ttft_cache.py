#!/usr/bin/env python3
"""
vLLM Prefix Caching 验证脚本 - TTFT 对比法（简化版）

核心原理：
- 发送两次完全相同的长文本请求
- 如果缓存生效，第二次的 TTFT（首字延迟）会显著下降

用法:
    python test_ttft_cache.py
"""

import os
import time
from dotenv import load_dotenv
from openai import OpenAI

# ================= 加载配置 =================
load_dotenv()

base_url = os.getenv("VLLM_BASE_URL")
model_name = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-397B-A17B-FP8")

if not base_url:
    raise ValueError("❌ 错误：未在 .env 中找到 VLLM_BASE_URL")

client = OpenAI(base_url=base_url, api_key="NOT_NEEDED")

# ================= 构造长文本 =================
# 重复的段落，构造约 15000-20000 tokens 的长 prompt
paragraph = "人工智能是计算机科学的一个分支，研究如何使机器具有智能行为。" * 500

system_prompt = f"你是一个 AI 助手。请基于以下背景知识回答问题：\n\n{paragraph}\n\n请简要回答用户问题。"

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "什么是人工智能？"}
]

# ================= TTFT 测量 =================
def measure_ttft(msgs):
    """流式测量首字延迟"""
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model_name,
        messages=msgs,
        stream=True,
        max_tokens=20,
        temperature=0.0
    )
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            return time.perf_counter() - start
    return time.perf_counter() - start

# ================= 执行测试 =================
if __name__ == "__main__":
    print(f"🎯 服务：{base_url}")
    print(f"📝 Prompt 长度：约 {len(system_prompt)} 字符")
    print("-" * 50)
    
    # 第 1 次：Cache Miss
    print("⏳ [请求 1] Cache Miss...")
    ttft_1 = measure_ttft(messages)
    print(f"   TTFT = {ttft_1:.4f} 秒")
    
    time.sleep(0.3)
    
    # 第 2 次：Cache Hit
    print("⏳ [请求 2] Cache Hit...")
    ttft_2 = measure_ttft(messages)
    print(f"   TTFT = {ttft_2:.4f} 秒")
    
    # 结果
    print("-" * 50)
    speedup = ttft_1 / ttft_2 if ttft_2 > 0 else 0
    if ttft_2 < ttft_1 * 0.7:
        print(f"✅ 缓存生效！加速 {speedup:.2f} 倍 ({ttft_1:.2f}s → {ttft_2:.2f}s)")
    else:
        print(f"⚠️ 缓存未生效 ({ttft_1:.2f}s → {ttft_2:.2f}s)")