# Guía de revisión — SIMA, 5 de septiembre de 2026 (actualizada tras la reorganización)

Este documento existe para que puedas revisar el avance sin leer el código: qué cambió, cómo
probar cada pieza en tu máquina en pocos minutos, y qué decisiones quedan en tus manos.

## 1. Avance medible

| Indicador | Antes (retomar, 9a0a15b) | Ahora |
|---|---|---|
| Pruebas automáticas | 5 (solo parser `.mini`) | **96** en 14 módulos, todas en verde (incluye una que renderiza las 31 páginas del producto) |
| Cobertura funcional de pruebas | parser | parser, backends, reencolado, pipeline completo con IA simulada, motor adaptativo, motor v2, refuerzo, ritmo, ciclo de aprendizaje, resúmenes, progreso, recordatorios, cola en BD, simulacro, olvido, banco, salud |
| Commits locales sobre `main` | — | 17 |
| Migraciones aplicadas | 0015 | 0023 (0022 elimina las tablas heredadas del quiz) |
| Módulos nuevos del núcleo | 0 | 8 (`adaptive`, `psychometrics`, `adaptive_generation`, `spaced_repetition`, `segments`, `summaries`, `progress`, `reminders`; 3 319 líneas con `job_queue`) |
| Tablas del modelo nuevo en uso | vacías | `Question`, `AnswerOption`, `StudentAnswer`, `AdaptiveProfile`, `Recommendation`, `StudyActivity`, `Summary`, `Flashcard` (SM-2), `Transcript`, `TranscriptSegment`, `PracticeSession`, `ReinforcementJob`, `SummaryJob` |
| Comandos de operación | — | `requeue_jobs`, `sync_question_bank`, `send_study_reminders`, `run_worker` |
| Modos de práctica | quiz por clase sin memoria | equilibrada, refuerzo de débiles, repaso de temas en riesgo, simulacro con nota |
| Organización de vistas | `views.py` de 1 992 líneas con funciones duplicadas | paquete `learning/views/` por dominio (8 módulos), sin duplicados, ayudantes compartidos con el worker |
| Organización de servicios | `services.py` de 1 849 líneas | paquete `learning/services/` (prompts, backends, generation, repairs, evidence, transcription), sin ciclos |
| Documentación de arquitectura | diagramas C4 de abril con componentes "planeados" y API de Claude | `docs/ARQUITECTURA.md` + C4 (contexto, contenedores, componentes) sincronizados con el código |

## 2. Qué hace SIMA ahora, de punta a punta

1. **Clase** (audio o texto) → transcripción con segmentos y minuto → ítems `.mini` verificados →
   banco de preguntas del curso, cada pregunta enlazada al fragmento de la clase que la respalda.
2. **Práctica adaptativa por curso** con memoria: habilidad por EAP, selección randomesque,
   dificultad recalibrada con respuestas reales, dominio por tema y nivel Bloom con Bayesian
   Knowledge Tracing, puerta de calidad para ítems malos.
3. **Retroalimentación inmediata** tras cada respuesta (correcto o no, explicación, fragmento y
   minuto de la clase) y **cierre de sesión** con temas, Bloom, fallos, nivel y XP.
4. **Refuerzo dirigido** generado a la medida del perfil (ítems, explicaciones, flashcards), con
   créditos y reembolso.
5. **Ritmo**: flashcards con SM-2, cola de repaso del curso, plan de hoy, meta diaria, racha.
6. **Olvido por tema**: vida media de la retención; lo dominado que se está olvidando aparece
   "en riesgo" y entra al plan antes de que haya que reaprenderlo.
7. **Simulacro**: examen de longitud fija sobre todo el curso, cobertura proporcional de temas,
   nota vigesimal.
8. **Resúmenes** por clase y acumulado del curso, generados en la cola de trabajos.
9. **Progreso** de dos semanas (respuestas, aciertos, habilidad) en curso e inicio;
   **recordatorios** por correo; **banco del curso** con evidencia de calibración y CSV.
10. **Operación**: cola en hilos (un proceso) o worker aparte en BD (`run_worker`), reencolado de
    huérfanos, `/salud/` para monitoreo, límite de trabajos pendientes por usuario, cabeceras de
    seguridad y logging rotativo para producción.
11. **Curso como unidad de estudio**: editar, archivar y restaurar; fecha de examen con cuenta regresiva
    que pone el simulacro al frente del plan cuando faltan 10 días o menos.

## 3. Cómo probarlo en 15 minutos

Requisitos: `.env` con tu clave de DeepSeek rotada (`CLOUD_API_KEY`), Postgres arriba.

```bash
python manage.py migrate
python manage.py test learning
python manage.py runserver 127.0.0.1:8002
```

Luego, con tu usuario en http://127.0.0.1:8002 :

| Paso | Dónde | Qué esperar |
|---|---|---|
| 1. Sube una clase en texto (pega 2–3 páginas de apuntes) | Curso → **Nueva clase** | Estado en vivo; al terminar, "N preguntas" y el banco del curso crece |
| 2. Practica | Curso → **Practicar** | Tras cada respuesta, franja verde/roja con la opción correcta y el fragmento de la clase |
| 3. Cierra la sesión | misma página | Temas, Bloom, fallos con extracto, nivel antes/después, recomendaciones |
| 4. Simulacro | Curso → **Simulacro** | Longitud fija, nota sobre 20 |
| 5. Refuerzo | Curso → **Generar refuerzo** | Cobra créditos; página de estado; al terminar, preguntas y explicaciones nuevas |
| 6. Resumen | Clase → **Resumen** / Curso → **Resumen del curso** | Cobra créditos, "En cola", la página se refresca sola hasta mostrar el resumen |
| 7. Repaso | Curso → **Repasar** | Tarjetas con De nuevo / Difícil / Bien / Fácil; intervalos SM-2 |
| 8. Banco | Curso → enlace "N preguntas en el banco" | Dificultad generada vs calibrada, uso, banderas; CSV |
| 9. Progreso | Curso e Inicio | Gráfico de dos semanas |
| 10. Salud | http://127.0.0.1:8002/salud/ | JSON con BD, cola y backend |
| 11. Editar curso | Curso → **Editar** | Pon una fecha de examen a 3 días: la cabecera muestra "Examen en 3 dias" y el plan propone el simulacro primero |
| 12. Archivar | Curso → **Archivar** | Desaparece del panel; en Inicio → Cursos aparece "Cursos archivados" con **Restaurar** |
| 13. Límite | Pide tres resúmenes seguidos de clases distintas | El cuarto avisa "trabajos en proceso" sin cobrar |

Para el worker aparte (opcional): pon `SIMA_QUEUE_MODE=db` en `.env`, reinicia el web y en otra
terminal `python manage.py run_worker`. Con `--once` sirve para el Programador de tareas.

Recordatorios por correo: marca la casilla en Inicio → Preferencias y ejecuta
`python manage.py send_study_reminders --dry-run` (con el backend de consola imprime el correo).

## 4. Decisiones que son tuyas

1. **Rotar la clave de DeepSeek** y actualizar `.env` (sigue expuesta en el historial remoto).
2. **Subir los commits**: `git push origin main fix-localmodel`; borrar `origin/dev-erick`.
3. **Modo de cola en despliegue**: `thread` (un proceso, simple) o `db` + `run_worker` (recomendado
   si el web corre con gunicorn/varios procesos).
4. **Producción**: con `DJANGO_DEBUG=0` hace falta `DJANGO_SECRET_KEY` (la app se niega a arrancar sin
   ella) y conviene `CSRF_TRUSTED_ORIGINS`, `SECURE_SSL_REDIRECT`/`BEHIND_PROXY` según el proxy; ver
   `.env.example`. Los logs quedan en `logs/sima.log`.
5. **Parámetros del motor** (umbrales de BKT, vida media base, puerta de calidad): están como
   constantes al inicio de `learning/adaptive.py` y `learning/psychometrics.py`; conviene ajustarlos
   con datos reales de un ciclo.
6. **Plan gratuito**: si incluye algún refuerzo o resumen al mes (hoy cobran créditos siempre).
7. **Diagramas C4**: los `.dsl` de `docs/` se regeneran con Structurizr Lite o el sitio de Structurizr
   si quieres las imágenes para el documento de tesis; el contenido ya refleja el sistema actual.

## 5. Referencias del motor (para la sustentación)

- Bock & Mislevy (1982), estimación EAP de la habilidad.
- Kingsbury & Zara (1989), selección randomesque para controlar la exposición.
- Pelánek (2016), calibración de dificultad tipo Elo en sistemas de aprendizaje.
- Corbett & Anderson (1994), Bayesian Knowledge Tracing.
- Settles & Meeder (2016), regresión de vida media para modelar el olvido.
- Wozniak (1990), algoritmo SM-2 de repetición espaciada.
- Sympson & Hetter (1985), control de exposición (sustituido por exclusión reciente + randomesque).
