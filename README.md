# SIMAApp

Plataforma de microaprendizaje que convierte clases universitarias grabadas (audio o texto)
en un banco de ítems de evaluación verificado, quizzes adaptativos (IRT 3PL), flashcards,
mapa conceptual y ejercicios, con seguimiento por curso.

Aplicación Django monolítica; toda la lógica vive en la app `learning/`.

## Requisitos

| Componente | Versión | Notas |
|---|---|---|
| Python | 3.12 – 3.14 | Verificado con 3.14.4. **No** usar 3.9: Django 5.2 exige ≥ 3.10 |
| PostgreSQL | 18 (o 13+) | `start-postgres.bat` espera el servicio `postgresql-x64-18` en el puerto 5433. Para pruebas rápidas sirve SQLite |
| Proveedor de IA en la nube | — | Cualquier API compatible con OpenAI (DeepSeek, OpenAI, Gemini, Qwen, Groq, Mistral) o Anthropic. Es la vía recomendada cuando el equipo no puede correr modelos locales |
| Node.js | 22 | Solo para el proxy público (`proxy-mini`) o el proxy del modelo local (`proxy-8003.js`). No hace falta para desarrollar |
| ffmpeg | — | Lo aporta `imageio-ffmpeg`; no requiere instalación aparte |

## Instalación

```bash
git clone https://github.com/LiveLinDev/SIMAApp.git
cd SIMAApp
py -3.14 -m venv .venv          # o py -3.12 / py -3.13
.venv\Scripts\activate
pip install -r requirements.txt  # incluye openai-whisper -> torch (~200 MB en CPU)
copy .env.example .env
```

Edita `.env` y completa como mínimo:

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD` (o `DB_ENGINE=sqlite` para no depender de Postgres)
- `CLOUD_API_KEY`, `CLOUD_API_BASE` y `CLOUD_MODEL` (hay un bloque por proveedor en `.env.example`)

`.env` está en `.gitignore`. **Nunca lo subas al repositorio**: en el pasado se publicaron
claves reales por esta vía.

## Arranque (modo nube)

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8002 --noreload
```

Abre `http://127.0.0.1:8002/`.

`--noreload` importa: el worker que procesa las clases es un hilo dentro del proceso de
`runserver`, y el autoreloader lo mata si un archivo cambia a mitad de un trabajo.

En Windows, `start-postgres.bat` seguido de `start-django.bat` hace lo mismo (levanta el
servicio de Postgres, crea la BD si no existe, migra y sirve en :8002).

> `start-everything.bat` **no** es para este modo: exige Ollama en :8001 y aborta si no está.

### Primera prueba

1. Crea un curso en **Cursos → Nuevo**.
2. Sube `clase_fotosintesis_3000.txt` desde `/api/nueva/` con verificación `web`.
3. Sigue el avance en `/clase/<id>/` y el detalle de cada etapa en `/clase/<id>/pipeline/`.
4. Con el banco listo: `/clase/<id>/quiz/iniciar/`, flashcards, mapa y ejercicios.

## Configuración que conviene conocer

- **Backends.** Hay dos: `cloud` (proveedor externo definido por `CLOUD_*`) y `local` (servidor
  compatible con OpenAI en `LOCAL_API_BASE`). Con una clave real en `CLOUD_API_KEY`, la nube es el
  backend por defecto. Los nombres antiguos (`anthropic`, `deepseek`, `qwen`) se siguen aceptando
  como alias y la migración `0016` renombra los trabajos existentes.
- **`CLOUD_DIRECT_MINI`** — con `True`, el proveedor entrega el MINI final en una sola pasada y
  **se omite la verificación factual contra fuentes**. Déjalo en `False` para el pipeline completo
  (generación → reparación → verificación → corrección).
- **`VERIFICATION_DEFAULT_MODE`** — `web` busca con DuckDuckGo y descarga fuentes; `eduqg` y
  `hybrid` requieren un corpus local en `EDUQG_REFERENCE_PATH`. Sin corpus, usa `web`.
- **Backend `local` en el selector** — aparece siempre aunque no haya servidor. Si se elige sin
  Ollama corriendo, el trabajo termina en `error`.

### Cambiar de proveedor de IA

Basta con cambiar `CLOUD_PROVIDER` y `CLOUD_API_KEY` en `.env` y reiniciar (endpoint y modelo tienen valor
por defecto por proveedor; se pueden fijar con `CLOUD_API_BASE` y `CLOUD_MODEL`). Antes de subir clases,
comprueba el proveedor con `python manage.py check_ai --ping --mini` (o `check-ia.bat`): valida la
configuración, hace una llamada mínima y genera ítems `.mini` con un texto de muestra midiendo cuántos
respetan el formato, el tiempo y el costo aproximado. Precios públicos por millón de tokens a septiembre
de 2026 (entrada / salida, USD); verifícalos antes de decidir:

| Proveedor | `CLOUD_MODEL` | Entrada | Salida | Notas |
|---|---|---|---|---|
| DeepSeek | `deepseek-v4-flash` | 0,22 | 0,66 | 0,44 / 1,32 en horas pico (01–04 y 06–10 UTC) desde el 16-ago. `deepseek-chat` **ya no existe** |
| OpenAI | `gpt-5-nano` · `gpt-5-mini` | 0,05 · 0,25 | 0,40 · 2,00 | Caché de prompt al ~10 % |
| Google | `gemini-3.1-flash-lite` | 0,25 | 1,50 | Requiere `CLOUD_MAX_TOKENS=0` (el endpoint compatible no acepta `max_tokens`) |
| Alibaba | `qwen-flash` (Qwen3.8 Flash) | 0,14 | 0,42 | 1 M tokens gratis por modelo los primeros 90 días |
| Groq | `openai/gpt-oss-120b` | 0,15 | 0,60 | Muy rápido; modelos abiertos |
| Mistral | `mistral-small-latest` | 0,15 | 0,60 | |
| Anthropic | `claude-haiku-4-5` · `claude-sonnet-5` | 1,00 · 2,00 | 5,00 · 10,00 | SDK nativo; `pip install anthropic` |

Una clase de ~4 400 palabras consume del orden de 40 k tokens de entrada y 15 k de salida en todo el
pipeline: con cualquiera de las opciones baratas cuesta centavos. El criterio para elegir no es el
precio sino cuán bien el modelo respeta el formato `.mini` en español y cuánto inventa; el paquete
reproducible del artículo (`validate_generation_experiment.py`) sirve para medir eso por proveedor
antes de cambiar.

## Modo local (opcional, requiere hardware)

Solo si el equipo puede correr un modelo. Instala [Ollama](https://ollama.com), descarga el
modelo de `.env` (`ollama pull qwen2.5:7b`; con ≥ 24 GB de VRAM, `qwen3:30b` da mejor
calidad) y usa `start-everything.bat`, que levanta Postgres, Ollama (:8001), el proxy
`proxy-8003.js` (:8003), Django (:8002) y el proxy público (:25564).

## Estructura

```
learning/
  views/          paquete de vistas por dominio: core (inicio, panel, salud), courses (curso, banco, CSV),
                  lessons (clases y pipeline), study (flashcards, repaso, ejercicios, mapa), pipeline (trazas),
                  practice (práctica, recomendaciones, refuerzo), summaries_views, _common (ayudantes)
  services/       paquete: prompts (plantillas y limpieza), backends (proveedores nube/local y call_ai),
                  generation (chunks y presupuesto de ítems), repairs (verificación y reparaciones .mini),
                  evidence (web, documentos fuente, EduQG), transcription (Whisper)
  job_queue.py    cola (hilos o BD), worker, reclamo de trabajos con bloqueo, reencolado, límite por usuario
  pipeline.py     etapas de una clase: transcripción → generación → reparaciones → verificación → corrección → banco
  portability.py  exportar/importar un curso como JSON (clases, resúmenes, flashcards)
  parse_mini.py   parser/serializador .mini, filtros de coherencia, aplicación de correcciones
  cat.py          IRT 3PL: probabilidad, información de Fisher y nivel
  psychometrics.py  EAP, randomesque, calibración Elo, Bayesian Knowledge Tracing, puerta de calidad
  adaptive.py     núcleo de acompañamiento: banco del curso, práctica CAT (equilibrada/débiles/riesgo/simulacro), perfil,
                  olvido por tema, plan de hoy, recomendaciones, racha/XP, informe del banco
  adaptive_generation.py  refuerzo dirigido: ítems nuevos, explicaciones y flashcards a la medida del perfil
  spaced_repetition.py    SM-2 para flashcards y cola de repaso por curso
  segments.py     segmentos de transcripción con tiempo y enlace pregunta ↔ fragmento de la clase
  summaries.py    resúmenes por clase y del curso (SummaryJob en cola)
  progress.py     serie de dos semanas y SVG de progreso
  reminders.py    recordatorios por correo
  credits.py      planes y ledger de créditos
  models.py       LessonJob (pipeline) · Course/ClassSession/Transcript/Quiz/Question/StudentAnswer/AdaptiveProfile/
                  PracticeSession/ReinforcementJob/SummaryJob/Flashcard/Summary/Recommendation/StudyActivity
  management/commands/  requeue_jobs · sync_question_bank · send_study_reminders · run_worker · export_course · import_course
  migrations/     23 migraciones
templates/        24 plantillas server-side
static/learning/  CSS
PROMPT.md, coherence_prompt.md, correct_prompt.md   prompts que el pipeline lee en ejecución
MINI_FORMAT_SPEC.md   especificación del formato .mini
docs/PIPELINE.md      pipeline etapa por etapa
docs/ARQUITECTURA.md  módulos y los tres flujos principales; diagramas C4 en docs/c4-*.dsl
desarollo/VALIDACION_FLUJO_SIMA.md   prueba real del pipeline y fallos conocidos
```

### Pipeline de una clase

```
POST /api/nueva/ → LessonJob(QUEUED) → cola (hilos o BD) → pipeline.process_lesson_job()
  Whisper (si es audio) → generación por chunks (PROMPT.md)
  → filtro de ítems incoherentes → reparación (no descarte)
  → filtro de opciones no uniformes → reparación
  → relleno hasta el objetivo de ítems (IRT necesita banco grande)
  → verificación factual (web/eduqg/hybrid) → aplicación de correcciones con traza
  → status=corrected · processing_log + 4 trazas JSON en el LessonJob
  → los ítems pasan al banco del curso (Question/AnswerOption)
```

### Ciclo de acompañamiento (núcleo adaptativo)

El valor de SIMA no está en generar preguntas sino en lo que pasa después. `learning/adaptive.py`
cierra el ciclo a nivel de **curso**, no de clase:

```
banco del curso (todas las clases)
  → /cursos/<id>/practicar/        sesión CAT (IRT 3PL) que arranca desde el nivel ya conocido,
                                    no repite lo acertado hace <3 días y empuja hacia temas débiles
  → cada respuesta                  StudentAnswer con theta antes/después
  → al terminar                     retroalimentación (temas, Bloom, fallos con la respuesta correcta),
                                    AdaptiveProfile recalculado desde todo el historial (peso reciente),
                                    recomendaciones concretas, XP y racha
  → curso y dashboard               nivel, temas débiles/dominados, "Hoy en SIMA" con la siguiente acción
```

Modo **refuerzo** (`focus=weak`): la sesión se limita a los temas con dominio < 60 %. El banco se
sincroniza solo al terminar cada clase y al iniciar una práctica; también a mano con
`python manage.py sync_question_bank`.

**Generación adaptativa** (`/cursos/<id>/refuerzo/`, `learning/adaptive_generation.py`): a partir de
los temas débiles, los niveles Bloom donde el estudiante falla y su θ, una sola llamada al modelo
produce ítems nuevos calibrados (`b ≈ θ`), una explicación por concepto fallado basada en la
transcripción y una flashcard por concepto. Los ítems pasan los filtros deterministas del pipeline y
entran al banco como `Quiz` de tipo `reinforcement`. Cobra `REINFORCEMENT_COST` (+ recargo de nube)
y reembolsa si la generación falla. Corre en la misma cola que las clases.

El **quiz por clase** (`/clase/<id>/quiz/iniciar/`) abre una práctica del curso limitada al banco de esa
clase, con la memoria del perfil. El quiz heredado (`QuizAttempt`) ya no tiene vistas ni rutas.

**Motor psicométrico v2** (`learning/psychometrics.py`): la habilidad se estima por **EAP** (media a
posteriori con prior normal, Bock & Mislevy 1982) en lugar de máxima verosimilitud, así el error estándar
existe desde la primera respuesta y el prior del perfil se integra de forma natural; la selección es
**randomesque** (Kingsbury & Zara 1989: elige al azar entre los 5 ítems más informativos) para no
sobreexponer siempre el mismo ítem; la dificultad `b` de cada ítem se **recalibra en línea** con una
regla tipo Elo de paso decreciente (Pelánek 2016) y se usa a partir de 3 observaciones; el dominio por
tema y nivel Bloom se sigue con **Bayesian Knowledge Tracing** (Corbett & Anderson 1994; p_init .25,
p_learn .12, p_slip .10, p_guess .25); y una **puerta de calidad** aparta ítems demasiado fáciles (≥ 97 %
de acierto) o sospechosos (≤ 10 % tras 8 intentos) para que no vuelvan a servirse.

**Ciclo de aprendizaje**: tras cada respuesta la práctica muestra al instante si fue correcta, la opción
correcta, la explicación del concepto (si existe) y el **fragmento de la clase que la respalda**, con la
marca de tiempo cuando la clase entró por audio (`learning/segments.py`: Whisper devuelve segmentos con
tiempo que se guardan como `TranscriptSegment`; cada pregunta se enlaza con el segmento de mayor
solapamiento de palabras clave). Los fallos de la retroalimentación final llevan el mismo extracto.

**Resúmenes** (`learning/summaries.py`, US-050): `/clase/<id>/resumen/` genera el resumen estructurado
de la clase (conceptos clave, párrafos, qué repasar primero) a partir de la transcripción y de las
preguntas que ya se evalúan; `/cursos/<id>/resumen/` integra los resúmenes de clase (o las
transcripciones, si no hay) en un documento por temas que prioriza los temas débiles del perfil. La
vista cobra `SUMMARY_COST` (+ recargo de nube) y deja un `SummaryJob` en la cola; el worker genera,
guarda y reembolsa si falla. La página muestra el estado y se refresca sola. Leer un resumen suma XP
una vez al día.

**Simulacro** (`focus=exam`): examen de longitud fija sobre todo el curso, con cobertura proporcional
de temas y sin sesgo hacia lo débil ni parada anticipada; la retroalimentación da la nota sobre 20. Si el
curso tiene **fecha de examen**, la cabecera muestra la cuenta regresiva y, a 10 días o menos, el plan de
hoy pone el simulacro en primer lugar.

**Límite por usuario**: `SIMA_MAX_PENDING_JOBS` (3) trabajos en cola o procesando (clases, refuerzos,
resúmenes); se comprueba antes de cobrar créditos.

**Exportar e importar un curso** (`learning/portability.py`): `python manage.py export_course <id> --out curso.json`
guarda las clases (transcripción y `.mini` verificado), resúmenes y flashcards; `python manage.py import_course
curso.json --user <usuario> [--name ...]` lo recrea para otro usuario o en otra máquina y reconstruye el banco de
preguntas sin volver a pagar la generación. El historial de práctica no viaja y las clases importadas quedan
privadas.

**Olvido por tema**: cada tema del perfil guarda una **vida media de retención** (regresión de vida
media simplificada, Settles & Meeder 2016: 3 días tras un acierto, se duplica con cada acierto
consecutivo, tope 90) y la fecha de la última respuesta. Un tema dominado cuya retención estimada
(`2^(-días/vida media)`) deja el dominio efectivo bajo 0,6 aparece **en riesgo** en el curso, entra al
plan de hoy y tiene su propio modo de práctica (`focus=risk`).

**Banco del curso** (`/cursos/<id>/banco/`): por pregunta, dificultad generada frente a la calibrada,
intentos, acierto y bandera de calidad; descarga del banco y de las respuestas del estudiante en CSV
(evidencia para la validación de la tesis).

**Progreso semanal** (`learning/progress.py`): serie diaria de respuestas, aciertos y θ de las últimas dos
semanas, dibujada como SVG en el servidor (sin JavaScript) en el curso y en "Hoy en SIMA", con la
comparativa contra la semana anterior.

**Recordatorios por correo** (`learning/reminders.py`): `python manage.py send_study_reminders`
(`--dry-run` para listar) escribe a quienes activaron la casilla en Preferencias y no han estudiado hoy,
con las tarjetas vencidas y el primer paso del plan. Configura `EMAIL_*`, `DEFAULT_FROM_EMAIL` y
`SIMA_SITE_URL` en `.env`; por defecto el backend imprime en consola. Prográmalo una vez al día con el
Programador de tareas de Windows o cron.

**Ritmo** (`learning/spaced_repetition.py` + `adaptive.daily_plan`): las flashcards siguen SM-2
(factor de facilidad, intervalos 1 → 6 → ×EF, reinicio con "again"); `/cursos/<id>/repasar/` sirve la
cola del curso (vencidas primero, luego nuevas) y cada calificación cuenta para la racha y la meta
diaria. El **plan de hoy** convierte la ruta de estudio en reglas sobre el perfil: repasar lo vencido
→ reforzar el tema débil (o practicar el refuerzo ya generado) → revisar los fallos de la última sesión
→ sesión de práctica (si el nivel es impreciso o llevas días sin practicar) → practicar la clase que aún
no has trabajado → subir una clase nueva. Aparece en el curso y en "Hoy en SIMA", junto con el progreso
de la meta diaria (`UserPreference.daily_goal`, en preguntas + tarjetas).

Guía de revisión paso a paso, métricas del avance y decisiones pendientes: `REVISION.md`. Título, objetivos e
indicadores vigentes de la tesis: `docs/MARCO_TESIS.md`.

## Tests

```bash
python manage.py test learning
```

Ochenta y seis tests: parser `.mini`, reencolado, resolución de backends, renderizado del selector,
**pipeline completo de una clase con el modelo simulado**, motor adaptativo (banco, sesión completa,
perfil, recomendaciones, vistas), motor v2 (EAP, randomesque, BKT, calibración, puerta de calidad),
refuerzo (cobro, generación con IA simulada, reembolso), ritmo (SM-2, cola de repaso, plan diario,
meta), ciclo de aprendizaje (segmentos, retroalimentación inmediata, retiro del quiz heredado),
resúmenes en cola, worker en BD, simulacro, olvido por tema, banco del curso, progreso, recordatorios
y `/salud/`. No hay cobertura con IA real (requiere clave y cuesta créditos).

## Problemas conocidos

- **Cola de trabajos.** Con `SIMA_QUEUE_MODE=thread` (por defecto) el worker vive en hilos dentro
  del proceso de Django; al arrancar con `runserver` la app reencola sola los trabajos huérfanos
  (`learning/apps.py`), con otro servidor exporta `SIMA_REQUEUE_ON_START=1`, y a mano
  `python manage.py requeue_jobs`. Con `SIMA_QUEUE_MODE=db` el web solo deja los trabajos en
  `QUEUED` y un proceso aparte los procesa: `python manage.py run_worker` (`--once` para el
  Programador de tareas; `--stale-minutes` devuelve a la cola los atascados). Varios workers pueden
  convivir (reclamo con `select_for_update(skip_locked=True)`). Recomendado `db` con gunicorn.
- **Monitoreo.** `GET /salud/` devuelve el estado de la base, de la cola por tipo de trabajo y del
  backend configurado (200 u 503).
- **Modelos `QuizAttempt`/`QuizResponse` heredados.** Ya no tienen vistas ni rutas; quedan las tablas
  con el historial antiguo. Pueden eliminarse con una migración cuando no haga falta consultarlo.
- **Prompt de verificación demasiado largo** con clases extensas (`exceed_context_size_error`
  en modelos locales): reducir `VERIFICATION_SOURCE_CHARS` o `VERIFICATION_MAX_SOURCES`.
- **URLs con caracteres no ASCII** pueden fallar al descargar fuentes; el pipeline continúa
  con las que sí pudo leer.
- **Modelos locales pequeños (7B)** producen errores conceptuales en los ítems; usa la nube o
  un modelo ≥ 14B para contenido que se vaya a usar en evaluaciones reales.

Detalle y evidencia en `desarollo/VALIDACION_FLUJO_SIMA.md` e `INFORME_PRUEBA_SIMA.md`.

## Ramas

- `main` y `fix-localmodel` — apuntan al mismo commit desde septiembre de 2026; trabaja sobre `main`.
- `feature/ui-and-database` — un commit sin fusionar (`e6aac1d`). Su renombrado del backend de nube
  ya quedó cubierto de forma más general (backend `cloud`); lo único pendiente de rescatar a mano es
  el rediseño del panel de subida de audio en `lesson_form.html`. El pin a Django 4.2 **no** debe
  adoptarse.

## Licencia

MIT. Ver `LICENSE`.
