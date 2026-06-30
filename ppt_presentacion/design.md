# Design Document — SIMA Plataforma de Microaprendizaje

## 1. Profile Baseline Declaration

- **Profile selection**: `profiles/strategic.md` (project proposal / startup pitch deck)
- **Selection rationale**: La presentación expone el desarrollo de una plataforma tecnológica prácticamente terminada, con arquitectura, pipeline, módulos y stack real. El audience son evaluadores técnicos/académicos que juzgarán viabilidad y solidez del producto.
- **Referenced dimensions**: Narrativa persuasiva (problema → solución → arquitectura → módulos → estado), densidad media-alta con datos técnicos, uso de big numbers + diagramas + tablas, tipografía sans-serif bold para títulos, estructura de cover hero + capítulos + contenido + cierre.
- **Deviation notes**: 
  - Se incorpora la identidad visual de SIMA real (colores verde primario, azul acento, tinta oscura) extraídos del CSS y templates del proyecto.
  - Se permite uso de bordes redondeados (8-28px) porque el producto real los usa extensivamente (estilo Duolingo/mobile-first).
  - Se usa un tono más cercano a producto tech que a consultoría corporativa tradicional.

## 2. Style Baseline Declaration

- **Style anchor selection**: 
  - **Duolingo product design** (la referencia visual explícita del proyecto): no se copia la paleta roja-verde chillona, sino la estructura de tarjetas con sombra inferior, botones con relieve, progreso visual circular, y jerarquía de información clara.
  - **Apple WWDC presentation style**: fondos oscuros, texto grande, diagrams limpios, animaciones sutiles (simuladas con gradients y shapes).
- **Referenced dimension explanation**: 
  - De Duolingo: layout de cards, badges, progreso circular, botones con sombra inferior (bottom-offset shadow), tipografía redondeada y amigable.
  - De Apple: dark mode para cover/capítulo/final, uso de gradientes sutiles, texto blanco sobre oscuro, espaciado generoso, diagramas con líneas finas y colores semitransparentes.

## 3. Style Details

### Color Design Principles

- **Tendencia general**: Entre estable y llamativo — base oscura para portada/capítulos/cierre, contenido en fondo claro (tinta muy pálida) para legibilidad de diagramas técnicos.
- **Temperatura**: Fresca, tecnológica, con acento cálido (verde éxito).
- **Primary**: `#24323f` — Tinta oscura de SIMA. Usada para fondos oscuros, títulos en páginas claras, diagramas principales.
- **Secondary**: `#6b7a88` — Gris azulado de SIMA. Para texto secundario, bordes, líneas decorativas.
- **Accent**: `#58cc02` — Verde primario de SIMA. Para big numbers, badges de éxito, CTAs, progreso, highlights. NUNCA como fondo grande (solo detalles).
- **Azul SIMA**: `#1cb0f6` — Usado como acento secundario: badges de información, links, estados activos, diagramas externos.
- **Background (light)**: `#f8fcff` — Blanco azulado muy pálido. Fondo de páginas de contenido. Más sofisticado que blanco puro.
- **Background (dark)**: `#0f1a22` — Versión oscura de la tinta. Para cover, capítulos, cierre. No es negro puro; tiene cuerpo.
- **Text (light pages)**: `#1a2633` — Negro azulado suave, no negro puro.
- **Text (dark pages)**: `#ffffff` — Blanco puro para máximo contraste.
- **Warning/Error**: `#ff4b4b` — Rojo Duolingo, usado muy esporádicamente para estados de error en diagramas.
- **Amarillo**: `#ffc800` — Para badges de racha, estrellas, logros.

### Font Usage Principles

- **Títulos**: `Liter` (sans-serif moderno, tech feel) — bold, usado en mayúsculas para títulos de capítulo y cover con letter-spacing expandido (2-4px).
- **Subtítulos / headings**: `QuattrocentoSans` — elegante, legible, usado para títulos de página de contenido.
- **Body text**: `QuattrocentoSans` — altamente legible, 20px para páginas de densidad media, 18px para alta densidad.
- **Big numbers / KPIs**: `Liter` — bold, 48-72px, con letter-spacing ligeramente negativo para impacto.
- **Código / técnico**: `Liter` — monospace feel (aunque no es mono, su geometría funciona bien para snippets cortos).
- **Font size hierarchy**:
  - Cover title: 56px
  - Chapter title: 44px
  - Page title: 28px
  - Subtitle/heading: 22px
  - Body: 18-20px
  - Big numbers: 48-64px
  - Annotations/captions: 14px

### Text Box and Container Styles

- **Cards**: Rounded rectangles con corner radius 16-20px (referencia a la UI real de SIMA). Fondo blanco sobre páginas claras, o `#1a2a38` sobre páginas oscuras. Sombra sutil: offset Y 4px, blur 12px, color `#00000015`.
- **Badges**: Pill-shaped (radius muy alto), fondo `#58cc02` para éxito, `#1cb0f6` para info, `#ffc800` para advertencia/destacado. Texto blanco o tinta oscura.
- **Separación de contenido**: Preferencia por whitespace + tamaño de fuente. Cuando se usan cards, se usa grid de 2-3 columnas con gap de 24px.
- **Decorative elements**: Líneas finas horizontales (1px, `#6b7a8840`) para separar secciones. Barras verticales de color (4px ancho, `#58cc02`) a la izquierda de títulos para énfasis. Números de paso en círculos (40px, `#58cc02`, texto blanco) para pipelines.

### Image Style

- **Icons**: Font Awesome solid (`fas`) para UI, regular (`far`) para estados. Color `$primary` o `$accent` según contexto. Uso estratégico: uno por card máximo.
- **Tables**: Estilo minimal. Header con fondo `#24323f`, texto blanco. Filas alternadas `#f8fcff` / `#ffffff`. Bordes horizontales sutiles 1px `#e0e8ef`. Primera columna bold.
- **Charts**: Charts solo si son necesarios para datos técnicos. Colores de series: `#58cc02`, `#1cb0f6`, `#ffc800`, `#ff4b4b`, `#6b7a88`. Estilo flat sin bordes, con grid lines muy sutiles.
- **Illustrations**: No se usan ilustraciones de stock. En su lugar: diagramas de arquitectura construidos con shapes (rectángulos redondeados, líneas, círculos) + texto, simulando C4 diagrams. Mockups de UI simulados con shapes y texto, no imágenes reales.

## 4. Layout System

### Global Layout Characteristics

- **Canvas**: 1280 x 720 (16:9)
- **Page margins**: 60px left/right, 50px top/bottom. Zona segura de contenido: 1160 x 620.
- **Elementos unificados**:
  - Esquina superior izquierda: logo "SIMA" en texto (Liter, 14px, bold, `#24323f` en light, `#ffffff` en dark) + badge de estado (opcional).
  - Esquina inferior derecha: número de página en 14px, `#6b7a88` (light) o `#ffffff60` (dark).
  - Esquina inferior izquierda: línea decorativa 40px x 3px `#58cc02` en páginas de contenido.
- **Grid**: 12-column grid implícito. Cards de 2-3 columnas alineadas. Elementos en left-right layouts deben tener alturas balanceadas.

### Special Page Layouts

- **Cover (Hero design)**: Fondo oscuro `#0f1a22` con gradiente radial sutil desde el centro (más claro `#1a2a38` hacia los bordes). Título centrado, 56px Liter bold, blanco. Subtítulo debajo, 22px QuattrocentoSans, `#6b7a88`. Big number o badge central opcional. No imagen de fondo externa.
- **Table of contents**: Fondo claro. Título "Agenda" grande a la izquierda. A la derecha, grid de 6 cards numeradas (01-06), cada una con número grande en `#58cc02` y título de capítulo. Layout asimétrico pero equilibrado.
- **Chapter dividers**: Fondo oscuro. Número de capítulo gigante (120px, `#24323f` con stroke `#58cc02` o semitransparente) en fondo. Título del capítulo centrado, 44px. Breve descripción debajo, 18px. Usar como "reset visual" entre secciones densas.
- **Closing page**: Similar a cover pero con mensaje de cierre y datos de contacto/repo.

### Content Page Layout Patterns

- **Pattern A — Left-Right Split**: 50/50. Izquierda: texto explicativo con título + bullets. Derecha: diagrama o mockup de UI construido con shapes.
- **Pattern B — Three/Four Cards**: Grid de 3 o 4 cards iguales, cada una con icono + título + descripción. Para listas de features, módulos, planes.
- **Pattern C — Pipeline/Timeline**: Línea horizontal o vertical conectando nodos numerados. Para el pipeline de 11 etapas (se puede condensar visualmente).
- **Pattern D — Big Number + Context**: Big number central (48-64px) con label debajo, y texto explicativo alrededor. Para métricas, KPIs, resultados de pruebas.
- **Pattern E — Full-Page Diagram**: Diagrama de arquitectura ocupando 80% de la página, con leyenda abajo. Para C4 y modelo de datos.
- **Prohibido**: left-right layouts donde un lado llega al fondo y el otro solo ocupa la mitad. Si hay desbalance, centrar verticalmente el contenido más corto o usar más whitespace arriba.

## 5. Style Usage Rules

- **$title** (textStyle): Cover title, chapter titles. Liter, 56px/44px, blanco, letter-spacing 2px. Solo en dark pages.
- **$subtitle** (textStyle): Page titles en contenido. QuattrocentoSans, 28px, `#24323f`, letter-spacing normal.
- **$heading** (textStyle): Subtítulos dentro de páginas. QuattrocentoSans, 22px, `#24323f` bold.
- **$body** (textStyle): Texto principal. QuattrocentoSans, 18px, `#1a2633`, lineHeight 1.6.
- **$caption** (textStyle): Anotaciones, fuentes, leyendas. QuattrocentoSans, 14px, `#6b7a88`.
- **$bigNumber** (textStyle): KPIs y números impactantes. Liter, 56px, `$accent` o `#1cb0f6`, bold.
- **$badge** (shape): Pill badge con fondo `$accent` o `#1cb0f6`, texto blanco, radius 100000 (máximo). Usado para estados, labels, categorías.
- **$card** (shape): Rounded rect, radius 16px, fill `#ffffff` (light) o `#1a2a38` (dark), shadow sutil.
- **$primary** (color): `#24323f` — títulos, fondos oscuros, diagramas principales.
- **$secondary** (color): `#6b7a88` — texto secundario, bordes, líneas.
- **$accent** (color): `#58cc02` — big numbers, badges de éxito, progreso, highlights.
- **$info** (color): `#1cb0f6` — badges de info, acento secundario, estados activos.
- **$warning** (color): `#ffc800` — badges de racha, logros, destacados.
- **$background** (color): `#f8fcff` — fondo de páginas de contenido.
- **$darkBg** (color): `#0f1a22` — fondo de cover, chapters, cierre.
- **$text** (color): `#1a2633` — texto body en páginas claras.
- **$lightText** (color): `#ffffff` — texto en páginas oscuras.
- **tableStyle $default**: headerFill `$primary`, headerColor `#ffffff`, bodyFill `["#f8fcff", "#ffffff"]`, bodyColor `$text`, border 1px `#e0e8ef`, firstColumnBold true.

## 6. Risk Prohibitions

- [ ] **NO usar imágenes de stock genéricas** de personas estudiando, laptops, etc. Usar solo shapes, diagrams, icons, y mockups construidos con elementos del skill.
- [ ] **NO usar degradados complejos o llamativos** — solo gradientes radiales muy sutiles en fondos oscuros. Degradados lineales fuertes están prohibidos.
- [ ] **NO usar colores fluorescentes** — el verde `#58cc02` es el único color saturado permitido, y solo en detalles pequeños (badges, acentos). Nunca como fondo de card completa.
- [ ] **NO usar bordes redondeados excesivos** en elementos grandes: cards max 20px, badges max 100000px (pill), botones 12px. No redondear shapes de diagrama de arquitectura (mantener 4-8px para C4).
- [ ] **NO dejar textos corridos** en páginas de pipeline: usar nodos conectados con líneas, no solo bullets sueltos.
- [ ] **NO usar font size < 14px** en ningún elemento. Body mínimo 18px, captions mínimo 14px, table text mínimo 14px.
- [ ] **NO usar colores rojo/verde/ambar para correcto/incorrecto/warning** en más de un badge por página. La paleta usa verde para éxito, azul para info, amarillo para destacados. Rojo solo para errores técnicos.
- [ ] **NO crear layouts desbalanceados** — en left-right, ambos lados deben tener altura visual similar. Si el texto es corto, expandir con más interlineado o agregar un elemento decorativo.
- [ ] **NO usar texto centrado en páginas de contenido** — solo en cover, capítulos, y cierre. Contenido alineado a la izquierda siempre.
- [ ] **NO mezclar dark y light pages sin transición** — usar chapter pages oscuras como buffers entre secciones de contenido claras.

## 7. Theme Definition

```yaml
theme:
  colors:
    primary: "#24323f"
    secondary: "#6b7a88"
    accent: "#58cc02"
    info: "#1cb0f6"
    warning: "#ffc800"
    background: "#f8fcff"
    darkBg: "#0f1a22"
    text: "#1a2633"
    lightText: "#ffffff"
    cardBg: "#ffffff"
    cardDarkBg: "#1a2a38"
    border: "#e0e8ef"
  textStyles:
    title:
      fontSize: 56
      color: "$lightText"
      fontFamily: "Liter"
      letterSpacing: 2
      lineHeight: 1.1
    chapterTitle:
      fontSize: 44
      color: "$lightText"
      fontFamily: "Liter"
      letterSpacing: 2
      lineHeight: 1.2
    subtitle:
      fontSize: 28
      color: "$primary"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.3
    heading:
      fontSize: 22
      color: "$primary"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.3
    body:
      fontSize: 18
      color: "$text"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.6
    caption:
      fontSize: 14
      color: "$secondary"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.4
    bigNumber:
      fontSize: 56
      color: "$accent"
      fontFamily: "Liter"
      lineHeight: 1.0
  tableStyles:
    default:
      fontSize: 14
      fontFamily: "QuattrocentoSans"
      headerFill: "$primary"
      headerColor: "$lightText"
      headerBold: true
      bodyFill: ["#f8fcff", "#ffffff"]
      bodyColor: "$text"
      firstColumnBold: true
      border:
        style: solid
        width: 1
        color: "$border"
```
