# ⚡ Características Zero-Config

## 🎯 La Filosofía Zero-Config

**Detén la escritura de boilerplate.** El RepoBrain Workspace automáticamente descubre y carga tus herramientas y contexto sin configuración manual.

## 🛠️ Descubrimiento Automático de Herramientas

Coloca cualquier archivo Python en `engine/engine/repobrain_engine/tools/` y el agente lo usará inmediatamente—sin imports, sin registro, sin boilerplate.

### Cómo Funciona

1. **Define tu Herramienta**:
```python
# engine/repobrain_engine/tools/sentiment_analyzer.py
def analyze_sentiment(text: str) -> dict:
    """Analiza el sentimiento del texto dado.
    
    Args:
        text: El texto a analizar
        
    Returns:
        Un diccionario con puntuación de sentimiento y etiqueta
    """
    if len(text) > 10:
        return {"score": 0.8, "label": "positivo"}
    return {"score": 0.3, "label": "neutral"}
```

2. **Refresca el Knowledge Hub** (una sola vez):
```bash
rb-refresh --workspace .
```

3. **Úsala Inmediatamente** en prompts:
```
"Analiza el sentimiento de estas reseñas de clientes..."
```

El agente descubrirá y usará automáticamente `analyze_sentiment()`.

## 🎓 Descubrimiento Automático de Skills

Coloca una carpeta de skill en `engine/repobrain_engine/skills/` (con `SKILL.md` y opcionalmente `tools.py`) y el agente cargará automáticamente:
- Documentación de `SKILL.md` en el contexto del prompt
- Funciones públicas de `tools.py` como herramientas invocables

### Ejemplo integrado: `agent-repo-init`

Este repositorio incluye:
- `engine/repobrain_engine/skills/agent-repo-init/`: integración de skill dentro del agente (`init_agent_repo`)
- `skills/agent-repo-init/`: paquete de skill portable con script de ejecución

`agent-repo-init` soporta:
- `quick`: scaffold limpio
- `full`: scaffold + perfil de runtime (`.env`, mission, perfil de contexto e informe)

Úsalo para crear una copia limpia del proyecto base sin heredar estado local de runtime (por ejemplo `.git`, cachés, entornos virtuales locales y archivos de memoria en ejecución).

## 📚 Carga Automática de Contexto

Agrega conocimiento a `.context/` y se inyecta automáticamente en cada prompt del agente—sin configuración necesaria.

### Cómo Funciona

1. **Crea Archivos de Conocimiento**:
```bash
# Crea directorio de contexto
mkdir -p .context

# Agrega tu conocimiento
echo "# Estándares de Codificación del Proyecto
- Usa docstrings estilo Google
- Anota con tipo todas las funciones
- Límite de 80 caracteres por línea" > .context/coding_standards.md

echo "# Documentación de API
## Endpoint de Usuario
GET /api/users - obtener todos los usuarios
POST /api/users - crear nuevo usuario" > .context/api_docs.md
```

2. **Refresca el Knowledge Hub** (una sola vez):
```bash
rb-refresh --workspace .
```

3. **Inyección Automática**:
Cada prompt al agente ahora incluye automáticamente todos los archivos `.context/`.

**Comportamiento actual del loader:**
- Lee solo archivos Markdown de nivel superior: `.context/*.md`
- Si cambias `engine/repobrain_engine/tools/`, reinicia el agente para recargar herramientas

### Organizar Contexto

**Estructura recomendada (nivel superior)**:
```
.context/
├── README.md                      # Índice
├── estandares_codificacion.md     # Guía de estilo
├── politicas_seguridad.md         # Requisitos de seguridad
├── arquitectura.md                # Diseño del sistema
└── esquema_base_datos.md          # Estructura de BD
```

## 🔗 Cómo Trabajan Juntas Herramientas + Contexto

**Escenario**: Construyendo una herramienta de análisis de datos

### Paso 1: Agrega Contexto (Lo que el agente debe saber)
```bash
# .context/database_schema.md
## Tabla de Usuarios
- id (int): Clave primaria
- email (string): Email del usuario
- created_at (timestamp): Fecha de creación de cuenta
```

### Paso 2: Agrega Herramientas (Lo que el agente puede hacer)
```python
# engine/repobrain_engine/tools/db_query.py
def query_users(email_pattern: str) -> list:
    """Consulta usuarios por patrón de email."""
    # Implementación
    return results
```

### Paso 3: Úsalo Naturalmente
```
"Encuentra todos los usuarios creados en el último mes con emails que coincidan con 'admin'"
```

El agente:
- 🧠 **Sabe** el esquema de base de datos (desde contexto)
- 🛠️ **Puede** consultar la base de datos (desde herramientas)
- ✅ **Hace** exactamente lo que necesitas

---

**Siguiente:** [Hoja de Ruta de Desarrollo](ROADMAP.md) | [Índice Completo](README.md)
