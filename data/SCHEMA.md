# Extraction Schema

**Vocabulary (entity types, relationship types, aliases, precedence, IDs) lives in
[`ONTOLOGY.md`](./ONTOLOGY.md). This file defines the JSON shape the extractor
must return and the validation rules applied to it.**

---

## 1. Extraction output (one object per chunk)

```json
{
  "chunk_id": "services/auth-service.md#overview",
  "document": "services/auth-service.md",
  "entities": [
    {
      "id": "service:auth-service",
      "type": "Service",
      "canonical_name": "Auth Service",
      "aliases": ["authn-svc", "Authentication Service"],
      "properties": { "version": "5.4" },
      "confidence": 0.98
    }
  ],
  "relationships": [
    {
      "source_id": "service:auth-service",
      "source_name": "Auth Service",
      "type": "USES",
      "target_id": "database:postgresql",
      "target_name": "PostgreSQL",
      "properties": { "purpose": "credential store" },
      "confidence": 0.97,
      "evidence": "The Auth Service uses PostgreSQL as its credential store."
    }
  ]
}
```

`chunk_id` format: `<relative_path>` for a whole-document chunk, or
`<relative_path>#<section-slug>` when a document over ~350 tokens is split (slug =
lower-cased `##` heading, spaces → `-`). See `architecture.md` §6.

---

## 2. Entity object

| Field | Type | Rule |
|-------|------|------|
| `id` | string | `"<type_lowercase>:<slug(canonical_name)>"`. Deterministic. See ONTOLOGY §4. |
| `type` | enum | One of the 11 types in ONTOLOGY §1. |
| `canonical_name` | string | Must match the canonical column in ONTOLOGY §3 when the entity appears there. |
| `aliases` | string[] | May be empty. Must not collide with another entity's canonical name. |
| `properties` | object | Free-form, but `version` (string) is the only property the pipeline reads. |
| `confidence` | float | `0.0`–`1.0`. Drop entities below `0.80`. |
| `source_chunk_id` | string | Added by the pipeline, not the model — the `chunk_id` above. |

---

## 3. Relationship object

| Field | Type | Rule |
|-------|------|------|
| `source_id` / `target_id` | string | Must equal the `id` of an entity extracted in this run (same chunk or resolved later). |
| `source_name` / `target_name` | string | Canonical names. |
| `type` | enum | One of the 12 relationship types in ONTOLOGY §2. |
| `properties` | object | Only the keys listed for that type in ONTOLOGY §2. |
| `confidence` | float | `0.0`–`1.0`. Drop below `0.80`. |
| `evidence` | string | Exact substring of the chunk text. Validation checks this. |
| `source_chunk_id` | string | Added by the pipeline. |

For `HANDLES`, `target_name` is one of the controlled data-concern strings
(ONTOLOGY §2 notes) and `target_id` is `concern:<slug>`.

---

## 4. Validation rules (applied after every extraction call)

1. JSON parses and matches the Pydantic models (`ExtractionResult`).
2. Every `type` is in the allowed enum.
3. Every relationship `type`'s properties are a subset of the allowed keys.
4. `evidence` is a literal substring of the chunk (whitespace-normalised).
5. `confidence` in `[0, 1]`; rows below `0.80` are dropped, not failed.
6. `ALTERNATIVE_TO` is stored once (not both directions).
7. On failure: retry up to 3 times with the validation error appended to the
   prompt. After 3 failures, log the chunk to `failed_chunks` and continue.

---

## 5. Example — a full chunk extraction

Input chunk (`libraries/celery.md#dependencies`):

> Celery depends on Python. Celery depends on Redis, which Meridian uses as the
> Celery broker and result backend.

Expected output:

```json
{
  "chunk_id": "libraries/celery.md#dependencies",
  "document": "libraries/celery.md",
  "entities": [
    { "id": "library:celery", "type": "Library", "canonical_name": "Celery", "aliases": [], "properties": {}, "confidence": 0.99 },
    { "id": "language:python", "type": "Language", "canonical_name": "Python", "aliases": [], "properties": {}, "confidence": 0.98 },
    { "id": "database:redis", "type": "Database", "canonical_name": "Redis", "aliases": ["Redis cache"], "properties": {}, "confidence": 0.97 }
  ],
  "relationships": [
    { "source_id": "library:celery", "source_name": "Celery", "type": "DEPENDS_ON", "target_id": "language:python", "target_name": "Python", "properties": { "optional": false }, "confidence": 0.98, "evidence": "Celery depends on Python." },
    { "source_id": "library:celery", "source_name": "Celery", "type": "DEPENDS_ON", "target_id": "database:redis", "target_name": "Redis", "properties": { "optional": false }, "confidence": 0.95, "evidence": "Celery depends on Redis, which Meridian uses as the Celery broker and result backend." }
  ]
}
```
