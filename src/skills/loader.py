import importlib.util
import inspect
from pathlib import Path
from typing import Dict, Callable, Any, List

def load_skills(agent_tools: Dict[str, Callable[..., Any]]) -> str:
    """
    Scans src/skills/ directory for skill packages.
    
    For each subfolder in src/skills/:
    1. Looks for tools.py: Registers public functions as tools.
    2. Looks for SKILL.md: Reads documentation content.
    
    Args:
        agent_tools: The dictionary of tools to update with new skill-based tools.
        
    Returns:
        A combined string of all SKILL.md contents to be injected into context.
    """
    skills_dir = Path(__file__).parent
    skill_docs: List[str] = []
    
    if not skills_dir.exists():
        print(f"⚠️ Skills directory not found: {skills_dir}")
        return ""

    print(f"📦 Scanning for skills in {skills_dir}...")

    # Iterate over directories in src/skills/
    for skill_path in skills_dir.iterdir():
        if not skill_path.is_dir() or skill_path.name.startswith("_") or skill_path.name == "__pycache__":
            continue
            
        skill_name = skill_path.name
        print(f"   ► Found skill: {skill_name}")
        
        # 1. Load Tools (tools.py)
        tools_file = skill_path / "tools.py"
        if tools_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"src.skills.{skill_name}.tools", tools_file
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    count = 0
                    for name, obj in inspect.getmembers(module, inspect.isfunction):
                        if not name.startswith("_") and obj.__module__ == module.__name__:
                            agent_tools[name] = obj
                            count += 1
                    print(f"     ✓ Loaded {count} tools from tools.py")
            except Exception as e:
                print(f"     ❌ Failed to load tools: {e}")
        
        # 2. Load Documentation (SKILL.md)
        doc_file = skill_path / "SKILL.md"
        if doc_file.exists():
            try:
                content = doc_file.read_text(encoding="utf-8").strip()
                if content:
                    skill_docs.append(f"\n--- SKILL: {skill_name} ---\n{content}")
                    print(f"     ✓ Loaded documentation from SKILL.md")
            except Exception as e:
                print(f"     ❌ Failed to load docs: {e}")
                
    return "\n".join(skill_docs)
