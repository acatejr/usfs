# Finding Duplicate Datasets (`dedupe`)

## What it does

The USFS inventory pulls dataset descriptions from three different Forest Service
sources. The same dataset is sometimes published in more than one place, often
with a slightly different title (for example, one copy ends in `(Map Service)`
and another does not). To a person these are obviously the same thing, but
because the titles are not *identical*, the tool treats them as two separate
records.

The `dedupe` command finds these **near-duplicates**. It compares the *meaning*
of each dataset's description — not just its title — and reports pairs that are
almost the same. This helps reviewers spot redundant entries and keep the
inventory clean.

## How to run it

From the project root:

```bash
uv run usfs dedupe
```

Before this works, the inventory must already be loaded and indexed. The normal
order is:

```bash
uv run usfs harvest    # download the source data and build the inventory
uv run usfs initdb     # set up the database
uv run usfs load       # load the inventory into the database
uv run usfs embed      # index the datasets so they can be compared
uv run usfs dedupe     # find near-duplicate pairs
```

### Adjusting sensitivity

`dedupe` only reports pairs that are at least 95% similar by default. You can
change that cutoff with `--threshold`:

```bash
uv run usfs dedupe --threshold 0.90
```

- A **higher** threshold (closer to `1.0`) reports fewer pairs, and only the
  ones that are nearly identical.
- A **lower** threshold reports more pairs, including ones that are merely
  related rather than truly duplicate.

`1.0` means "identical meaning"; `0.0` means "completely unrelated."

## Reading the results

Each line of output describes **one pair** of datasets that look like
duplicates of each other:

```
0.987  Wildfire Perimeters [fsgeodata:3a9f1c2b]  <->  Wildfire Perimeters [gdd:7e4d8a01]
```

Reading left to right:

| Part | Meaning |
|------|---------|
| `0.987` | The similarity score. `0.987` means the two datasets are ~98.7% alike — almost certainly the same dataset. |
| `Wildfire Perimeters` | The title of the first dataset. |
| `[fsgeodata:3a9f1c2b]` | The first dataset's **source** (`fsgeodata`) and a short **ID** (`3a9f1c2b`). |
| `<->` | Separator: "this dataset is similar to that one." |
| `Wildfire Perimeters [gdd:7e4d8a01]` | The second dataset, its source (`gdd`), and its ID. |

If no pairs are found above the threshold, the command prints:

```
No near-duplicate pairs found above threshold.
```

## Why the two titles can look the same

It is normal for both titles on a line to read identically. That does **not**
mean the tool is comparing a dataset to itself. The two halves are always
distinct records — you can confirm this by the bracketed labels:

- The **source** (`fsgeodata`, `gdd`, or `rda`) usually differs, showing the
  same dataset was published in two different places.
- The **ID** is always different. Two records can only appear together on a line
  if their IDs are different.

In short: matching titles next to *different* source/ID labels is the tool
working correctly — it has caught the same dataset listed twice.

## What to do with the results

The `dedupe` command **only reports** near-duplicates; it does not delete
anything. It is a review aid. Use the list to decide which redundant entries, if
any, should be removed or merged, and to understand how much overlap exists
across the three Forest Service sources.

## Quick reference

| Question | Answer |
|----------|--------|
| What does it find? | Pairs of datasets that mean nearly the same thing. |
| Does it delete anything? | No. It only reports pairs for review. |
| What is a good score? | `0.95` and above is a strong duplicate signal. |
| Why do titles look identical? | Same dataset, different source/ID — that's expected. |
| What must run first? | `harvest` → `load` → `embed`, then `dedupe`. |

## Step-by-step example

Here is what happens, start to finish, when two near-duplicate datasets exist in
the inventory.

**1. Two records come from different sources.** The same dataset was published in
the Geodata Clearinghouse and in the Geospatial Data Discovery feed, with
slightly different titles:

```
Source: fsgeodata   Title: "Wildfire Final Perimeters (Map Service)"
Source: gdd         Title: "Wildfire Final Perimeters"
```

**2. Each gets its own entry.** Because the titles are not *identical*, the tool
assigns each a different ID and stores them as two separate records — it does not
yet know they are the same thing.

**3. You run the command:**

```bash
uv run usfs dedupe
```

**4. The tool compares meanings, not titles.** It looks at the indexed
description of every dataset and measures how similar each pair is. Our two
records describe the same wildfire perimeters, so they score very high — say
`0.987` (98.7% alike).

**5. The score clears the threshold.** `0.987` is above the default cutoff of
`0.95`, so the pair is reported. (A pair scoring `0.80` would be skipped at the
default, but would appear if you lowered the threshold with `--threshold 0.80`.)

**6. You read the result:**

```
0.987  Wildfire Final Perimeters (Map Service) [fsgeodata:3a9f1c2b]  <->  Wildfire Final Perimeters [gdd:7e4d8a01]
```

This single line tells you the two records are almost certainly the same
dataset. The different sources (`fsgeodata` vs. `gdd`) and different IDs
(`3a9f1c2b` vs. `7e4d8a01`) confirm they are two genuine, separate records — not
one record matched against itself.

**7. You decide what to do.** The tool stops here; it only reports. A reviewer
can now choose to keep one copy, merge them, or leave both — `dedupe` never
changes the inventory on its own.
