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
| Cuenta DeepSeek | — | Backend de IA en la nube. Es la vía recomendada cuando el equipo no puede correr modelos locales |
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
- `DEEPSEEK_API_KEY`

`.env` está en `.gitignore`. **Nunca lo subas al repositorio**: en el pasado se publicaron
claves reales por esta vía.

## Arranque (modo nube con DeepSeek)

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

- **`DEEPSEEK_DIRECT_MINI`** — con `True`, DeepSeek entrega el MINI final en una sola pasada
  y **se omite la verificación factual contra fuentes**. Déjalo en `False` si quieres el pipeline
  completo (generación → reparación → verificación → corrección).
- **`VERIFICATION_DEFAULT_MODE`** — `web` busca con DuckDuckGo y descarga fuentes; `eduqg` y
  `hybrid` requieren un corpus local en `EDUQG_REFERENCE_PATH`. Sin corpus, usa `web`.
- **`SIMA_PC`** — heredado. Si vale `erick`, `settings.py` ignora `LOCAL_API_BASE` y usa
  `REMOTE_LOCAL_API_BASE`. Déjalo en `local`.
- **Etiqueta "Claude" en la interfaz** — el backend de nube se llama `anthropic` internamente
  por compatibilidad; el proveedor real es el que tenga clave (`get_available_backends()` en
  `learning/services.py`). Con clave de DeepSeek, es DeepSeek.
- **Backend `local` en el selector** — aparece siempre aunque no haya servidor. Si se elige sin
  Ollama corriendo, el trabajo termina en `error`.

## Modo local (opcional, requiere hardware)

Solo si el equipo puede correr un modelo. Instala [Ollama](https://ollama.com), descarga el
modelo de `.env` (`ollama pull qwen2.5:7b`; con ≥ 24 GB de VRAM, `qwen3:30b` da mejor
calidad) y usa `start-everything.bat`, que levanta Postgres, Ollama (:8001), el proxy
`proxy-8003.js` (:8003), Django (:8002) y el proxy público (:25564).

## Estructura

```
learning/
  views.py        vistas: registro, dashboard, cursos, subida, detalle, quiz, flashcards, mapa, ejercicios
  services.py     prompts, llamadas a IA (DeepSeek / Anthropic / local), chunking, verificación web y EduQG, Whisper
  job_queue.py    cola en memoria + worker; orquestación del pipeline por etapas; trazas
  parse_mini.py   parser/serializador .mini, filtros de coherencia, aplicación de correcciones
  cat.py          IRT 3PL: selección del siguiente ítem y estimación de habilidad (theta)
  credits.py      planes y ledger de créditos
  models.py       LessonJob (pipeline) · Course/ClassSession/Quiz/Question (modelo nuevo, parcial)
  migrations/     15 migraciones
templates/        20 plantillas server-side
static/learning/  CSS
PROMPT.md, coherence_prompt.md, correct_prompt.md   prompts que el pipeline lee en ejecución
MINI_FORMAT_SPEC.md   especificación del formato .mini
docs/PIPELINE.md      pipeline etapa por etapa
desarollo/VALIDACION_FLUJO_SIMA.md   prueba real del pipeline y fallos conocidos
```

### Pipeline de una clase

```
POST /api/nueva/ → LessonJob(QUEUED) → cola en memoria → process_lesson_job()
  Whisper (si es audio) → generación por chunks (PROMPT.md)
  → filtro de ítems incoherentes → reparación (no descarte)
  → filtro de opciones no uniformes → reparación
  → relleno hasta el objetivo de ítems (IRT necesita banco grande)
  → verificación factual (web/eduqg/hybrid) → aplicación de correcciones con traza
  → status=corrected · processing_log + 4 trazas JSON en el LessonJob
```

## Tests

```bash
python manage.py test learning
```

Ocho tests: cinco sobre el parser `.mini` y tres sobre el reencolado de trabajos. No hay
cobertura del pipeline completo, las vistas ni CAT.

## Problemas conocidos

- **Cola en memoria.** El worker vive dentro del proceso de Django. Al arrancar con
  `runserver`, la app reencola automáticamente los trabajos que quedaron en `QUEUED`/`PROCESSING`
  (`learning/apps.py`); con otro servidor, exporta `SIMA_REQUEUE_ON_START=1`. Para hacerlo a
  mano: `python manage.py requeue_jobs` (`--dry-run` solo lista).
- **Modelo de datos duplicado.** El pipeline y el quiz operan sobre `LessonJob`; las tablas
  del modelo nuevo (`Quiz`, `Question`, `AnswerOption`, `StudentAnswer`) existen pero están
  vacías. `ClassSession.legacy_lesson_job` hace de puente.
- **Prompt de verificación demasiado largo** con clases extensas (`exceed_context_size_error`
  en modelos locales): reducir `VERIFICATION_SOURCE_CHARS` o `VERIFICATION_MAX_SOURCES`.
- **URLs con caracteres no ASCII** pueden fallar al descargar fuentes; el pipeline continúa
  con las que sí pudo leer.
- **Modelos locales pequeños (7B)** producen errores conceptuales en los ítems; usa la nube o
  un modelo ≥ 14B para contenido que se vaya a usar en evaluaciones reales.

Detalle y evidencia en `desarollo/VALIDACION_FLUJO_SIMA.md` e `INFORME_PRUEBA_SIMA.md`.

## Ramas

- `main` y `fix-localmodel` — apuntan al mismo commit desde septiembre de 2026; trabaja sobre `main`.
- `feature/ui-and-database` — un commit sin fusionar (`e6aac1d`) que renombra el backend de nube a
  `deepseek` en interfaz y servicios, rediseña el panel de subida de audio y fija Django 4.2.
  Entra en conflicto con `job_queue.py`, `services.py`, `settings.py` y `lesson_form.html`; requiere
  revisión manual antes de rescatar nada, y el pin a Django 4.2 **no** debe adoptarse.

## Licencia

MIT. Ver `LICENSE`.
