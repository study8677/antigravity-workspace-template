# 🔌 MCP 集成指南

## 🌐 什么是 MCP？

[Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 是连接 AI 应用与外部工具/数据源的标准协议。启用后可以：
- 🔗 同时连接多个 MCP 服务器并使用其中的工具
- 📊 访问数据库、API、文件系统、浏览器等
- 🔄 将远端工具与本地工具透明合并

## 🚀 快速配置

1) `.env` 启用 MCP
```bash
MCP_ENABLED=true
RB_ALLOW_MCP=true
```

`MCP_ENABLED=true` 让配置的 MCP server 对 engine 可见。`RB_ALLOW_MCP=true`
是 `rb-ask` 自动连接外部 MCP server 的显式 opt-in；只有信任这些 server 时才开启。

2) 编辑 `mcp_servers.json`
```json
{
  "servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "enabled": true,
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "your-github-token" }
    },
    {
      "name": "filesystem",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
      "enabled": true
    }
  ]
}
```

3) 调用知识库问答
```bash
rb-ask "有哪些 MCP 工具可用？" --workspace .
```
当两个开关都开启时，问答流水线会连接已启用的服务器、发现工具并与本地工具合并。

## 🏗️ 架构
Agent → MCP 客户端管理器 → 多个 MCP 服务器；本地工具与远端工具合并成统一工具集对外使用。

## 📡 支持的传输

| transport | 适用场景 |
|-----------|----------|
| `stdio`   | 本地/CLI 服务器 |
| `http`    | 远端/云端服务 |
| `sse`     | 兼容 SSE 的 HTTP 服务器 |

## 🛠️ 内置 MCP 辅助工具

- `list_mcp_servers()` — 列出连接的服务器
- `list_mcp_tools()` — 枚举所有可用 MCP 工具
- `get_mcp_tool_help(name)` — 查看工具帮助
- `mcp_health_check()` — 服务器健康检查

## 📋 预置模板

`mcp_servers.json` 已包含文件系统、GitHub、PostgreSQL、Brave Search、Memory、Puppeteer、Slack 等模板，按需启用并填好密钥即可。

## 🔧 自定义 MCP 服务器

使用 [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) 与 FastMCP：
```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My Analysis Server")

@mcp.tool()
def analyze_text(text: str) -> str:
    """情感分析或摘要."""
    return f"Analysis of: {text}"

if __name__ == "__main__":
    mcp.run()
```
然后在 `mcp_servers.json` 注册：
```json
{
  "name": "my-analysis",
  "transport": "stdio",
  "command": "python",
  "args": ["engine/repobrain_engine/tools/my_server.py"],
  "enabled": true
}
```
重新运行 `rb-ask` 即可使用。

## 🔐 安全注意事项

- 机密信息建议通过环境变量管理；当前实现会把 `mcp_servers.json` 中 `env` 的值原样传给 MCP 进程，不会自动解析 `\${VAR_NAME}` 占位符。
- Stdio MCP server 会继承父进程环境变量以及配置里的 `env` 值。每个启用的 MCP server 都应视为拥有本地 workspace 权限的代码。
- 对不可信服务器可放进容器、限制文件权限、监控调用。

## 🧪 测试 MCP 集成
```python
from repobrain_engine.mcp_client import MCPClientManagerSync

manager = MCPClientManagerSync(config_path="mcp_servers.json")
manager.initialize()

print(manager.get_status())
print(list(manager.get_all_tools_as_callables().keys()))
manager.shutdown()
```

## 🐛 故障排查

- 无法连接：先手动运行服务器命令（如 `python engine/repobrain_engine/tools/my_server.py`），确认 `npx` 等命令存在。
- 工具未出现：重启 Agent，并确认对应 MCP 服务器已在 `mcp_servers.json` 里启用。
- 性能问题：禁用不需要的服务器；远程优先用 `http`；必要时缓存结果。

## 📚 资源

- [MCP 官方文档](https://modelcontextprotocol.io/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP 示例](https://github.com/modelcontextprotocol/python-sdk/tree/main/examples)

---

**下一步：** [Swarm 协议](SWARM_PROTOCOL.md) | [文档索引](README.md)
