<div align="center">

<img src="docs/assets/logo.svg" alt="RepoBrain" width="200"/>

# RepoBrain

### Motor de conocimiento de repositorios, portable entre IDEs, para Q&A de codebases con evidencia.

<sub>Anteriormente conocido como <b>Antigravity Workspace Template</b> — el mismo proyecto, nuevo nombre.</sub>

`rb-refresh` construye la capa de conocimiento portable; `rb-ask` enruta preguntas
al contexto de módulo correcto y responde con evidencia de código. Plugins, CLI y
MCP son canales de entrega alrededor de ese flujo.

Idioma: [English](README.md) | [中文](README_CN.md) | **Español**

[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/study8677/repobrain/test.yml?style=for-the-badge&label=CI)](https://github.com/study8677/repobrain/actions)
[![DeepWiki](https://img.shields.io/badge/DeepWiki-Docs-blue?style=for-the-badge&logo=gitbook&logoColor=white)](https://deepwiki.com/study8677/repobrain)
[![NLPM](https://img.shields.io/badge/NLPM-audited-7C3AED?style=for-the-badge)](https://github.com/xiaolai/nlpm-for-claude)

<br/>

<img src="https://img.shields.io/badge/Cursor-✓-000000?style=flat-square" alt="Cursor"/>
<img src="https://img.shields.io/badge/Claude_Code-✓-D97757?style=flat-square" alt="Claude Code"/>
<img src="https://img.shields.io/badge/Windsurf-✓-06B6D4?style=flat-square" alt="Windsurf"/>
<img src="https://img.shields.io/badge/Gemini_CLI-✓-4285F4?style=flat-square" alt="Gemini CLI"/>
<img src="https://img.shields.io/badge/VS_Code_+_Copilot-✓-007ACC?style=flat-square" alt="VS Code"/>
<img src="https://img.shields.io/badge/Codex-✓-412991?style=flat-square" alt="Codex"/>
<img src="https://img.shields.io/badge/Cline-✓-FF6B6B?style=flat-square" alt="Cline"/>
<img src="https://img.shields.io/badge/Aider-✓-8B5CF6?style=flat-square" alt="Aider"/>

<br/><br/>

<img src="docs/assets/demo.gif" alt="Demo de rb-ask — respuestas fundamentadas con rutas de archivo y números de línea" width="800"/>

</div>

<br/>

<div align="center">
<img src="docs/assets/before_after.svg" alt="Before vs After RepoBrain" width="800"/>
</div>

<br/>

## ¿Por qué RepoBrain?

> El techo de capacidad de un AI Agent = **la calidad del contexto que puede leer.**

El motor es el núcleo: `rb-refresh` despliega un clúster multi-agente que lee tu código autónomamente — cada módulo obtiene su propio Agent que genera documentación de conocimiento. `rb-ask` enruta preguntas al Agent correcto, con respuestas basadas en código real con rutas de archivo y números de línea.

**En vez de darle a Claude Code / Codex un `grep` del repositorio para que busque por su cuenta, dale un ChatGPT para tu repositorio.**

**Comparado de tú a tú con Codex CLI y Claude Code en 36 preguntas sobre 3 bases de código Python reales (`fastapi`, `requests`, `sqlmodel`) — RepoBrain 99% en búsquedas factuales, 97% en auditoría/seguridad, 2.1× más rápido que Codex en factuales.** [Ver comparativa abajo.](#comparativa-directa-repobrain-vs-codex-cli-vs-claude-code-2026-05-09)

```
Enfoque tradicional:                    Enfoque RepoBrain:
  CLAUDE.md = 5000 líneas de docs         Claude Code llama ask_project("¿cómo funciona auth?")
  El agente lee todo, olvida la mitad     Router → ModuleAgent lee código real, devuelve respuesta exacta
  La tasa de alucinación sigue alta       Fundamentado en código real, rutas de archivo y git
```

| Problema | Sin RepoBrain | Con RepoBrain |
|:---------|:---------------|:----------------|
| El agente olvida el estilo de código | Repites las mismas correcciones | Lee `.repobrain/conventions.md` — lo hace bien a la primera |
| Incorporar un codebase nuevo | El agente adivina la arquitectura | `rb-refresh` → ModuleAgents aprenden cada módulo |
| Cambiar entre IDEs | Reglas diferentes en cada uno | Una carpeta `.repobrain/` — todos los IDEs la comparten |
| Preguntar "¿cómo funciona X?" | El agente lee archivos al azar | `ask_project` MCP → Router enruta al ModuleAgent responsable |

La arquitectura son **archivos + un motor Q&A en vivo**, no plugins. Portable entre cualquier IDE, cualquier LLM, cero lock-in.

---

## Comandos Slash

Los mismos cuatro comandos slash funcionan tanto en **Claude Code** como en **Codex CLI**. Claude los expone con el espacio de nombres `/repobrain:<nombre>`; Codex auto-descubre el directorio `commands/` y los presenta sin prefijo, como `/<nombre>`. Mismo flujo en ambos hosts — sin reaprender.

| Claude Code | Codex CLI | Propósito |
|---|---|---|
| `/repobrain:rb-setup` | `/rb-setup` | Configuración inicial — elige proveedor LLM, escribe `.env` |
| `/repobrain:rb-refresh [quick]` | `/rb-refresh [quick]` | Crea una base completa o actualiza manualmente solo los grupos Agent afectados |
| `/repobrain:rb-ask <pregunta>` | `/rb-ask <pregunta>` | Q&A enrutada sobre el código actual |
| `/repobrain:rb-init <nombre>` | `/rb-init <nombre>` | Crea un nuevo repo multi-agente desde esta plantilla |

Sesión típica inicial: **rb-setup → rb-refresh → rb-ask**. Detalles abajo.

### `rb-setup` — configuración inicial

Ejecútalo **una vez por proyecto**, justo después de instalar el plugin. Selector interactivo del proveedor LLM (OpenAI / DeepSeek / Groq / 阿里灵积 / NVIDIA NIM / Ollama local / cualquier endpoint OpenAI-compatible), luego escribe `.env` en la raíz del proyecto con `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `RB_ASK_TIMEOUT_SECONDS`. También asegura que `.env` esté en `.gitignore`. Sáltatelo si ya tienes un `.env` funcional.

```
# Claude Code
/repobrain:rb-setup

# Codex CLI
/rb-setup
```

### `rb-refresh` — construir / refrescar la base de conocimiento

El primer refresh debe ser completo para crear una generación base. Después,
`quick` compara solo commits, exige un worktree limpio y usa ImpactPlanner más
un Verifier independiente para ejecutar únicamente los grupos Agent afectados.
Nunca cambia automáticamente a refresh completo. `failed-only` reanuda los
grupos fallidos o pendientes del mismo commit. `rb-ask` solo avisa de commits
nuevos y nunca actualiza la base automáticamente.

```
# Claude Code
/repobrain:rb-refresh
/repobrain:rb-refresh quick

# Codex CLI
/rb-refresh
/rb-refresh quick
```

Tiempo: pocos minutos en repos pequeños, más en repos grandes. Requiere `rb-setup` ya completado.

### `rb-ask` — Q&A enrutada sobre el código

**La razón principal por la que existe este plugin**. Enruta tu pregunta al ModuleAgent adecuado (y a GitAgent cuando aplica), y devuelve una respuesta fundamentada en el código real, con rutas de archivo y números de línea. Úsalo **antes** de hacer grep manual o leer archivos — es más rápido y más preciso. Buenas formas de pregunta: "¿dónde se define/maneja X?", "¿por qué se hizo Y de esta forma?", "¿cómo funciona el flujo de auth?", "¿qué depende del módulo Z?".

```
# Claude Code
/repobrain:rb-ask "¿Cómo funciona la autenticación?"

# Codex CLI
/rb-ask "¿Cómo funciona la autenticación?"
```

Requiere una base de conocimiento — si ves "sin índice" o respuestas vacías, ejecuta `rb-refresh` primero.

### `rb-init` — andamiar un nuevo repo multi-agente

Crea un **nuevo** proyecto desde la plantilla RepoBrain. Dos modos: `quick` (andamio rápido, copia limpia) y `full` (añade runtime profile, `.env`, archivo de misión, config de sandbox, `git init` opcional). Es para **empezar un repo nuevo** — **no** lo necesitas antes de `rb-refresh` en un proyecto existente.

```
# Claude Code
/repobrain:rb-init my-agent
/repobrain:rb-init my-agent full

# Codex CLI
/rb-init my-agent
/rb-init my-agent full
```

> El plugin también incluye el skill `agent-repo-init` (es el backend que `rb-init` invoca — Codex / Claude también lo emparejan por descripción) y el servidor MCP opcional `rb-mcp` (`ask_project` + `refresh_project`) para integración tipo herramienta.

---

## Inicio Rápido

**Opción A — Instalación de una línea como plugin de Claude Code / Codex CLI (recomendado)**
```bash
# Claude Code (auto-instala juntos el CLI rb y el motor Python vía SessionStart)
/plugin marketplace add study8677/repobrain
/plugin install repobrain@repobrain
/repobrain:rb-setup            # interactivo: elige proveedor LLM, pega API key, escribe .env
/repobrain:rb-refresh          # el primer refresh crea .repobrain/ automáticamente
/repobrain:rb-ask "¿Cómo funciona este proyecto?"

# Codex CLI (instala el motor manualmente primero; los hooks de Codex aún no son soportados)
pipx install "git+https://github.com/study8677/repobrain.git#subdirectory=engine"
pipx inject --force --include-apps repobrain-engine "git+https://github.com/study8677/repobrain.git#subdirectory=cli"
codex plugin marketplace add study8677/repobrain
/rb-setup                        # mismos comandos en Codex, sin el prefijo repobrain:
/rb-refresh
/rb-ask "¿Cómo funciona este proyecto?"
```

Codex CLI auto-descubre los comandos slash desde el directorio `commands/` del plugin, así que los mismos cuatro comandos están disponibles sin el prefijo `repobrain:` (`/rb-setup`, `/rb-refresh`, `/rb-ask`, `/rb-init`). También puedes seguir usando el CLI directo (`rb-refresh --workspace .`, `rb-ask "..." --workspace .`) y diagnosticar la instalación con `rb doctor --workspace .`.

Si la sesión actual de Claude Code dice que la herramienta MCP de RepoBrain no está conectada, reinicia Claude Code una vez y vuelve a ejecutar `/repobrain:rb-refresh`. Es un problema de carga de sesión, no de API key. Consulta [troubleshooting](docs/en/TROUBLESHOOTING.md).

Después de instalar y configurar dispondrás de los comandos slash `rb-ask <pregunta>`, `rb-refresh`, `rb-init <nombre>` en ambos hosts, y del servidor MCP `repobrain` (`ask_project` + `refresh_project`). Ver [INSTALL.md](INSTALL.md) para detalles de instalación y troubleshooting.

**Opción B — Instalación manual: motor + CLI vía pip**
```bash
# 1. Instalar motor + CLI
pip install "git+https://github.com/study8677/repobrain.git#subdirectory=cli"
pip install "git+https://github.com/study8677/repobrain.git#subdirectory=engine"

# 2. Configurar .env (cualquier API compatible con OpenAI)
cd mi-proyecto
cat > .env <<EOF
OPENAI_BASE_URL=https://tu-endpoint/v1
OPENAI_API_KEY=tu-key
OPENAI_MODEL=tu-modelo
RB_ASK_TIMEOUT_SECONDS=120
EOF

# 3. Construir base de conocimiento (ModuleAgents aprenden cada módulo)
rb-refresh --workspace .

# 4. Preguntar
rb-ask "¿Cómo funciona la autenticación en este proyecto?"

# 5. (Opcional) Registrar como servidor MCP para Claude Code
claude mcp add repobrain rb-mcp -- --workspace $(pwd)
```

**Opción C — Solo archivos de contexto (cualquier IDE, sin LLM)**
```bash
pip install git+https://github.com/study8677/repobrain.git#subdirectory=cli
rb init mi-proyecto && cd mi-proyecto
# Los archivos de entrada del IDE hacen bootstrap hacia AGENTS.md; el contexto dinámico vive en .repobrain/
```

---

## Características de un Vistazo

```
  rb init             Inyectar archivos de contexto (--force para sobrescribir)
       │
       ▼
  .repobrain/       Base de conocimiento compartida — cada IDE lee de aquí
       │
       ├──► rb-refresh     Aprendizaje multi-agente dinámico → docs de conocimiento + mapa estructural
       ├──► rb-ask         Router → ModuleAgent Q&A con evidencia de código en vivo
       └──► rb-mcp         Servidor MCP → Claude Code llama directamente
```

**Clúster Multi-Agente Dinámico** — Durante `rb-refresh`, el motor usa **agrupación funcional inteligente**: archivos agrupados por relaciones de import, co-ubicación en directorios y prefijos de nombre. El código fuente se pre-carga directamente en el contexto del agente (sin tool calls), y los artefactos de build se filtran automáticamente. Cada sub-agente analiza ~30K tokens de código enfocado en 1 llamada LLM y produce un **documento de conocimiento Markdown completo** (`agents/*.md`). Módulos grandes generan múltiples agent docs en paralelo (uno por grupo, sin fusión ni pérdida de información). Un **Map Agent** lee todos los docs y genera `map.md` — un índice de enrutamiento. Durante `rb-ask`, Router lee `map.md` para seleccionar módulos relevantes, luego alimenta sus agent docs a los agentes de respuesta. **Completamente agnóstico al lenguaje** — detección de módulos por estructura de directorios pura, análisis de código realizado íntegramente por LLMs. Funciona con cualquier lenguaje de programación.

**GitAgent** — Un agente dedicado a analizar el historial git — entiende quién cambió qué y por qué.

**Feedback de auditoría NLPM** — Este repositorio se ha beneficiado de [NLPM](https://github.com/xiaolai/nlpm-for-claude), un linter de programación en lenguaje natural para plugins de Claude Code, skills y definiciones de agentes creado por [xiaolai](https://github.com/xiaolai). Su auditoría ayudó a encontrar mejoras útiles en frontmatter de skills e higiene de dependencias.

---

## Comandos CLI

| Comando | Qué hace | ¿Necesita LLM? |
|:--------|:---------|:---------------:|
| `rb init <dir>` | Inyectar plantillas de arquitectura cognitiva | No |
| `rb init <dir> --force` | Re-inyectar, sobrescribiendo archivos existentes | No |
| `rb refresh --workspace <dir>` | Wrapper CLI conveniente para el pipeline de refresh del knowledge hub | Sí |
| `rb ask "pregunta" --workspace <dir>` | Wrapper CLI conveniente para el flujo Q&A enrutado del proyecto | Sí |
| `rb-refresh` | Aprendizaje multi-agente del codebase, genera docs de conocimiento + `conventions.md` + `structure.md` | Sí |
| `rb-ask "pregunta"` | Router → ModuleAgent/GitAgent Q&A enrutado | Sí |
| `rb-mcp --workspace <dir>` | **Iniciar servidor MCP** — expone `ask_project` + `refresh_project` a Claude Code | Sí |
| `rb report "mensaje"` | Registrar un hallazgo en `.repobrain/memory/` | No |
| `rb log-decision "qué" "por qué"` | Registrar una decisión arquitectónica | No |

`rb ask` / `rb refresh` están disponibles cuando `cli/` y `engine/` están instalados. `rb-ask` / `rb-refresh` son los entrypoints disponibles con solo el engine.

---

## Dos Paquetes, Un Flujo de Trabajo

```
repobrain/
├── cli/                     # rb CLI — ligero, instalable con pip
│   └── templates/           # .cursorrules, CLAUDE.md, .repobrain/, ...
└── engine/                  # Motor multi-agente + Knowledge Hub
    └── repobrain_engine/
        ├── _cli_entry.py    # rb-ask / rb-refresh puntos de entrada
        ├── config.py        # Configuración Pydantic
        ├── hub/             # ★ Núcleo: clúster multi-agente
        │   ├── agents.py    #   Refresh/Ask Swarm agents (ScanAnalyst/ArchitectureReviewer/ConventionWriter + ContextCurator/DeepAnalyst/AnswerSynthesizer)
        │   ├── contracts.py #   Modelos Pydantic: claims, evidencia, estado de refresh
        │   ├── ask_pipeline.py    # facts estructurados + swarm legacy
        │   ├── refresh_pipeline.py # orquestación de refresh basado en evidencia
        │   ├── ask_tools.py #   Exploración de código
        │   ├── scanner.py   #   Escaneo multi-lenguaje de proyecto
        │   ├── module_grouping.py # agrupación funcional inteligente
        │   ├── incremental.py #   committed-diff / --quick agent-group refresh
        │   ├── host_runner.py #   local CLI backend, no API key
        │   ├── storage.py   #   generation dirs + current.json
        │   ├── mcp_server.py#   Servidor MCP (rb-mcp)
        │   └── language_adapters/ # adaptadores específicos de lenguaje
        ├── mcp_client.py    # Consumidor MCP (conecta herramientas externas)
        ├── memory.py        # Memoria de interacción persistente
        ├── tools/           # Herramientas MCP + extensiones
        ├── skills/          # Cargador de habilidades
        └── sandbox/         # Ejecución de código (local / microsandbox)
```

**CLI** (`pip install .../cli`) — Cero deps de LLM. Inyecta plantillas, registra reportes y decisiones offline.

**Engine** (`pip install .../engine`) — Runtime de conocimiento del repositorio. Alimenta `rb-ask`, `rb-refresh`, `rb-mcp`. Usa el endpoint OpenAI-compatible escrito por `rb-setup` (OpenAI, DeepSeek, Groq, DashScope, NVIDIA NIM, Ollama o personalizado).

**Nuevas actualizaciones de empaquetado de skills:**
- `engine/repobrain_engine/skills/graph-retrieval/` — herramientas de recuperación orientadas a grafo para razonamiento de estructura y rutas de llamadas.
- `engine/repobrain_engine/skills/knowledge-layer/` — herramientas de capa de conocimiento para consolidación de contexto semántico del proyecto.

```bash
# Instalar ambos para la experiencia completa
pip install "git+https://...#subdirectory=cli"
pip install "git+https://...#subdirectory=engine"
```

---

## Cómo Funciona

### 1. `rb init` — Inyectar archivos de contexto

```bash
rb init mi-proyecto
# ¿Ya inicializado? Usa --force para sobrescribir:
rb init mi-proyecto --force
```

Crea `AGENTS.md` (reglas de comportamiento autoritativas), archivos bootstrap de IDE (`.cursorrules`, `CLAUDE.md`, `.windsurfrules`, `.clinerules`, `.github/copilot-instructions.md`) y archivos de contexto dinámico en `.repobrain/`.

### 2. `rb-refresh` — Aprendizaje multi-agente

```bash
rb-refresh --workspace mi-proyecto
```

**Pipeline de 8 pasos:**
1. Escanear codebase (lenguajes, frameworks, estructura)
2. Pipeline multi-agente genera `conventions.md`
3. Generar `structure.md` — árbol de archivos agnóstico al lenguaje con conteos de líneas
4. Construir grafo de conocimiento (`knowledge_graph.json` + mermaid)
5. Escribir índices de documentos/datos/media
6. **Análisis completo por LLM** — archivos agrupados por grafo de imports + directorio + prefijo, pre-cargados en contexto (~30K tokens por sub-agente), artefactos de build filtrados automáticamente. Cada sub-agente lee el código fuente completo y produce un **documento de conocimiento Markdown completo** (`agents/*.md`). Módulos grandes generan múltiples agent docs (uno por grupo, sin fusión). Control global de concurrencia API previene rate-limiting. **Completamente agnóstico al lenguaje** — funciona con cualquier lenguaje de programación.
7. **RefreshGitAgent** analiza historial git, genera `_git_insights.md`
8. **Map Agent** lee todos los agent docs → genera `map.md` (índice de enrutamiento de módulos con descripciones y temas clave)

### 3. `rb-ask` — Q&A basado en Router

```bash
rb-ask "¿Cómo funciona la autenticación en este proyecto?"
```

El pipeline de ask usa una **vía semántica**: Router lee `map.md` → selecciona módulos → lee `agents/*.md` → LLM responde con referencias al código. Múltiples agent docs se leen en paralelo, luego un Synthesizer combina las respuestas.

Si los agent docs aún no se han generado, recurre al swarm legacy Router → ModuleAgent/GitAgent.

---

## Compatibilidad de IDEs

La arquitectura está codificada en **archivos** — cualquier agente que lea archivos del proyecto se beneficia:

| IDE | Archivo de configuración |
|:----|:------------------------|
| Cursor | `.cursorrules` |
| Claude Code | `CLAUDE.md` |
| Windsurf | `.windsurfrules` |
| VS Code + Copilot | `.github/copilot-instructions.md` |
| Gemini CLI / Codex / DeepSeek Harness | `AGENTS.md` |
| Cline | `.clinerules` |
| Google Antigravity | `.repobrain/rules.md` |

Todo se genera con `rb init`: `AGENTS.md` es el único rulebook de comportamiento, los archivos específicos por IDE son bootstraps ligeros, y `.repobrain/` guarda el contexto dinámico compartido del proyecto.

---

## Funciones Avanzadas

<details>
<summary><b>Servidor MCP — Dale a Claude Code un ChatGPT para tu codebase</b></summary>

Claude Code no necesita leer cientos de archivos de documentación — puede llamar `ask_project` como herramienta en vivo, respaldada por un clúster multi-agente dinámico: Router enruta preguntas al ModuleAgent correcto, devuelve respuestas precisas con rutas de archivo y números de línea.

**Configuración:**

```bash
# Instalar motor
pip install "git+https://github.com/study8677/repobrain.git#subdirectory=engine"

# Refrescar base de conocimiento primero (ModuleAgents aprenden cada módulo)
rb-refresh --workspace /ruta/al/proyecto

# Registrar como servidor MCP en Claude Code
claude mcp add repobrain rb-mcp -- --workspace /ruta/al/proyecto
```

**Herramientas expuestas a Claude Code:**

| Herramienta | Qué hace |
|:------------|:---------|
| `ask_project(pregunta)` | Router → ModuleAgent/GitAgent responde preguntas del codebase. Devuelve rutas + números de línea. |
| `refresh_project(quick?)` | Reconstruir base de conocimiento. ModuleAgents re-aprenden el código. |

</details>

<details>
<summary><b>Clúster Multi-Agente Dinámico</b> — Aprendizaje por módulo + enrutamiento inteligente</summary>

El núcleo del motor es **un clúster de Agents creado dinámicamente por módulo de código**:

```
 rb-refresh:                                 rb-ask:

 Para cada módulo:                           Router (lee map.md)
 ┌ Agrupar archivos por grafo de imports       └── leer agents/*.md → respuesta LLM
 ├ Pre-cargar ~30K tokens por sub-agente
 ├ Filtrar artefactos de build
 ├ Sub-agentes → documentos Markdown agent
 ├ agents/{module}.md (o /group_N.md)
 └ Map Agent → map.md
```

**Innovaciones clave:**
- **LLM como analizador**: Sin AST ni regex — el código fuente se alimenta directamente al LLM. Funciona con cualquier lenguaje de programación de forma inmediata.
- **Agrupación inteligente**: Archivos agrupados por relaciones de import, co-ubicación en directorios y prefijos de nombre. Artefactos de build filtrados automáticamente. Límite duro de caracteres (800K) previene desbordamiento de contexto.
- **Sin pérdida de información**: Módulos grandes producen múltiples `agent.md` (uno por grupo) — sin fusión ni compresión. Durante `rb-ask`, múltiples agent docs son leídos por LLMs en paralelo, luego un Synthesizer combina las respuestas.
- **Control global de concurrencia API**: `RB_API_CONCURRENCY` limita las llamadas LLM simultáneas entre todos los módulos, previniendo rate-limiting.
- **Detección de módulos agnóstica al lenguaje**: Estructura de directorios pura — sin `__init__.py` ni marcadores específicos de lenguaje.

```bash
# ModuleAgents aprenden tu codebase
rb-refresh

# Solo escanear archivos cambiados desde el último refresh
rb-refresh --quick

# Router enruta inteligentemente al ModuleAgent correcto
rb-ask "¿Qué patrones de testing usa este proyecto?"

# Registrar hallazgos y decisiones (sin LLM)
rb report "El módulo de auth necesita refactoring"
rb log-decision "Usar PostgreSQL" "El equipo tiene experiencia profunda"
```

Funciona con el endpoint OpenAI-compatible seleccionado por `rb-setup`. Basado en OpenAI Agent SDK + LiteLLM.
</details>

<details>
<summary><b>Integración MCP (Consumidor)</b> — Permitir a los agentes llamar herramientas externas</summary>

`MCPClientManager` permite a tus agentes conectarse a servidores MCP externos (GitHub, bases de datos, etc.), descubriendo y registrando herramientas automáticamente.

```json
// mcp_servers.json
{
  "servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "enabled": true
    }
  ]
}
```

Configura `MCP_ENABLED=true` para hacer visibles los servidores y
`RB_ALLOW_MCP=true` solo cuando quieras que `rb-ask` conecte servidores externos
automáticamente. Los servidores MCP por stdio heredan el entorno del proceso y
los valores `env` configurados, así que trátalos como código con permisos
locales.
</details>

<details>
<summary><b>Sandbox</b> — Entorno de ejecución de código configurable</summary>

| Variable | Default | Opciones |
|:---------|:--------|:---------|
| `SANDBOX_TYPE` | `local` | `local` · `microsandbox` |
| `SANDBOX_TIMEOUT_SEC` | `30` | segundos |
| `RB_RETRIEVAL_MODE` | `compact` | `off` · `compact` · `full` |

El sandbox por defecto es para workspaces locales confiables, no para aislar
código no confiable. El retrieval graph redacta secretos comunes antes de
escribir a disco, pero `full` aún puede conservar fragmentos de código. Ver
[docs Sandbox](docs/es/SANDBOX.md).
</details>

---

## Comparativa directa: RepoBrain vs Codex CLI vs Claude Code (2026-05-09)

Benchmark asimétrico sobre tres bases de código Python reales — `fastapi/fastapi`,
`psf/requests`, `fastapi/sqlmodel` — preguntando a cada herramienta **las mismas
36 preguntas** en tres bandas de dificultad. Las tres usaron `gpt-5.5` con alto
nivel de razonamiento; Codex y Claude tuvieron acceso de lectura al workspace.
Codex actuó como evaluador (rúbrica de 4 ejes, 0-3 cada uno; todas las
afirmaciones verificadas contra el código fuente real).

| Tipo de pregunta | RepoBrain | Codex CLI | Claude Code |
|:---|:---:|:---:|:---:|
| 15 búsquedas factuales | **179/180 (99%)** | 179/180 (99%) | 178/180 (99%) |
| 12 síntesis (tour del proyecto / arquitectura) | 116/144 (81%) | **144/144 (100%)** | 136/144 (94%) |
| 9 auditoría / seguridad | **105/108 (97%)** | 104/108 (96%) | 98/108 (91%) |

**Factuales + auditoría combinadas (24 celdas): RepoBrain 284/288, Codex
283/288, Claude 276/288.** RepoBrain supera ligeramente a ambas — y es más
rápido que Codex en cada pregunta individual.

**Latencia** (segundos por pregunta de promedio, mismo proxy):

| Tipo de pregunta | RepoBrain | Codex | Claude |
|:---|:---:|:---:|:---:|
| Factual | **56s** | 119s | 42s |
| Auditoría | 160s | 177s | **100s** |

RepoBrain es **2.1× más rápido que Codex en factuales** y empata con Codex en
auditoría, manteniendo o superando su precisión. Claude es el más rápido en
auditoría pero pierde 7 puntos de precisión.

**Dos arreglos del motor que produjeron el cambio** (commits en esta rama):

1. `_ask_with_agent_md` ahora inyecta los documentos a nivel de proyecto
   (`conventions.md`, `module_registry.md`, `map.md`, `structure.md`) en sus
   prompts de respuesta — elimina los rechazos del tipo "module knowledge does
   not include project-wide conventions".
2. Los agentes de respuesta del path structured-facts ahora reciben
   `search_code`, `read_file`, `list_directory`, `read_file_metadata`,
   `search_by_type` enlazados en runtime — el LLM puede ahora hacer grep y
   leer el código real en lugar de parafrasear el KG.

Reporte completo (datos, metodología, tablas por celda, advertencias):
[`artifacts/benchmark-2026-05-09/REPORT.md`](artifacts/benchmark-2026-05-09/REPORT.md).

---

## Documentación

| | |
|:--|:--|
| 🇬🇧 English | **[`docs/en/`](docs/en/)** |
| 🇨🇳 中文 | **[`docs/zh/`](docs/zh/)** |
| 🇪🇸 Español | **[`docs/es/`](docs/es/)** |

---

## Contribuyendo

¡Las ideas también son contribuciones! Abre un [issue](https://github.com/study8677/repobrain/issues) para reportar bugs, sugerir funcionalidades o proponer arquitectura.

## Contribuidores

<table>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/Lling0000">
        <img src="https://github.com/Lling0000.png" width="80" /><br/>
        <b>⭐ Lling0000</b>
      </a><br/>
      <sub><b>Contribuidor Principal</b> · Sugerencias creativas · Administrador del proyecto · Ideación y feedback</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/devalexanderdaza">
        <img src="https://github.com/devalexanderdaza.png" width="80" /><br/>
        <b>Alexander Daza</b>
      </a><br/>
      <sub>Sandbox MVP · Workflows OpenSpec · Docs de análisis técnico · PHILOSOPHY</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/chenyi">
        <img src="https://github.com/chenyi.png" width="80" /><br/>
        <b>Chen Yi</b>
      </a><br/>
      <sub>Primer prototipo CLI · Refactor de 753 líneas · Extracción DummyClient · Docs quick-start</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/Subham-KRLX">
        <img src="https://github.com/Subham-KRLX.png" width="80" /><br/>
        <b>Subham Sangwan</b>
      </a><br/>
      <sub>Carga dinámica de herramientas (#4) · Protocolo swarm multi-agente (#3)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/shuofengzhang">
        <img src="https://github.com/shuofengzhang.png" width="80" /><br/>
        <b>shuofengzhang</b>
      </a><br/>
      <sub>Fix ventana de contexto de memoria · Manejo graceful de cierre MCP (#28)</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/goodmorning10">
        <img src="https://github.com/goodmorning10.png" width="80" /><br/>
        <b>goodmorning10</b>
      </a><br/>
      <sub>Mejora de carga de contexto en <code>rb ask</code> — añadió CONTEXT.md, AGENTS.md y memory/*.md como fuentes de contexto (#29)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/BBear0115">
        <img src="https://github.com/BBear0115.png" width="80" /><br/>
        <b>BBear0115</b>
      </a><br/>
      <sub>Empaquetado de skills y mejoras de recuperación KG · Sincronización README multilingüe (#30)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/SunkenCost">
        <img src="https://github.com/SunkenCost.png" width="80" /><br/>
        <b>SunkenCost</b>
      </a><br/>
      <sub>Comando <code>rb clean</code> · Protección de entrada <code>__main__</code> (#37)</sub>
    </td>
    <td align="center" width="20%">
      <a href="https://github.com/aravindhbalaji04">
        <img src="https://github.com/aravindhbalaji04.png" width="80" /><br/>
        <b>Aravindh Balaji</b>
      </a><br/>
      <sub>Superficie de instrucciones unificada en torno a <code>AGENTS.md</code> (#41)</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="20%">
      <a href="https://github.com/xiaolai">
        <img src="https://github.com/xiaolai.png" width="80" /><br/>
        <b>xiaolai</b>
      </a><br/>
      <sub>Feedback de auditoría <a href="https://github.com/xiaolai/nlpm-for-claude">NLPM</a> · Fixes de frontmatter de skills · Revisión de higiene de dependencias (#51, #52, #53)</sub>
    </td>
  </tr>
</table>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=study8677/repobrain&type=Date)](https://star-history.com/#study8677/repobrain&Date)

## Licencia

Licencia MIT. Ver [LICENSE](LICENSE) para detalles.

---

<div align="center">

**[📚 Documentación completa →](docs/es/)**

*Construido para la era del desarrollo AI-nativo*

Enlace amigo: [LINUX DO](https://linux.do/)

</div>
