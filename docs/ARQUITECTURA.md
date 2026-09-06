# Arquitectura de SIMA (septiembre 2026)

Monolito Django con una sola app (`learning`) organizada por responsabilidad. Este documento
describe los módulos y los tres flujos principales. Los diagramas C4 (`c4-contexto.dsl`,
`c4-contenedores.dsl`, `c4-componentes.dsl`) están sincronizados con este estado.

## Módulos

| Paquete / módulo | Responsabilidad |
|---|---|
| `learning/views/` | Vistas por dominio: `core` (inicio, panel, salud), `courses`, `lessons`, `practice`, `study`, `summaries_views`, `pipeline`, `_common` (ayudantes). `__init__` reexporta nombres explícitos: una vista nueva se agrega ahí. |
| `learning/services/` | Servicios de IA: `prompts`, `backends` (proveedores y `call_ai`), `generation` (chunks y presupuesto de ítems), `repairs` (verificación y reparaciones), `evidence` (web y EduQG), `transcription` (Whisper). `__init__` reexporta todo. |
| `job_queue.py` | Pipeline de una clase y cola de trabajos. Modo `thread` (hilos en el web) o `db` (worker aparte que reclama en la base). Reencolado de huérfanos, límite de trabajos por usuario, instantánea para `/salud/`. |
| `parse_mini.py` | Formato `.mini`: parser, serializador, filtros deterministas, aplicación de correcciones. |
| `cat.py`, `psychometrics.py` | IRT 3PL; EAP, randomesque, calibración Elo, Bayesian Knowledge Tracing, puerta de calidad. |
| `adaptive.py` | Banco del curso, sesión de práctica (modos equilibrada / débiles / riesgo / simulacro), perfil por tema y Bloom, olvido por vida media, plan de hoy, recomendaciones, XP y racha, informe del banco. |
| `adaptive_generation.py` | Refuerzo dirigido (`ReinforcementJob`). |
| `summaries.py` | Resúmenes de clase y de curso (`SummaryJob`). |
| `spaced_repetition.py` | SM-2 y cola de repaso. |
| `segments.py` | Segmentos con tiempo y enlace pregunta ↔ fragmento de la clase. |
| `progress.py`, `reminders.py` | Serie de dos semanas con SVG; correos de recordatorio. |
| `credits.py` | Planes, estimaciones, cobro y reembolso (ledger). |
| `models.py` | Modelo de datos (23 migraciones). |
| `management/commands/` | `run_worker`, `requeue_jobs`, `sync_question_bank`, `send_study_reminders`. |

## Flujo 1: de la clase al banco de preguntas

```
POST /api/nueva/ ──► LessonJob(QUEUED) + cobro de créditos
   │  (thread) hilo del web            (db) manage.py run_worker reclama con skip_locked
   ▼
process_lesson_job
   Whisper (audio) ──► transcript + TranscriptSegment (minuto)
   generation: chunks ──► call_ai ──► .mini bruto
   parse_mini: filtros de coherencia y uniformidad ──► repairs (no descarte)
   repairs: verificación factual (web / eduqg / hybrid, o MINI directo) ──► correcciones con traza
   status = corrected ──► ClassSession READY ──► Transcript
   adaptive.sync_question_bank ──► Question / AnswerOption ──► segments.attach_sources (fragmento y minuto)
```

## Flujo 2: práctica adaptativa con memoria

```
POST /cursos/<id>/practicar/ (focus: balanced | weak | risk | exam)
   start_practice: banco del curso (sin ítems apartados) · θ inicial y prior desde AdaptiveProfile
   select_next_item: información de Fisher + balance Bloom + empuje a temas débiles/nunca vistos
                     (exam: cobertura proporcional de temas) · randomesque k = 5
   answer_question: StudentAnswer · EAP(θ, SE) · calibración Elo del ítem · puerta de calidad
                     ──► redirect ?last=<respuesta> ──► franja con la opción correcta, explicación,
                         fragmento y minuto de la clase
   parada: n ≥ objetivo, o SE ≤ 0.30 con n ≥ 4 (no en simulacro), o banco agotado
   finish_session: retroalimentación · update_profile (BKT por tema y Bloom, vida media de retención)
                   · recomendaciones · XP y racha
```

## Flujo 3: el día del estudiante

```
Inicio «Hoy en SIMA» y curso ──► adaptive.daily_plan
   1 tarjetas vencidas (SM-2)            ──► /cursos/<id>/repasar/
   1 examen a ≤ 10 días                  ──► simulacro
   2 tema débil                          ──► práctica focus=weak · generar refuerzo (ReinforcementJob)
   2 tema en riesgo de olvido            ──► práctica focus=risk
   3 fallos recientes                    ──► retroalimentación de la última sesión
   3 nivel impreciso o días sin practicar──► práctica equilibrada
   4 clase sin trabajar                  ──► práctica filtrada a esa clase
   5 al día                              ──► subir una clase nueva
Recordatorio por correo (send_study_reminders) si no estudió hoy.
```

## Trabajos y créditos

Tres tipos de trabajo comparten el mismo ciclo: `LessonJob`, `ReinforcementJob`, `SummaryJob`.
La vista valida, comprueba el límite por usuario (`SIMA_MAX_PENDING_JOBS`), cobra créditos y deja
el trabajo en `QUEUED`; el worker lo marca `PROCESSING`, ejecuta y termina en `DONE`/`corrected`
o `ERROR` con reembolso. Un reinicio reencola lo pendiente (`requeue_jobs`, o el worker con
`--stale-minutes`).

## Configuración

Todo por variables de entorno (`.env`, ver `.env.example`): proveedor de IA (`CLOUD_*`), Whisper,
cola (`SIMA_QUEUE_MODE`, `SIMA_MAX_PENDING_JOBS`), correo (`EMAIL_*`, `SIMA_SITE_URL`) y producción
(`DJANGO_SECRET_KEY`, `CSRF_TRUSTED_ORIGINS`, `SECURE_*`, `BEHIND_PROXY`). Con `DJANGO_DEBUG=0` la
aplicación se niega a arrancar sin `DJANGO_SECRET_KEY`.
