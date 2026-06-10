# mcp_manager.py
"""
MCP (Model Context Protocol) 管理器
负责管理多个 MCP 子进程、工具转换和调用

支持从 YAML 配置文件加载多个 MCP 服务器
"""

import asyncio
import os
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Optional

import yaml

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.websocket import websocket_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore
    websocket_client = None  # type: ignore


class McpServerInstance:
    """单个 MCP 服务器实例"""
    
    def __init__(
        self, 
        name: str, 
        description: str, 
        command: str = "", 
        args: list[str] = None, 
        env: Optional[dict] = None,
        websocket_url: Optional[str] = None
    ):
        self.name = name
        self.description = description
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.websocket_url = websocket_url  # WebSocket URL，如果提供则使用 WebSocket 传输
        self.session: Optional[ClientSession] = None
        self.mcp_tools: list[dict] = []
        self._exit_stack = AsyncExitStack()
        self._started = False
        self._transport_type = "websocket" if websocket_url else "stdio"

    async def start(self) -> bool:
        """启动 MCP 服务器"""
        if not MCP_AVAILABLE:
            print(f"❌ MCP 库未安装，请先运行：pip install mcp")
            return False
            
        try:
            if self._transport_type == "websocket" and self.websocket_url:
                # WebSocket 传输模式
                print(f"[dim]正在通过 WebSocket 连接到：{self.websocket_url}...[/dim]")
                
                # 建立 WebSocket 连接
                ws_transport = await self._exit_stack.enter_async_context(
                    websocket_client(self.websocket_url)
                )
                self.read, self.write = ws_transport
                
                # 建立 Session
                self.session = await self._exit_stack.enter_async_context(
                    ClientSession(self.read, self.write)
                )
                await self.session.initialize()
            else:
                # stdio 传输模式（原有逻辑）
                # 处理环境变量中的 ${VAR} 占位符
                processed_env = {}
                for key, value in self.env.items():
                    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                        env_var = value[2:-1]
                        processed_env[key] = os.environ.get(env_var, "")
                    else:
                        processed_env[key] = value
                
                # 合并到当前环境
                full_env = os.environ.copy()
                full_env.update(processed_env)
                
                server_params = StdioServerParameters(
                    command=self.command,
                    args=self.args,
                    env=full_env
                )
                
                # 启动 stdio 通信
                stdio_transport = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                self.read, self.write = stdio_transport
                
                # 建立 Session
                self.session = await self._exit_stack.enter_async_context(
                    ClientSession(self.read, self.write)
                )
                await self.session.initialize()
            
            # 获取可用工具并转换为 OpenAI/Codex 兼容格式
            raw_tools = await self.session.list_tools()
            self.mcp_tools = []
            for tool in raw_tools.tools:
                self.mcp_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                })
            
            self._started = True
            transport_info = f"({self._transport_type})"
            print(f"[green]✅ {self.name}: 加载了 {len(self.mcp_tools)} 个工具 {transport_info}[/green]")
            return True
            
        except Exception as e:
            print(f"❌ MCP 服务器 '{self.name}' 启动失败：{e}")
            return False

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具"""
        if not self.session:
            return "❌ MCP 服务未启动"
            
        try:
            result = await self.session.call_tool(name, arguments)
            output = []
            for item in result.content:
                if item.type == "text":
                    output.append(item.text)
                elif item.type == "image":
                    output.append("[返回了一张图片]")
            return "\n".join(output) if output else "✅ 执行成功 (无输出)"
        except Exception as e:
            return f"❌ MCP 执行错误：{str(e)}"

    async def close(self):
        """清理资源"""
        await self._exit_stack.aclose()
        self._started = False

    def is_started(self) -> bool:
        """检查是否已启动"""
        return self._started


class McpManager:
    """
    MCP 服务器管理器 - 支持多服务器配置
    
    用法:
        # 从配置文件加载
        mcp = McpManager.from_config("mcp_config.yaml")
        await mcp.start_all()
        
        # 获取所有工具
        all_tools = mcp.get_all_tools()
        
        # 调用工具
        result = await mcp.call_tool("playwright_navigate", {"url": "https://example.com"})
        
        # 关闭
        await mcp.close_all()
    """
    
    def __init__(self):
        self.servers: dict[str, McpServerInstance] = {}
        self.settings: dict = {}

    @classmethod
    def from_config(cls, config_path: str) -> "McpManager":
        """从 YAML 配置文件创建管理器"""
        manager = cls()
        
        config_file = Path(config_path)
        if not config_file.exists():
            print(f"⚠️  配置文件不存在：{config_path}，MCP 功能将不可用")
            return manager
        
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            print(f"❌ 读取配置文件失败：{e}")
            return manager
        
        if not config or not config.get("enabled", True):
            print("ℹ️  MCP 功能在配置文件中被禁用")
            return manager
        
        manager.settings = config.get("settings", {})
        
        # 加载启用的服务器
        for server_cfg in config.get("servers", []):
            if not server_cfg.get("enabled", True):
                continue
                
            server = McpServerInstance(
                name=server_cfg.get("name", "unknown"),
                description=server_cfg.get("description", ""),
                command=server_cfg.get("command", ""),
                args=server_cfg.get("args", []),
                env=server_cfg.get("env", {}),
                websocket_url=server_cfg.get("websocket_url")  # 可选的 WebSocket URL
            )
            manager.servers[server.name] = server
        
        return manager

    async def start_all(self) -> dict[str, bool]:
        """启动所有配置的 MCP 服务器"""
        results = {}
        for name, server in self.servers.items():
            print(f"[dim]正在启动 MCP 服务器：{name}...[/dim]")
            success = await server.start()
            results[name] = success
            # 注意：start() 方法内部已经打印了结果，这里不再重复打印
        return results

    async def start_server(self, name: str) -> bool:
        """启动指定名称的 MCP 服务器"""
        if name not in self.servers:
            print(f"❌ 未找到 MCP 服务器：{name}")
            return False
        return await self.servers[name].start()

    def get_all_tools(self) -> list[dict]:
        """获取所有 MCP 服务器的工具列表"""
        all_tools = []
        for server in self.servers.values():
            if server.is_started():
                all_tools.extend(server.mcp_tools)
        return all_tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """调用 MCP 工具（自动查找所属服务器）"""
        for server in self.servers.values():
            if server.is_started() and any(t["function"]["name"] == name for t in server.mcp_tools):
                return await server.call_tool(name, arguments)
        return f"❌ 未找到工具：{name}"

    async def close_all(self):
        """关闭所有 MCP 服务器"""
        for server in self.servers.values():
            await server.close()
        self.servers.clear()

    def get_server_names(self) -> list[str]:
        """获取所有服务器名称"""
        return list(self.servers.keys())

    def is_available(self) -> bool:
        """检查是否有可用的 MCP 服务器"""
        return any(server.is_started() for server in self.servers.values())
