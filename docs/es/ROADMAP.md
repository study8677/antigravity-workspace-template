# Hoja de Ruta de Desarrollo

## Visión: Capa de Conocimiento de Repositorios con Evidencia

RepoBrain converge hacia un motor portable de conocimiento de repositorios:
refresca un workspace en `.repobrain/`, responde preguntas con evidencia de
código y expone la misma capa mediante plugins, CLI y MCP.

## Estado Actual

| Fase | Estado | Descripción |
|------|--------|-------------|
| 1 Foundation | Completa | Estructura base, configuración, memoria |
| 2 DevOps | Completa | Docker, CI/CD |
| 3 Protocolos | Completa | Reglas, artifacts, contratos de trabajo |
| 4 Memoria Avanzada | Completa | Resumización recursiva y buffers |
| 5 Arquitectura de Herramientas | Completa | Dispatch genérico y function calling |
| 6 Descubrimiento Dinámico | Completa | Herramientas y contexto zero-config |
| 7 Multi-Agent Swarm | Completa | Orquestación Router-Worker |
| 8 MCP Integration | Completa | Soporte MCP server / consumer |
| 9 Endurecimiento de Producto | Completa | Fronteras de seguridad, observabilidad, docs e instalación |
| 10 Knowledge Hub | Completa | Refresh del codebase, conocimiento modular y Q&A enrutado |

## Funcionalidad Principal Completada (Hasta Agosto 2026)

### Fase 9: Endurecimiento de Producto ✅
- **Sandbox**: frontera local confiable, opt-in a Microsandbox/E2B y warnings de fallback
- **Retrieval graph**: mantener experiencia de desarrollo con redacción de secretos y documentación de riesgos
- **MCP**: conservar comodidad opt-in y aclarar `RB_ALLOW_MCP`, entorno y permisos de servidores externos
- **Instalación y documentación**: sostener la línea `rb-setup -> rb-refresh -> rb-ask`
- **Contract checks**: verificar scripts de instalación, docs de sandbox, modelo por defecto y quick starts

### Fase 10: Knowledge Hub ✅
- **Almacenamiento generativo**: base de conocimiento modular en directorio `.repobrain/`
- **Evidencia estructurada**: claims JSON + verificación de fuente (ruta de archivo + rango de líneas)
- **Soporte multi-lenguaje**: Python, TypeScript/JavaScript, Go, Rust, Java, Kotlin, Swift, C/C++, C#
- **Host-runner**: backend CLI local (RB_HOST_RUNNER), sin necesidad de API key
- **Refresh incremental**: `rb-refresh --quick` solo actualiza agent-groups afectados
- **Arquitectura de agentes**:
  - Refresh Swarm: ScanAnalyst → ArchitectureReviewer → ConventionWriter
  - Ask Swarm: Router + ModuleAgent dinámico + GitAgent

## Casos de Uso

- Onboarding: ejecutar `rb-refresh` y preguntar con `rb-ask`, recibiendo evidencia de archivos.
- Colaboración multi-IDE: Claude Code, Codex CLI, Cursor y otros usan la misma `.repobrain/`.
- Publicación segura: el repo documenta límites locales confiables, MCP y riesgos del retrieval graph.

---

**Siguiente:** [Índice Completo](README.md)
