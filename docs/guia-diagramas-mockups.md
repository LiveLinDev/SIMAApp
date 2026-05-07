# Guía para generar diagramas C4 y mockups de SIMA

Esta guía está pensada para que una IA genere los artefactos de arquitectura y diseño de SIMA.
Contiene todo el contexto del sistema actual y las funcionalidades planeadas.
Los diagramas se generan en **Structurizr DSL** y los mockups en **Figma** (via prompt para IA de diseño).

---

## Contexto del sistema actual

SIMA es una plataforma web de microaprendizaje para estudiantes universitarios peruanos.
Permite convertir grabaciones de clases o apuntes en material de estudio personalizado.

### Stack actual
- Backend: Django 4.x + SQLite (dev) / PostgreSQL (prod)
- IA: Claude (Anthropic API) para generación y verificación de contenido
- Transcripción: Whisper local (openai-whisper)
- Frontend: HTML + CSS vanilla (sin framework JS)
- Despliegue: servidor único, sin contenedores aún

### Funcionalidades existentes
- Registro y login de usuarios
- Planes de suscripción: Gratis, Básico ($5), Pro ($10), Ilimitado ($25)
- Creación de "LessonJob": el usuario sube texto o audio de una clase
- Transcripción automática del audio con Whisper
- Generación de contenido educativo (resumen, flashcards, quizzes) con Claude
- Verificación/validación del contenido generado con un segundo prompt a Claude
- Descarga del resultado en JSON
- Dashboard con historial de clases procesadas

### Funcionalidades planeadas (inspiradas en Duolingo)
- Racha diaria (streak) con contador y recompensas visuales
- Sistema de XP y niveles por actividad de estudio
- Flashcards interactivas con modo repaso espaciado (spaced repetition)
- Quizzes adaptativos: dificultad ajustada según rendimiento previo
- Mini-lecciones: fragmentos cortos del contenido de la clase
- Progreso por tema/materia con barra visual
- Notificaciones de repaso ("¿Repasaste hoy?")
- Perfil público con logros y estadísticas
- Modo móvil optimizado (PWA o responsive prioritario)

---

## Parte 1 — Diagramas C4 en Structurizr DSL

### Instrucciones para la IA

Genera los tres niveles del modelo C4 usando **Structurizr DSL**.
Usa el contexto del sistema descrito arriba.
El output debe ser un bloque de código DSL válido para pegar en https://structurizr.com/dsl

---

### C4 Nivel 1 — Diagrama de Contexto

**Prompt para la IA:**

```
Genera un diagrama C4 de Contexto en Structurizr DSL para el sistema SIMA.

Actores externos:
- Estudiante universitario: usa la plataforma web desde el navegador o móvil para subir clases y estudiar con el material generado.
- Administrador: gestiona usuarios y planes desde el panel de Django Admin.

Sistemas externos:
- Anthropic Claude API: servicio externo de IA que recibe prompts y devuelve contenido educativo generado (resúmenes, flashcards, quizzes).
- Whisper (local): modelo de transcripción de audio que corre en el mismo servidor, no es un servicio externo de red.

Sistema principal:
- SIMA: plataforma web de microaprendizaje que transforma grabaciones y apuntes de clases universitarias en material de estudio personalizado.

Relaciones:
- El Estudiante usa SIMA para subir clases, repasar flashcards, hacer quizzes y ver su progreso.
- El Administrador gestiona SIMA vía Django Admin.
- SIMA llama a Claude API para generar y verificar contenido educativo.
- SIMA usa Whisper localmente para transcribir audios subidos por el estudiante.

Estilo: usa colores diferenciados para el sistema principal (verde), actores (azul) y sistemas externos (gris).
```

---

### C4 Nivel 2 — Diagrama de Contenedores

**Prompt para la IA:**

```
Genera un diagrama C4 de Contenedores en Structurizr DSL para el sistema SIMA.

Contenedores dentro de SIMA:

1. Web Application (Django)
   - Tecnología: Python / Django 4.x
   - Responsabilidad: renderiza HTML server-side, maneja autenticación, rutas, lógica de negocio y orquesta los servicios de IA.
   - Expone: interfaz web HTML/CSS para el navegador.

2. Base de datos
   - Tecnología: SQLite (desarrollo) / PostgreSQL (producción)
   - Responsabilidad: almacena usuarios, perfiles, planes, LessonJobs (clases procesadas), transcripciones, outputs de IA, progreso del estudiante.

3. Almacenamiento de archivos
   - Tecnología: sistema de archivos local (carpeta /media)
   - Responsabilidad: guarda los archivos de audio subidos por los estudiantes antes de transcribir.

4. Servicio de transcripción (Whisper)
   - Tecnología: openai-whisper corriendo en proceso Python dentro del mismo servidor
   - Responsabilidad: convierte archivos de audio a texto para alimentar la generación de contenido.

5. Servicio de generación IA (Claude)
   - Tecnología: Anthropic Claude API (HTTP externo)
   - Responsabilidad: recibe prompts con el contenido de la clase y devuelve resúmenes, flashcards, quizzes y verificaciones.

Relaciones:
- El navegador del estudiante hace requests HTTP al Web Application.
- El Web Application lee y escribe en la Base de datos.
- El Web Application guarda y lee archivos de audio en Almacenamiento de archivos.
- El Web Application llama al Servicio de transcripción con la ruta del archivo de audio.
- El Web Application llama a Claude API con prompts y recibe el contenido generado.

Actores externos (heredados del nivel 1):
- Estudiante universitario
- Administrador

Estilo: diferencia contenedores internos (verde/azul) de sistemas externos (gris).
```

---

### C4 Nivel 3 — Diagrama de Componentes (Web Application)

**Prompt para la IA:**

```
Genera un diagrama C4 de Componentes en Structurizr DSL para el contenedor "Web Application (Django)" de SIMA.

Componentes dentro del Web Application:

1. Views (learning/views.py)
   - Responsabilidad: maneja las rutas HTTP. Contiene: home, register, dashboard, plans, free_lesson, api_lesson, lesson_detail, submit_toon, submit_verification, download_json.

2. Models (learning/models.py)
   - Responsabilidad: define las entidades del dominio: Profile (usuario + plan), LessonJob (clase procesada con su estado, transcripción, outputs de IA), Plan (free/basic/pro/unlimited).

3. Services (learning/services.py)
   - Responsabilidad: lógica de integración con IA. Funciones: build_generation_prompt, build_verification_prompt, call_claude, transcribe_audio, configure_local_ffmpeg.

4. Forms (learning/forms.py)
   - Responsabilidad: validación de inputs del usuario. Formularios: RegisterForm, FreeLessonForm, ApiLessonForm, PlanForm, ManualResultForm, VerificationResultForm.

5. Templates (templates/learning/)
   - Responsabilidad: renderizado HTML. Páginas: home (landing), dashboard, lesson_detail, lesson_form, plans.

6. Django Admin
   - Responsabilidad: interfaz de administración para gestionar usuarios, planes y jobs.

7. Auth (django.contrib.auth)
   - Responsabilidad: autenticación, sesiones y permisos de usuario.

Relaciones:
- Views usa Forms para validar inputs.
- Views usa Models para leer y escribir datos.
- Views usa Services para orquestar transcripción y generación de IA.
- Views renderiza Templates con el contexto de datos.
- Services llama a Claude API (externo) y a Whisper (local).
- Models persiste en la Base de datos (PostgreSQL/SQLite).
- Django Admin gestiona Models directamente.
- Auth protege las Views con @login_required.

Estilo: agrupa los componentes por capa (presentación, lógica, datos, integración).
```

---

## Parte 2 — Mockups en Figma

### Instrucciones para la IA de diseño (Figma AI / Galileo / v0 / similar)

El sistema de diseño de SIMA usa:
- Colores: verde primario `#58cc02`, verde oscuro `#46a302`, azul `#1cb0f6`, tinta `#24323f`, gris `#6b7a88`, fondo `#f8fcff`
- Tipografía: Inter, sans-serif
- Estilo: tarjetas con bordes redondeados (8-28px), sombras tipo "offset bottom" (box-shadow hacia abajo), botones con sombra inferior de color más oscuro
- Referencia visual: Duolingo (gamificado, colorido, mobile-first)
- Plataforma: web responsive, prioridad móvil

---

### Mockup 1 — Landing page (home)

**Prompt para Figma AI:**

```
Diseña el mockup de la landing page de SIMA, una plataforma de microaprendizaje para estudiantes universitarios.

Layout desktop (1280px): dos columnas. Izquierda: copy + CTAs. Derecha: preview de tarjeta de teléfono.
Layout móvil (390px): una columna, la tarjeta va arriba.

Sección hero:
- Eyebrow pequeño en verde: "Para estudiantes universitarios"
- Título grande (bold, ~5rem desktop): "Convierte tus clases en material de estudio listo para repasar"
- Subtítulo en gris: "Pega el texto de tus apuntes o sube el audio de una clase y SIMA genera resúmenes, preguntas de práctica y tarjetas de repaso en segundos."
- Dos botones en fila: "Empezar gratis" (verde, sombra verde oscuro) y "Ya tengo cuenta" (blanco, borde gris, sombra gris)
- Tarjeta de teléfono (330px ancho, bordes muy redondeados 28px, sombra inferior azul claro):
  - Badge amarillo redondeado: "12 días seguidos 🔥"
  - Título: "Fotosíntesis"
  - Subtítulo gris: "Biología — Semana 4"
  - Barra de progreso verde al 68%
  - Texto pequeño: "68% completado"
  - Botón azul: "Generar resumen"
  - Botón fantasma gris: "Ver preguntas"

Sección "¿Cómo funciona?" (fondo blanco, padding generoso):
- Título: "¿Cómo funciona?"
- Lista de 3 pasos en fila (desktop) o columna (móvil):
  1. Círculo verde con "1" + "Sube tu clase" + descripción corta
  2. Círculo verde con "2" + "SIMA lo procesa" + descripción corta
  3. Círculo verde con "3" + "Estudia a tu ritmo" + descripción corta

Sección de planes (4 tarjetas en fila desktop, 2x2 tablet, 1 columna móvil):
- Gratis $0, Básico $5, Pro $10 (destacado con borde verde), Ilimitado $25
- Cada tarjeta: badge de plan, precio grande, descripción, botón "Elegir plan"

Sistema de diseño: colores SIMA, Inter, estilo Duolingo.
```

---

### Mockup 2 — Dashboard del estudiante

**Prompt para Figma AI:**

```
Diseña el mockup del dashboard principal de SIMA para un estudiante autenticado.

Header (topbar):
- Logo SIMA a la izquierda (cuadrado verde redondeado con "S" + texto "SIMA")
- Navegación derecha: "Inicio", "Planes", botón "Salir"

Contenido principal:

Sección superior (dos columnas):
- Izquierda: saludo "Hola, [nombre]" pequeño en verde + título grande "Tu portafolio de clases"
- Derecha: tarjeta de estado con "Plan Pro", número grande en verde "14", texto "clases restantes este mes"

Sección de racha y XP (fila de 3 tarjetas pequeñas):
- Tarjeta 1: 🔥 "12 días" + "Racha actual"
- Tarjeta 2: ⚡ "340 XP" + "Esta semana"
- Tarjeta 3: 🏆 "Nivel 5" + "Estudiante avanzado"

Acciones rápidas (dos botones grandes en fila):
- "Nueva clase con IA" (verde, ícono de micrófono)
- "Clase manual" (blanco/borde, ícono de texto)

Lista de clases recientes (últimas 5):
- Cada fila: título de la clase + materia + estado (badge de color: "Completada" verde, "En proceso" amarillo) + flecha derecha
- Ejemplo de filas: "Fotosíntesis · Biología", "Revolución Industrial · Historia", "Derivadas · Cálculo"

Sección de progreso semanal:
- Mini gráfico de barras (7 días) mostrando minutos de estudio por día
- Título: "Esta semana"

Sistema de diseño: colores SIMA, Inter, estilo Duolingo, mobile-first.
```

---

### Mockup 3 — Sesión de flashcards / quiz

**Prompt para Figma AI:**

```
Diseña el mockup de la pantalla de sesión de estudio con flashcards de SIMA.
Esta pantalla es mobile-first (390px), también mostrar versión desktop centrada (max 480px).

Header de sesión:
- Botón X para salir (izquierda)
- Barra de progreso lineal verde (ej: 4/10 completadas)
- Contador de XP ganado en la sesión: "+20 XP" en verde (derecha)

Tarjeta de flashcard (centro, grande, bordes redondeados 20px, sombra):
- Parte frontal visible:
  - Badge pequeño arriba: "Fotosíntesis · Biología"
  - Pregunta grande centrada: "¿Qué organelo realiza la fotosíntesis?"
  - Ícono de "voltear" abajo en gris
- Estado "volteada" (segunda pantalla):
  - Respuesta: "El cloroplasto. Contiene clorofila que absorbe luz solar para convertir CO₂ y agua en glucosa."
  - Tres botones de autoevaluación en fila:
    - Rojo "Difícil" 
    - Amarillo "Regular"
    - Verde "Fácil"

Indicador de racha debajo de la tarjeta:
- "🔥 ¡Vas bien! 4 seguidas"

Mostrar también el estado de "respuesta correcta" con animación sugerida:
- Fondo verde claro, ícono de check grande, texto "¡Correcto!" y "+10 XP"

Sistema de diseño: colores SIMA, Inter, estilo Duolingo, animaciones suaves sugeridas con notas en el mockup.
```

---

### Mockup 4 — Detalle de clase procesada

**Prompt para Figma AI:**

```
Diseña el mockup de la pantalla de detalle de una clase procesada en SIMA.

Header:
- Eyebrow: "Clase con IA · Completada"
- Título grande: "Fotosíntesis"
- Badge de estado verde: "✓ Lista para estudiar"

Tabs de navegación horizontal (sticky):
- "Resumen" | "Flashcards (12)" | "Quiz" | "Transcripción"

Vista activa: "Resumen"
- Bloque de texto con el resumen generado por IA (3-4 párrafos de ejemplo)
- Botón flotante abajo: "Iniciar repaso →" (verde, ancho completo en móvil)

Vista: "Flashcards (12)"
- Grid de tarjetas pequeñas (2 columnas móvil, 3 desktop):
  - Cada tarjeta muestra la pregunta + badge de dificultad (verde/amarillo/rojo según historial)
  - Botón "Repasar todas" arriba

Vista: "Quiz"
- Pregunta de opción múltiple de ejemplo:
  - "¿Cuál es el producto principal de la fotosíntesis?"
  - 4 opciones como botones (A, B, C, D)
  - Una opción seleccionada en azul
  - Botón "Confirmar respuesta" verde

Barra lateral (solo desktop, 280px):
- Progreso de la clase: barra circular al 68%
- "8 de 12 flashcards dominadas"
- "Último repaso: hace 2 días"
- Botón "Descargar material"

Sistema de diseño: colores SIMA, Inter, estilo Duolingo.
```

---

### Mockup 5 — Perfil y logros del estudiante

**Prompt para Figma AI:**

```
Diseña el mockup de la pantalla de perfil y logros de un estudiante en SIMA.

Header de perfil:
- Avatar circular con iniciales del usuario (fondo verde)
- Nombre de usuario grande
- Nivel actual: "Nivel 5 · Estudiante Avanzado" con barra de XP hacia el siguiente nivel
- Estadísticas en fila: "12 🔥 días", "340 ⚡ XP", "24 📚 clases"

Sección de logros (badges):
- Grid de badges (3 columnas):
  - Badge desbloqueado (colorido): "Primera clase", "7 días seguidos", "Quiz perfecto", "10 clases"
  - Badge bloqueado (gris, candado): "30 días seguidos", "50 clases", "Maestro del quiz"
- Cada badge: ícono + nombre + descripción corta al hacer hover

Sección de materias estudiadas:
- Lista con barra de progreso por materia:
  - "Biología · 8 clases · ████████░░ 80%"
  - "Historia · 5 clases · ██████░░░░ 60%"
  - "Cálculo · 3 clases · ████░░░░░░ 40%"

Sección de actividad reciente (últimos 7 días):
- Calendario de calor estilo GitHub (7 columnas, colores verde según intensidad)

Sistema de diseño: colores SIMA, Inter, estilo Duolingo, mobile-first.
```

---

## Notas finales para la IA

- Para los diagramas C4: genera cada nivel por separado. El DSL de Structurizr usa bloques `workspace`, `model` y `views`. Incluye `styles` al final para colorear los elementos.
- Para los mockups de Figma: genera cada pantalla por separado. Incluye variantes móvil (390px) y desktop (1280px) para cada una. Usa auto-layout en todos los frames.
- El nombre interno del sistema es SIMA. El tagline es "Convierte tus clases en material de estudio listo para repasar".
- Las funcionalidades de gamificación (racha, XP, niveles, logros) aún no están implementadas en el backend, son parte del diseño futuro.
