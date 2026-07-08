# test_context_limit_regex.py
"""
测试 vLLM 上下文超限错误正则表达式的捕获能力
"""

import re

# 简化版本 - 修复括号匹配问题
CONTEXT_LIMIT_RE = re.compile(
    r"context.*(length|limit|size|window).*(exceed|over|too long)|"
    r"input.*(tokens).*exceed|"
    r"length.*exceed.*maximum|"
    r"input.*too long|"
    r"out of.*(memory|kv cache)|"
    r"(400|500).*(Bad Request|Internal Server Error)",
    re.IGNORECASE
)

# 测试用例：常见的 vLLM 上下文超限错误消息
test_cases = [
    # vLLM 典型错误
    ("Context length exceeded. The model only supports 262144 tokens but received 300000.", True),
    ("Input tokens exceed maximum context length of 262144", True),
    ("The input is too long. Maximum context size is 262144 tokens.", True),
    ("Request length exceeds maximum allowed context window", True),
    
    # OOM / KV Cache 错误
    ("Out of memory while allocating KV cache", True),
    ("GPU out of memory during context processing", True),
    ("KV cache allocation failed: out of memory", True),
    
    # HTTP 状态码错误
    ("400 Bad Request: input is too long", True),
    ("500 Internal Server Error: context processing failed", True),
    
    # 不应该匹配的正常消息
    ("The context is very important for understanding", False),
    ("Your request was successful", False),
    ("The model generated 1000 tokens", False),
    
    # 边界情况
    ("Context length: 262144, this is the limit", False),  # 只是说明，不是错误
    ("Maximum context supported: 262144 tokens", False),  # 只是说明
]

print("=" * 80)
print("vLLM 上下文超限错误正则表达式测试")
print("=" * 80)

passed = 0
failed = 0

for error_msg, should_match in test_cases:
    match = CONTEXT_LIMIT_RE.search(error_msg)
    matched = match is not None
    
    status = "✅" if matched == should_match else "❌"
    
    if matched == should_match:
        passed += 1
    else:
        failed += 1
    
    print(f"\n{status} 测试：{'应匹配' if should_match else '不应匹配'}")
    print(f"   消息：{error_msg[:80]}...")
    print(f"   结果：{'匹配' if matched else '未匹配'} (期望：{'匹配' if should_match else '不匹配'})")
    if match:
        print(f"   匹配内容：{match.group()[:100]}")

print("\n" + "=" * 80)
print(f"测试结果：{passed} 通过，{failed} 失败，总计 {len(test_cases)} 项")
print("=" * 80)

if failed > 0:
    print("\n⚠️  部分测试未通过，可能需要调整正则表达式")
    exit(1)
else:
    print("\n✅ 所有测试通过！正则表达式可以正确捕获上下文超限错误")
    exit(0)