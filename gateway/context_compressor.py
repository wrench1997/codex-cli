# context_compressor.py
"""
上下文压缩模块 - 用于在 vLLM 上下文超限时自动压缩对话历史

压缩策略（按优先级分段执行）：
1. 【第一段】压缩工具调用结果（只保留关键信息）
2. 【第二段】删除最早的用户 -assistant 对话对（保留最近 N 轮）
3. 【第三段】摘要化长文本内容（可选，需要额外模型调用）
4. 【第四段】激进压缩（保留最小对话集）

分段压缩优势：
- 渐进式压缩，避免一次性丢失过多信息
- 可按优先级保留重要上下文
- 支持多级压缩阈值，适应不同场景
"""

from __future__ import annotations

import json
from typing import Any


class ContextCompressor:
    """上下文压缩器"""
    
    def __init__(self, max_history_rounds: int = 20):
        """
        初始化压缩器
        
        Args:
            max_history_rounds: 保留的最大对话轮数（默认 20 轮）
        """
        self.max_history_rounds = max_history_rounds
    
    def compress(self, messages: list[dict[str, Any]], strategy: str = "drop_oldest") -> list[dict[str, Any]]:
        """
        压缩对话历史
        
        Args:
            messages: OpenAI 格式的对话列表
            strategy: 压缩策略
                - "drop_oldest": 删除最早的对话对
                - "compress_tools": 压缩工具调用结果
                - "hybrid": 混合策略（先压缩工具，再删除对话）
        
        Returns:
            压缩后的对话列表
        """
        if strategy == "drop_oldest":
            return self._drop_oldest_rounds(messages)
        elif strategy == "compress_tools":
            return self._compress_tool_outputs(messages)
        elif strategy == "hybrid":
            messages = self._compress_tool_outputs(messages)
            return self._drop_oldest_rounds(messages)
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    
    def _drop_oldest_rounds(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        删除最早的对话轮，保留 system 消息和最近 N 轮对话
        
        一轮对话 = 1 个 user 消息 + 1 个 assistant 消息
        """
        if len(messages) <= 1:
            return messages
        
        # 分离 system 消息和其他消息
        system_messages = [m for m in messages if m.get("role") == "system"]
        other_messages = [m for m in messages if m.get("role") != "system"]
        
        # 如果没有非 system 消息，直接返回
        if not other_messages:
            return messages
        
        # 计算保留多少轮（一轮 = user + assistant）
        total_rounds = len(other_messages) // 2
        rounds_to_keep = min(self.max_history_rounds, total_rounds)
        
        # 如果总轮数不超过限制，不需要压缩
        if total_rounds <= self.max_history_rounds:
            return messages
        
        # 保留最近的 N 轮
        messages_to_keep = other_messages[-(rounds_to_keep * 2):]
        
        # 重组消息：system + 最近的对话
        result = system_messages + messages_to_keep
        
        print(f"[ContextCompressor] 删除最早对话：{len(messages)} -> {len(result)} 条消息 "
              f"(保留最近 {rounds_to_keep} 轮)")
        
        return result
    
    def _compress_tool_outputs(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        压缩工具调用结果，只保留关键信息
        
        压缩策略：
        1. 对于超长的工具输出，截断并添加摘要
        2. 对于文件内容，只保留文件名和操作类型
        3. 对于搜索/执行结果，只保留前 N 行和后 N 行
        """
        MAX_OUTPUT_LENGTH = 500  # 工具输出最大长度
        KEEP_HEAD_LINES = 10     # 保留前 N 行
        KEEP_TAIL_LINES = 10     # 保留后 N 行
        
        result = []
        compressed_count = 0
        
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            
            # 只处理 tool 角色的消息（工具调用结果）
            if role == "tool" and isinstance(content, str) and len(content) > MAX_OUTPUT_LENGTH:
                # 压缩策略：保留头部和尾部，中间用省略号代替
                lines = content.split('\n')
                if len(lines) > KEEP_HEAD_LINES + KEEP_TAIL_LINES:
                    head = '\n'.join(lines[:KEEP_HEAD_LINES])
                    tail = '\n'.join(lines[-KEEP_TAIL_LINES:])
                    compressed_content = (
                        f"{head}\n"
                        f"\n... [省略 {len(lines) - KEEP_HEAD_LINES - KEEP_TAIL_LINES} 行] ...\n"
                        f"{tail}"
                    )
                else:
                    # 如果行数不多但字符数超了，直接截断
                    compressed_content = content[:MAX_OUTPUT_LENGTH] + "\n\n... [内容已截断]"
                
                result.append({
                    "role": "tool",
                    "content": compressed_content
                })
                compressed_count += 1
            else:
                result.append(msg)
        
        if compressed_count > 0:
            print(f"[ContextCompressor] 压缩工具输出：{compressed_count} 个工具结果被压缩")
        
        return result
    
    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """
        估算消息的 token 数量（粗略估算）
        
        使用简单规则：
        - 英文：1 token ≈ 4 字符
        - 中文：1 token ≈ 1.5 字符
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        total_chars += len(item["text"])
        
        # 粗略估算：混合中英文，按 1 token ≈ 3 字符计算
        estimated_tokens = total_chars // 3
        return estimated_tokens
    
    def needs_compression(self, messages: list[dict[str, Any]], max_tokens: int = 262144) -> bool:
        """
        判断是否需要压缩
        
        Args:
            messages: 对话消息列表
            max_tokens: 最大 token 限制（默认 262144）
        
        Returns:
            True 如果需要压缩
        """
        estimated = self.estimate_tokens(messages)
        # 保留 10% 余量
        threshold = max_tokens * 0.9
        return estimated > threshold


def compress_on_context_limit(
    messages: list[dict[str, Any]],
    compressor: ContextCompressor | None = None,
    max_tokens: int = 262144,
    target_ratio: float = 0.75  # 目标使用率（保留 25% 余量）
) -> list[dict[str, Any]]:
    """
    上下文超限时的分段压缩函数
    
    【分段压缩策略】按优先级逐步执行：
    
    第一段：压缩工具输出
      - 截断超长工具结果，保留头尾关键信息
      - 适合：工具返回大量文件内容、搜索结果时
    
    第二段：删除最早对话轮（温和模式）
      - 保留最近 15 轮对话
      - 适合：对话历史适中，只需轻微压缩
    
    第三段：删除最早对话轮（标准模式）
      - 保留最近 10 轮对话
      - 适合：对话历史较长，需要明显压缩
    
    第四段：删除最早对话轮（激进模式）
      - 保留最近 5 轮对话
      - 适合：对话历史非常长，需要大幅压缩
    
    第五段：极限压缩（最后手段）
      - 仅保留最近 3 轮对话
      - 适合：上下文严重超限的极端情况
    
    Args:
        messages: 原始对话消息
        compressor: 压缩器实例（可选，会创建默认实例）
        max_tokens: 最大 token 限制
        target_ratio: 目标 token 使用率（默认 0.75，即保留 25% 余量）
    
    Returns:
        压缩后的消息列表
    """
    if compressor is None:
        compressor = ContextCompressor()
    
    original_count = len(messages)
    original_tokens = compressor.estimate_tokens(messages)
    compressed_messages = messages.copy()
    
    # 压缩报告
    compression_report = {
        "original_tokens": original_tokens,
        "original_count": original_count,
        "stages_executed": [],
        "final_tokens": original_tokens,
        "final_count": original_count,
    }
    
    target_threshold = int(max_tokens * target_ratio)
    
    # =========================================================
    # 第一段：压缩工具输出
    # =========================================================
    compressed_messages = compressor.compress(compressed_messages, strategy="compress_tools")
    if len(compressed_messages) < original_count:
        compression_report["stages_executed"].append("compress_tools")
    
    compression_report["final_tokens"] = compressor.estimate_tokens(compressed_messages)
    compression_report["final_count"] = len(compressed_messages)
    
    # 检查是否已满足要求
    if compression_report["final_tokens"] <= target_threshold:
        print(f"[ContextCompressor] [PASS] 第一段压缩后已满足要求："
              f"{compression_report['original_tokens']} -> {compression_report['final_tokens']} tokens "
              f"(目标：{target_threshold})")
        compression_report["stages_executed"].append("done_after_compress_tools")
        return compressed_messages
    
    # =========================================================
    # 第二段：删除最早对话（温和模式 - 保留 15 轮）
    # =========================================================
    compressor.max_history_rounds = 15
    compressed_messages = compressor.compress(compressed_messages, strategy="drop_oldest")
    compression_report["final_tokens"] = compressor.estimate_tokens(compressed_messages)
    compression_report["final_count"] = len(compressed_messages)
    
    if compression_report["final_tokens"] <= target_threshold:
        print(f"[ContextCompressor] [PASS] 第二段压缩后已满足要求（保留 15 轮）："
              f"{compression_report['final_tokens']} tokens")
        compression_report["stages_executed"].append("drop_oldest_15_rounds")
        return compressed_messages
    
    # =========================================================
    # 第三段：删除最早对话（标准模式 - 保留 10 轮）
    # =========================================================
    compressor.max_history_rounds = 10
    compressed_messages = compressor.compress(compressed_messages, strategy="drop_oldest")
    compression_report["final_tokens"] = compressor.estimate_tokens(compressed_messages)
    compression_report["final_count"] = len(compressed_messages)
    
    if compression_report["final_tokens"] <= target_threshold:
        print(f"[ContextCompressor] [PASS] 第三段压缩后已满足要求（保留 10 轮）："
              f"{compression_report['final_tokens']} tokens")
        compression_report["stages_executed"].append("drop_oldest_10_rounds")
        return compressed_messages
    
    # =========================================================
    # 第四段：删除最早对话（激进模式 - 保留 5 轮）
    # =========================================================
    compressor.max_history_rounds = 5
    compressed_messages = compressor.compress(compressed_messages, strategy="drop_oldest")
    compression_report["final_tokens"] = compressor.estimate_tokens(compressed_messages)
    compression_report["final_count"] = len(compressed_messages)
    
    if compression_report["final_tokens"] <= target_threshold:
        print(f"[ContextCompressor] [PASS] 第四段压缩后已满足要求（保留 5 轮）："
              f"{compression_report['final_tokens']} tokens")
        compression_report["stages_executed"].append("drop_oldest_5_rounds")
        return compressed_messages
    
    # =========================================================
    # 第五段：极限压缩（仅保留 3 轮）
    # =========================================================
    compressor.max_history_rounds = 3
    compressed_messages = compressor.compress(compressed_messages, strategy="drop_oldest")
    compression_report["final_tokens"] = compressor.estimate_tokens(compressed_messages)
    compression_report["final_count"] = len(compressed_messages)
    
    print(f"[ContextCompressor] [WARN] 已执行极限压缩（保留 3 轮）："
          f"{compression_report['original_tokens']} -> {compression_report['final_tokens']} tokens")
    compression_report["stages_executed"].append("drop_oldest_3_rounds 极限")
    
    # 最终报告
    removed_count = original_count - len(compressed_messages)
    if removed_count > 0:
        print(f"[ContextCompressor] [SUMMARY] 压缩总结：删除 {removed_count} 条消息 "
              f"({original_count} -> {len(compressed_messages)})")
        print(f"              执行阶段：{' -> '.join(compression_report['stages_executed'])}")
    
    return compressed_messages
