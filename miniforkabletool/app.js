/* ================================================================
   MiniForkable Tool v3
   Cualquier JSON -> prompt de fork .mini con análisis profundo
   ================================================================ */

const $ = (id) => document.getElementById(id);

let currentAnalysis = null;
let currentFork = null;
let lastTestMini = '';

/* ------------------------------------------------------------------
   Demos
   ------------------------------------------------------------------ */
const DEMO_SESSION = {
  success: true,
  message: "Sesión completada",
  data: {
    sessionId: "f990cb0a-90a7-46d6-96e0-6160d2ba7739",
    totalQuestions: "3",
    correctAnswers: "0",
    incorrectAnswers: "3",
    skippedAnswers: "0",
    scorePercentage: "0.00",
    totalTimeMs: "7",
    avgTimeMs: "2.3333333333333333",
    responses: [
      {
        id: "27c21122-d6fb-4718-a0f7-47d20ebeda24",
        session_id: "f990cb0a-90a7-46d6-96e0-6160d2ba7739",
        question_id: "247794f8-0325-4ef1-8bd9-d9bc5dd13ca4",
        position_in_session: null,
        presented_at: "2026-06-03T20:54:26.753Z",
        first_interaction_at: "2026-06-03T20:54:31.365Z",
        responded_at: "2026-06-03T20:54:31.765Z",
        time_to_submit_ms: 5,
        thinking_time_ms: 4612,
        selected_option_keys: "A",
        outcome: "incorrect",
        is_correct: false,
        revision_count: 0,
        client_context: null,
        payload: null,
        created_at: "2026-06-03T20:54:31.766Z",
        updated_at: "2026-06-03T20:54:31.766Z",
        question_number: "1",
        question_text: "En un proyecto de desarrollo de software...",
        correct_answer: "C",
        explanation: "En un entorno ágil, los cambios...",
        difficulty: "medium",
        options: [
          { key: "A", text: "Aceptar la sugerencia..." },
          { key: "B", text: "Rechazar la sugerencia..." },
          { key: "C", text: "Evaluar el impacto..." },
          { key: "D", text: "Consultar con el patrocinador..." }
        ]
      },
      {
        id: "02d87890-0ba8-4d69-8fef-c7b435be3e0f",
        session_id: "f990cb0a-90a7-46d6-96e0-6160d2ba7739",
        question_id: "b5e98618-aa6c-4383-92c3-370173b0d671",
        position_in_session: null,
        presented_at: "2026-06-03T20:54:26.753Z",
        first_interaction_at: "2026-06-03T20:54:33.932Z",
        responded_at: "2026-06-03T20:54:34.308Z",
        time_to_submit_ms: 1,
        thinking_time_ms: 7179,
        selected_option_keys: "D",
        outcome: "incorrect",
        is_correct: false,
        revision_count: 0,
        client_context: null,
        payload: null,
        created_at: "2026-06-03T20:54:34.309Z",
        updated_at: "2026-06-03T20:54:34.309Z",
        question_number: "10",
        question_text: "En un proyecto de salud digital...",
        correct_answer: "B",
        explanation: "Cuando los requisitos no están completamente definidos...",
        difficulty: "hard",
        options: [
          { key: "A", text: "Contrato de precio fijo cerrado..." },
          { key: "B", text: "Contrato de tiempo y materiales..." },
          { key: "C", text: "Contrato de costo reembolsable..." },
          { key: "D", text: "Contrato de precio fijo con ajuste..." }
        ]
      }
    ]
  }
};

const DEMO_USERS = {
  users: [
    { id: 1, name: "Ada Lovelace", email: "ada@upc.pe", role: "admin", active: true },
    { id: 2, name: "Alan Turing", email: "alan@upc.pe", role: "editor", active: true },
    { id: 3, name: "Grace Hopper", email: "grace@upc.pe", role: "viewer", active: false }
  ]
};

const DEMO_PRODUCTS = {
  products: [
    { sku: "LAP-001", name: "Laptop Pro X1", price: 1299.99, stock: 45, category: "Electronics", tags: ["laptop", "pro"] },
    { sku: "MOU-002", name: "Wireless Mouse MX", price: 79.99, stock: 120, category: "Peripherals", tags: ["mouse", "wireless"] }
  ]
};

function loadDemoJson() {
  $("jsonInput").value = JSON.stringify(DEMO_SESSION, null, 2);
  analyzeJson();
}
function loadDemoUsers() {
  $("jsonInput").value = JSON.stringify(DEMO_USERS, null, 2);
  analyzeJson();
}
function loadDemoProducts() {
  $("jsonInput").value = JSON.stringify(DEMO_PRODUCTS, null, 2);
  analyzeJson();
}
function clearAll() {
  $("jsonInput").value = "";
  analyzeJson();
}

/* ------------------------------------------------------------------
   Token estimation
   ------------------------------------------------------------------ */
function estimateTokens(text) {
  if (!text) return 0;
  return Math.max(1, Math.ceil(text.length / 3.7));
}

function todayCompact() {
  return new Date().toISOString().slice(0, 10).replaceAll("-", "");
}

function normalizeName(value, fallback = "data") {
  const clean = String(value || fallback).trim().toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9_\-]+/g, "_").replace(/^_+|_+$/g, "");
  return clean || fallback;
}

function singular(name) {
  const n = normalizeName(name);
  const explicit = {
    responses: "response", classes: "class", kisses: "kiss", glasses: "glass",
    bosses: "boss", boxes: "box", churches: "church", brushes: "brush",
    horses: "horse", houses: "house", cases: "case", bases: "base",
    users: "user", products: "product", logs: "log", items: "item",
    orders: "order", patients: "patient", questions: "question",
    answers: "answer", sessions: "session", events: "event",
    transactions: "transaction", messages: "message", assessments: "assessment",
    quizzes: "quiz", endpoints: "endpoint", exercises: "exercise"
  };
  if (explicit[n]) return explicit[n];
  if (n.endsWith("ies") && n.length > 4) return n.slice(0, -3) + "y";
  if (/([cs]h|x|z|o)es$/.test(n) && n.length > 3) return n.slice(0, -2);
  if (n.endsWith("s") && n.length > 1 && !n.endsWith("ss")) return n.slice(0, -1);
  return n;
}

function prefixFromDomain(domain) {
  const s = singular(domain);
  const map = {
    assessment: "a", evaluacion: "a", quiz: "q", usuario: "u", user: "u",
    producto: "p", product: "p", log: "l", endpoint: "e", response: "r",
    order: "o", patient: "p", item: "i", question: "q", answer: "a",
    session: "s", event: "e", transaction: "t", message: "m"
  };
  if (map[s]) return map[s];
  return normalizeName(s).slice(0, 3) || "g";
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[ch]));
}

/* ------------------------------------------------------------------
   Deep JSON analysis
   ------------------------------------------------------------------ */
function findBestRecordArray(data) {
  const candidates = [];

  function scan(obj, path, depth) {
    if (!obj || typeof obj !== "object") return;
    if (Array.isArray(obj)) {
      if (obj.length === 0) return;
      const objItems = obj.filter((x) => x && typeof x === "object" && !Array.isArray(x));
      if (objItems.length > 0) {
        const allKeys = new Set();
        objItems.forEach((item) => Object.keys(item).forEach((k) => allKeys.add(k)));
        candidates.push({
          path,
          depth,
          length: obj.length,
          objCount: objItems.length,
          fieldCount: allKeys.size,
          sample: objItems[0],
          records: objItems,
        });
      } else if (obj.length > 0 && typeof obj[0] !== "object") {
        candidates.push({
          path,
          depth,
          length: obj.length,
          objCount: 0,
          fieldCount: 1,
          sample: obj[0],
          records: obj,
        });
      }
    } else {
      for (const [key, val] of Object.entries(obj)) {
        scan(val, path ? `${path}.${key}` : key, depth + 1);
      }
    }
  }

  scan(data, "", 0);

  // Score: prioritize arrays with many objects, many fields, reasonable depth
  candidates.sort((a, b) => {
    const score = (c) => c.objCount * 15 + c.fieldCount * 8 - c.depth * 3 + Math.log1p(c.length);
    return score(b) - score(a);
  });

  if (candidates.length) return candidates[0];

  // Fallback: wrap root object as single record
  if (data && typeof data === "object" && !Array.isArray(data)) {
    return {
      path: "(root)",
      depth: 0,
      length: 1,
      objCount: 1,
      fieldCount: Object.keys(data).length,
      sample: data,
      records: [data],
    };
  }
  return null;
}

function extractSchema(records) {
  const schema = {};
  const allKeys = new Set();
  records.forEach((r) => {
    if (r && typeof r === "object") Object.keys(r).forEach((k) => allKeys.add(k));
  });

  allKeys.forEach((key) => {
    const values = records.map((r) => r?.[key]).filter((v) => v !== undefined);
    const types = new Set(values.map((v) => {
      if (v === null) return "null";
      if (Array.isArray(v)) return "array";
      return typeof v;
    }));

    const nonNullSample = values.find((v) => v !== null && v !== undefined);
    let subtype = null;
    let nestedFields = null;
    let arrayItemSample = null;

    if (Array.isArray(nonNullSample) && nonNullSample.length > 0) {
      arrayItemSample = nonNullSample[0];
      if (arrayItemSample && typeof arrayItemSample === "object" && !Array.isArray(arrayItemSample)) {
        nestedFields = [...new Set(nonNullSample.flatMap((o) => (o && typeof o === "object" ? Object.keys(o) : [])))];
        subtype = "object";
      } else {
        subtype = typeof arrayItemSample;
      }
    } else if (typeof nonNullSample === "object" && nonNullSample !== null) {
      nestedFields = Object.keys(nonNullSample);
    }

    schema[key] = {
      types: [...types],
      sample: nonNullSample,
      subtype,
      nestedFields,
      arrayItemSample,
      isNullable: values.some((v) => v === null),
      arrayLength: Array.isArray(nonNullSample) ? nonNullSample.length : null,
    };
  });

  return schema;
}

function detectArrayStrategy(key, info) {
  if (!info.types.includes("array") || info.subtype !== "object" || !info.nestedFields) {
    return null;
  }
  const nf = info.nestedFields;
  // Pattern: quiz options with key+text
  if (nf.includes("key") && nf.includes("text")) {
    return { type: "key_value", label: "key:value pairs", sep: ";" };
  }
  // Pattern: assessment options with text+correct
  if (nf.includes("text") && nf.includes("correct")) {
    return { type: "text_correct", label: "text* for correct", sep: "," };
  }
  // Pattern: simple id+name objects
  if (nf.length === 2 && nf.includes("id") && (nf.includes("name") || nf.includes("text"))) {
    return { type: "id_name", label: "id:name pairs", sep: ";" };
  }
  // Default: compact JSON
  return { type: "json", label: "JSON compact", sep: null };
}

function detectObjectStrategy(key, info) {
  if (info.types.includes("array") || info.types.includes("null") && info.types.length === 1) return null;
  if (typeof info.sample !== "object" || info.sample === null) return null;
  const nf = info.nestedFields || [];
  if (nf.length <= 3) {
    return { type: "flatten", label: "flatten k=v", sep: ";" };
  }
  return { type: "json", label: "JSON compact", sep: null };
}

function buildStrategies(schema) {
  const strategies = {};
  for (const [key, info] of Object.entries(schema)) {
    const arr = detectArrayStrategy(key, info);
    if (arr) {
      strategies[key] = { ...arr, sourceType: info.types.join("/") };
      continue;
    }
    const obj = detectObjectStrategy(key, info);
    if (obj) {
      strategies[key] = { ...obj, sourceType: info.types.join("/") };
      continue;
    }
    // Primitive
    let label = info.types.join("/");
    if (info.types.includes("boolean")) label += " -> 1/0";
    strategies[key] = { type: "primitive", label, sourceType: info.types.join("/") };
  }
  return strategies;
}

/* ------------------------------------------------------------------
   MINI serialization
   ------------------------------------------------------------------ */
function serializeMiniValue(key, value, strategy, schemaInfo) {
  if (value === null || value === undefined) return "";

  if (strategy.type === "primitive") {
    if (typeof value === "boolean") return value ? "1" : "0";
    if (Array.isArray(value)) return value.map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v))).join(";");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value)
      .replaceAll("\\", "\\\\")
      .replaceAll("|", "\\|")
      .replaceAll("\n", " ")
      .replaceAll("\r", " ")
      .trim();
  }

  if (strategy.type === "key_value") {
    if (!Array.isArray(value)) return serializeMiniValue(key, value, { type: "primitive" }, schemaInfo);
    return value
      .map((o) => {
        if (!o || typeof o !== "object") return String(o);
        const k = o.key ?? o.id ?? o.code ?? "?";
        const t = o.text ?? o.name ?? o.value ?? "";
        return `${k}:${t}`;
      })
      .join(";");
  }

  if (strategy.type === "text_correct") {
    if (!Array.isArray(value)) return serializeMiniValue(key, value, { type: "primitive" }, schemaInfo);
    return value
      .map((o) => {
        if (!o || typeof o !== "object") return String(o);
        const t = o.text ?? o.name ?? "";
        const c = o.correct ? "*" : "";
        return `${t}${c}`;
      })
      .join(",");
  }

  if (strategy.type === "id_name") {
    if (!Array.isArray(value)) return serializeMiniValue(key, value, { type: "primitive" }, schemaInfo);
    return value
      .map((o) => {
        if (!o || typeof o !== "object") return String(o);
        const id = o.id ?? o.key ?? "?";
        const name = o.name ?? o.text ?? "";
        return `${id}:${name}`;
      })
      .join(";");
  }

  if (strategy.type === "flatten") {
    if (!value || typeof value !== "object") return serializeMiniValue(key, value, { type: "primitive" }, schemaInfo);
    const nf = schemaInfo.nestedFields || Object.keys(value);
    return nf
      .map((k) => {
        const v = value[k];
        if (v === null || v === undefined) return `${k}=`;
        return `${k}=${String(v).replaceAll(";", ",").replaceAll("|", "\\|")}`;
      })
      .join(";");
  }

  if (strategy.type === "json") {
    return JSON.stringify(value)
      .replaceAll("\\", "\\\\")
      .replaceAll("|", "\\|")
      .replaceAll("\n", " ")
      .replaceAll("\r", " ");
  }

  return String(value);
}

function recordsToMini(records, prefix, fields, strategies, schema) {
  const header = `${prefix}|n=${records.length}|d=${todayCompact()}|t=${normalizeName(currentFork?.domain || "data")}|k=${fields.join(",")}`;
  const lines = records.map((row, idx) => {
    if (!row || typeof row !== "object") return `${prefix}${idx + 1}|${row}`;
    return fields.map((f) => {
      const strat = strategies[f] || { type: "primitive" };
      const info = schema[f] || {};
      return serializeMiniValue(f, row[f], strat, info);
    }).join("|");
  });
  return [header, ...lines].join("\n");
}

/* ------------------------------------------------------------------
   Prompt generation
   ------------------------------------------------------------------ */
function generateForkPrompt(domain, prefix, fields, strategies, schema, sampleRecords) {
  const miniExample = recordsToMini(sampleRecords.slice(0, 2), prefix, fields, strategies, schema);

  const fieldDocs = fields.map((f) => {
    const s = strategies[f];
    const info = schema[f];
    let doc = `- **${f}**: `;
    if (s.type === "primitive") {
      doc += `tipo ${info.types.join("/")}. `;
      if (info.types.includes("boolean")) doc += `Usar 1/0. `;
      doc += `Ejemplo: "${String(info.sample ?? "").slice(0, 60)}".`;
    } else if (s.type === "key_value") {
      doc += `array de objetos {key, text}. Serializar como \`K:texto;K:texto\`. Ejemplo: "${serializeMiniValue(f, info.sample, s, info).slice(0, 80)}".`;
    } else if (s.type === "text_correct") {
      doc += `array de objetos {text, correct}. Serializar como \`texto*,texto\` (asterisco marca correcta). Ejemplo: "${serializeMiniValue(f, info.sample, s, info).slice(0, 80)}".`;
    } else if (s.type === "id_name") {
      doc += `array de objetos {id, name}. Serializar como \`id:nombre;id:nombre\`. Ejemplo: "${serializeMiniValue(f, info.sample, s, info).slice(0, 80)}".`;
    } else if (s.type === "flatten") {
      const nf = info.nestedFields || [];
      doc += `objeto anidado. Aplanar como \`${nf.map((k) => `${k}=valor`).join(";")}\`. Ejemplo: "${serializeMiniValue(f, info.sample, s, info).slice(0, 80)}".`;
    } else if (s.type === "json") {
      doc += `estructura anidada. Serializar como JSON compacto escapado. Ejemplo: "${serializeMiniValue(f, info.sample, s, info).slice(0, 80)}...".`;
    }
    return doc;
  }).join("\n");

  const grammar = `document   ::= header "\\n" record+ ("\\n")*
header     ::= "${prefix}" "|" meta ("|" meta)*
meta       ::= key "=" value
record     ::= ${fields.map(() => "field").join(' "|" ')}
field      ::= text | json_compact | key_value_pairs
key_value  ::= key ":" value (";" key ":" value)*
text       ::= cualquier Unicode excepto salto de línea y pipe no escapado
roundtrip  ::= .mini-${prefix} -> JSON canónico con campos [${fields.join(", ")}]`;

  const prompt = `## SYSTEM PROMPT

Eres un generador estricto de .mini-${prefix}, una bifurcación de .mini para el dominio "${domain}".

## FORMATO DE SALIDA — .mini-${prefix}

El output es texto plano en formato .mini-${prefix}. Una línea de cabecera seguida de una línea por registro.

### Cabecera
\`\`\`
${prefix}|n=<cantidad>|d=<AAAAMMDD>|t=<tema>|k=${fields.join(",")}
\`\`\`

### Registro
Campos posicionales en este orden exacto:
\`\`\`
${fields.join("|")}
\`\`\`

### Mapeo de campos
${fieldDocs}

### Reglas de escaping
- Sin espacios alrededor de \`|\`
- Sin saltos de línea dentro de un registro
- Escapa \`|\` dentro de valores como \\|
- Si un valor es booleano usa 1/0
- Si un valor es null o undefined, deja el campo vacío
- Si un valor es lista de primitivos usa punto y coma como separador interno
- No uses JSON, YAML, XML, Markdown ni explicaciones fuera del bloque .mini

## OUTPUT

Genera EXCLUSIVAMENTE las líneas .mini-${prefix} (una cabecera + N registros).

PROHIBIDO:
- Texto explicativo fuera del bloque
- JSON, YAML, XML u otro formato
- Items que no emerjan de los datos de entrada

REQUERIDO:
- Round-trip determinista a JSON canónico
- Validar que cada registro tenga exactamente ${fields.length} campos

## EJEMPLO

Input JSON (2 registros):
\`\`\`json
${JSON.stringify(sampleRecords.slice(0, 2), null, 2)}
\`\`\`

Output .mini-${prefix}:
\`\`\`
${miniExample}
\`\`\`

## TAREA

Cuando te pida generar datos de ${domain} en formato JSON, conviértelos EXCLUSIVAMENTE a .mini-${prefix} siguiendo las reglas anteriores.`;

  return { prompt, grammar, example: miniExample };
}

/* ------------------------------------------------------------------
   UI: Analysis
   ------------------------------------------------------------------ */
function analyzeJson() {
  const raw = $("jsonInput").value;
  $("jsonStats").textContent = `${raw.length} caracteres · ${estimateTokens(raw)} tokens estimados`;

  if (!raw.trim()) {
    $("detectedBadge").textContent = "Sin JSON todavía";
    $("detectedBadge").className = "badge badge-blue";
    $("schemaTable").querySelector("tbody").innerHTML = "";
    $("schemaSummary").textContent = "0 campos";
    $("forkDomain").value = "";
    $("forkPrefix").value = "";
    $("forkFields").value = "";
    currentAnalysis = null;
    return;
  }

  let data;
  try {
    data = JSON.parse(raw);
  } catch (err) {
    $("detectedBadge").textContent = "JSON inválido";
    $("detectedBadge").className = "badge badge-red";
    return;
  }

  const candidate = findBestRecordArray(data);
  if (!candidate) {
    $("detectedBadge").textContent = "No se encontraron registros";
    $("detectedBadge").className = "badge badge-warn";
    return;
  }

  const schema = extractSchema(candidate.records);
  const strategies = buildStrategies(schema);
  const fields = Object.keys(schema);

  const pathParts = candidate.path.split(".");
  const lastPart = pathParts.pop() || "data";
  const wrapperNames = ["data", "result", "results", "body", "payload", "content", "records", "items", "list", "array", "values", "objects"];
  let domainPart = lastPart;
  if (wrapperNames.includes(lastPart) && pathParts.length > 0) {
    domainPart = pathParts.pop() || lastPart;
  }
  const domainName = singular(normalizeName(domainPart));
  const prefix = prefixFromDomain(domainName);

  currentAnalysis = {
    candidate,
    schema,
    strategies,
    fields,
    domainName,
    prefix,
  };

  // Fill inputs
  $("forkDomain").value = domainName;
  $("forkPrefix").value = prefix;
  $("forkFields").value = fields.join(",");

  // Badge
  $("detectedBadge").textContent = `Detectado: ${domainName} · ${candidate.records.length} registros · ${fields.length} campos`;
  $("detectedBadge").className = "badge badge-ok";
  $("schemaSummary").textContent = `${fields.length} campos · ${candidate.records.length} registros`;

  // Table
  const tbody = $("schemaTable").querySelector("tbody");
  tbody.innerHTML = fields.map((f) => {
    const s = strategies[f];
    const info = schema[f];
    const badgeClass =
      s.type === "primitive" ? "strategy-primitive" :
      s.type === "key_value" || s.type === "id_name" || s.type === "text_correct" ? "strategy-keyvalue" :
      s.type === "flatten" ? "strategy-flatten" : "strategy-json";
    const example = String(serializeMiniValue(f, info.sample, s, info)).slice(0, 70);
    return `<tr>
      <td><code>${escapeHtml(f)}</code></td>
      <td><span class="field-strategy-badge ${badgeClass}">${escapeHtml(s.label)}</span></td>
      <td class="muted">${escapeHtml(s.sourceType)}</td>
      <td class="mono muted" style="font-size:12px;">${escapeHtml(example)}${example.length >= 70 ? "…" : ""}</td>
    </tr>`;
  }).join("");

  // Prefill test input
  $("testInput").value = JSON.stringify(candidate.records.slice(0, 2), null, 2);
}

function updatePrefix() {
  const domain = $("forkDomain").value;
  if (!domain) return;
  $("forkPrefix").value = prefixFromDomain(domain);
}

/* ------------------------------------------------------------------
   UI: Generate Fork
   ------------------------------------------------------------------ */
function generateFork() {
  if (!currentAnalysis) {
    analyzeJson();
  }
  if (!currentAnalysis) {
    alert("Primero pega un JSON válido.");
    return;
  }

  const domain = normalizeName($("forkDomain").value || currentAnalysis.domainName);
  const prefix = normalizeName($("forkPrefix").value || currentAnalysis.prefix);
  const fields = $("forkFields").value.split(",").map((f) => normalizeName(f.trim(), "")).filter(Boolean);

  if (!fields.length) {
    alert("Agrega al menos un campo.");
    return;
  }

  // Rebuild strategies for current fields only
  const strategies = {};
  for (const f of fields) {
    strategies[f] = currentAnalysis.strategies[f] || { type: "primitive", label: "primitive", sourceType: "unknown" };
  }

  currentFork = { domain, prefix, fields, strategies, schema: currentAnalysis.schema };

  const sampleRecords = currentAnalysis.candidate.records.slice(0, 3);
  const generated = generateForkPrompt(domain, prefix, fields, strategies, currentAnalysis.schema, sampleRecords);

  $("forkPrompt").textContent = generated.prompt;
  $("forkPrompt").classList.remove("muted");
  $("forkGrammar").textContent = generated.grammar;
  $("forkGrammar").classList.remove("muted");
  $("forkExample").textContent = generated.example;
  $("forkExample").classList.remove("muted");

  switchTab("prompt");
}

/* ------------------------------------------------------------------
   UI: Tabs
   ------------------------------------------------------------------ */
function switchTab(tab) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $("panelPrompt").classList.toggle("active", tab === "prompt");
  $("panelGrammar").classList.toggle("active", tab === "grammar");
  $("panelExample").classList.toggle("active", tab === "example");
  $("panelTester").classList.toggle("active", tab === "tester");
}

/* ------------------------------------------------------------------
   UI: Copy / Download
   ------------------------------------------------------------------ */
async function copyText(text, okMessage) {
  try {
    await navigator.clipboard.writeText(text);
    alert(okMessage || "Copiado.");
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
    alert(okMessage || "Copiado.");
  }
}

function copyPrompt() {
  const text = $("forkPrompt").textContent;
  if (!text.trim()) { generateFork(); copyPrompt(); return; }
  copyText(text, "Prompt copiado al portapapeles.");
}

function downloadPrompt() {
  if (!currentFork) generateFork();
  const text = $("forkPrompt").textContent;
  if (!text.trim()) return;
  const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `prompt_mini_${currentFork.prefix}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* ------------------------------------------------------------------
   UI: Tester
   ------------------------------------------------------------------ */
function testFork() {
  if (!currentFork) {
    alert("Primero genera el fork.");
    return;
  }
  let data;
  try {
    data = JSON.parse($("testInput").value);
  } catch (err) {
    $("testOutput").innerHTML = `<span class="bad">JSON inválido: ${escapeHtml(err.message)}</span>`;
    return;
  }

  const candidate = findBestRecordArray(data);
  if (!candidate) {
    $("testOutput").innerHTML = `<span class="bad">No se encontró array de registros en el JSON de prueba.</span>`;
    return;
  }

  const mini = recordsToMini(candidate.records, currentFork.prefix, currentFork.fields, currentFork.strategies, currentFork.schema);
  lastTestMini = mini;
  $("testOutput").classList.remove("muted");
  $("testOutput").textContent = mini;
}

function highlightMini(text) {
  return text.split("\n").map((line) => {
    let html = escapeHtml(line).replaceAll("|", '<span class="pipe">|</span>').replaceAll("*", '<span class="star">*</span>');
    html = html.replace(/([a-zA-Z_]+)=/g, '<span class="key">$1</span>=');
    return `<span class="mini-line">${html}</span>`;
  }).join("");
}

function splitMiniLine(line) {
  const parts = [];
  let current = "";
  let escaped = false;
  for (const ch of line) {
    if (escaped) { current += ch; escaped = false; continue; }
    if (ch === "\\") { escaped = true; continue; }
    if (ch === "|") { parts.push(current); current = ""; continue; }
    current += ch;
  }
  parts.push(current);
  return parts;
}

function validateMiniText(text) {
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  const errors = [];
  if (!lines.length) return { ok: false, errors: ["No hay contenido .mini."], lines, header: "", records: [] };
  const header = lines[0];
  const records = lines.slice(1);
  if (!/^[a-zA-Z][a-zA-Z0-9_-]*\|/.test(header)) errors.push("La cabecera debe comenzar con un discriminador, por ejemplo a|, q|, r|.");
  const nMatch = header.match(/(?:^|\|)n=(\d+)/);
  if (nMatch && Number(nMatch[1]) !== records.length) errors.push(`La cabecera declara n=${nMatch[1]}, pero hay ${records.length} registros.`);
  const kMatch = header.match(/(?:^|\|)k=([^|]+)/);
  if (kMatch) {
    const expected = kMatch[1].split(",").filter(Boolean).length;
    records.forEach((r, idx) => {
      const got = splitMiniLine(r).length;
      if (got !== expected) errors.push(`Registro ${idx + 1}: tiene ${got} campos, pero k declara ${expected}.`);
    });
  }
  return { ok: errors.length === 0, errors, lines, header, records };
}

function validateTestOutput() {
  const text = lastTestMini;
  if (!text.trim()) {
    $("testOutput").textContent = "Primero haz clic en 'Convertir con fork' para generar output .mini.";
    return;
  }
  const res = validateMiniText(text);
  const base = lastTestMini;
  if (res.ok) {
    $("testOutput").textContent = base + `\n\n---\n✓ Validación correcta: ${res.records.length} registros, cabecera válida.`;
  } else {
    $("testOutput").textContent = base + `\n\n---\n✗ Errores:\n${res.errors.join("\n")}`;
  }
}

/* ------------------------------------------------------------------
   Init
   ------------------------------------------------------------------ */
loadDemoJson();
