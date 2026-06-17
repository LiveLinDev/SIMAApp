const data = require('./test_session.json');

function normalizeName(value, fallback = 'data') {
  const clean = String(value || fallback).trim().toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9_\-]+/g, '_').replace(/^_+|_+$/g, '');
  return clean || fallback;
}
function todayCompact() {
  return new Date().toISOString().slice(0, 10).replaceAll('-', '');
}
function findBestRecordArray(data) {
  const candidates = [];
  function scan(obj, path, depth) {
    if (!obj || typeof obj !== 'object') return;
    if (Array.isArray(obj)) {
      if (obj.length === 0) return;
      const objItems = obj.filter(x => x && typeof x === 'object' && !Array.isArray(x));
      if (objItems.length > 0) {
        const allKeys = new Set();
        objItems.forEach(item => Object.keys(item).forEach(k => allKeys.add(k)));
        candidates.push({ path, depth, length: obj.length, objCount: objItems.length, fieldCount: allKeys.size, sample: objItems[0], records: objItems });
      }
    } else {
      for (const [key, val] of Object.entries(obj)) {
        scan(val, path ? `${path}.${key}` : key, depth + 1);
      }
    }
  }
  scan(data, '', 0);
  candidates.sort((a, b) => {
    const score = c => c.objCount * 15 + c.fieldCount * 8 - c.depth * 3 + Math.log1p(c.length);
    return score(b) - score(a);
  });
  return candidates[0];
}
function extractSchema(records) {
  const schema = {};
  const allKeys = new Set();
  records.forEach(r => { if (r && typeof r === 'object') Object.keys(r).forEach(k => allKeys.add(k)); });
  allKeys.forEach(key => {
    const values = records.map(r => r?.[key]).filter(v => v !== undefined);
    const types = new Set(values.map(v => { if (v === null) return 'null'; if (Array.isArray(v)) return 'array'; return typeof v; }));
    const nonNullSample = values.find(v => v !== null && v !== undefined);
    let subtype = null, nestedFields = null, arrayItemSample = null;
    if (Array.isArray(nonNullSample) && nonNullSample.length > 0) {
      arrayItemSample = nonNullSample[0];
      if (arrayItemSample && typeof arrayItemSample === 'object' && !Array.isArray(arrayItemSample)) {
        nestedFields = [...new Set(nonNullSample.flatMap(o => (o && typeof o === 'object' ? Object.keys(o) : [])))];
        subtype = 'object';
      } else {
        subtype = typeof arrayItemSample;
      }
    } else if (typeof nonNullSample === 'object' && nonNullSample !== null) {
      nestedFields = Object.keys(nonNullSample);
    }
    schema[key] = { types: [...types], sample: nonNullSample, subtype, nestedFields, arrayItemSample, isNullable: values.some(v => v === null), arrayLength: Array.isArray(nonNullSample) ? nonNullSample.length : null };
  });
  return schema;
}
function detectArrayStrategy(key, info) {
  if (!info.types.includes('array') || info.subtype !== 'object' || !info.nestedFields) return null;
  const nf = info.nestedFields;
  if (nf.includes('key') && nf.includes('text')) return { type: 'key_value', label: 'key:value pairs', sep: ';' };
  if (nf.includes('text') && nf.includes('correct')) return { type: 'text_correct', label: 'text* for correct', sep: ',' };
  if (nf.length === 2 && nf.includes('id') && (nf.includes('name') || nf.includes('text'))) return { type: 'id_name', label: 'id:name pairs', sep: ';' };
  return { type: 'json', label: 'JSON compact', sep: null };
}
function detectObjectStrategy(key, info) {
  if (info.types.includes('array') || (info.types.includes('null') && info.types.length === 1)) return null;
  if (typeof info.sample !== 'object' || info.sample === null) return null;
  const nf = info.nestedFields || [];
  if (nf.length <= 3) return { type: 'flatten', label: 'flatten k=v', sep: ';' };
  return { type: 'json', label: 'JSON compact', sep: null };
}
function buildStrategies(schema) {
  const strategies = {};
  for (const [key, info] of Object.entries(schema)) {
    const arr = detectArrayStrategy(key, info);
    if (arr) { strategies[key] = { ...arr, sourceType: info.types.join('/') }; continue; }
    const obj = detectObjectStrategy(key, info);
    if (obj) { strategies[key] = { ...obj, sourceType: info.types.join('/') }; continue; }
    let label = info.types.join('/');
    if (info.types.includes('boolean')) label += ' -> 1/0';
    strategies[key] = { type: 'primitive', label, sourceType: info.types.join('/') };
  }
  return strategies;
}
function serializeMiniValue(key, value, strategy, schemaInfo) {
  if (value === null || value === undefined) return '';
  if (strategy.type === 'primitive') {
    if (typeof value === 'boolean') return value ? '1' : '0';
    if (Array.isArray(value)) return value.map(v => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join(';');
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value)
      .replaceAll('\\', '\\\\')
      .replaceAll('|', '\\|')
      .replaceAll('\n', ' ')
      .replaceAll('\r', ' ')
      .trim();
  }
  if (strategy.type === 'key_value') {
    if (!Array.isArray(value)) return serializeMiniValue(key, value, { type: 'primitive' }, schemaInfo);
    return value.map(o => { if (!o || typeof o !== 'object') return String(o); const k = o.key ?? o.id ?? o.code ?? '?'; const t = o.text ?? o.name ?? o.value ?? ''; return `${k}:${t}`; }).join(';');
  }
  if (strategy.type === 'flatten') {
    if (!value || typeof value !== 'object') return serializeMiniValue(key, value, { type: 'primitive' }, schemaInfo);
    const nf = schemaInfo.nestedFields || Object.keys(value);
    return nf.map(k => { const v = value[k]; if (v === null || v === undefined) return `${k}=`; return `${k}=${String(v).replaceAll(';', ',').replaceAll('|', '\\|')}`; }).join(';');
  }
  if (strategy.type === 'json') {
    return JSON.stringify(value).replaceAll('\\', '\\\\').replaceAll('|', '\\|').replaceAll('\n', ' ').replaceAll('\r', ' ');
  }
  return String(value);
}
function recordsToMini(records, prefix, fields, strategies, schema) {
  const header = `${prefix}|n=${records.length}|d=${todayCompact()}|t=${normalizeName('response')}|k=${fields.join(',')}`;
  const lines = records.map((row, idx) => {
    if (!row || typeof row !== 'object') return `${prefix}${idx + 1}|${row}`;
    return fields.map(f => {
      const strat = strategies[f] || { type: 'primitive' };
      const info = schema[f] || {};
      return serializeMiniValue(f, row[f], strat, info);
    }).join('|');
  });
  return [header, ...lines].join('\n');
}
function validateMiniText(text) {
  const lines = text.split(/\r?\n/).filter(l => l.trim());
  const errors = [];
  if (!lines.length) return { ok: false, errors: ['No hay contenido .mini.'], lines, header: '', records: [] };
  const header = lines[0];
  const records = lines.slice(1);
  if (!/^[a-zA-Z][a-zA-Z0-9_-]*\|/.test(header)) errors.push('La cabecera debe comenzar con un discriminador, por ejemplo a|, q|, r|.');
  const nMatch = header.match(/(?:^|\|)n=(\d+)/);
  if (nMatch && Number(nMatch[1]) !== records.length) errors.push(`La cabecera declara n=${nMatch[1]}, pero hay ${records.length} registros.`);
  const kMatch = header.match(/(?:^|\|)k=([^|]+)/);
  if (kMatch) {
    const expected = kMatch[1].split(',').filter(Boolean).length;
    records.forEach((r, idx) => {
      const got = r.split('|').length;
      if (got !== expected) errors.push(`Registro ${idx + 1}: tiene ${got} campos, pero k declara ${expected}.`);
    });
  }
  return { ok: errors.length === 0, errors, lines, header, records };
}

const candidate = findBestRecordArray(data);
const schema = extractSchema(candidate.records);
const strategies = buildStrategies(schema);
const fields = Object.keys(schema);
const mini = recordsToMini(candidate.records, 'r', fields, strategies, schema);
console.log('=== Total lines:', mini.split('\n').length);
console.log('=== Line lengths:');
mini.split('\n').forEach((line, i) => console.log(`Line ${i}: ${line.length} chars`));
const v = validateMiniText(mini);
console.log('=== Validation OK:', v.ok);
console.log('=== Errors:', v.errors);
