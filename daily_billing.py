#!/usr/bin/env python3
"""
当天计费脚本 - 基于 TTFT 对比的 vLLM Prefix Caching 验证

功能:
- 输入 token 计费
- 输出 token 计费
- 通过 TTFT（首字延迟）对比判断缓存命中
- 缓存命中节省计算

用法:
    python daily_billing.py
"""

import os
import time
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI

# ================= 加载配置 =================
load_dotenv()

base_url = os.getenv("VLLM_BASE_URL")
model_name = os.getenv("MODEL_NAME", "Qwen/Qwen3.5-397B-A17B-FP8")

# ================= 价格配置 (每 1M tokens，人民币) =================
# DeepSeek-V4-Pro 价格
PRICING = {
    "input_price_per_1m": 3.0,       # 输入 token 价格 (缓存未命中，¥/1M tokens)
    "output_price_per_1m": 6.0,      # 输出 token 价格 (¥/1M tokens)
    "cached_input_price_per_1m": 0.025,  # 缓存命中的输入 token 价格 (¥/1M tokens)
}

if not base_url:
    raise ValueError("❌ 错误：未在 .env 中找到 VLLM_BASE_URL")

client = OpenAI(base_url=base_url, api_key="NOT_NEEDED")

# ================= 计费统计 =================
# TTFT 缓存命中判断配置
TTFT_CACHE_HIT_THRESHOLD = float(os.getenv("TTFT_CACHE_HIT_THRESHOLD", "0.5"))  # 秒
TTFT_HISTORY_MAX = 10

class BillingStats:
    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.cached_input_tokens = 0
        self.normal_input_tokens = 0
        self.request_count = 0
        self.cache_hit_count = 0
        # TTFT 历史用于动态比较
        self.ttft_history = []
        
    def is_cache_hit_by_ttft(self, ttft: float) -> bool:
        """基于 TTFT 判断是否缓存命中"""
        # 方法 1：绝对阈值
        if ttft < TTFT_CACHE_HIT_THRESHOLD:
            return True
        # 方法 2：与历史平均比较（如果有足够数据）
        if len(self.ttft_history) >= 3:
            avg_ttft = sum(self.ttft_history) / len(self.ttft_history)
            # 如果当前 TTFT 显著低于平均值（比如 50%），认为缓存命中
            if ttft < avg_ttft * 0.5:
                return True
        return False
    
    def record_ttft(self, ttft: float):
        """记录 TTFT 到历史"""
        self.ttft_history.append(ttft)
        if len(self.ttft_history) > TTFT_HISTORY_MAX:
            self.ttft_history.pop(0)
        
    def add_request(self, input_tokens, output_tokens, ttft=None):
        """添加一次请求的统计数据（基于 TTFT 判断缓存命中）"""
        self.request_count += 1
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        
        # 基于 TTFT 判断缓存命中
        cache_hit = False
        cached_tokens = 0
        if ttft is not None:
            self.record_ttft(ttft)
            cache_hit = self.is_cache_hit_by_ttft(ttft)
            if cache_hit:
                # 缓存命中时，认为大部分输入 token 来自缓存
                cached_tokens = int(input_tokens * 0.9)  # 假设 90% 命中
                self.cache_hit_count += 1
        
        self.cached_input_tokens += cached_tokens
        self.normal_input_tokens += (input_tokens - cached_tokens)
    
    def calculate_cost(self):
        """计算总费用"""
        normal_input_cost = (self.normal_input_tokens / 1_000_000) * PRICING["input_price_per_1m"]
        cached_input_cost = (self.cached_input_tokens / 1_000_000) * PRICING["cached_input_price_per_1m"]
        output_cost = (self.total_output_tokens / 1_000_000) * PRICING["output_price_per_1m"]
        
        total_input_cost = normal_input_cost + cached_input_cost
        total_cost = total_input_cost + output_cost
        
        # 如果没有缓存，原本需要的费用
        original_input_cost = (self.total_input_tokens / 1_000_000) * PRICING["input_price_per_1m"]
        original_total = original_input_cost + output_cost
        
        # 节省的费用
        saved_cost = original_total - total_cost
        
        return {
            "input_cost": total_input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
            "saved_cost": saved_cost,
            "original_total": original_total,
        }
    
    def print_report(self):
        """打印计费报告"""
        costs = self.calculate_cost()
        
        print("\n" + "=" * 60)
        print(f"📊 当天计费报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        print("\n📈 Token 统计:")
        print(f"   请求次数：        {self.request_count}")
        print(f"   缓存命中次数：    {self.cache_hit_count}")
        print(f"   缓存命中率：      {self.cache_hit_count/self.request_count*100:.1f}%" if self.request_count > 0 else "   缓存命中率：      N/A")
        print(f"   输入 Token 总数：   {self.total_input_tokens:,}")
        print(f"     └─ 普通输入：    {self.normal_input_tokens:,}")
        print(f"     └─ 缓存命中：    {self.cached_input_tokens:,}")
        print(f"   输出 Token 总数：   {self.total_output_tokens:,}")
        
        print("\n💰 费用明细 (人民币):")
        print(f"   输入费用：        ¥{costs['input_cost']:.6f}")
        print(f"     └─ 普通输入：    ¥{costs['original_total'] - costs['output_cost'] - costs['saved_cost']:.6f}")
        print(f"     └─ 缓存命中：    ¥{costs['input_cost'] - (costs['original_total'] - costs['output_cost'] - costs['saved_cost']):.6f}")
        print(f"   输出费用：        ¥{costs['output_cost']:.6f}")
        print(f"   ─────────────────────────────")
        print(f"   实际总费用：      ¥{costs['total_cost']:.6f}")
        print(f"   原始总费用：      ¥{costs['original_total']:.6f}")
        print(f"   💵 缓存节省：     ¥{costs['saved_cost']:.6f} ({costs['saved_cost']/costs['original_total']*100:.1f}%)")
        print("=" * 60)


# ================= 全局统计实例 =================
stats = BillingStats()

def measure_ttft(messages, max_tokens=20):
    """流式测量首字延迟 (TTFT)"""
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        stream=True,
        max_tokens=max_tokens,
        temperature=0.0
    )
    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            return time.perf_counter() - start
    return time.perf_counter() - start


def chat_with_billing(messages, max_tokens=100, **kwargs):
    """
    带计费统计的聊天调用 - 基于 TTFT 对比判断缓存命中
    
    原理:
    - 首次请求 TTFT 较长 (Cache Miss)
    - 相同请求再次发送时，如果 TTFT 显著下降 (>30%)，则判定为 Cache Hit
    - Cache Hit 时，假设 80% 的输入 tokens 来自缓存
    
    返回：(response, usage_info)
    """
    # 先测量 TTFT
    ttft = measure_ttft(messages, max_tokens=min(20, max_tokens))
    
    # 正式请求获取完整响应和 token 统计
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        max_tokens=max_tokens,
        stream=False,
        **kwargs
    )
    
    # 提取 usage 信息
    usage = response.usage
    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens
    
    # 更新统计（基于 TTFT 判断缓存命中）
    stats.add_request(input_tokens, output_tokens, ttft)
    is_cache_hit = stats.is_cache_hit_by_ttft(ttft) if ttft else False
    cached_tokens = int(input_tokens * 0.9) if is_cache_hit else 0
    
    return response, {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "ttft": ttft,
        "is_cache_hit": is_cache_hit,
    }


# ================= 示例测试 =================
if __name__ == "__main__":
    print(f"🎯 服务：{base_url}")
    print(f"📝 模型：{model_name}")
    print(f"💰 价格配置：输入=¥{PRICING['input_price_per_1m']}/1M, 输出=¥{PRICING['output_price_per_1m']}/1M, 缓存=¥{PRICING['cached_input_price_per_1m']}/1M")
    print("-" * 60)
    
    # 构造长文本用于测试缓存
    paragraph = "人工智能是计算机科学的一个分支，研究如何使机器具有智能行为。" * 500
    system_prompt = f"你是一个 AI 助手。请基于以下背景知识回答问题：\n\n{paragraph}\n\n请简要回答用户问题。"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "什么是人工智能？"}
    ]
    
# 第 1 次：Cache Miss
    print("\n⏳ [请求 1] Cache Miss...")
    resp1, info1 = chat_with_billing(messages, max_tokens=50)
    print(f"   TTFT: {info1['ttft']:.4f}s, 输入 Token: {info1['input_tokens']:,}, 输出 Token: {info1['output_tokens']:,}, 缓存：{info1['cached_tokens']:,}, 命中：{info1['is_cache_hit']}")
    print(f"   回复：{resp1.choices[0].message.content[:50]}...")
    
    # 第 2 次：Cache Hit
    print("\n⏳ [请求 2] Cache Hit...")
    resp2, info2 = chat_with_billing(messages, max_tokens=50)
    print(f"   TTFT: {info2['ttft']:.4f}s, 输入 Token: {info2['input_tokens']:,}, 输出 Token: {info2['output_tokens']:,}, 缓存：{info2['cached_tokens']:,}, 命中：{info2['is_cache_hit']}")
    print(f"   回复：{resp2.choices[0].message.content[:50]}...")
    
    # 第 3 次：不同问题，部分缓存命中
    messages2 = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "人工智能有哪些应用？"}
    ]
    print("\n⏳ [请求 3] 部分 Cache Hit...")
    resp3, info3 = chat_with_billing(messages2, max_tokens=50)
    print(f"   TTFT: {info3['ttft']:.4f}s, 输入 Token: {info3['input_tokens']:,}, 输出 Token: {info3['output_tokens']:,}, 缓存：{info3['cached_tokens']:,}, 命中：{info3['is_cache_hit']}")
    print(f"   回复：{resp3.choices[0].message.content[:50]}...")
    
    # 打印计费报告
    stats.print_report()
