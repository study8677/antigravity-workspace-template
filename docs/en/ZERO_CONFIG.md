# ⚡ Zero-Config Features

## 🎯 The Zero-Config Philosophy

**Stop writing boilerplate.** The RepoBrain Workspace automatically discovers and loads your tools and context without manual configuration.

## 🛠️ Auto Tool Discovery

Drop any Python file into `engine/repobrain_engine/tools/` and the agent will use it immediately—no imports, no registration, no boilerplate.

### How It Works

1. **Define Your Tool**:
```python
# engine/engine/repobrain_engine/tools/sentiment_analyzer.py
def analyze_sentiment(text: str) -> dict:
    """Analyzes the sentiment of given text.
    
    Args:
        text: The text to analyze
        
    Returns:
        A dictionary with sentiment score and label
    """
    # Your implementation
    if len(text) > 10:
        return {"score": 0.8, "label": "positive"}
    return {"score": 0.3, "label": "neutral"}
```

2. **Refresh the Knowledge Hub** (one-time):
```bash
rb-refresh --workspace .
```

3. **Use Immediately** in prompts:
```
"Analyze the sentiment of these customer reviews..."
```

The agent will automatically discover and use `analyze_sentiment()`.

### Tool Discovery Mechanics

The discovery process:
1. 🔍 Scans `engine/engine/repobrain_engine/tools/` for all `.py` files
2. 📋 Indexes all top-level functions
3. 📚 Extracts docstrings for help text
4. 🔗 Registers public module-level functions with the agent

### Tool Guidelines

**Function Signatures:**
```python
# ✅ Good - clear parameters and return type
def fetch_weather(city: str, unit: str = "celsius") -> dict:
    """Fetch weather data for a city."""
    pass

# ✅ Good - use type hints
def parse_json(data: str) -> dict:
    """Parse JSON string."""
    pass

# ❌ Avoid - ambiguous parameters
def process(x, y, z):
    pass

# ❌ Avoid - no docstring
def calculate_tax_rate(amount):
    pass
```

**Docstring Format:**
```python
def my_tool(param1: str, param2: int) -> str:
    """One-line summary of what the tool does.
    
    Longer description explaining behavior, edge cases,
    and important details for the agent.
    
    Args:
        param1: Description of param1
        param2: Description of param2
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When something is invalid
    """
```

### Multiple Files Example

```
engine/repobrain_engine/tools/
├── sentiment_analyzer.py
│   └── analyze_sentiment()
├── data_processor.py
│   ├── parse_csv()
│   ├── clean_data()
│   └── validate_schema()
└── api_client.py
    ├── fetch_api_data()
    └── post_request()
```

All 7 functions are automatically discovered and available to the agent!

## 🎓 Auto Skill Discovery

Drop a folder under `engine/repobrain_engine/skills/` with `SKILL.md` and optional `tools.py`, and the agent will load both:
- Skill docs from `SKILL.md` into prompt context
- Public functions from `tools.py` as callable tools

### Built-in Example: `agent-repo-init`

This repository includes:
- `engine/repobrain_engine/skills/agent-repo-init/`: in-agent skill integration (`init_agent_repo`)
- `skills/agent-repo-init/`: portable skill package with script runner

`agent-repo-init` supports:
- `quick` mode: clean scaffold
- `full` mode: scaffold + runtime profile defaults (`.env`, mission, context profile, init report)

Use it to create a clean project copy from this template without inheriting local runtime state (for example `.git`, caches, local virtual environments, and runtime memory files).

## 📚 Auto Context Loading

Add knowledge to `.context/` and it's automatically injected into every agent prompt—no configuration needed.

### How It Works

1. **Create Knowledge Files**:
```bash
# Create context directory
mkdir -p .context

# Add your knowledge
echo "# Project Coding Standards
- Use Google-style docstrings
- Type hint all functions
- 80-character line limit" > .context/coding_standards.md

echo "# API Documentation
## User Endpoint
GET /api/users - fetch all users
POST /api/users - create new user" > .context/api_docs.md
```

2. **Refresh the Knowledge Hub** (one-time):
```bash
rb-refresh --workspace .
```

3. **Automatic Injection**:
Every prompt to the agent now includes all `.context/` files automatically.

### Context Loading Mechanics

The loading process:
1. 🔍 Scans `.context/` directory
2. 📄 Reads top-level markdown files (`.md`) only
3. 🧠 Injects content into the prompt context
4. 🔄 Reloads context when the agent runs

### Organizing Context

**Recommended structure (current loader reads top-level `.md` only):**
```
.context/
├── README.md                 # Index
├── coding_standards.md       # Code style guide
├── security_policies.md      # Security requirements
├── architecture.md           # System design
└── database_schema.md        # DB structure
```

### Context Index File

Create `.context/README.md` as a guide:

```markdown
# Knowledge Base Index

This directory contains all context automatically injected into the agent.

## 📋 Organization

### Standards
- [Coding Standards](coding_standards.md)
- [Security Policies](security_policies.md)

### Project Information
- [Architecture](architecture.md)
- [Database Schema](database_schema.md)
```

## 🔗 How Tools + Context Work Together

**Scenario**: Building a data analysis tool

### Step 1: Add Context (What the agent should know)
```bash
# .context/database_schema.md
## Users Table
- id (int): Primary key
- email (string): User email
- created_at (timestamp): Account creation date
```

### Step 2: Add Tools (What the agent can do)
```python
# engine/repobrain_engine/tools/db_query.py
def query_users(email_pattern: str) -> list:
    """Query users by email pattern."""
    # Implementation
    return results
```

### Step 3: Use Naturally
```
"Find all users created in the last month with emails matching 'admin'"
```

The agent:
- 🧠 **Knows** the database schema (from context)
- 🛠️ **Can** query the database (from tools)
- ✅ **Does** exactly what you need

## 🎓 Best Practices

### For Tool Discovery
- 📝 Always include docstrings
- 🏷️ Use type hints for clarity
- 🎯 One function per responsibility
- ❌ Avoid wildcard imports in tool files

### For Context Loading
- 📚 Keep context files focused (max 100 lines)
- 🏗️ Keep important context files at `.context/` top-level
- 🔄 Update context when standards change
- 🔍 Make file names self-documenting

### Performance Tips
- ⚡ Limit total context to ~50KB
- 🧹 Archive old context files
- 🔑 Use context for stable, reference information
- 📦 Use tools for dynamic operations

## 🔄 Hot Reload

Tools are discovered at agent startup, so after changing `engine/repobrain_engine/tools/` you should restart the agent.
Context files are loaded from `.context/*.md` on agent run.

## 🐛 Troubleshooting

### Tools not appearing
```bash
# 1. Check file is in engine/repobrain_engine/tools/
ls -la engine/repobrain_engine/tools/

# 2. Verify it's valid Python
python -m py_compile engine/repobrain_engine/tools/my_tool.py

# 3. Check for syntax errors
python -c "import repobrain_engine.tools.my_tool"

# 4. Refresh the knowledge hub
rb-refresh --workspace .
```

### Context not loading
```bash
# 1. Check context directory exists
ls -la .context/

# 2. Verify files are readable
cat .context/your_file.md

# 3. Check file size (should be < 100KB)
du -sh .context/

# 4. Refresh the knowledge hub
rb-refresh --workspace .
```

### Agent performance issues
```bash
# Check total context size
du -sh .context/

# Remove large or outdated files
rm .context/old_documentation.md

# Refresh the knowledge hub
rb-refresh --workspace .
```

## 📚 Examples

### Example 1: Custom Tool + Context
```bash
# Add context about user requirements
echo "Users must be at least 18 years old" > .context/age_requirement.md

# Add tool to validate age
cat > engine/repobrain_engine/tools/age_validator.py << 'EOF'
def validate_age(birth_date: str) -> bool:
    """Check if person is at least 18 years old."""
    # Implementation
    return age >= 18
EOF

# Agent now knows the requirement AND can validate it!
```

### Example 2: API Documentation
```bash
# Document your API
cat > .context/api_reference.md << 'EOF'
# API Reference
## POST /users
Creates a new user
- email (required): string
- name (required): string
- age (optional): number
EOF

# Tool to create users
cat > engine/repobrain_engine/tools/user_service.py << 'EOF'
def create_user(email: str, name: str, age: int = None) -> dict:
    """Create a new user in the system."""
    # Validates per context requirements automatically
    pass
EOF
```

## 🚀 Advanced Features

- **Context Versioning**: Use git to track context changes
- **Conditional Context**: Load context based on task type
- **Dynamic Tools**: Generate tools from schemas
- **Tool Composition**: Combine tools for complex workflows

---

**Next:** [Development Roadmap](ROADMAP.md) | [Full Index](README.md)
