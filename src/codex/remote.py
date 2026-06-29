# remote.py
"""
SSH 远程连接模块（可选功能）

此模块提供 SSH 远程服务器连接功能。
依赖：fabric, paramiko

如果没有安装这些依赖，模块会优雅降级，不影响主程序运行。
"""

import os
import re
from dataclasses import dataclass
from typing import Dict, Optional, Any, Tuple

# 尝试导入依赖，失败时设置为 None
try:
    from fabric import Connection
    from paramiko.ssh_exception import SSHException, AuthenticationException
    REMOTE_AVAILABLE = True
except ImportError:
    Connection = None
    SSHException = Exception
    AuthenticationException = Exception
    REMOTE_AVAILABLE = False


@dataclass
class RemoteHost:
    """远程主机配置"""
    name: str
    host: str
    user: str
    port: int = 22
    key_path: Optional[str] = None
    workspace: str = "~/codex-workspace"
    password: Optional[str] = None


class RemoteManager:
    """SSH 远程管理器"""
    
    def __init__(self):
        self.connections: Dict[str, Connection] = {}
        self.current_remote: Optional[str] = None  # 存储连接 key
        self.remotes: Dict[str, RemoteHost] = {}
        self.config_path = os.path.expanduser("~/.ssh/config")
        self._conn: Optional[Connection] = None  # 当前连接对象
        if REMOTE_AVAILABLE:
            self.load_config()

    def load_config(self):
        """从 ~/.ssh/config 加载远程主机配置（OpenSSH 格式）"""
        if not REMOTE_AVAILABLE:
            return
            
        if not os.path.exists(self.config_path):
            return
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析 OpenSSH config 格式
        current_host = None
        host_data = {}
        
        for line in content.split('\n'):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith('#'):
                continue
            
            host_match = re.match(r'^Host\s+(\S+)', line_stripped, re.IGNORECASE)
            if host_match:
                if current_host and host_data:
                    self._add_host_from_data(current_host, host_data)
                current_host = host_match.group(1)
                host_data = {}
            elif current_host:
                kv_match = re.match(r'^(\w+)\s+(.+)$', line_stripped)
                if kv_match:
                    key, value = kv_match.groups()
                    host_data[key.lower()] = value
        
        if current_host and host_data:
            self._add_host_from_data(current_host, host_data)

    def _add_host_from_data(self, name: str, data: Dict[str, str]):
        """从解析的数据创建 RemoteHost"""
        if 'hostname' not in data and 'host' not in data:
            return
        
        host = data.get('hostname') or data.get('host')
        user = data.get('user', 'root')
        port = int(data.get('port', 22))
        key_path = data.get('identityfile')
        workspace = data.get('workspace', "~/codex-workspace")
        
        self.remotes[name] = RemoteHost(
            name=name,
            host=host,
            user=user,
            port=port,
            key_path=key_path,
            workspace=workspace
        )

    def save_config(self):
        """将配置保存为 OpenSSH config 格式"""
        if not REMOTE_AVAILABLE:
            return False, "SSH 模块不可用"
            
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        
        lines = []
        for name, r in self.remotes.items():
            lines.append(f"Host {name}")
            lines.append(f"    HostName {r.host}")
            lines.append(f"    User {r.user}")
            lines.append(f"    Port {r.port}")
            if r.key_path:
                lines.append(f"    IdentityFile {r.key_path}")
            lines.append(f"    Workspace {r.workspace}")
            lines.append("")
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        return True, "配置已保存"

    def add_remote(self, name: str, host: str, user: str, port: int = 22,
                   key_path: Optional[str] = None, workspace: str = "~/codex-workspace"):
        """添加远程主机配置"""
        self.remotes[name] = RemoteHost(name, host, user, port, key_path, workspace)
        self.save_config()
        return True, f"已添加远程主机：{name}"

    def connect(self, name: str = None, host: str = None, user: str = None, 
                port: int = 22, key_path: str = None) -> Tuple[bool, str]:
        """
        连接到远程主机。
        若无密钥配置，将在终端动态提示输入密码。
        """
        if not REMOTE_AVAILABLE:
            return False, "❌ SSH 模块不可用，请安装依赖：pip install fabric paramiko"
        
        # 1. 尝试从配置中提取
        if name and name in self.remotes:
            config = self.remotes[name]
            target_host = config.host
            target_user = config.user
            target_port = config.port
            target_key = config.key_path
        else:
            # 直连模式
            target_host = host
            target_user = user
            target_port = int(port) if port else 22
            target_key = key_path

        if not target_host or not target_user:
            return False, "❌ 连接失败：未指定有效的主机地址 (host) 或用户名 (user)"

        try:
            import getpass
            
            connect_kwargs = {
                "look_for_keys": False,
                "allow_agent": False
            }
            
            if target_key:
                connect_kwargs["key_filename"] = target_key
            else:
                prompt = f"\n🔒 [{target_user}@{target_host}:{target_port}] Password: "
                target_password = getpass.getpass(prompt)
                connect_kwargs["password"] = target_password

            # 初始化连接对象
            self._conn = Connection(
                host=target_host,
                user=target_user,
                port=target_port,
                connect_kwargs=connect_kwargs
            )
            
            # 显式触发网络握手
            self._conn.open() 
            conn_key = name if name else f"{target_user}@{target_host}:{target_port}"
            
            self.connections[conn_key] = self._conn
            self.current_remote = conn_key
            
            return True, f"🔌 成功连接到 {target_user}@{target_host}:{target_port}"

        except Exception as e:
            self._conn = None
            error_msg = str(e)
            if "Authentication failed" in error_msg:
                error_msg = "认证失败，密码错误"
            return False, f"❌ 远程连接失败：{error_msg}"

    def get_conn(self) -> Optional[Connection]:
        """获取当前激活的远程连接"""
        if not self.current_remote:
            return None
        return self.connections.get(self.current_remote)

    def is_remote(self) -> bool:
        """是否已连接远程"""
        return self.current_remote is not None

    def get_workspace(self) -> str:
        """获取远程工作目录"""
        if self.current_remote and self.current_remote in self.remotes:
            return self.remotes[self.current_remote].workspace
        return "~/codex-workspace"

    def get_status(self) -> str:
        """获取连接状态"""
        if self.current_remote:
            if self.current_remote in self.remotes:
                r = self.remotes[self.current_remote]
                return f"远程模式 [{r.name}] {r.user}@{r.host}"
            return f"远程模式 {self.current_remote}"
        return "本地模式"

    def disconnect(self) -> Tuple[bool, str]:
        """断开当前连接"""
        if self.current_remote:
            conn = self.connections.get(self.current_remote)
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            del self.connections[self.current_remote]
            self.current_remote = None
            self._conn = None
            return True, "已断开连接"
        return False, "没有活动的连接"


# 全局单例
remote_manager = RemoteManager()


def get_remote_tools() -> list:
    """
    获取 SSH 远程工具列表（仅在模块可用时返回）
    """
    if not REMOTE_AVAILABLE:
        return []
    
    return [
        {
            "type": "function",
            "function": {
                "name": "connect_remote",
                "description": "连接到远程服务器（支持通过别名读取配置，或直接指定 IP/用户/端口直连。密码将在连接时由用户在后续终端交互输入）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "远程主机别名"},
                        "host": {"type": "string", "description": "目标服务器 IP 或域名"},
                        "user": {"type": "string", "description": "SSH 登录用户名"},
                        "port": {"type": "integer", "description": "SSH 端口号", "default": 22},
                        "key_path": {"type": "string", "description": "密钥文件路径（可选）"},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_remote_file",
                "description": "读取远程服务器文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "远程文件路径（相对或绝对）"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_remote_file",
                "description": "写入内容到远程文件",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_remote_command",
                "description": "在远程服务器执行 shell 命令",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"},
                        "timeout": {"type": "integer", "default": 30},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_remote_dir",
                "description": "列出远程目录内容",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "default": "."},
                    },
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "disconnect_remote",
                "description": "断开当前远程连接",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "remote_status",
                "description": "显示远程连接状态",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    ]