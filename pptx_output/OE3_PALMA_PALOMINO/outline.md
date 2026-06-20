# Presentation Outline

## Page 1 [cover]
- **Title**: OE3 – Desarrollo e Implementación de SIMA
- **Content**: Plataforma inteligente de microaprendizaje basada en IA | Erick Palomino | Adrián Palma

## Page 2 [table_of_contents]
- **Title**: Agenda
- **Content**: 1. Introducción OE3; 2. Stack Tecnológico; 3. Product Backlog; 4. Pipeline de Desarrollo; 5. Vistas del Sistema; 6. Arquitectura; 7. Evaluación Adaptativa; 8. Futuro y Validación OE4; 9. Conclusiones

## Page 3 [content]
- **Title**: Objetivo Específico 3 – Desarrollo e Implementación
- **Content**: Desarrollar una plataforma inteligente de microaprendizaje que integre módulos de transcripción automática, postprocesamiento, generación de microcontenidos educativos y evaluaciones adaptativas personalizadas, orientadas al seguimiento del progreso del estudiante. La implementación prioriza ejecución local, trazabilidad técnica y control de calidad educativo.

## Page 4 [content]
- **Title**: Entorno Tecnológico y Stack de Desarrollo
- **Content**: Tabla comparativa de capas: Aplicación web (Django 5.2), IA local (Qwen3-30B compatible OpenAI), Proxy IA (Node proxy 8003), Transcripción (Whisper local), Búsqueda web (ddgs + urllib/HTML), Persistencia (PostgreSQL / SQLite dev), Evaluación (IRT 3PL propio). Explicación de la configuración de IA local apuntando a 127.0.0.1:8003/v1.

## Page 5 [content]
- **Title**: Épicas del Product Backlog
- **Content**: 5 épicas principales: Ingesta y transcripción inteligente de clases; Estructuración semántica de conocimiento; Validación pedagógica con verificación web; Persistencia y modelado de conocimiento educativo; Generación de aprendizaje adaptativo y seguimiento de progreso. Cada una con Story Points y prioridad Alta.

## Page 6 [content]
- **Title**: Historias de Usuario – Ingesta y Persistencia
- **Content**: Tabla de historias: (1) Como estudiante, quiero subir una clase grabada y ver su progreso de procesamiento en tiempo real mediante un pipeline de etapas. (2) Como estudiante, quiero ver el costo en créditos antes de confirmar el procesamiento. (3) Como estudiante, quiero agrupar mis clases en cursos y visualizar mi avance por curso. Criterios de aceptación BDD y Story Points.

## Page 7 [content]
- **Title**: Historias de Usuario – Generación y Evaluación
- **Content**: Tabla de historias: (4) Como estudiante, quiero que el sistema genere automáticamente flashcards, quizzes y un mapa conceptual a partir de mi clase. (5) Como estudiante, quiero realizar el cuestionario múltiples veces con dificultad adaptativa mediante IRT. (6) Como estudiante, quiero recibir retroalimentación personalizada con mi nivel pedagógico y recomendaciones de estudio. Criterios BDD y Story Points.

## Page 8 [content]
- **Title**: Pipeline de Desarrollo Implementado
- **Content**: Diagrama de flujo del pipeline: Preparación (texto/audio) → Transcripción (Whisper local) → Generación (contenido + PROMPT.md → MINI inicial) → Coherencia (MINI revisado con trace) → Verificación (MINI + fuentes web → reporte eN) → Corrección (MINI final con cambios trazables) → Estudio (quiz, flashcards, mapa, ejercicios). Cada etapa con entrada, salida y control de calidad.

## Page 9 [content]
- **Title**: Vista – Dashboard y Landing
- **Content**: Capturas de pantalla del dashboard principal (vista clara con cursos, créditos, racha, actividad reciente) y landing page. Descripción de las funcionalidades visibles: cursos registrados, créditos disponibles, racha actual, progreso general, clases procesadas recientemente. Referencia a las capturas: dashboard_light.png y landing_light.png.

## Page 10 [content]
- **Title**: Vista – Gestión de Cursos y Clases
- **Content**: Capturas de la creación de curso, formulario de subida de clase, detalle de clase con transcripción, lista de clases por curso. Funcionalidades: creación de curso con nombre, ciclo, temas y objetivo; subida de audio/video con cálculo de créditos; visualización de progreso por curso. Referencia: course-detail.png, course-form.png, lesson-detail.png.

## Page 11 [content]
- **Title**: Vista – Pipeline de Procesamiento
- **Content**: Captura del pipeline de procesamiento visual por etapas (carga, transcripción, extracción, validación) con estados en tiempo real. Explicación de la trazabilidad: cada etapa expone prompt, entrada, salida, evidencia web y correcciones. Modal de verificación con fuentes. Referencia: pipeline_viz_light.png, pipeline_verification_modal.png.

## Page 12 [content]
- **Title**: Vista – Microcontenidos Generados
- **Content**: Capturas de flashcards, mapa conceptual de clase (class-map), ejercicio de emparejamiento (matching), ejercicio de completar (cloze). Descripción: cada microcontenido se genera a partir del MINI final parseado. Flashcards con pregunta/respuesta/tema. Mapa con nodos de dominio. Referencia: flashcards.png, class-map.png, matching.png, cloze.png.

## Page 13 [content]
- **Title**: Vista – Quiz Adaptativo
- **Content**: Capturas del quiz en ejecución (pregunta con 4 alternativas, temporizador, nivel Bloom) y resultado final. Descripción: selección de items por información IRT, descarte de items sin 4 alternativas, traducción de theta a nivel pedagógico 1-7. Referencia: quiz-active.png, quiz-result.png.

## Page 14 [content]
- **Title**: Vista – Resultados y Seguimiento de Progreso
- **Content**: Captura de resultados del quiz con precisión, XP, racha, historial CAT, niveles Bloom respondidos. Descripción del seguimiento: theta estimado, error estándar, nivel pedagógico (Inicial a Experto), temas fuertes y débiles, recomendaciones inteligentes. Referencia: quiz-results.png, lesson-detail-with-history.png.

## Page 15 [content]
- **Title**: Arquitectura del Sistema – C4 Contenedores y Componentes
- **Content**: Descripción de la arquitectura C4: Contexto (estudiante, SIMA, Whisper, Qwen local, buscador web, BD) y Contenedores (interfaz web, backend Django, cola local, servicios de IA, persistencia). Componentes internos: generación, verificación, parseo MINI, CAT/IRT y progreso. Mención de las figuras de arquitectura ya documentadas en OE2.

## Page 16 [content]
- **Title**: Evaluación Adaptativa con IRT 3PL
- **Content**: Explicación del modelo IRT 3PL con parámetros a, b y c por item. Estimación de theta y error estándar después de cada respuesta. Selección de la siguiente pregunta por máxima información. Traducción de theta (-3 a +3) a nivel pedagógico 1-7: Inicial, Básico, En desarrollo, Intermedio, Avanzado, Dominio, Experto. Filtro de banco: solo items con exactamente 4 alternativas.

## Page 17 [content]
- **Title**: Futuro del Desarrollo y Validación en OE4
- **Content**: Lo que falta a futuro: implementar creación de cursos, asociar cada clase a un curso, guardar progreso por curso, añadir parser .mini a JSON con JavaScript, generar resúmenes y flashcards además de quizzes, implementar racha diaria, crear dashboard del estudiante, añadir retroalimentación personalizada, implementar niveles Bloom en preguntas, preparar base para evaluación adaptativa por curso. Validación OE4: pruebas funcionales (≥15), métricas automáticas (precisión transcripción ≥85%, calidad NLP ≥80%), evaluaciones experimentales antes/después (≥15% mejora), porcentaje de casos superados ≥85%.

## Page 18 [final]
- **Title**: Conclusiones
- **Content**: SIMA integra transcripción, generación educativa, verificación externa y evaluación adaptativa en un flujo local trazable. La IA local protege el control del entorno y permite demostrar trazas completas del pipeline. La verificación web con consultas generadas por IA mejora la auditabilidad. El mapeo de theta a niveles pedagógicos hace comprensible el resultado. La vista pipeline convierte el proceso interno en evidencia de desarrollo para sustentación. Gracias.
