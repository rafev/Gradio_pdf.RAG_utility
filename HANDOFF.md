# Handoff: hybrid KG schema and ontology cross-references

**Status:** designed, not implemented. Pick this up when API credits are topped up. Written 2026-09-24.
**Estimated API cost to complete:** about $9 for 21 papers (re-extraction ~$8, entity linking ~$1). It grows linearly with the corpus, so do it before adding many more papers.

---

## 1. Why

The corpus will grow beyond sleep research into health, biomarkers, longevity, machine learning and statistics. The current entity types (`Method, Model, Dataset, Task, Metric, Concept, Field`) were designed around ML papers, and they already strain on a 21-paper health corpus:

- 137 of 358 entities fell into the catch-all type **Concept**.
- 258 of 1,458 edges fell into the catch-all relation **RELATED_TO**. Most of these are health *associations* the schema can't express.
- Merging via alternative names (aliases) is too permissive. `Type 2 Diabetes` picked up the alias `diabetes`, and `R (statistical software)` picked up `R`. Either could swallow unrelated entities from future papers. Merge results also depend slightly on ingest order (356 vs 358 entities after an order change).

The fix has two parts:
1. A **two-level hybrid schema**: stable, domain-general core types plus a free-text `subtype`.
2. **Ontology cross-references** ("xrefs"), used as the primary identity for merging.

The graph stays a **property graph** (NetworkX, per-edge provenance). Xrefs give shared identity without moving to RDF, and an RDF/JSON-LD export stays possible later.

---

## 2. Step 0: fix the extraction cache key (prerequisite, no API cost)

`data/extractions/<sha256>.json` is keyed only by PDF content (`src/paper_rag/ingest/pipeline.py`, `_ingest_one`). Change the schema and run `--rebuild`, and it would **silently reuse old-schema extractions**.

- Add `SCHEMA_VERSION = 2` in `kg_extract.py`.
- Change the cache path to `data/extractions/v{SCHEMA_VERSION}/{sha256}.json`, and move the existing files to `v1/`.
- Test: bumping the version forces a new extraction call, and the same version reuses the cache.

---

## 3. Draft hybrid schema (v2)

### 3.1 Entity: core `type` plus free-text `subtype`

The core types describe **what a thing is**, not its role in one study. Roles such as exposure or outcome are expressed by relations. That is what lets `Sleep Duration` be the same node whether a paper treats it as an exposure or as an outcome.

| Core type | Covers | Example subtypes | Examples from corpus / roadmap |
|---|---|---|---|
| **Condition** | diseases, disorders, adverse health outcomes | chronic disease, psychiatric disorder, mortality | Type 2 Diabetes, Depression, All-cause Mortality |
| **Trait** | behaviours and physiological or phenotypic traits of people | sleep behaviour, circadian phenotype, ageing phenotype | Sleep Duration, Chronotype, Social Jetlag, Biological Age |
| **Exposure** | external, environmental or occupational factors and interventions | occupational, environmental, pharmacological, behavioural intervention | Shift Work, Light at Night, Metformin, CBT-I |
| **Biomarker** | measurable molecular or physiological indicators | glycemic marker, hormone, epigenetic, genetic variant, proteomic | HbA1c, Cortisol, DNA methylation age, rs-numbers |
| **Measure** | instruments, scales, metrics and statistics | questionnaire, device, performance metric, effect-size statistic | MCTQ, PSQI, Actigraphy score, AUROC, Hazard Ratio |
| **Method** | study designs, statistical and ML techniques | study design, regression, causal inference, deep learning | Cross-sectional Study, Mendelian Randomization, Cox Regression, Gradient Boosting |
| **Model** | *named* trained models, algorithms or clocks | epigenetic clock, neural network, risk score | GrimAge, PhenoAge, BERT, SCORE |
| **Dataset** | cohorts, biobanks, surveys, benchmark datasets | biobank, cohort, national survey, benchmark | UK Biobank, NHANES, NHIS, ImageNet |
| **Population** | demographic or clinical groups studied | age group, occupational group, patient group | Shift-working nurses, Adolescents with T1D, Older adults |
| **Task** | problems that methods or models address | prediction, classification, staging | Sleep Staging, Mortality Prediction |
| **Concept** | *fallback*: theories and abstract ideas that fit nothing else | theory, mechanism | Two-process model, Circadian Misalignment (mechanism) |
| **Field** | disciplines | – | Chronobiology, Epidemiology, Machine Learning |

**Tie-break rules** for the extraction prompt:

- A named predictive model or clock (GrimAge, PhenoAge) is a **Model**. The quantity it outputs ("epigenetic age acceleration") is a **Biomarker**.
- Instruments (MCTQ) are a **Measure**. The trait they quantify (chronotype) is a **Trait**.
- Prefer a specific core type over Concept. Concept should stay under about 10% of entities.
- The subtype is a short lowercase noun phrase. The prompt lists the existing subtypes per type so Claude reuses them (the same technique already used for entity names).

**Colour groups for the UI.** The three-group rule stays (see README: seven hues don't pass all-pairs contrast); papers stay white and ringed.

| Group | Colour | Types |
|---|---|---|
| Health | orange `#d95926` | Condition, Trait, Exposure, Biomarker |
| Methods & data | blue `#3987e5` | Method, Model, Measure, Task, Dataset |
| Context | aqua `#199e70` | Population, Concept, Field |

### 3.2 Relations: types plus optional properties

| Relation | Direction | Use |
|---|---|---|
| **ASSOCIATED_WITH** | exposure/trait → outcome | the main health relation (replaces most RELATED_TO) |
| **PREDICTS** | Model/Measure/Biomarker → Condition/Trait | predictive-performance claims |
| **MEASURES** | Measure/Biomarker → Trait/Condition | instrument or marker quantifies a construct |
| **MODIFIES** | Exposure (intervention) → Condition/Trait/Biomarker | intervention effects |
| PROPOSES, USES, STUDIES, EVALUATES_ON | THIS_PAPER → entity | paper-level (STUDIES is new: the paper's subject) |
| EXTENDS, OUTPERFORMS | Method/Model → Method/Model | ML and methods lineage |
| IS_A, PART_OF | taxonomic | structure |
| RELATED_TO | – | last-resort fallback only |

New **optional** properties on `Relation`. They are null unless the paper states them, so ML papers aren't burdened:

```python
class Relation(BaseModel):
    source: str
    target: str
    type: RelationType
    evidence: str
    page: int | None
    # v2 additions (all optional)
    direction: Literal["positive", "negative", "nonlinear", "null", "mixed"] | None
    shape: str | None          # e.g. "U-shaped", "inverted U", "dose-response"
    effect: str | None         # verbatim, e.g. "HR 1.21 (1.10–1.33)", "AUROC 0.82"
    design: Literal["cross-sectional", "longitudinal", "case-control", "RCT",
                    "mendelian-randomization", "meta-analysis", "simulation", "other"] | None
    population: str | None     # entity name of the Population / Dataset it holds in
```

Example (Bouman 2023): `Social Jetlag —ASSOCIATED_WITH→ HbA1c` with `direction=positive, effect="+1.87 mmol/mol (0.75–2.99)", design=cross-sectional, population="Working adults with T2D"`. A second edge covers the retirees with `direction=negative`. The agent can then answer "in whom, how strong, what design" straight from the graph.

---

## 4. Ontology cross-references (xrefs)

### 4.1 Design

- Each entity gets `xrefs: [{"id": "MONDO:0005148", "label": "type 2 diabetes mellitus", "source": "ols4", "score": 0.93}]`.
- **Xrefs are the primary identity for merging:**
  - Same xref → merge, even with different names.
  - Different xrefs of the same ontology → **never** merge, even with similar names or a shared alias. This fixes T1D vs T2D and the `diabetes` alias problem.
- **Claude must not invent IDs.** Models produce plausible-looking but wrong ontology IDs. Linking is *retrieve then choose*:
  1. Look up candidates by label and aliases in real ontology services (free public APIs).
  2. Claude picks the best candidate for each entity from that list, or "none", in batches of about 20 entities. It never types an ID itself.
- Linking runs as a **separate pass** over the graph (`python -m paper_rag.link`), not inside extraction. It is cached per canonical entity key in `data/xrefs.json`, so only new entities are linked on later runs.

### 4.2 Which vocabularies, by core type

| Core type | Primary | Secondary |
|---|---|---|
| Condition | MONDO (unifies DOID, Orphanet, OMIM) | HP (phenotypes), MeSH |
| Trait | OBA (Ontology of Biological Attributes), EFO | HP, MeSH |
| Exposure | ECTO (exposures), ChEBI (chemicals and drugs) | MeSH |
| Biomarker | ChEBI (molecules), HGNC/UniProt (genes/proteins), EFO (measurements) | NCIT |
| Measure | NCIT, EFO; STATO for statistics (HR, AUROC) | LOINC *(licence/registration required, optional)* |
| Method | STATO (statistics), OBI (study designs) | Wikidata (ML techniques) |
| Model / Task / Dataset | Wikidata | – |
| Population | NCIT, EFO | – |
| Concept / Field | MeSH, Wikidata | – |

**Services:**
- **EBI OLS4 search API** covers MONDO, HP, EFO, ECTO, ChEBI, OBI, STATO, NCIT, OBA and more. It supports `ontology=` filters, so query only the ontologies for that entity's type.
- **Wikidata** `wbsearchentities` covers ML/stats models, datasets and methods.
- **MeSH:** check whether OLS4 indexes it. Otherwise use NCBI E-utilities.
- Respect rate limits (throttle about 5 requests/second) and cache every response.

### 4.3 UI and agent usage

- The NodeCard shows xrefs as links, such as an OLS page for `MONDO:0005148` or a Wikidata page for `Q…`.
- `find_entities` also matches by xref id, and tool outputs include xrefs so the agent can say "Type 2 Diabetes (MONDO:0005148)".
- Future option: export to JSON-LD/RDF using the xrefs as IRIs if interoperability is ever needed.

---

## 5. Implementation plan (in order)

| # | Change | Files | API cost |
|---|---|---|---|
| 0 | Versioned extraction cache (section 2) | `ingest/kg_extract.py`, `ingest/pipeline.py`, tests | – |
| 1 | v2 schema: types, `subtype`, relations + properties, tie-break rules and existing-subtype list in the prompt | `ingest/kg_extract.py` | – |
| 2 | Store `subtype`, relation properties and `xrefs`. Tighter alias merging: require a type match, ignore aliases under 3 characters, and never merge via an alias that is itself an existing entity's canonical name. | `graph/store.py`, `graph/export.py` | – |
| 3 | Entity-linking pass (OLS4 + Wikidata retrieval, Claude choose-from-candidates), cached | new `graph/linking.py`, new `link/__main__.py` | ~$1 |
| 4 | Xref-first merging in `_upsert_entity` / `resolve` | `graph/store.py` | – |
| 5 | Agent: subtype, xrefs and relation properties in tool outputs; new tool `find_associations(source?, target?, direction?, design?)`; update tool enums (derived automatically from the type lists) | `agent/tools.py`, `agent/prompts.py` | – |
| 6 | UI: new type→group mapping, subtype on nodes and tooltips, xref links in NodeCard, relation properties as chips on edges | `frontend/src/lib/palette.ts`, `lib/types.ts`, `components/NodeCard.tsx`, `GraphScene.tsx` | – |
| 7 | Tests: schema v2 round-trip, xref merge and block rules, alias tightening, linking with mocked HTTP, cache versioning | `tests/` | – |
| 8 | Re-extract: `python -m paper_rag.ingest --rebuild` (v2 cache misses → new Claude calls), then `python -m paper_rag.link` | – | ~$8 |
| 9 | Verify with the graph-quality metrics below | – | – |

Optional: consolidate subtypes after ingest. Cluster near-duplicate subtypes per type (fuzzy match plus embeddings) into a mapping in `data/subtypes.json`, which is cheap and deterministic.

### Success criteria (step 9)

| Metric | Before (v1) | Target (v2) |
|---|---|---|
| Entities typed Concept | 137 / 358 (38%) | < 10% |
| Edges typed RELATED_TO | 258 / 1,458 | < 5% of typed relations |
| Entities with at least one xref | 0 | > 70% for Condition/Trait/Exposure/Biomarker |
| Cross-xref merges (same ontology, different IDs) | n/a | 0 |
| Merge results stable under ingest order | 356 vs 358 | identical |
| Citation links between corpus papers | 17 | ≥ 17 |
| All tests | 30 + 5 pass | all pass |

---

## 6. Current project state (for whoever picks this up)

- **Corpus:** 21 papers in `corpus/papers/`, renamed `author-year.pdf`; original names in `data/rename_log.json`. Two front-matter PDFs are set aside in `corpus/excluded/`.
- **Built index:** 1,284 chunks (bge-base-en-v1.5, local GPU, `HF_HUB_OFFLINE=1`) and a KG of 379 nodes and 1,458 edges. v1 extractions are cached in `data/extractions/`, with rebuilds costing $0.
- **Run:**
  - Ingest: `uv run python -m paper_rag.ingest`
  - Local app: `uv run python -m paper_rag.api`, then open http://127.0.0.1:8000
  - Public (Cloudflare quick tunnel plus admin approval): `.\scripts\serve.ps1 -Public` (install `cloudflared` first)
- **Observed costs (Opus 5):** full extraction of 21 papers ≈ $6.80. One cross-paper question ≈ 125k input / 3k output tokens (mostly cached); a simple question ≈ 28k input.
- **Environment notes:**
  - git needs `-c safe.directory=…`, or run once: `git config --global --add safe.directory "D:/Python Training Data/GitHub/Gradio_pdf.RAG_utility"`.
  - `uv` is on PATH only in new shells.
- **Not committed yet.** All of this is uncommitted on `main`.
