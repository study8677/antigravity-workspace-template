# ⚡ 零配置特性

## 🎯 零配置理念

**告别重复配置。** RepoBrain 会自动发现工具与上下文，无需手动注册。

## 🛠️ 自动发现工具

把任意 Python 文件放进 `engine/engine/repobrain_engine/tools/`，Agent 会立刻识别其顶层函数——无需 import、无需登记。

### 工作方式
1) 🔍 扫描 `engine/repobrain_engine/tools/` 下所有 `.py`  
2) 📋 索引顶层函数并读取 docstring  
3) ✅ 注册公开函数为可调用工具  

### 示例
```python
# engine/repobrain_engine/tools/sentiment_analyzer.py
def analyze_sentiment(text: str) -> dict:
    """情感分析：返回分数与标签。"""
    if len(text) > 10:
        return {"score": 0.8, "label": "positive"}
    return {"score": 0.3, "label": "neutral"}
```
运行一次 `rb-refresh --workspace .` 后即可在对话里直接使用 `analyze_sentiment()`。

### 编写建议
- 必写 docstring，说明参数/返回值/边界。  
- 使用类型注解，避免模糊参数。  
- 一个函数只做一件事，不要用 `*args/**kwargs` 随意接收。  

## 🎓 自动发现 Skill

把一个技能目录放到 `repobrain_engine/skills/` 下（包含 `SKILL.md`，可选 `tools.py`），Agent 会自动加载：
- `SKILL.md` 内容会注入提示上下文
- `tools.py` 中的公开函数会注册为可调用工具

### 内置示例：`agent-repo-init`

当前仓库包含：
- `repobrain_engine/skills/agent-repo-init/`：Agent 内部可调用 skill（`init_agent_repo`）
- `skills/agent-repo-init/`：可移植 skill 包（脚本入口）

`agent-repo-init` 支持：
- `quick`：干净脚手架初始化
- `full`：脚手架 + 运行时默认配置（`.env`、mission、上下文 profile、初始化报告）

可用于从本模板初始化一个干净的新项目，避免继承本地运行态数据（如 `.git`、缓存目录、本地虚拟环境、运行时记忆文件）。

## 📚 自动注入上下文

把知识文件放到 `.context/` 会被自动拼接进系统提示，Agent 对话天然“带背景”。

### 工作方式
1) 扫描 `.context/` 顶层目录（当前只读取 `.md`）  
2) 读取内容并注入系统提示  
3) 每次运行 Agent 时重新加载上下文  

### 组织建议
```
.context/
├── README.md                  # 索引
├── coding_standards.md
├── security_policies.md
├── architecture.md
└── database_schema.md
```
保持单文件 <100 行，命名自解释，旧内容及时归档。

## 🔗 工具 + 上下文 如何协同

**场景**：构建数据分析工具  
- 上下文：`.context/database_schema.md` 记录表结构  
- 工具：`engine/repobrain_engine/tools/db_query.py` 提供查询函数  
- 对话：直接让 Agent“查找最近一月创建的用户”，它既“知道”结构，也“能”查询。

## 🎓 最佳实践
- 工具：写清 docstring 与类型；避免通配导入；函数单一职责。  
- 上下文：精简、可维护，关键文件优先放在 `.context/` 顶层；内容稳定的放上下文，动态操作放工具。  
- 性能：控制上下文总量（推荐 <50KB），定期清理旧文件。  

## 🐛 排查指引

**工具没加载？**
```bash
ls -la engine/repobrain_engine/tools/
python -m py_compile engine/repobrain_engine/tools/my_tool.py
rb-refresh --workspace .  # 重新刷新知识库
```

**上下文未注入？**
```bash
ls -la .context/
cat .context/your_file.md
du -sh .context/
rb-refresh --workspace .  # 重新刷新知识库
```

## 🚀 进阶

- 用 git 管理上下文版本  
- 按任务类型选择性注入上下文  
- 从 schema 动态生成工具  
- 组合工具完成更复杂的流程  

---

**下一步：** [开发路线图](ROADMAP.md) | [文档索引](README.md)
