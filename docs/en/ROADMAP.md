# 🗺️ Development Roadmap

## Vision: Evidence-Grounded Repository Knowledge Layer

RepoBrain is converging on a portable repository knowledge engine: refresh a
workspace into `.repobrain/`, ask grounded questions with source evidence, and
expose the same knowledge through plugins, CLI, and MCP without locking users to
one IDE.

## 📊 Current Status

| Phase | Status | Description |
|-------|--------|-------------|
| 1️⃣ **Foundation** | ✅ Complete | Scaffold, configuration, memory system |
| 2️⃣ **DevOps** | ✅ Complete | Docker, CI/CD pipelines |
| 3️⃣ **RepoBrain Compliance** | ✅ Complete | Rules, artifacts, protocols |
| 4️⃣ **Advanced Memory** | ✅ Complete | Recursive summarization, buffer management |
| 5️⃣ **Cognitive Architecture** | ✅ Complete | Generic tool dispatch, function calling |
| 6️⃣ **Dynamic Discovery** | ✅ Complete | Auto tool & context loading |
| 7️⃣ **Multi-Agent Swarm** | ✅ Complete | Router-Worker orchestration |
| 8️⃣ **MCP Integration** | ✅ Complete | Model Context Protocol support |
| 9️⃣ **Enterprise Core** | ✅ Complete | Safety boundaries, observability, deployment polish |
| 🔟 **Knowledge Hub** | ✅ Complete | Multi-agent project context system |

## ✅ Completed Phases

### Phase 1: Foundation ✅
**Goal**: Establish project scaffold and core infrastructure

**Achievements:**
- Project structure with agents/ and tools/ modules
- Configuration management via `config.py`
- Markdown-based memory system (`memory/agent_memory.md`)
- Artifact-First protocol setup

### Phase 2: DevOps ✅
**Goal**: Production deployment capabilities

**Achievements:**
- Dockerfile with minimal footprint
- `docker-compose.yml` for local dev stack
- GitHub Actions CI/CD workflows
- Environment-based configuration

### Phase 3: RepoBrain Compliance ✅
**Goal**: Full compliance with RepoBrain platform specifications

**Achievements:**
- `.repobrain/` rules integration
- `.cursorrules` IDE auto-detection
- Artifact output structure
- Think-Act-Reflect loop implementation

### Phase 4: Advanced Memory ✅
**Goal**: Overcome token/context limitations

**Achievements:**
- Recursive summarization algorithm
- Summary buffer for long conversations
- Automatic context compression
- Configurable memory thresholds

### Phase 5: Cognitive Architecture ✅
**Goal**: Unified tool handling and function calling

**Achievements:**
- Generic ReAct pattern implementation
- Python function to tool schema conversion
- Function parameter validation
- Tool result formatting

### Phase 6: Dynamic Discovery ✅
**Goal**: Zero-config tool and knowledge loading

**Achievements:**
- Automatic tool discovery from `engine/repobrain_engine/tools/`
- Auto-injection from `.context/` files
- Hot reload on file changes
- Docstring-based help generation

### Phase 7: Multi-Agent Swarm ✅
**Goal**: Collaborative multi-specialist execution

**Achievements:**
- **Refresh Swarm**: Three-agent handoff chain (ScanAnalyst → ArchitectureReviewer → ConventionWriter) for project analysis
- **Ask Swarm**: Dynamic Router-Worker pattern with per-module agents for grounded Q&A
- Module-based question routing with file evidence
- Git history integration for change tracking

### Phase 8: MCP Integration ✅
**Goal**: Universal external tool connectivity

**Achievements:**
- MCP server connection management
- Tool discovery from MCP servers
- Stdio, HTTP, and SSE transport support
- Pre-configured server templates
- Custom MCP server creation guide

**Implemented by:** [@devalexanderdaza](https://github.com/devalexanderdaza)

## 🚀 Phase 9: Enterprise Core (Completed with Future Extensions)

**Completed:** 2025

**Productized Achievements:**
- Safety boundaries and model selection controls
- Observability through `rb report`, status tracking, and structured logs
- Deployment polish: host-runner backend, incremental refresh, stable CLI

The core phase is complete. Below are **future extension ideas** (not currently in-progress) that would build on this foundation:

### Future Extension: Sandbox Environment 🔒
**Objective**: Safe, isolated code execution for high-risk operations

**Proposed Solutions:**
- **E2B Integration**: Deploy to E2B infrastructure for sandboxed Python execution
- **Docker Containerization**: Lightweight per-task containers
- **Resource Limits**: CPU, memory, disk quotas per execution
- **Network Isolation**: Controlled external access
- **Timeout Enforcement**: Automatic task termination

**Example Usage:**
```python
from repobrain_engine.sandbox.factory import get_sandbox

sandbox = get_sandbox()
result = sandbox.execute(
    code="import numpy; print(numpy.__version__)",
    timeout=30,
)
```

**Benefits:**
- ✅ Run untrusted or risky code safely
- ✅ Parallel task isolation
- ✅ Cost-efficient resource scaling
- ✅ Compliance with security policies

### Future Extension: Orchestrated Flows 🔀
**Objective**: Complex, structured task pipelines with DAG support

**Proposed Architecture:**
- **DAG Definition**: YAML or JSON task graphs
- **Conditional Execution**: Branch on results
- **Parallel Steps**: Execute independent tasks concurrently
- **Error Handling**: Retry, fallback, and compensation strategies
- **Monitoring**: Real-time execution tracking

**Example DAG:**
```yaml
# workflows/data_pipeline.yaml
name: daily_data_pipeline
steps:
  fetch_data:
    agent: DataCollector
    input: {"source": "api", "date": "today"}
  
  validate_data:
    agent: DataValidator
    depends_on: fetch_data
    input: "{fetch_data.output}"
  
  analyze_trends:
    agent: AnalysisEngine
    depends_on: validate_data
    parallel:
      - sentiment_analysis
      - correlation_analysis
  
  report_generation:
    agent: ReportWriter
    depends_on: [analyze_trends]
    input: "{analyze_trends.output}"
  
  notify_stakeholders:
    agent: NotificationService
    depends_on: report_generation
```

**Benefits:**
- 📊 Model complex business processes
- 🔄 Automatic retry and recovery
- 📈 Real-time monitoring and observability
- 🎯 Composable, reusable workflows

### Future Extension: Distributed Agent Fleet 🌍
**Objective**: Multi-agent coordination across regions

**Planned Features:**
- **Global Agent Registry**: Discover agents worldwide
- **Message Queue Integration**: Async agent communication (RabbitMQ, Kafka)
- **State Replication**: Distributed state management
- **Load Balancing**: Intelligent task distribution
- **Failover**: Automatic agent replacement

### Future Extension: Observability & Monitoring 📊
**Objective**: Production-grade observability beyond current status tracking

**Planned Components:**
- **Metrics**: Agent performance, tool usage, success rates
- **Traces**: Distributed tracing across agent calls
- **Logs**: Structured logging with correlation IDs
- **Alerts**: Anomaly detection and alerting
- **Dashboards**: Real-time agent health monitoring

### Future Extension: Enterprise Integrations 🔗
**Objective**: Out-of-the-box enterprise connectors

**Target Integrations:**
- 🏢 **HR Systems**: Workday, SuccessFactors
- 📊 **Analytics**: Tableau, Power BI connectors
- 💼 **CRM**: Salesforce, HubSpot
- 📧 **Communication**: Slack, Microsoft Teams
- 🗄️ **Databases**: PostgreSQL, MongoDB, data warehouses

## 🎯 How to Contribute

### For Ideas (No Code Required!)
The repository knowledge layer is still evolving. **Ideas are as valuable as code.**

Have thoughts on sandbox boundaries, retrieval evidence, MCP safety, or observability?
- **Open an Issue** with your proposal
- **Discuss tradeoffs** and feasibility
- **Get added as a contributor** for adoptable architectures!

### For Implementation
Ready to code? Pick a product-hardening component:

1. **Identify a component** (Sandbox, Retrieval, MCP, Observability)
2. **Propose architecture** (open an issue first!)
3. **Submit PR** with implementation
4. **Become a contributor!**

### Focus Areas for Contributors
- 🔒 Sandbox integration (Microsandbox, E2B)
- 🔎 Retrieval graph quality and redaction
- 📊 Observability stack
- 🔗 MCP server boundaries
- 📚 Documentation and install-contract drift checks

## ✅ Phase 10: Knowledge Hub ✅
**Goal**: Multi-agent project context system — automated conventions extraction and Q&A

**Completed:** March 2026

**Achievements:**
- Hub module (`engine/repobrain_engine/hub/`) with scanner, agents, refresh/ask pipelines
- `rb-refresh` — scans project and generates `.repobrain/conventions.md` via LLM
- `rb-ask` — answers project questions using reviewer agent
- `rb report` / `rb log-decision` — local memory and decision logging
- OpenAI Agent SDK integration with LiteLLM for model flexibility

## 📈 Development Timeline

- **2024 H2**: Foundation through MCP Integration (Phases 1–8) ✅
- **2025**: Enterprise Core (Phase 9) — sandbox MVP, safety docs, observability ✅
- **2026 Q1–Q2**: Knowledge Hub (Phase 10) — generation storage, structured evidence, multi-language adapters ✅
- **2026 Q3** (current): Host-runner backend, incremental refresh, agent-group architecture ✅
- **2026+**: Continued refinement and community-driven features

*(Development is community-driven and evolves based on real-world usage)*

## 💡 Product Use Cases

**Scenario 1: Faster Codebase Onboarding**
```
User: "How does authentication work here?"

RepoBrain:
├─ Reads map.md to select auth-related modules
├─ Pulls the relevant agent docs and source evidence
├─ Adds graph context when structural relationships matter
└─ Answers with concrete file paths and line references
```

**Scenario 2: Shared Knowledge Across IDEs**
```
Team:
├─ Runs rb-refresh after meaningful source changes
├─ Commits or shares the appropriate .repobrain/ artifacts
├─ Uses rb-ask, slash commands, or rb-mcp from different hosts
└─ Gets one consistent repository model instead of host-specific docs drift
```

## 🔮 The Vision

RepoBrain should make repository knowledge portable, grounded, and easy to
refresh. Advanced runtime features are useful only when they make that core
workflow safer or more accurate.

---

**Questions or ideas?** Open an issue on GitHub or [propose a contribution](https://github.com/study8677/repobrain/issues).

**Next:** [Full Index](README.md)

## 👥 Contributors

- [@devalexanderdaza](https://github.com/devalexanderdaza) — First contributor. Implemented demo tools, enhanced agent functionality, helped shape the early roadmap and completed MCP integration.
- [@Subham-KRLX](https://github.com/Subham-KRLX) — Added dynamic tools and context loading (Fixes #4) and the multi-agent cluster protocol (Fixes #6).
