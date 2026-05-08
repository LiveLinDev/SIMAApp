# SIMA – Contexto funcional para agente de desarrollo

## 1. Nombre del proyecto

**SIMA**  
**Plataforma de microaprendizaje basada en inteligencia artificial para la generación de contenido educativo personalizado y evaluaciones adaptativas orientadas al seguimiento progresivo del estudiante a partir de clases universitarias grabadas en Perú.**

---

## 2. Propósito general

SIMA debe funcionar como una plataforma personal de estudio para estudiantes universitarios. El sistema debe permitir que cada estudiante registre sus cursos, suba clases grabadas y obtenga automáticamente materiales de aprendizaje personalizados, como resúmenes, flashcards, quizzes y evaluaciones adaptativas.

La plataforma no debe tratar cada audio como un archivo aislado. Cada clase subida debe pertenecer a un curso creado por el usuario, de modo que la inteligencia artificial tenga contexto sobre la materia, el progreso del estudiante y las evaluaciones generadas anteriormente.

---

## 3. Enfoque principal de la plataforma

La plataforma debe centrarse en tres ideas:

1. **Microaprendizaje personalizado:** convertir clases largas en contenidos breves y útiles.
2. **Evaluación adaptativa por curso:** generar preguntas y adaptar la dificultad según el desempeño del estudiante.
3. **Seguimiento progresivo:** mostrar evolución, fortalezas, debilidades, rachas y recomendaciones de estudio.

---

## 4. Flujo general del usuario

### 4.1 Registro e inicio

El usuario debe poder:

- Crear una cuenta.
- Iniciar sesión.
- Elegir un plan gratuito o de pago.
- Recibir créditos según el plan elegido.
- Consultar sus créditos disponibles.
- Ver el historial de uso de créditos.

Los créditos sirven para limitar el uso de funciones costosas, como transcripción de audio, generación de resúmenes, flashcards y quizzes mediante IA.

### 4.2 Selección de plan y créditos

El sistema debe manejar planes como:

- **Plan gratuito:** créditos limitados.
- **Plan estándar:** más minutos de audio y más generaciones.
- **Plan premium:** mayor capacidad de procesamiento y funciones avanzadas.

Cada acción debe descontar créditos según su costo:

- Subir y transcribir clase.
- Generar resumen.
- Generar flashcards.
- Generar quiz.
- Generar evaluación adaptativa.
- Regenerar contenido.

La app debe mostrar antes del procesamiento cuántos créditos se consumirán.

---

## 5. Gestión de cursos

El estudiante debe crear cursos antes de subir clases.

### 5.1 Datos mínimos de un curso

Cada curso debe tener:

- Nombre del curso.
- Ciclo o periodo académico.
- Descripción opcional.
- Docente opcional.
- Temas principales.
- Nivel aproximado del curso.
- Objetivo del estudiante.

Ejemplo:

```txt
Curso: Biología General
Ciclo: 2026-1
Temas: fotosíntesis, célula, genética, respiración celular
Objetivo: prepararse para parciales y reforzar conceptos semanales
```

### 5.2 Importancia del curso como contexto

Cada curso funciona como un contenedor de:

- Clases grabadas.
- Transcripciones.
- Resúmenes.
- Flashcards.
- Quizzes.
- Evaluaciones adaptativas.
- Historial de respuestas.
- Progreso del estudiante.
- Temas fuertes y débiles.

La IA debe usar el contexto del curso para generar materiales coherentes con la asignatura.

---

## 6. Dashboard principal del estudiante

El dashboard debe mostrar una visión general del progreso del usuario.

Debe incluir:

- Cursos registrados.
- Créditos disponibles.
- Racha actual.
- Actividad reciente.
- Próximas recomendaciones.
- Progreso general.
- Notificaciones de repaso.
- Clases procesadas recientemente.

Ejemplo de recomendaciones:

```txt
Repasa fotosíntesis: fallaste 3 preguntas de análisis.
Completa 10 flashcards para mantener tu racha.
Tienes una evaluación pendiente en Biología General.
```

---

## 7. Subida de clases grabadas

El usuario debe subir clases dentro de un curso específico.

### 7.1 Datos de una clase

Cada clase debe tener:

- Curso asociado.
- Título de la clase.
- Archivo de audio o video.
- Fecha de la clase.
- Tema principal opcional.
- Duración.
- Estado de procesamiento.

Ejemplo:

```txt
Curso: Biología General
Clase: Fotosíntesis y respiración celular
Duración: 45 min
Procesamiento solicitado: transcripción + resumen + flashcards + quiz
```

### 7.2 Validaciones

Antes de procesar:

- Verificar que el usuario tenga créditos suficientes.
- Validar formato del archivo.
- Calcular costo estimado en créditos.
- Confirmar procesamiento con el usuario.

---

## 8. Pipeline de procesamiento de una clase

El pipeline principal debe ser:

```txt
Audio/Video
→ Transcripción automática
→ Limpieza textual
→ Segmentación temática
→ Extracción de conceptos clave
→ Generación de resumen
→ Generación de flashcards
→ Generación de preguntas
→ Evaluación adaptativa
→ Retroalimentación personalizada
→ Almacenamiento por curso
```

---

## 9. Transcripción automática

El sistema debe convertir la clase grabada en texto.

### 9.1 Tecnología sugerida

- Whisper u otro modelo Speech-to-Text.
- Procesamiento por bloques de audio.
- Soporte para marcas de tiempo.

### 9.2 Datos generados

La transcripción debe guardar:

- Texto completo.
- Timestamps.
- Segmentos.
- Confianza promedio, si está disponible.
- Referencia al archivo original.
- Curso y clase asociados.

---

## 10. Limpieza y estructuración del texto

Después de transcribir, el texto debe ser procesado para hacerlo útil.

Funciones esperadas:

- Restaurar puntuación.
- Corregir errores básicos.
- Separar párrafos.
- Detectar temas.
- Identificar conceptos clave.
- Detectar definiciones.
- Detectar ejemplos.
- Detectar posibles preguntas.

El resultado debe ser una transcripción organizada, no solo texto plano.

---

## 11. Generación de microcontenidos

A partir de la transcripción procesada, el sistema debe generar:

### 11.1 Resúmenes

- Resumen breve.
- Resumen estructurado por temas.
- Resumen por clase.
- Resumen acumulado del curso como función futura.

### 11.2 Flashcards

Cada flashcard debe tener:

- Pregunta o concepto.
- Respuesta.
- Tema.
- Dificultad.
- Curso.
- Clase de origen.
- Timestamp o referencia textual.

Ejemplo:

```txt
Pregunta: ¿Dónde ocurre la fotosíntesis?
Respuesta: En los cloroplastos.
Tema: Fotosíntesis
Dificultad: Baja
```

### 11.3 Quizzes

Cada quiz debe estar asociado a:

- Curso.
- Clase.
- Tema.
- Nivel cognitivo.
- Dificultad.
- Historial de respuestas del estudiante.

### 11.4 Glosario

El sistema puede generar términos importantes con definiciones breves.

---

## 12. Taxonomía de Bloom

La generación de preguntas debe usar la Taxonomía de Bloom para clasificar el nivel cognitivo.

Niveles:

- Recordar.
- Comprender.
- Aplicar.
- Analizar.
- Evaluar.
- Crear.

Ejemplo:

```txt
Pregunta: ¿Dónde ocurre la fotosíntesis?
Bloom: Recordar
Dificultad: Baja

Pregunta: ¿Qué ocurriría si una planta no recibe luz?
Bloom: Analizar
Dificultad: Alta
```

Bloom se usa para organizar pedagógicamente los ítems.

---

## 13. Evaluación adaptativa

La evaluación adaptativa debe funcionar por curso, no de forma global.

Cada curso debe tener su propio perfil de progreso.

### 13.1 Datos por curso

Para cada estudiante y curso se debe guardar:

- Nivel estimado.
- Temas dominados.
- Temas débiles.
- Preguntas respondidas.
- Historial de aciertos.
- Historial de errores.
- Dificultad recomendada.
- Evolución temporal.

### 13.2 Uso de IRT/CAT

IRT/CAT se usa para adaptar la dificultad de las preguntas según el desempeño.

Bloom clasifica el nivel cognitivo. IRT/CAT decide qué pregunta mostrar según el rendimiento.

Ejemplo:

```txt
Bloom: Comprender
Dificultad IRT: Media
Tema: Fotosíntesis
Estado del estudiante: necesita refuerzo
```

---

## 14. Retroalimentación personalizada

Después de cada quiz, el sistema debe generar retroalimentación clara.

Debe incluir:

- Puntaje obtenido.
- Preguntas correctas.
- Preguntas incorrectas.
- Explicación del error.
- Tema relacionado.
- Nivel Bloom afectado.
- Recomendación de estudio.
- Flashcards sugeridas.
- Próxima dificultad recomendada.

Ejemplo:

```txt
Tuviste buen desempeño en preguntas de memoria, pero fallaste en preguntas de análisis.
Se recomienda repasar el tema "función de la luz en la fotosíntesis" y completar 5 flashcards antes del siguiente quiz.
```

---

## 15. Ruta de estudio adaptativa

El sistema debe generar una ruta sugerida por curso.

Ejemplo:

```txt
Ruta recomendada:
1. Leer resumen de la clase.
2. Repasar 10 flashcards.
3. Resolver quiz de dificultad media.
4. Revisar preguntas falladas.
5. Repetir conceptos débiles en 48 horas.
6. Avanzar al siguiente tema.
```

La ruta cambia según:

- Aciertos.
- Errores.
- Tiempo sin estudiar.
- Racha.
- Temas pendientes.
- Nivel de dificultad.

---

## 16. Sistema de racha y gamificación

La plataforma debe incluir gamificación para fomentar hábito de estudio.

### 16.1 Racha

La racha se mantiene si el estudiante realiza una acción útil de aprendizaje.

Acciones válidas:

- Responder un quiz.
- Repasar flashcards.
- Revisar errores.
- Subir una clase.
- Completar una evaluación.
- Estudiar un mínimo de tiempo.
- Cumplir una recomendación diaria.

### 16.2 Elementos de gamificación

- Racha diaria.
- XP por actividad.
- Insignias.
- Niveles.
- Metas semanales.
- Recordatorios.
- Logros por curso.

Ejemplos de insignias:

```txt
Primera clase procesada
7 días de racha
Dominio de un tema
Primer quiz perfecto
Curso con 10 clases procesadas
```

---

## 17. Vista del curso

Cada curso debe tener una pantalla propia.

Debe mostrar:

- Nombre del curso.
- Progreso general.
- Clases subidas.
- Materiales generados.
- Resúmenes.
- Flashcards.
- Quizzes.
- Evaluaciones adaptativas.
- Temas fuertes.
- Temas débiles.
- Racha del curso.
- Recomendaciones.

Ejemplo:

```txt
Curso: Biología General
Dominio general: 68%
Clases procesadas: 4
Flashcards creadas: 80
Quizzes completados: 6
Tema débil: respiración celular
Recomendación: resolver quiz de dificultad media
```

---

## 18. Vista de clase procesada

Cada clase procesada debe mostrar:

- Audio o video original.
- Transcripción completa.
- Transcripción por segmentos.
- Resumen.
- Conceptos clave.
- Flashcards generadas.
- Quiz generado.
- Preguntas falladas.
- Botón para generar más preguntas.
- Botón para exportar resumen.
- Timestamps para volver al audio original.

---

## 19. Formato `.mini`

SIMA debe usar el formato `.mini` como salida compacta de IA.

### 19.1 Propósito

El formato `.mini` reduce el consumo de tokens en respuestas de Claude API.

En lugar de pedir JSON completo, se solicita a Claude una salida comprimida usando separadores y campos abreviados.

### 19.2 Flujo del formato `.mini`

```txt
Claude API
→ salida .mini
→ parser en JavaScript
→ JSON
→ API REST
→ base de datos
```

### 19.3 Ventaja

`.mini` no es el formato final de almacenamiento. Es una capa intermedia optimizada para reducir costos de generación.

El backend debe trabajar con JSON ya parseado.

### 19.4 Ejemplo conceptual

```txt
i1|Recordar|La fotosíntesis ocurre en ___|raíces,cloroplastos*,flores,tallo|low
i2|Analizar|Sin luz, la planta ___|muere a largo plazo*,crece más,vive igual,produce más O2|high
```

Luego JavaScript convierte eso a:

```json
[
  {
    "id": "i1",
    "bloom": "Recordar",
    "question": "La fotosíntesis ocurre en ___",
    "options": ["raíces", "cloroplastos", "flores", "tallo"],
    "correct_answer": "cloroplastos",
    "difficulty": "low"
  },
  {
    "id": "i2",
    "bloom": "Analizar",
    "question": "Sin luz, la planta ___",
    "options": ["muere a largo plazo", "crece más", "vive igual", "produce más O2"],
    "correct_answer": "muere a largo plazo",
    "difficulty": "high"
  }
]
```

---

## 20. API REST

El sistema debe enviar el JSON final a servicios API REST.

Servicios esperados:

- Crear curso.
- Listar cursos.
- Subir clase.
- Procesar clase.
- Guardar transcripción.
- Guardar resumen.
- Guardar flashcards.
- Guardar quiz.
- Registrar respuesta.
- Actualizar progreso.
- Consultar recomendaciones.
- Consultar créditos.
- Actualizar racha.

---

## 21. Base de datos

La base de datos debe organizar la información por usuario, curso y clase.

Entidades principales:

- User.
- Plan.
- Credits.
- Course.
- ClassSession.
- Transcript.
- Segment.
- Summary.
- Flashcard.
- Quiz.
- Question.
- Answer.
- AdaptiveProfile.
- StudyStreak.
- Recommendation.

Relación principal:

```txt
User
→ Courses
→ ClassSessions
→ Transcripts
→ Microcontents
→ Quizzes
→ Answers
→ Progress
```

---

## 22. Seguimiento progresivo

El seguimiento progresivo debe mostrar evolución del estudiante en el tiempo.

Métricas sugeridas:

- Dominio general por curso.
- Dominio por tema.
- Preguntas respondidas.
- Porcentaje de aciertos.
- Flashcards dominadas.
- Tiempo de estudio.
- Racha.
- Evolución semanal.
- Temas con mayor error.
- Progreso por nivel Bloom.

Ejemplo:

```txt
Semana 1: 45% dominio
Semana 2: 58% dominio
Semana 3: 72% dominio
```

---

## 23. Recomendaciones inteligentes

El sistema debe generar recomendaciones usando el historial del estudiante.

Ejemplos:

```txt
Repasa el tema "fotosíntesis" porque tuviste 40% de aciertos.
Completa 5 flashcards para mantener tu racha.
Resuelve una evaluación corta de dificultad media.
Vuelve a revisar la clase del minuto 12:30 al 18:00.
```

---

## 24. Posible módulo docente

Para el MVP, el enfoque principal es el estudiante. Como función futura, puede existir un rol docente.

El docente podría:

- Crear cursos oficiales.
- Subir clases para todos.
- Revisar materiales generados.
- Aprobar preguntas.
- Ver analíticas grupales.
- Detectar temas donde muchos estudiantes fallan.

---

## 25. Flujo final resumido

```txt
1. Usuario se registra.
2. Elige plan.
3. Recibe créditos.
4. Crea cursos.
5. Sube clase dentro de un curso.
6. Se calcula costo en créditos.
7. Se transcribe el audio.
8. Se limpia y segmenta el texto.
9. La IA genera microcontenidos en .mini.
10. JavaScript convierte .mini a JSON.
11. JSON se envía a servicios API REST.
12. Se guardan materiales por curso.
13. El estudiante responde quizzes.
14. El sistema adapta dificultad y registra progreso.
15. Se generan recomendaciones.
16. Se actualiza racha y dashboard.
```

---

## 26. Definición corta de SIMA

**SIMA es una plataforma personal de microaprendizaje que permite a estudiantes universitarios crear cursos, subir clases grabadas y generar automáticamente resúmenes, flashcards, quizzes y evaluaciones adaptativas, manteniendo seguimiento progresivo por curso mediante IA, créditos de uso y gamificación.**

---

## 27. Prioridades para el MVP

### Ya implementado

- Registro de usuario.
- Selección de plan.
- Créditos por plan.
- Subida de grabaciones.
- Generación de evaluación con IA.
- Guardado asociado al usuario.

### Próximos pasos recomendados

1. Implementar creación de cursos.
2. Asociar cada clase subida a un curso.
3. Guardar progreso por curso.
4. Añadir parser `.mini` a JSON con JavaScript.
5. Generar resúmenes y flashcards además de quizzes.
6. Implementar racha diaria.
7. Crear dashboard del estudiante.
8. Añadir retroalimentación personalizada.
9. Implementar niveles Bloom en preguntas.
10. Preparar base para evaluación adaptativa por curso.

---

## 28. Principio de diseño

La plataforma debe sentirse como un espacio personal de aprendizaje.

El usuario no solo sube audios. El usuario construye su propio entorno académico, curso por curso, y la IA acompaña su progreso.
