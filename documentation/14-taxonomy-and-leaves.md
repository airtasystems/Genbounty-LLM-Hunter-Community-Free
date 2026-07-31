# 14 - Taxonomy & leaf catalog

Play categories are exact cataloged `L1.L2` leaves. Unknown or incomplete paths are
rejected (fail closed). This page is an operator browse guide for authoring plays. It does
**not** mean a play JSON file ships for every leaf - the schema/gold craft reference is
`playbooks/_template.json` (see [07 - Playbooks](07-playbooks.md)).

## Sources of truth

| Source | Role |
|--------|------|
| `playbooks/categories.py` → `PLAY_CATEGORY_TREE` | UI labels, hints, L1/L2 tree |
| `playbooks/taxonomy/category_catalog.json` | Machine catalog: capability families, leaf presets, technique families |
| `playbooks/category_catalog.py` | Loads/validates catalog against the tree |

Tables below track the tree. If taxonomy changes, regenerate this page from the sources
above (or use the live APIs).

## L1 groups

| L1 id | Label | Default L2 | Leaves | Hint |
|-------|-------|------------|--------|------|
| `other` | Mission | `custom` | 1 | Name the hunt - every mission is identified by its hunt name. |

**Total leaves:** 1 (`mission.hunt`). Operators name missions by **hunt name**; new file ids
are the hunt-name slug (not `other_custom_*`). The leaf id `mission.hunt` remains the
internal storage value.

## Capability families

Each leaf maps to a `capability_family` in the catalog. Required capabilities are hard
gates (`|` means any-of). Optional capabilities enrich authoring but do not make a
category applicable. `category_vectors` is the sole artifact-vector source for multimodal
leaves (empty for text-only).

| Family | Profile | Required | Optional | Vectors |
|--------|---------|----------|----------|---------|
| `text` | `-` | - | - | - |

Campaign / Generate skip plays whose required capabilities are not confirmed for the
target. Details: [07 - Strategy selection & capability gating](07-playbooks.md).

## Leaves by L1

Each row is an authoring leaf (`play_category` = `L1.L2`). New play file stems use the
**hunt-name slug** (e.g. `hidden_reasoning_leak.json`), not `{l1}_{l2}`.

### `other` - Mission

| Leaf | Label | Hint |
|------|-------|------|
| `mission.hunt` | Hunt | Short hunt name required; it also becomes the default mission file id. |

`mission.hunt` requires a hunt name (`play_category_label`) and authored `attack_techniques`
on every category. Display breadcrumb is the hunt name alone.

## Inspect live

**UI:** Missions → **Plan Mission** → Brief (hunt name + mission brief).

**API:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/plays/categories` | Taxonomy tree (Mission → Hunt; frozen for compatibility) |
| GET | `/api/plays/category-presets` | Mission preset catalog (`leaf_count`, families, leaf presets) |
| GET | `/api/plays/category-presets/{l1}/{l2}` | Exact leaf preset (`other`/`custom`); unknown leaves → HTTP 422 |

Operators set hunt name + brief in the UI; they do not pick among taxonomy leaves.

## See also

- [15 - Authoring a play](15-authoring-a-play.md)
- [07 - Playbooks & strategies](07-playbooks.md)
- [10 - API reference](10-api-reference.md)
