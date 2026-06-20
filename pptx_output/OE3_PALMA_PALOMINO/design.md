# Design Document

## 1. Profile Baseline Declaration
- **Profile selection**: `profiles/academic.md`
- **Selection rationale**: This is a thesis defense / academic project presentation for OE3 (development objective). The audience is an academic committee evaluating engineering software development. The academic profile is the closest match.
- **Referenced dimensions**: Design philosophy (content is king, rigorous, logically clear), high information density, chart-dominant ratio, color guidance (university/academic tones), font guidance, navigation bar, content page layouts, argumentation-driven narrative style.
- **Deviation notes**: 
  - We will use a slightly more modern tech-education feel than a pure traditional thesis because the project is a software platform (SIMA). This means using screenshots prominently, which is acceptable in software engineering defenses.
  - We are not strictly reusing original paper figures; we are using real application screenshots as evidence of development.

## 2. Style Baseline Declaration
- **Style anchor selection**: Swiss International Style + Nature/Science figure clarity + modern SaaS dashboard presentation aesthetics (for screenshot integration)
- **Referenced dimension explanation**: 
  - From Swiss Style: strict grid alignment, clear typographic hierarchy, minimal decoration, high readability.
  - From Nature/Science: clean figure labeling, high-contrast data presentation, restrained color use.
  - From modern SaaS presentation: how to integrate screenshots cleanly without clutter, using cards and subtle shadows to frame app captures.
- **Do not force-fit**: The presentation is primarily academic but includes a software product. We combine academic rigor with clean product presentation.

## 3. Style Details

### 1. Color Design Principles
- **Overall tendency**: Conservative & steady with a touch of modern tech clarity. The audience is academic, but the content is software development.
- **Temperature**: Cool-neutral, mineral/papery feel.
- **Primary color**: Deep navy blue `#0F2B46` — conveys academic credibility, engineering professionalism, and trust.
- **Background**: Warm off-white `#F8F9FA` — softer than pure white, reduces eye strain, and feels more premium.
- **Text**: Dark charcoal `#1A1A2E` for body text, high readability.
- **Secondary**: Slate gray `#6B7B8C` for subtitles, annotations, secondary text.
- **Accent**: Muted teal `#0D9488` — used very sparingly for key highlights, active states, and important data points. Avoids cliché bright blues and keeps the palette sophisticated.
- **Card background**: Pure white `#FFFFFF` for content cards on the off-white page background, creating subtle elevation.
- **Table header**: Primary navy `#0F2B46` with white text.
- **Table body alternating**: White `#FFFFFF` and light gray `#F1F5F9`.

### 2. Font Usage Principles
- **Title font**: `QuattrocentoSans` — clean, academic, highly readable on projectors. Used in Bold for titles.
- **Body font**: `QuattrocentoSans` — same family for consistency, regular weight for body text.
- **Font size hierarchy**:
  - Cover title: 40px, bold
  - Cover subtitle: 20px, regular
  - Page title: 28px, bold
  - Section subtitle / card header: 22px, bold
  - Body text: 18px (heavy content), 20px (moderate content)
  - Table text: 16px
  - Footnotes / annotations: 14px
  - Navigation bar text: 14px, bold

### 3. Text Box and Container Styles
- **Content separation**: Use whitespace and font size differences for hierarchy. When cards are needed for screenshot framing, use white rectangles with subtle 1px light gray borders (`#E5E7EB`) and no fill on the card itself (or white fill if on off-white background).
- **Decorative elements**: 
  - A thin accent line (3px, teal `#0D9488`) below page titles to anchor the content area.
  - A left-side vertical accent bar (4px, teal) for key quotes or callouts.
  - Navigation bar at top: navy `#0F2B46` background with white text, current section highlighted with a teal underline or white text on teal pill.
- **No excessive shapes**: Keep it academic. No rounded bubbly cards unless framing screenshots.

### 4. Image Style
- **Icons**: Outline style Font Awesome icons (`far`), used sparingly and only for section markers or bullet enhancement. Color: teal `#0D9488` or navy `#0F2B46`.
- **Tables**: Minimal three-line style. Header row with navy background and white bold text. Body rows with alternating white/light gray. No vertical borders, only horizontal lines.
- **Charts**: Not heavily used in this presentation, but if needed, use the same color family (navy, teal, slate gray).
- **Illustrations / Screenshots**: 
  - Screenshots are the primary visual evidence. They should be placed inside white cards with subtle shadow to lift them from the page.
  - Each screenshot must have a caption below (14px, gray) describing what is shown.
  - Use `cover` or `contain` fit as appropriate. Do not stretch screenshots.

## 4. Layout System

### 1. Global Layout Characteristics
- **Page size**: 1280 x 720 (16:9)
- **Page margins**: 60px left/right, 80px top (below nav bar), 60px bottom.
- **Navigation bar**: Horizontal top bar, height 50px, full width, navy background. Contains 5-6 section titles evenly distributed. Current section highlighted with teal bottom border or pill.
- **Page title area**: Below nav bar, y=60, height ~40px. Title left-aligned, with a teal accent line below it spanning ~100px.
- **Page number**: Bottom-right corner, 14px, gray.
- **Grid alignment**: All elements must align to a strict grid. Left-right layouts must have aligned bottom edges. Top-bottom layouts must be centered horizontally.

### 2. Special Page Layouts
- **Cover (Page 1)**: Hero design. Full-bleed navy background (`#0F2B46`). Large centered title in white (40px). Subtitle in light gray below. Author names and date at bottom. A subtle geometric accent (a thin diagonal line or a semi-transparent shape) to add depth without clutter.
- **Table of contents (Page 2)**: Asymmetric two-column. Left side: large "AGENDA" text in navy, rotated 90 degrees or stacked vertically. Right side: numbered chapter list with dotted leaders or grid typography. Each item with a teal number and navy text.
- **Final page (Page 18)**: Navy background (`#0F2B46`), centered white text with key conclusions. "Gracias" as large text.

### 3. Content Page Layout Patterns
- **Text-heavy pages (e.g., Stack Tecnológico, User Stories)**: Full-width table or structured list. Title at top, table spanning full width below.
- **Screenshot pages (e.g., Dashboard, Quiz)**: Left-right split or top-bottom. If one screenshot: center it in a white card, caption below. If multiple screenshots: 2x2 grid of white cards, each with screenshot and caption.
- **Mixed pages (e.g., Pipeline, Arquitectura)**: Left side text/diagram description, right side diagram or simplified flowchart using shapes and arrows.
- **Prohibited**: Screenshot-only pages without explanatory text. Misaligned bottom edges in left-right layouts. Text smaller than 14px.

## 5. Style Usage Rules
- `$title`: Cover title, large white text on navy.
- `$subtitle`: Subtitles, cover subtitle, page secondary headers.
- `$heading`: Page titles (28px bold navy).
- `$body`: Body text (18-20px charcoal).
- `$caption`: Screenshot captions, footnotes (14px gray).
- `$navText`: Navigation bar text (14px white, bold for active).
- `$primary` (navy): Navigation bar, table headers, page titles, key shapes.
- `$secondary` (slate): Secondary text, annotations, inactive nav items.
- `$accent` (teal): Highlights, active nav indicator, accent lines, icons.
- `$background` (off-white): Page backgrounds for content pages.
- `$cardBg` (white): Card backgrounds for screenshots and tables.
- `$text` (charcoal): All body text.

## 6. Risk Prohibitions
- [ ] Do NOT use blue/cyan as primary color (avoid cheap tech-blue). Navy is the chosen primary.
- [ ] Do NOT use gradient backgrounds or shadows on text boxes. Only flat, academic styling.
- [ ] Do NOT use decorative icons where data or screenshots should be.
- [ ] Do NOT let screenshots go without captions or context text.
- [ ] Do NOT use font sizes below 14px for any readable text.
- [ ] Do NOT create left-right layouts where one side is much taller than the other without balancing.
- [ ] Do NOT use neon or high-saturation colors (purple, bright green, orange) as accents. Teal is restrained enough.
- [ ] Do NOT forget the navigation bar on content pages (after Page 2).
- [ ] Do NOT use wrap:false on multi-line body text. Only use wrap:false for single-line labels, titles, and badges.

## 7. Theme Definition

```yaml
theme:
  colors:
    primary: "#0F2B46"
    secondary: "#6B7B8C"
    accent: "#0D9488"
    background: "#F8F9FA"
    text: "#1A1A2E"
    cardBg: "#FFFFFF"
    lightGray: "#F1F5F9"
    borderGray: "#E5E7EB"
    white: "#FFFFFF"
  textStyles:
    title:
      fontSize: 40
      color: "$white"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.2
    subtitle:
      fontSize: 20
      color: "$secondary"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.3
    heading:
      fontSize: 28
      color: "$primary"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.2
    body:
      fontSize: 18
      color: "$text"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.5
    caption:
      fontSize: 14
      color: "$secondary"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.3
    navText:
      fontSize: 14
      color: "$white"
      fontFamily: "QuattrocentoSans"
      lineHeight: 1.2
  tableStyles:
    default:
      fontSize: 16
      fontFamily: "QuattrocentoSans"
      headerFill: "$primary"
      headerColor: "$white"
      headerBold: true
      bodyFill: ["$cardBg", "$lightGray"]
      bodyColor: "$text"
      border:
        style: solid
        width: 1
        color: "$borderGray"
```
