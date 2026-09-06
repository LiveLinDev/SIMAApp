"""Evidencia para la verificacion: busqueda web, documentos fuente y referencia EduQG."""
from __future__ import annotations

from pathlib import Path
import csv
import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from django.conf import settings

from .backends import (
    call_ai,
)
from .prompts import (
    read_prompt,
)


_EDUQG_CACHE = {}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())

    def text(self):
        return re.sub(r"\s+", " ", unescape(" ".join(self.parts))).strip()


def build_verification_source_context(mini_content: str, verification_mode: str = "web") -> str:
    source_context, _trace = build_verification_context(mini_content, verification_mode=verification_mode)
    return source_context


def build_verification_context(mini_content: str, verification_mode: str = "web") -> tuple[str, dict]:
    mode = normalize_verification_mode(verification_mode)
    parts = []
    trace = {
        "mode": mode,
        "web": {"enabled": False, "queries": [], "configured_sources": []},
        "eduqg": {"enabled": False, "matches": []},
    }

    if mode in {"eduqg", "hybrid"}:
        eduqg_context, eduqg_trace = build_eduqg_context(mini_content)
        parts.append(eduqg_context)
        trace["eduqg"] = eduqg_trace

    if mode in {"web", "hybrid"} and getattr(settings, "VERIFICATION_FETCH_SOURCES", True):
        web_context, web_trace = build_web_context(mini_content)
        parts.append(web_context)
        trace["web"] = web_trace

    context = "\n\n".join(part for part in parts if part.strip())
    budget = int(getattr(settings, "VERIFICATION_CONTEXT_MAX_CHARS", 14000) or 0)
    if budget > 0 and len(context) > budget:
        context = fit_context(context, budget)
        trace["context_truncated"] = True
    trace["context_chars"] = len(context)
    return context, trace


def fit_context(context: str, max_chars: int) -> str:
    """
    Recorta el contexto a un presupuesto de caracteres conservando bloques completos
    (cada fuente es un bloque separado por linea en blanco). Los proveedores con pocos
    tokens por minuto (niveles gratuitos) rechazan peticiones grandes con 413.
    """
    if len(context) <= max_chars:
        return context
    kept, used = [], 0
    for block in context.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        extra = len(block) + (2 if kept else 0)
        if used + extra > max_chars:
            if not kept:  # un solo bloque enorme: cortarlo en vez de quedarse sin contexto
                kept.append(block[: max(200, max_chars - 40)].rstrip() + " [...]")
            break
        kept.append(block)
        used += extra
    return "\n\n".join(kept)


def normalize_verification_mode(verification_mode: str) -> str:
    mode = (verification_mode or getattr(settings, "VERIFICATION_DEFAULT_MODE", "web") or "web").strip().lower()
    return mode if mode in {"web", "eduqg", "hybrid"} else "web"


def build_web_source_context(mini_content: str) -> str:
    context, _trace = build_web_context(mini_content)
    return context


def build_web_context(mini_content: str) -> tuple[str, dict]:
    urls = collect_verification_urls(read_prompt("verify_prompt.md"), mini_content)
    max_sources = max(0, int(getattr(settings, "VERIFICATION_MAX_SOURCES", 6)))
    timeout = max(1, int(getattr(settings, "VERIFICATION_SOURCE_TIMEOUT", 8)))
    chars = max(400, int(getattr(settings, "VERIFICATION_SOURCE_CHARS", 2200)))
    academic_enabled = bool(getattr(settings, "VERIFICATION_ACADEMIC_SEARCH", True))
    trace = {
        "enabled": True,
        "search_provider": "ddgs web search + academic targets",
        "academic_search": {
            "enabled": academic_enabled,
            "targets": ["arxiv.org", "scholar.google.com", "semanticscholar.org"],
        },
        "queries": [],
        "configured_sources": [],
        "query_generation": {},
        "evidence_summary": {"queries": 0, "results": 0, "usable_sources": 0},
    }
    snippets = []

    if getattr(settings, "VERIFICATION_DYNAMIC_WEB_SEARCH", True):
        query_entries = build_verification_query_entries(mini_content)
        trace["query_generation"] = {
            "source": query_entries[0].get("source", "") if query_entries else "",
            "count": len(query_entries),
            "error": query_entries[0].get("error", "") if query_entries else "",
        }
        query_entries = query_entries[: max(1, int(getattr(settings, "VERIFICATION_SEARCH_QUERIES", 3)))]
        result_limit = max(1, int(getattr(settings, "VERIFICATION_SEARCH_RESULTS", 3)))
        fetched_urls = set()
        for entry in query_entries:
            query = entry["query"]
            results = search_web(query, max_results=result_limit, timeout=timeout)
            academic_queries = _academic_search_queries(query) if academic_enabled else []
            for academic_query in academic_queries:
                academic_results = search_web(academic_query, max_results=1, timeout=timeout)
                for result in academic_results:
                    result["search_source"] = academic_query
                results.extend(academic_results)
            results = _dedupe_search_results(results)
            query_trace = {
                "query": query,
                "source": entry.get("source", "keyword"),
                "claim": entry.get("claim", ""),
                "academic_queries": academic_queries,
                "results": [],
            }
            for result in results:
                url = result["url"]
                if url in fetched_urls:
                    continue
                fetched_urls.add(url)
                document = fetch_source_document(url, timeout=timeout, max_chars=chars)
                result_trace = {**result, **document}
                query_trace["results"].append(result_trace)
                if document.get("ok"):
                    snippets.append(
                        f"BUSQUEDA_WEB: {query}\n"
                        f"FUENTE_BUSQUEDA: {result.get('search_source', 'web')}\n"
                        f"URL: {url}\n"
                        f"TITULO: {result.get('title', '')}\n"
                        f"CONTENIDO: {document.get('snippet', '')}"
                    )
            trace["queries"].append(query_trace)
        trace["evidence_summary"] = _web_evidence_summary(trace["queries"])

    for url in urls[:max_sources]:
        document = fetch_source_document(url, timeout=timeout, max_chars=chars)
        trace["configured_sources"].append(document)
        if document.get("ok"):
            snippets.append(f"URL: {url}\nCONTENIDO: {document.get('snippet', '')}")
        else:
            snippets.append(f"URL: {url}\nERROR_FETCH: {document.get('error', 'No se pudo leer la fuente.')}")

    return "\n\n".join(snippets), trace


def _academic_search_queries(query: str) -> list[str]:
    return [
        f"{query} site:arxiv.org",
        f"{query} site:scholar.google.com",
        f"{query} site:semanticscholar.org",
    ]


def _dedupe_search_results(results: list[dict]) -> list[dict]:
    deduped = []
    seen = set()
    for result in results:
        url = result.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(result)
    return deduped


def _web_evidence_summary(queries: list[dict]) -> dict:
    total = sum(len(query.get("results", [])) for query in queries)
    ok = sum(1 for query in queries for result in query.get("results", []) if result.get("ok"))
    return {"queries": len(queries), "results": total, "usable_sources": ok}


def build_verification_queries(mini_content: str) -> list[str]:
    return [entry["query"] for entry in build_verification_query_entries(mini_content)]


def build_verification_query_entries(mini_content: str) -> list[dict]:
    prompt = _build_ai_query_prompt(mini_content)
    if prompt:
        try:
            raw_output = call_ai(prompt + "\n/no_think", backend="local", role="verification")
            queries = _parse_ai_queries(raw_output)
            if queries:
                return [
                    {"query": query, "source": "ai", "claim": query, "error": ""}
                    for query in queries
                ]
        except Exception as exc:
            fallback = _fallback_verification_query_entries(mini_content)
            return [{**entry, "error": str(exc)[:240]} for entry in fallback]

    return _fallback_verification_query_entries(mini_content)


def _build_ai_query_prompt(mini_content: str) -> str:
    try:
        from ..parse_mini import parse_mini
    except Exception:
        return ""

    assessment = parse_mini(mini_content)
    rows = []
    for item in assessment.items[:8]:
        correct = next((opt.get("text", "") for opt in item.options if opt.get("correct")), "")
        if not correct:
            continue
        rows.append(
            f"- tema: {item.topic}\n"
            f"  enunciado: {item.statement}\n"
            f"  respuesta_correcta: {correct}"
        )

    if not rows:
        return ""

    return (
        "Eres un verificador academico. Extrae afirmaciones facticas comprobables "
        "desde estos items MINI y conviertelas en busquedas web precisas.\n\n"
        "Reglas:\n"
        "1. Devuelve solo texto plano: una busqueda por linea.\n"
        "2. Cada busqueda debe incluir el tema y la respuesta correcta que se quiere validar.\n"
        "3. Evita preguntas genericas; apunta a fuentes educativas, institucionales o enciclopedicas.\n"
        "4. Maximo 6 busquedas, 8 a 16 palabras por busqueda.\n\n"
        "ITEMS:\n"
        f"{chr(10).join(rows)}"
    )


def _parse_ai_queries(raw_output: str) -> list[str]:
    queries = []
    for raw_line in (raw_output or "").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^\s*(?:[-*•]|\d+[\).\:-])\s*", "", line)
        line = line.strip().strip("\"'`")
        if not line or line.lower() in {"no_think", "/no_think"}:
            continue
        if "|" in line:
            line = line.split("|")[-1].strip()
        line = re.sub(r"\s+", " ", line)
        if len(line.split()) < 3:
            continue
        line = line[:180]
        if line not in queries:
            queries.append(line)
        if len(queries) >= 6:
            break
    return queries


def _fallback_verification_query_entries(mini_content: str) -> list[dict]:
    keywords = _extract_keywords(mini_content)
    joined = " ".join(keywords[:10])
    title = ""
    assessment_topic = re.search(r"\|t=([^|]+)", mini_content)
    if assessment_topic:
        title = assessment_topic.group(1).replace("_", " ")
    questions = []
    for line in mini_content.splitlines():
        if line.startswith("i") and "|" in line:
            parts = line.split("|")
            if len(parts) > 4:
                questions.append(f"{parts[2]} {parts[3]}")
        if len(questions) >= 2:
            break
    candidates = [
        f"{title} {joined} facts",
        f"{' '.join(questions)}",
        f"{title} historia verificacion",
    ]
    queries = []
    for candidate in candidates:
        compact = re.sub(r"\s+", " ", candidate).strip()
        if compact and compact not in queries:
            queries.append(compact[:180])
    fallback_queries = queries or [joined or "educational multiple choice verification"]
    return [
        {"query": query, "source": "keyword", "claim": "", "error": ""}
        for query in fallback_queries
    ]


def search_web(query: str, max_results: int = 3, timeout: int = 8) -> list[dict]:
    """Busca en DuckDuckGo usando la libreria ddgs (maneja bloqueos y rate limits)."""
    try:
        from ddgs import DDGS
    except Exception:
        return []

    try:
        with DDGS() as ddgs:
            raw_results = ddgs.text(query, max_results=max(max_results, 5))
    except Exception:
        return []

    results = []
    for result in raw_results:
        url = normalize_search_result_url(result.get("href", ""))
        title = strip_html(result.get("title", ""))
        if not url or "duckduckgo.com" in urlparse(url).netloc:
            continue
        if any(r["url"] == url for r in results):
            continue
        results.append({"url": url, "title": title})
        if len(results) >= max_results:
            break
    return results


def normalize_search_result_url(href: str) -> str:
    parsed = urlparse(href)
    params = parse_qs(parsed.query)
    if "uddg" in params:
        return unquote(params["uddg"][0])
    if href.startswith("//"):
        return "https:" + href
    return href


def strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<.*?>", "", unescape(value))).strip()


def build_eduqg_source_context(mini_content: str) -> str:
    context, _trace = build_eduqg_context(mini_content)
    return context

    raw_reference_path = (getattr(settings, "EDUQG_REFERENCE_PATH", "") or "").strip()
    if not raw_reference_path:
        return (
            "EDUQG_LOCAL:\n"
            "EDUQG_REFERENCE_PATH esta vacio. El verificador no usara EduQG hasta que "
            "apuntes esa variable a un archivo .json/.jsonl/.csv/.txt o a una carpeta con esos archivos."
        )
    reference_path = Path(raw_reference_path)
    max_chars = max(1000, int(getattr(settings, "EDUQG_SOURCE_CHARS", 6000)))

    if not reference_path.exists():
        return (
            "EDUQG_LOCAL:\n"
            "No se encontro EDUQG_REFERENCE_PATH. El verificador no usara EduQG hasta que "
            "apuntes esa variable a un archivo .json/.jsonl/.csv/.txt o a una carpeta con esos archivos."
        )

    files = []
    if reference_path.is_file():
        files = [reference_path]
    else:
        for pattern in ("*.jsonl", "*.json", "*.csv", "*.txt", "*.md"):
            files.extend(reference_path.rglob(pattern))

    if not files:
        return (
            f"EDUQG_LOCAL:\nNo se encontraron archivos EduQG legibles en {reference_path}. "
            "Se mantiene el prompt de verificacion sin contexto EduQG."
        )

    keywords = _extract_keywords(mini_content)
    snippets = []
    remaining = max_chars
    for path in files[:12]:
        if remaining <= 0:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            snippets.append(f"ARCHIVO: {path}\nERROR_EDUQG: {exc}")
            continue
        snippet = _select_relevant_text(text, keywords, limit=min(remaining, 1800))
        if snippet:
            snippets.append(f"ARCHIVO: {path}\nCONTENIDO_EDUQG: {snippet}")
            remaining -= len(snippet)

    if not snippets:
        return f"EDUQG_LOCAL:\nNo se pudo extraer texto util desde {reference_path}."
    return "EDUQG_LOCAL:\n" + "\n\n".join(snippets)


def build_eduqg_context(mini_content: str) -> tuple[str, dict]:
    raw_reference_path = (getattr(settings, "EDUQG_REFERENCE_PATH", "") or "").strip()
    trace = {
        "enabled": True,
        "path": raw_reference_path,
        "exists": False,
        "files": [],
        "records_loaded": 0,
        "matches": [],
        "error": "",
    }
    if not raw_reference_path:
        trace["error"] = "EDUQG_REFERENCE_PATH esta vacio."
        return (
            "EDUQG_LOCAL:\nEDUQG_REFERENCE_PATH esta vacio. Configura una carpeta o archivo EduQG.",
            trace,
        )

    reference_path = Path(raw_reference_path)
    trace["exists"] = reference_path.exists()
    if not reference_path.exists():
        trace["error"] = "No se encontro EDUQG_REFERENCE_PATH."
        return (
            "EDUQG_LOCAL:\nNo se encontro EDUQG_REFERENCE_PATH. Configura una carpeta o archivo EduQG.",
            trace,
        )

    try:
        records, files = load_eduqg_records(reference_path)
    except Exception as exc:
        trace["error"] = str(exc)
        return f"EDUQG_LOCAL:\nERROR_EDUQG: {exc}", trace

    trace["files"] = [str(path) for path in files]
    trace["records_loaded"] = len(records)
    if not records:
        trace["error"] = "No se encontraron registros EduQG legibles."
        return "EDUQG_LOCAL:\nNo se encontraron registros EduQG legibles.", trace

    keywords = set(_extract_keywords(mini_content))
    scored = []
    for record in records:
        score = score_record(record["text"], keywords)
        scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)

    top_k = max(1, int(getattr(settings, "EDUQG_TOP_K", 5)))
    matches = scored[:top_k]
    max_chars = max(1000, int(getattr(settings, "EDUQG_SOURCE_CHARS", 6000)))
    remaining = max_chars
    blocks = []
    for score, record in matches:
        excerpt = record["excerpt"][: min(remaining, 1400)]
        if not excerpt:
            continue
        match = {
            "score": round(score, 4),
            "file": record["file"],
            "title": record["title"],
            "question": record["question"],
            "answer": record["answer"],
            "excerpt": excerpt,
        }
        trace["matches"].append(match)
        blocks.append(
            "EDUQG_MATCH:\n"
            f"archivo: {record['file']}\n"
            f"titulo: {record['title']}\n"
            f"score: {round(score, 4)}\n"
            f"pregunta_ejemplo: {record['question']}\n"
            f"respuesta_ejemplo: {record['answer']}\n"
            f"contexto: {excerpt}"
        )
        remaining -= len(excerpt)
        if remaining <= 0:
            break

    if not blocks:
        trace["error"] = "No se pudo extraer contexto util."
        return "EDUQG_LOCAL:\nNo se pudo extraer contexto util.", trace
    return "EDUQG_LOCAL:\n" + "\n\n".join(blocks), trace


def load_eduqg_records(reference_path: Path) -> tuple[list[dict], list[Path]]:
    files = collect_eduqg_files(reference_path)
    cache_key = (
        str(reference_path),
        tuple((str(path), path.stat().st_mtime, path.stat().st_size) for path in files),
    )
    if cache_key in _EDUQG_CACHE:
        return _EDUQG_CACHE[cache_key], files

    max_records = max(1, int(getattr(settings, "EDUQG_MAX_RECORDS", 6000)))
    records = []
    for path in files:
        if len(records) >= max_records:
            break
        records.extend(read_eduqg_file(path, limit=max_records - len(records)))

    _EDUQG_CACHE.clear()
    _EDUQG_CACHE[cache_key] = records
    return records, files


def collect_eduqg_files(reference_path: Path) -> list[Path]:
    if reference_path.is_file():
        return [reference_path]
    files = []
    for pattern in ("*.json", "*.jsonl", "*.csv", "*.txt", "*.md"):
        files.extend(reference_path.rglob(pattern))
    return sorted(files, key=lambda path: str(path).lower())


def read_eduqg_file(path: Path, limit: int) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return records_from_json(data, path, limit=limit)
    if suffix == ".jsonl":
        records = []
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if len(records) >= limit:
                    break
                if line.strip():
                    records.extend(records_from_json(json.loads(line), path, limit=limit - len(records)))
        return records
    if suffix == ".csv":
        records = []
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                text = " ".join(str(value) for value in row.values() if value)
                records.append(generic_eduqg_record(path, "CSV", text))
                if len(records) >= limit:
                    break
        return records
    text = path.read_text(encoding="utf-8", errors="replace")
    return [generic_eduqg_record(path, path.stem, text[:8000])] if text.strip() else []


def records_from_json(data, path: Path, limit: int) -> list[dict]:
    records = []
    chapters = data if isinstance(data, list) else [data]
    for chapter in chapters:
        if len(records) >= limit:
            break
        if not isinstance(chapter, dict):
            text = json.dumps(chapter, ensure_ascii=False)
            records.append(generic_eduqg_record(path, "JSON", text))
            continue
        bname = str(chapter.get("bname", "EduQG"))
        chapter_id = chapter.get("chapter", "")
        summary = str(chapter.get("summary", ""))
        questions = chapter.get("questions") or []
        for question_entry in questions:
            if len(records) >= limit:
                break
            records.append(record_from_eduqg_question(path, bname, chapter_id, summary, question_entry))
        if not questions:
            text = " ".join(str(chapter.get(key, "")) for key in ("intro", "chapter_text", "summary", "keyterm"))
            records.append(generic_eduqg_record(path, f"{bname} capitulo {chapter_id}", text))
    return records


def record_from_eduqg_question(path: Path, bname: str, chapter_id, summary: str, entry: dict) -> dict:
    question = entry.get("question", {}) if isinstance(entry, dict) else {}
    answer = entry.get("answer", {}) if isinstance(entry, dict) else {}
    question_text = str(question.get("normal_format") or question.get("question_text") or question.get("cloze_format") or "")
    choices = str(question.get("question_choices", ""))
    answer_text = str(answer.get("ans_text", ""))
    context = " ".join([
        str(entry.get("hl_sentences", "")),
        str(entry.get("hl_context", "")),
        summary[:1600],
    ])
    text = " ".join([bname, str(chapter_id), question_text, choices, answer_text, context])
    return {
        "file": str(path),
        "title": f"{bname} capitulo {chapter_id}".strip(),
        "question": question_text,
        "answer": answer_text,
        "text": normalize_text_for_score(text),
        "excerpt": re.sub(r"\s+", " ", context or text).strip(),
    }


def generic_eduqg_record(path: Path, title: str, text: str) -> dict:
    compact = re.sub(r"\s+", " ", text).strip()
    return {
        "file": str(path),
        "title": title,
        "question": "",
        "answer": "",
        "text": normalize_text_for_score(compact),
        "excerpt": compact[:2400],
    }


def normalize_text_for_score(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def score_record(text: str, keywords: set[str]) -> float:
    if not keywords:
        return 0
    hits = sum(1 for keyword in keywords if keyword in text)
    return hits / max(len(keywords), 1)


def _extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{5,}", text.lower())
    stop = {
        "pregunta", "respuesta", "opcion", "opciones", "correcta", "dificultad",
        "explicacion", "topic", "historia", "origen", "objetivo", "relacion",
    }
    ranked = []
    for word in words:
        if word not in stop and word not in ranked:
            ranked.append(word)
        if len(ranked) >= 20:
            break
    return ranked


def _select_relevant_text(text: str, keywords: list[str], limit: int = 1800) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    lowered = compact.lower()
    positions = [lowered.find(keyword) for keyword in keywords if lowered.find(keyword) >= 0]
    if not positions:
        return compact[:limit]
    start = max(min(positions) - 300, 0)
    return compact[start:start + limit]


def collect_verification_urls(*texts: str) -> list[str]:
    configured = getattr(settings, "VERIFICATION_SOURCE_URLS", "")
    candidates = re.split(r"[\s,]+", configured.strip()) if configured else []
    for text in texts:
        if not text:
            continue
        candidates.extend(re.findall(r"https?://[^\s<>'\"|,]+", text))
        candidates.extend(re.findall(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>'\"|,]*)?", text, flags=re.I))

    urls = []
    seen = set()
    for raw in candidates:
        url = raw.strip().rstrip(").,;")
        if not url:
            continue
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        key = url.rstrip("/")
        if key not in seen:
            seen.add(key)
            urls.append(key)
    return urls


def fetch_source_snippet(url: str, timeout: int = 8, max_chars: int = 2200) -> str:
    try:
        req = Request(url, headers={"User-Agent": "SIMA verifier/1.0"})
        with urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            raw = response.read(350_000)
            charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        if "html" in content_type.lower() or "<html" in text[:500].lower():
            parser = _HTMLTextExtractor()
            parser.feed(text)
            text = parser.text()
        else:
            text = re.sub(r"\s+", " ", text).strip()
        if not text or "Request unsuccessful" in text or "Incapsula incident" in text:
            return f"URL: {url}\nERROR_FETCH: La fuente no devolvió texto verificable."
        return f"URL: {url}\nCONTENIDO: {text[:max_chars]}"
    except Exception as exc:
        return f"URL: {url}\nERROR_FETCH: {exc}"


def fetch_source_document(url: str, timeout: int = 8, max_chars: int = 2200) -> dict:
    last_error = ""
    min_chars = max(120, min(350, max_chars // 8))
    for attempt in range(2):
        try:
            retry_timeout = timeout + (attempt * 4)
            req = Request(url, headers={"User-Agent": "SIMA verifier/1.0 (+https://sima.local)"})
            with urlopen(req, timeout=retry_timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(500_000)
                charset = response.headers.get_content_charset() or "utf-8"

            text = raw.decode(charset, errors="replace")
            if "html" in content_type.lower() or "<html" in text[:500].lower():
                parser = _HTMLTextExtractor()
                parser.feed(text)
                text = parser.text()
            else:
                text = re.sub(r"\s+", " ", text).strip()

            blocked_markers = ("Request unsuccessful", "Incapsula incident", "Access Denied", "Just a moment")
            if not text or any(marker.lower() in text.lower() for marker in blocked_markers):
                return {
                    "url": url,
                    "ok": False,
                    "content_type": content_type,
                    "chars": len(text),
                    "snippet": "",
                    "error": "La fuente no devolvio texto verificable.",
                }
            if len(text) < min_chars:
                return {
                    "url": url,
                    "ok": False,
                    "content_type": content_type,
                    "chars": len(text),
                    "snippet": text[:max_chars],
                    "error": "La fuente devolvio muy poco texto util para verificar.",
                }
            return {
                "url": url,
                "ok": True,
                "content_type": content_type,
                "chars": len(text),
                "snippet": text[:max_chars],
                "error": "",
            }
        except Exception as exc:
            last_error = str(exc)

    return {
        "url": url,
        "ok": False,
        "content_type": "",
        "chars": 0,
        "snippet": "",
        "error": last_error,
    }
