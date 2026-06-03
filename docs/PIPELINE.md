# Pipeline de Generación de Items SIMA — Documentación End-to-End

## Resumen del flujo

```
Audio/Texto → Transcripción → Generación MINI → Filtro de incoherentes
    → Recuperación de incoherentes (reparación específica)
    → Reparación de coherencia general → Verificación (Web + EduQG) → Correcciones
    → Relleno de items (si falta conteo para IRT) → Validación final → JSON → Usuario
```

## 1. Entrada de usuario

- **Audio**: Se sube un archivo de audio (mp3, wav, etc.)
- **Texto**: Se pega o sube un texto directamente
- El sistema crea un `LessonJob` con `status=QUEUED`

## 2. Transcripción (Whisper local)

- Si la entrada es audio, se ejecuta Whisper localmente
- El texto transcrito se guarda en `job.transcript`
- Si la entrada ya es texto, se salta este paso

## 3. Generación de items MINI

- El contenido se divide en chunks adaptativos según conteo de palabras (`generation_chunk_plan()`)
- Cada chunk se envía al modelo local (Qwen3 30B) con el prompt `PROMPT.md`
- El prompt incluye la **Regla de Oro de Coherencia**:
  - Todo enunciado debe ser pregunta con `?` o completación con `____`
  - Las 4 alternativas deben ser de la misma categoría semántica
  - PROHIBIDO enunciados declarativos sueltos
- El modelo responde con líneas MINI (`a|...` cabecera + `iN|...` items)
- `extract_mini_lines()` aísla el bloque MINI del ruido del LLM

## 4. Filtro automático de incoherentes (sin pérdida permanente)

- `filter_incoherent_items()` revisa cada item:
  - Si el enunciado NO contiene `?` ni `____` ni `...`, se marca como incoherente
  - **NO se descarta permanentemente** — se separa en un MINI aparte
  - Se reconstruye la cabecera del MINI de coherentes
- En la prueba real: 53 items generados → 22 incoherentes detectados → 31 coherentes retenidos temporalmente

## 4b. Recuperación de items incoherentes

- Los items incoherentes (enunciados declarativos) se envían a `repair_incoherent_mini()`
- Prompt específico: "Convierte CADA enunciado en pregunta con ? o completación con ____"
- Se conserva el contenido factual, opciones y parámetros IRT
- Los reparados se mergean de vuelta con `merge_mini_chunks()`
- Se re-filtra; si aún quedan incoherentes, solo esos se descartan
- **Objetivo**: Maximizar el conteo de items para IRT (Item Response Theory), que requiere bancos grandes (50-100+ items) para estimación de habilidad precisa

## 5. Reparación de coherencia general con IA local

- `repair_mini_coherence()` envía TODO el banco de items + contexto fuente al LLM
- El prompt `coherence_prompt.md` instruye reescritura quirúrgica:
  - Convertir enunciados declarativos a preguntas
  - Alinear distractores a la misma categoría semántica
  - Preservar el conocimiento factual del enunciado original
- Si el output cambió, se reemplaza; si no, se conserva el original
- Post-reparación se re-filtran incoherentes

## 6. Construcción de contexto de verificación

Según `verification_mode` (`web`, `eduqg`, `hybrid`):

### 6a. Contexto Web (`build_web_context()`)

- Se generan queries de búsqueda a partir de keywords extraídos del MINI
- `search_web()` usa **ddgs** (DuckDuckGo Search) para obtener resultados
- Se fetchean los documentos encontrados y se extraen snippets
- **Fix reciente**: Se reemplazó el scraper HTML roto por `ddgs` — ahora devuelve resultados reales

### 6b. Contexto EduQG (`build_eduqg_context()`)

- Carga registros desde `EDUQG_REFERENCE_PATH` (cacheado en memoria)
- Calcula score de keyword overlap entre cada registro y el MINI
- Retorna los top-K matches con excerpts
- En la prueba: 3397 registros cargados, 5 matches (scores bajos porque el dataset no es de historia peruana)

## 7. Verificación por IA (`verify_items()`)

- Se ensambla el prompt `verify_prompt.md` con:
  - El bloque MINI a verificar
  - `CONTEXTO_DE_VERIFICACION_FETCHED` (web snippets)
  - `EDUQG_LOCAL` (matches del dataset)
- El modelo verificador revisa:
  - Corrección factual de la respuesta marcada con `*`
  - Plausibilidad de distractores
  - Ausencia de ambigüedad
  - Coherencia de parámetros IRT con nivel Bloom
  - Distribución de respuestas correctas (no siempre en A)
- Output esperado:
  ```
  v|d=<YYYYMMDD>|n=<total>|e=<count>|s=VERIFICADO
  e<N>|<item_id>|<error_type>|<field>|<original>|<fix>|<fuente>
  ```
- **Fix reciente**: El parser de correcciones ahora hace fallback de IDs `L1`-`L6` al primer item con ese nivel Bloom, resolviendo el bug donde errores detectados se ignoraban silenciosamente.

## 8. Aplicación de correcciones (`apply_corrections_with_trace()`)

- Parsea el reporte de errores línea por línea
- Busca cada item por ID (`i1`, `i2`, etc.)
- **Fallback**: Si el ID es `L1`-`L6`, busca el primer item con ese nivel Bloom
- Aplica el fix según `error_type`:
  - `wrong_answer`: reemplaza opciones
  - `wrong_statement`: reemplaza enunciado
  - `implausible_distractor`: reemplaza opciones
  - etc.
- Devuelve el MINI corregido + una traza auditable de cada cambio

## 9. Relleno de items (si es necesario para IRT)

- Si el conteo final es menor al 80% del objetivo planificado:
  - `_fill_items_if_needed()` genera items adicionales con el LLM
  - Prompt: "Genera N items MINI adicionales sobre el contenido"
  - Máximo 15 items por llamada de relleno
  - Se mergean al banco existente
- **Por qué es crítico**: IRT (Item Response Theory) necesita bancos grandes para:
  - Estimación precisa de theta (habilidad del estudiante)
  - Cobertura adecuada del rango de dificultad (-3 a +3)
  - Fiabilidad del assessment (menor error estándar de medición)

## 10. Validación final y persistencia

- `validate_mini_parse()` asegura que `n=` en la cabecera coincide con el número real de items
- Se guarda `job.corrected_output`
- Se guarda `job.correction_trace` (JSON con auditoría de cada cambio)
- `status` cambia a `CORRECTED`

## 11. Consumo por el usuario

- El frontend renderiza los items como quiz interactivo
- Los items se convierten a JSON con `assessment_to_dict()`
- Cada item incluye: enunciado, opciones, respuesta correcta, metadatos IRT

## Configuración clave (.env)

```bash
# Modelo local
LOCAL_MODEL=qwen3-30b-endpoint
LOCAL_API_BASE=http://127.0.0.1:8001/v1

# Verificación
VERIFICATION_DEFAULT_MODE=web        # web | eduqg | hybrid
VERIFICATION_FETCH_SOURCES=true
VERIFICATION_MAX_SOURCES=6
VERIFICATION_SEARCH_QUERIES=3
VERIFICATION_SEARCH_RESULTS=3

# EduQG
EDUQG_REFERENCE_PATH=F:\Agente\datasets\eduqg
EDUQG_TOP_K=5
EDUQG_SOURCE_CHARS=6000
```

## Fixes recientes aplicados

| Problema | Causa | Solución |
|----------|-------|----------|
| Web verification 0 fuentes | DuckDuckGo bloqueaba scraper HTML simple | Reemplazado por librería `ddgs` |
| Correcciones ignoradas | Verificador devolvía `L1` en lugar de `i1` | Fallback por nivel Bloom en `apply_corrections_with_trace` |
| Pérdida masiva de items | 22/53 items descartados permanentemente | Recuperación específica de incoherentes + relleno automático |
| Items declarativos | LLM generaba enunciados sin `?`/`____` | Filtro automático + reparación específica + reparación general |

## Métricas de la prueba real (transcripcióntemplate.md)

| Etapa | Resultado |
|-------|-----------|
| Input | 4,439 palabras (historia del Perú) |
| Generados | 53 items en 2 chunks |
| Post-detección | 53 items (22 incoherentes detectados, NO descartados aún) |
| Post-recuperación | ~50 items (los 22 reparados + 31 originales, menos duplicados) |
| Post-reparación general | ~50 items, 0 incoherentes |
| Post-relleno (si aplica) | Hasta 80-90 items (objetivo IRT para 4,400 palabras) |
| Errores detectados | 10 (fechas incorrectas, causas erróneas, "primer presidente" mal) |
| Correcciones aplicadas | **10** (tras fix de IDs) |
| Distribución Bloom final | Variable según cobertura (L1-L6) |
