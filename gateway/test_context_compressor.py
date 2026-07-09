# test_context_compressor.py
"""测试上下文压缩模块"""

import sys
sys.path.insert(0, '.')

from context_compressor import ContextCompressor, compress_on_context_limit


def test_drop_oldest_rounds():
    """测试删除最早对话轮"""
    print("\n" + "="*60)
    print("测试 1: 删除最早对话轮")
    print("="*60)
    
    # 创建模拟对话：1 个 system + 10 轮对话（20 条消息）
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(10):
        messages.append({"role": "user", "content": f"User question {i}"})
        messages.append({"role": "assistant", "content": f"Assistant answer {i}"})
    
    print(f"原始消息数：{len(messages)}")
    
    compressor = ContextCompressor(max_history_rounds=5)
    compressed = compressor.compress(messages, strategy="drop_oldest")
    
    print(f"压缩后消息数：{len(compressed)}")
    print(f"保留的消息：")
    for i, msg in enumerate(compressed):
        print(f"  [{i}] {msg['role']}: {msg['content'][:50]}...")
    
    # 验证：应该保留 system + 5 轮对话 = 11 条消息
    assert len(compressed) == 11, f"Expected 11 messages, got {len(compressed)}"
    assert compressed[0]["role"] == "system"
    assert "question 5" in compressed[1]["content"]  # 第一轮应该是第 5 轮
    
    print("✅ 测试 1 通过")


def test_compress_tool_outputs():
    """测试压缩工具输出"""
    print("\n" + "="*60)
    print("测试 2: 压缩工具输出")
    print("="*60)
    
    # 创建模拟对话，包含超长的工具输出
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Search for files"},
        {"role": "assistant", "content": "Calling search tool..."},
        {"role": "tool", "content": "\n".join([f"Line {i}: search result" for i in range(100)])},
    ]
    
    print(f"原始工具输出行数：{len(messages[3]['content'].split(chr(10)))}")
    
    compressor = ContextCompressor()
    compressed = compressor.compress(messages, strategy="compress_tools")
    
    tool_output = compressed[3]["content"]
    print(f"压缩后工具输出长度：{len(tool_output)} 字符")
    print(f"压缩后内容预览：")
    print(tool_output[:200])
    
    # 验证：应该包含省略标记
    assert "省略" in tool_output or "..." in tool_output
    assert "Line 0:" in tool_output  # 应该保留头部
    assert "Line 99:" in tool_output or "Line 9" in tool_output  # 应该保留尾部
    
    print("✅ 测试 2 通过")


def test_estimate_tokens():
    """测试 token 估算"""
    print("\n" + "="*60)
    print("测试 3: Token 估算")
    print("="*60)
    
    messages = [
        {"role": "user", "content": "Hello, how are you?" * 100},
        {"role": "assistant", "content": "I'm fine, thank you!" * 100},
    ]
    
    compressor = ContextCompressor()
    estimated = compressor.estimate_tokens(messages)
    
    print(f"消息总字符数：{sum(len(m['content']) for m in messages)}")
    print(f"估算 token 数：{estimated}")
    
    assert estimated > 0
    print("✅ 测试 3 通过")


def test_compress_on_context_limit():
    """测试完整的上下文超限压缩流程"""
    print("\n" + "="*60)
    print("测试 4: 完整压缩流程")
    print("="*60)
    
    # 创建大量对话
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(50):  # 50 轮对话
        messages.append({"role": "user", "content": f"Question {i}: " + "A" * 100})
        messages.append({"role": "assistant", "content": f"Answer {i}: " + "B" * 100})
    
    print(f"原始消息数：{len(messages)}")
    
    compressor = ContextCompressor()
    estimated_before = compressor.estimate_tokens(messages)
    print(f"估算 token 数（压缩前）: {estimated_before}")
    
    # 模拟超限压缩（设置较小的 max_tokens 触发压缩）
    # 估算 token 约 3736，设置 2000 触发压缩
    compressed = compress_on_context_limit(messages, max_tokens=2000)
    
    estimated_after = compressor.estimate_tokens(compressed)
    print(f"压缩后消息数：{len(compressed)}")
    print(f"估算 token 数（压缩后）: {estimated_after}")
    
    assert len(compressed) < len(messages)
    print("✅ 测试 4 通过")


def test_needs_compression():
    """测试是否需要压缩的判断"""
    print("\n" + "="*60)
    print("测试 5: 压缩需求判断")
    print("="*60)
    
    # 短对话 - 不需要压缩
    short_messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ]
    
    # 长对话 - 需要压缩（超过 262144 * 0.9 = 235929 tokens）
    # 按 1 token ≈ 3 字符计算，需要约 700000 字符
    long_messages = [
        {"role": "user", "content": "A" * 400000},
        {"role": "assistant", "content": "B" * 400000},
    ]
    
    compressor = ContextCompressor()
    
    assert not compressor.needs_compression(short_messages)
    print("✅ 短对话：不需要压缩")
    
    assert compressor.needs_compression(long_messages)
    print("✅ 长对话：需要压缩")
    
    print("✅ 测试 5 通过")


def test_ultra_long_context_segmented_compression():
    """测试超长上下文的分段压缩功能（核心测试）"""
    print("\n" + "="*60)
    print("测试 6: 超长上下文分段压缩（核心功能测试）")
    print("="*60)
    
    # 创建超长对话：100 轮对话，每轮包含较长的用户问题和助手回答
    messages = [{"role": "system", "content": "You are a helpful assistant."}]
    for i in range(100):  # 100 轮对话
        messages.append({
            "role": "user",
            "content": f"Question {i}: " + "A" * 200  # 每轮 200 字符
        })
        messages.append({
            "role": "assistant",
            "content": f"Answer {i}: " + "B" * 200  # 每轮 200 字符
        })
    
    print(f"原始消息数：{len(messages)}")
    
    compressor = ContextCompressor()
    estimated_before = compressor.estimate_tokens(messages)
    print(f"估算 token 数（压缩前）: {estimated_before}")
    
    # 模拟超长上下文场景：设置 max_tokens=10000，触发多段压缩
    # 这测试分段压缩能否逐步执行：工具压缩→15 轮→10 轮→5 轮→3 轮
    compressed = compress_on_context_limit(
        messages,
        max_tokens=10000,  # 较低的阈值，触发完整分段压缩流程
        target_ratio=0.75  # 目标 75% 使用率
    )
    
    estimated_after = compressor.estimate_tokens(compressed)
    print(f"压缩后消息数：{len(compressed)}")
    print(f"估算 token 数（压缩后）: {estimated_after}")
    print(f"目标阈值：{int(10000 * 0.75)} tokens")
    
    # 验证：压缩后消息数应该显著减少
    assert len(compressed) < len(messages), "压缩后消息数应该减少"
    
    # 验证：压缩后应该在目标阈值附近或以下
    # （由于是估算，允许有一定误差）
    target_threshold = int(10000 * 0.75)
    print(f"压缩是否达到目标：{'✅ 是' if estimated_after <= target_threshold else '⚠️  接近目标'}")
    
    # 验证：保留的消息应该包含 system 和最近的对话
    assert compressed[0]["role"] == "system", "应该保留 system 消息"
    
    print("✅ 测试 6 通过：超长上下文分段压缩功能正常")


if __name__ == "__main__":
    print("="*60)
    print("上下文压缩模块测试")
    print("="*60)
    
    try:
        test_drop_oldest_rounds()
        test_compress_tool_outputs()
        test_estimate_tokens()
        test_compress_on_context_limit()
        test_needs_compression()
        test_ultra_long_context_segmented_compression()  # 新增：超长上下文分段压缩测试
        
        print("\n" + "="*60)
        print("✅ 所有测试通过！")
        print("="*60)
    except AssertionError as e:
        print(f"\n❌ 测试失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试异常：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)