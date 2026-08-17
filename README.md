# Regulatory Text Scraping and Validation

This repository contains code and data-processing tools for collecting, cleaning, organizing, and validating U.S. state regulatory text.

The project currently focuses on scraping state regulations from Cornell Law School, cleaning the scraped text, and comparing the resulting regulatory text with regulatory statistics from QuantGov (GMU) data.

## Project Goals

The main goals of this repository are to:

- Scrape complete state regulatory text from Cornell Law School.
- Preserve the regulatory hierarchy associated with each regulation.
- Clean text introduced by the Cornell website.
- Store state regulatory text in a consistent format across states.
- Compare scraped regulatory text with QuantGov regulatory statistics.
- Validate word counts and regulatory restriction counts across datasets.
- Build a structured regulatory-text dataset that can later be used for economic and LLM-based analysis.

## Repository Structure

A typical project structure is:

```text
GSR_work/
│
├── 000_papers/
│
├── 001_data/
│   │
│   ├── states_clean_data/
│   │   ├── .gitkeep
│   │   ├── arizona_cleaned_regulation_text.csv
│   │   ├── california_cleaned_regulation_text.csv
│   │   ├── new-mexico_cleaned_regulation_text.csv
│   │   ├── new-york_cleaned_regulation_text.csv
│   │   └── texas_cleaned_regulation_text.csv
│   │
│   ├── states_raw_data/
│   │   ├── .gitkeep
│   │   ├── cornell_arizona_failed_urls.csv
│   │   ├── cornell_arizona_regulations.csv
│   │   ├── cornell_california_failed_urls.csv
│   │   ├── cornell_california_regulations.csv
│   │   ├── cornell_new-mexico_failed_urls.csv
│   │   ├── cornell_new-mexico_regulations.csv
│   │   ├── cornell_new-york_failed_urls.csv
│   │   ├── cornell_new-york_regulations.csv
│   │   ├── cornell_texas_failed_urls.csv
│   │   └── cornell_texas_regulations.csv
│   │
│   ├── 00_title_scrape_notebook.ipynb
│   ├── 01_title_clean_up.ipynb
│   └── scrape.py
│
├── 002_compare_GMU/
│   │
│   ├── gmu_state_data/
│   │   └── ...
│   │
│   └── 00_compare_to_gmu.ipynb
│
├── .gitignore
└── README.md
```

The exact structure may evolve as additional states and processing steps are added.

## Data Sources

### Cornell Law School

Cornell's Legal Information Institute provides state regulatory text in a hierarchical structure.

Example:

```text
Title 1 - General Provisions
> Division 1 - Office of Administrative Law
> Chapter 1 - Review of Proposed Regulations
> Article 1 - Chapter Definitions
> Cal. Code Regs. Tit. 1, § 1 - Chapter Definitions
```

The scraper recursively follows the regulatory hierarchy until it reaches pages containing regulation text.

The raw scraped data generally contains columns such as:

- `hierarchy`
- `name`
- `text`
- `url`

Depending on the scraper version, additional metadata may also be stored.

### GMU / QuantGov

The GMU regulatory dataset contains regulatory statistics at different levels of a state's regulatory hierarchy.

Important columns include:

- `document_reference`
- `words`
- `shall`
- `must`
- `may_not`
- `prohibited`
- `required`

An example `document_reference` is:

```text
Title 1, Chapter 1
```

or:

```text
Title 1, Chapter 1, Division 1
```

These references are used to identify the corresponding subset of Cornell regulatory text.

## Scraping Workflow

The Cornell scraper begins from a state's main regulatory page and recursively follows links within the regulatory hierarchy.

Conceptually, the scraper performs a depth-first traversal:

```text
State
└── Title
    └── Division
        └── Chapter
            └── Article
                └── Regulation
```

When a page containing regulation text is reached, the scraper saves:

1. The regulation hierarchy.
2. The regulation name.
3. The regulation text.
4. The source URL.

The scraper then backtracks through the hierarchy and continues to the next unvisited page.

Failed URLs can also be stored separately so that unsuccessful pages can be retried later without rerunning the entire scrape.

## Cleaning Regulatory Text

Cornell pages contain additional website text surrounding the actual regulation.

For example, a raw text field may look like:

```text
Cal. Code Regs. Tit. 2, § 203.4 - Classes to Which Applicable
State Regulations Compare Employee development appraisal shall not be used ...
Notes Cal. Code Regs. Tit. 2, § 203.4 State regulations are updated quarterly ...
```

The cleaning process:

1. Removes everything before and including `State Regulations`.
2. Keeps the actual regulation text.
3. Splits everything after `Notes` into a separate `notes` column.
4. Removes the word `Notes` from the final regulation text.
5. Preserves the original internal spacing and formatting.

Example cleaned output:

```text
text:
Compare Employee development appraisal shall not be used in examinations
for promotion to classes with a maximum salary of less than $530 a month.

notes:
Cal. Code Regs. Tit. 2, § 203.4 State regulations are updated quarterly ...
```

A typical cleaning loop is:

```python
states_to_clean = [
    "california",
    "new-york",
    "new-mexico",
    "arizona",
    "texas",
]

for state in states_to_clean:
    pre_df = pd.read_csv(
        f"states_raw_data/cornell_{state}_regulations.csv"
    )

    df = clean_regulation_text(pre_df)

    df.to_csv(
        f"states_clean_data/{state}_cleaned_regulation_text.csv",
        index=False,
    )
```

## Matching GMU Documents to Cornell Regulatory Text

The GMU dataset identifies regulatory documents using the `document_reference` column.

For example:

```text
Title 1, Chapter 1
```

The Cornell dataset stores the full hierarchy:

```text
Title 1 - General Provisions
> Division 1 - Office of Administrative Law
> Chapter 1 - Review of Proposed Regulations
> Article 1 - Chapter Definitions
> Cal. Code Regs. Tit. 1, § 1 - Chapter Definitions
```

To connect the datasets, each GMU document reference is split into components.

Example:

```python
"Title 1, Chapter 1"
```

becomes:

```python
["Title 1", "Chapter 1"]
```

The Cornell dataset is then filtered to rows whose `hierarchy` contains all required components.

A reference such as:

```text
Title 1, Chapter 1, Division 1
```

requires a matching Cornell hierarchy to contain all three components.

## Validation Against GMU

After matching a GMU document to the corresponding Cornell rows, the repository calculates comparable statistics from the scraped text.

The comparison currently includes:

| Measure | GMU Column | Cornell Calculation |
|---|---|---|
| Total words | `words` | Word count across matched `text` rows |
| Shall | `shall` | Count of `shall` |
| Must | `must` | Count of `must` |
| May not | `may_not` | Count of the phrase `may not` |
| Prohibited | `prohibited` | Count of `prohibited` |
| Required | `required` | Count of `required` |

The resulting comparison dataframe contains columns similar to:

```text
document_reference
gmu_words
our_words
gmu_shall
our_shall
gmu_must
our_must
gmu_may_not
our_may_not
gmu_prohibited
our_prohibited
gmu_required
our_required
matched_rows
```

This makes it possible to identify differences between the Cornell regulatory text and the GMU dataset.

## Regulatory Restriction Counting

Restriction terms are counted directly from the matched regulatory text.

The primary terms currently used are:

```text
shall
must
may not
prohibited
required
```

The GMU column is named:

```python
may_not
```

but the phrase searched for in regulation text is:

```text
may not
```

Counts should be case-insensitive and should use complete-word matching so that unrelated substrings are not accidentally counted.

## Loading State Data

A typical workflow for loading data is:

```python
state = "california"

gmu_df = pd.read_csv(f"gmu_state_data/{state}/{state}_restrictions.csv")

df_our_data = pd.read_csv(f"states_clean_data/{state}_cleaned_regulation_text.csv")
```

The data can then be passed into the matching and comparison functions.

## Recommended Validation Workflow

Before running the comparison for an entire state, manually inspect several document references.

For example:

```python
test_reference = gmu_df.iloc[0]["document_reference"]

matched_df = find_matching_regulations(df_our_data, test_reference)

print(test_reference)

matched_df[["hierarchy", "text"]]
```

This is important because regulatory hierarchies differ across states and not every state uses exactly the same combination or ordering of:

- Titles
- Divisions
- Chapters
- Subchapters
- Articles
- Parts
- Sections

Matching logic should therefore be checked when a new state is added.

## Important Matching Considerations

Hierarchy matching should distinguish between similarly numbered components.

For example:

```text
Chapter 1
```

should not accidentally match:

```text
Chapter 10
Chapter 11
Chapter 12
```

The matching functions should therefore use sufficiently precise patterns when identifying hierarchy components.

Other possible complications include:

- Repealed regulations
- Reserved sections
- Missing hierarchy levels
- State-specific naming conventions
- Cornell pages containing navigation or comparison boilerplate
- Duplicate or redirected pages
- Temporary connection failures during scraping

## Python Requirements

The project currently relies primarily on Python and pandas.

Typical imports include:

```python
import pandas as pd
import re
```

The scraper may require additional packages depending on the current implementation, such as:

```text
requests
beautifulsoup4
playwright
```

Install project dependencies as needed:

```bash
pip install pandas requests beautifulsoup4
```

If Playwright is used:

```bash
pip install playwright
playwright install
```

## Running the Pipeline

The general state-level workflow is:

```text
1. Scrape Cornell regulatory pages
        ↓
2. Save raw state regulatory data
        ↓
3. Clean regulation text
        ↓
4. Save cleaned state data
        ↓
5. Load GMU state data
        ↓
6. Match GMU document references to Cornell hierarchies
        ↓
7. Calculate Cornell word and restriction counts
        ↓
8. Compare Cornell results with GMU statistics
        ↓
9. Investigate discrepancies
```

## Current States

The cleaning workflow has been structured to support multiple states, including:

- California
- New York
- New Mexico
- Arizona
- Texas

The scraper and matching logic are intended to be generalized to additional states.

## Future Work

Potential extensions to the repository include:

- Expanding collection to all 50 states.
- Improving hierarchy matching across state-specific regulatory structures.
- Adding automated validation checks.
- Tracking failed or missing regulation pages.
- Detecting repealed and reserved regulations.
- Comparing regulatory text across years.
- Building a searchable regulatory database.
- Measuring semantic similarity across regulations.
- Creating regulation-level embeddings.
- Applying LLM-based regulatory classification and coding.
- Comparing LLM-generated regulatory measures with existing QuantGov measures.

## Research Use

This repository is being developed as part of research on U.S. state regulation and the use of large language models for regulatory-text analysis.

The scraped and cleaned data are intended to support reproducible comparisons between existing quantitative regulatory measures and measures derived directly from regulatory text.

## Notes

This project is under active development. File names, folder organization, scraper behavior, and cleaning procedures may change as additional states are added and validation improves.
