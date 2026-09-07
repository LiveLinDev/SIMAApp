# Marco de la tesis (vigente desde el 6 de septiembre de 2026)

**Título.** Notación compacta para la generación verificada de ítems IRT con modelos de lenguaje en una plataforma de microaprendizaje con evaluación adaptativa para la educación universitaria

**Proyecto.** TP202610039 · Ingeniería de Software, UPC · Erick Joaquín Palomino Santa Cruz y Adrián Enrique Jesús Palma Obispo · asesor Jorge Luis Mayta Guillermo.

**Tesis en dos capas.** La contribución es la notación compacta `.mini` (especificación, parsers, reporte de
verificación) y el pipeline de generación verificada de ítems IRT con modelos de lenguaje. SIMA es la plataforma
de microaprendizaje con evaluación adaptativa que los integra y en la que se validan, en un curso universitario.

## Problema y pregunta

El problema de investigación radica en que los ítems de evaluación generados con modelos de lenguaje llegan en salidas verbosas, con errores de formato y afirmaciones no verificadas, lo que impide usarlos directamente en evaluación adaptativa; a la vez, las clases universitarias grabadas rara vez se convierten en práctica guiada para el estudiante.

¿Cómo una notación compacta y un pipeline de generación verificada de ítems IRT con modelos de lenguaje permiten sostener una plataforma de microaprendizaje con evaluación adaptativa en la educación universitaria?

## Objetivo general

Diseñar y validar una notación compacta y un pipeline de generación verificada de ítems IRT con modelos de lenguaje, integrados en una plataforma de microaprendizaje con evaluación adaptativa para la educación universitaria.

## Objetivos específicos e indicadores

| Objetivo | Enunciado | Indicadores |
|---|---|---|
| OE1 | Analizar técnicas, herramientas y frameworks de reconocimiento automático de voz, modelos de lenguaje, formatos de serialización estructurada y evaluación adaptativa, con el fin de seleccionar los componentes de la notación, del pipeline y de la plataforma. | Acta de aprobación del asesor especializado sobre el benchmarking de técnicas, herramientas y frameworks de reconocimiento automático de voz, modelos de lenguaje, formatos de serialización y evaluación adaptativa (≥ 16 alternativas). · Acta de aprobación del asesor especializado sobre los criterios técnicos definidos (precisión, latencia, complejidad, costo y requerimientos computacionales) y las alternativas evaluadas en la matriz comparativa. · Acta de aprobación del asesor especializado sobre los componentes seleccionados que cumplen los umbrales mínimos de desempeño, incluida la comparación de formatos de serialización por consumo de tokens. |
| OE2 | Especificar la notación compacta .mini y diseñar la arquitectura del pipeline de generación verificada y de la plataforma de microaprendizaje con evaluación adaptativa, incluyendo sus interfaces y su esquema de despliegue. | Especificación de la notación .mini con parsers verificados: ≥ 95 % de ítems parseables e ida y vuelta sin pérdida sobre el corpus de referencia. · Aprobación del asesor especializado sobre los diagramas funcionales y arquitectónicos (C4) sincronizados con la implementación. · Aprobación del asesor especializado sobre los prototipos funcionales de la plataforma para el estudiante. |
| OE3 | Construir la plataforma integrando los módulos de transcripción automática, generación verificada de ítems en notación .mini, evaluación adaptativa por IRT, refuerzo dirigido y seguimiento del progreso del estudiante. | Número de módulos funcionales implementados e integrados: transcripción automática, generación verificada en .mini, evaluación adaptativa, refuerzo dirigido, repaso y seguimiento del progreso (≥ 5). · Porcentaje de funcionalidades principales desarrolladas según los requerimientos (≥ 80 %), verificadas mediante pruebas automáticas (≥ 100 pruebas en verde). · Número de flujos de usuario implementados: carga de clase, práctica adaptativa con retroalimentación, refuerzo, repaso y plan de estudio (≥ 4). |
| OE4 | Validar la notación, el pipeline y la plataforma mediante métricas de eficiencia y generabilidad del formato, pruebas del sistema y una evaluación experimental en un curso universitario. | Eficiencia y generabilidad de la notación: ≥ 30 % menos tokens que JSON compacto y ≥ 90 % de salidas parseables en al menos dos modelos de lenguaje. · Pruebas del sistema: ≥ 15 pruebas funcionales, de integración y de calidad con ≥ 85 % superadas; precisión de transcripción ≥ 85 %; ≥ 85 % de ítems válidos tras el pipeline y acuerdo entre docentes evaluadores. · Evaluación experimental en una sección de un curso universitario: ganancia normalizada pre/post ≥ 0,3, error estándar de la habilidad ≤ 0,35 en ≥ 80 % de las sesiones y uso ≥ 2 sesiones por semana. |

## Alcance

- Dentro: un curso universitario, una sección (25 a 40 estudiantes), un ciclo; 8 a 12 clases grabadas o en texto;
  pipeline completo; práctica adaptativa con retroalimentación inmediata; refuerzo, resúmenes, repaso y plan de estudio;
  rol estudiante.
- Fuera (trabajo futuro): varias carreras o universidades; roles docente y administrador con funciones propias; capa
  social; planes de pago como negocio; despliegue a escala y aplicación móvil; medir el rendimiento final del curso.

## Dónde está cada cosa

- Notación: `MINI_FORMAT_SPEC.md`, `learning/parse_mini.py`, paquete reproducible `../mini_paper_reproducible_package/`.
- Pipeline: `learning/pipeline.py`, `learning/services/` (generation, repairs, evidence), `learning/job_queue.py`.
- Evaluación adaptativa: `learning/cat.py`, `learning/psychometrics.py`, `learning/adaptive.py`.
- Validación: `python manage.py test learning`, `python manage.py check_ai --mini --runs N`, `/cursos/<id>/banco/` y los CSV;
  guía de revisión en `REVISION.md`.
