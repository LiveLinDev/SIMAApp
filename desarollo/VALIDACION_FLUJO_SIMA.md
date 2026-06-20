# Validación del Flujo SIMA

## Coherencia, veracidad y fallos rápidos

**Fecha:** 19/06/2026  
**Versión:** 1.0  
**Autor:** Equipo SIMA

---

## 1. Resumen del flujo validado

El pipeline de SIMA convierte audio o texto de una clase en un banco de ítems MINI verificados, listos para quiz adaptativo (IRT/CAT), flashcards, mapa conceptual y ejercicios.

```
Audio/Texto
    ↓
Transcripción (Whisper local)
    ↓
Generación MINI (Qwen3 / Claude)
    ↓
Filtro de incoherentes  →  Recuperación de incoherentes
    ↓
Reparación de opciones malformadas
    ↓
Reparación de coherencia general
    ↓
Verificación (Web / EduQG / Hybrid)
    ↓
Aplicación de correcciones
    ↓
Relleno de ítems (si es necesario para IRT)
    ↓
Validación final + JSON → Usuario
```

Cada etapa guarda logs de etapa (`processing_log`) y trazas JSON (`transcript_repair_trace`, `mini_coherence_trace`, `verification_trace`, `correction_trace`) que permiten auditar qué pasó.

---

## 2. Validación de coherencia

### 2.1 Regla de oro del MINI

Todo ítem generado debe cumplir:

- El enunciado es una **pregunta con `?`** o una **completación con `____`**.
- Tiene **exactamente 4 opciones** separadas por comas.
- Las 4 opciones pertenecen a la **misma categoría semántica**.
- Una opción está marcada como correcta con `*`.
- Incluye metadatos: nivel Bloom (L1-L6), dificultad, demanda, área, parámetros IRT (a, b, c).

### 2.2 Filtro de incoherentes (sin pérdida permanente)

`filter_incoherent_items()` separa los ítems que no cumplen la regla de oro, pero **no los descarta**: se envían a una función de reparación específica.

**Prueba real (historia del Perú, ~4.400 palabras):**

| Etapa | Resultado |
|-------|-----------|
| Generados | 53 ítems |
| Incoherentes detectados | 22 |
| Coherentes retenidos | 31 |

### 2.3 Recuperación de incoherentes

`repair_incoherent_mini()` envía solo los ítems declarativos al LLM con el prompt:

> "Convierte CADA enunciado en una pregunta con `?` o una completación con `____`."

Se conserva el conocimiento factual y los parámetros IRT. Los ítems reparados se mergean de vuelta.

### 2.4 Reparación de coherencia general

`repair_mini_coherence()` revisa TODO el banco con el contexto de la clase/transcripción y reescribe quirúrgicamente ítems con sentido dudoso. Después se vuelve a filtrar.

### 2.5 Reparación de opciones uniformes

`filter_nonuniform_items()` detecta:

- Opciones fusionadas por comas (3 distractores en 1).
- Distractores con longitud muy diferente a la correcta.
- Categorías semánticas inconsistentes.

`repair_option_uniformity()` repara y devuelve ítems con 4 opciones plausibles.

### 2.6 Resultado de coherencia en la prueba real

| Etapa | Resultado |
|-------|-----------|
| Post-recuperación | ~50 ítems |
| Post-reparación general | ~50 ítems, 0 incoherentes |
| Post-relleno | Hasta 80-90 ítems (objetivo IRT para ~4.400 palabras) |

---

## 3. Validación de veracidad

### 3.1 Modos de verificación

El sistema soporta tres modos configurables en el formulario API o por `.env`:

- `web`: solo búsqueda web.
- `eduqg`: solo referencias locales EduQG.
- `hybrid`: web + EduQG.

### 3.2 Búsqueda web

`build_verification_query_entries()` usa el LLM para extraer afirmaciones factuales del MINI y generar queries de búsqueda. Luego `search_web()` usa `ddgs` (DuckDuckGo) para obtener URLs reales.

Se fetchean los documentos con `fetch_source_document()`:

- Descarga hasta 500 KB de HTML.
- Extrae texto útil con parser HTML propio.
- Descarta páginas bloqueadas (Incapsula, Access Denied, etc.).
- Aplica timeout de 8 s con un reintento (+4 s).

### 3.3 Fuentes académicas

Para cada query se ejecutan búsquedas dirigidas a:

- `site:arxiv.org`
- `site:scholar.google.com`
- `site:semanticscholar.org`

### 3.4 Evidencia real de verificación

Ejemplo de verificación con clase de fotosíntesis (19/06/2026):

- **Modo:** web
- **Queries generadas por IA:** 6
- **Resultados recuperados:** 4
- **Fuentes usables:** 2

Se recuperaron snippets de Wikipedia, arXiv y Google Académico. Algunas URLs con caracteres no-ASCII fallaron por encoding (`'ascii' codec can't encode character...`), pero el sistema siguió con las fuentes que sí pudo leer.

### 3.5 Aplicación de correcciones

`apply_corrections_with_trace()`:

- Parsea el reporte del verificador línea por línea.
- Busca ítems por ID (`i1`, `i2`, ...).
- Tiene fallback por nivel Bloom (`L1`-`L6`).
- Aplica cambios según tipo de error: `wrong_answer`, `wrong_statement`, `implausible_distractor`, etc.
- Guarda traza auditable de cada corrección.

**Prueba real (historia del Perú):**

| Métrica | Valor |
|---------|-------|
| Errores detectados | 10 |
| Correcciones aplicadas | 10 |

---

## 4. Fallos rápidos detectados y mitigación

Durante la validación del flujo real se encontraron errores intermitentes. A continuación el registro y la causa probable.

### 4.1 Error: `A string literal cannot contain NUL (0x00) characters`

- **Visto en:** `ClassSession #20`, `LessonJob #19`.
- **Cuándo:** al final del pipeline, después de "Listo - Clase verificada y corregida".
- **Causa:** el output de la IA local o alguna fuente web contuvo el carácter nulo `\x00`, que SQLite no permite en campos de texto.
- **Impacto:** el `save()` final falla, el job queda en estado `error` a pesar de que todo el procesamiento funcionó.
- **Mitigación actual:** reintentar el job. Al ser contenido generado estocásticamente, la segunda ejecución puede no incluir el NUL.
- **Mitigación recomendada:** sanitizar `\x00` de `verification_output`, `corrected_output`, `processing_log` y `verification_trace` antes de guardar.

### 4.2 Error: `exceed_context_size_error`

- **Visto en:** `LessonJob #60` (16.577 tokens > 4.096 ctx) y `LessonJob #59` (14.073 tokens > 8.192 ctx).
- **Causa:** el prompt de verificación creció demasiado porque incluyó la transcripción + el MINI + muchos snippets web.
- **Impacto:** el modelo local rechaza la petición.
- **Mitigación actual:** reintentar. En ocasiones se recuperan menos fuentes y el prompt cabe.
- **Mitigación recomendada:** limitar `context_chars` en `build_verification_context()` o recortar snippets cuando el prompt total supere un umbral seguro.

### 4.3 Error: conexión al servidor IA local

- **Visto en:** `LessonJob #23`.
- **Mensaje:** `No se pudo conectar al servidor de IA en http://127.0.0.1:8003/v1`.
- **Causa:** el `llama-server` / proxy local no estaba corriendo o se reinició mientras procesaba.
- **Impacto:** el job falla en cualquier etapa que requiera LLM.
- **Mitigación actual:** reintentar cuando el servidor vuelva a estar disponible.
- **Mitigación recomendada:** health-check del backend antes de encolar y cola persistente ante fallos.

### 4.4 Error de encoding en URLs no-ASCII

- **Visto en:** verificación de fotosíntesis.
- **Mensaje:** `'ascii' codec can't encode character '\\xe9' in position 27`.
- **Causa:** URLs con acentos (ej. `Pigmento_fotosintético`) no se codifican correctamente antes de hacer fetch.
- **Impacto:** se descarta una fuente potencialmente válida.
- **Mitigación recomendada:** aplicar `urllib.parse.quote()` a la ruta de la URL antes de `urlopen()`.

### 4.5 Ítems declarativos y opciones malformadas

- **Detectado:** en múltiples generaciones.
- **Causa:** el LLM a veces genera enunciados sin `?`/`____` o fusiona opciones.
- **Mitigación implementada:**
  - Filtro automático (`filter_incoherent_items`).
  - Recuperación específica (`repair_incoherent_mini`).
  - Reparación de opciones (`repair_option_uniformity`).
  - Relleno automático si el banco queda muy pequeño (`_fill_items_if_needed`).

---

## 5. Checklist rápido de validación end-to-end

Para validar una clase desde cero:

1. **Subir audio o texto** en `/api/nueva/`.
2. **Verificar cola:** el job pasa a `QUEUED` → `PROCESSING`.
3. **Auditar transcripción:** revisar que `transcript` tenga texto coherente.
4. **Revisar logs:** `processing_log` debe mostrar todas las etapas sin saltos.
5. **Ver MINI parseado:** en `lesson_detail` debe aparecer el conteo de ítems.
6. **Ver pipeline:** `/clase/<id>/pipeline/` muestra prompts, outputs y evidencia.
7. **Iniciar quiz:** `/clase/<id>/quiz/iniciar/` debe crear `QuizAttempt`.
8. **Completar quiz:** ver que theta, SE y nivel se actualicen.
9. **Revisar flashcards/mapas:** se generan desde el MINI final.
10. **Ver créditos:** el ledger descuenta el monto correcto.

---

## 6. Configuración clave para reproducir la validación

```bash
# Modelo local
LOCAL_MODEL=qwen3-30b-endpoint
LOCAL_API_BASE=http://127.0.0.1:8003/v1
LOCAL_API_TIMEOUT=120

# Verificación
VERIFICATION_DEFAULT_MODE=web
VERIFICATION_FETCH_SOURCES=true
VERIFICATION_MAX_SOURCES=6
VERIFICATION_SOURCE_TIMEOUT=8
VERIFICATION_SEARCH_QUERIES=3
VERIFICATION_SEARCH_RESULTS=3

# EduQG
EDUQG_REFERENCE_PATH=F:\Agente\datasets\eduqg
EDUQG_TOP_K=5
EDUQG_SOURCE_CHARS=6000
```

---

## 7. Conclusión

El flujo SIMA es funcional end-to-end: transcribe, genera, repara, verifica y corrige ítems educativos. La coherencia se valida mediante filtros automáticos + reparación con IA. La veracidad se valida con búsqueda web real y (opcionalmente) EduQG.

Los principales riesgos actuales son **intermitentes**, no estructurales:

- Caracteres NUL en outputs de IA.
- Prompts que exceden el contexto del modelo local.
- Servidor IA local no disponible.
- Encoding de URLs no-ASCII.

Reintentar el procesamiento suele funcionar, pero se recomienda aplicar las mitigaciones listadas para hacer el pipeline robusto.
