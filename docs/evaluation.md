# Evaluation

Validation methodology and results for poster2json.

## Metrics

The pipeline is validated using four complementary metrics:

| Metric | Description | Threshold | Rationale |
|--------|-------------|-----------|-----------|
| **Word Capture (w)** | Proportion of reference vocabulary in extracted text | ≥0.75 | Measures lexical completeness |
| **ROUGE-L (r)** | Longest common subsequence similarity | ≥0.75 | Captures sequential text preservation |
| **Number Capture (n)** | Proportion of numeric values preserved | ≥0.75 | Validates quantitative data integrity |
| **Field Proportion (f)** | Ratio of extracted to reference JSON elements | 0.50–1.50 | Accommodates layout variability |

### Pass Criteria

A poster passes validation if ALL conditions are met:
- Word Capture ≥ 0.75
- ROUGE-L ≥ 0.75
- Number Capture ≥ 0.75
- Field Proportion between 0.50 and 1.50

## Metric Implementation

### Word Capture

Measures vocabulary overlap between extracted and reference text:

```python
word_capture = len(extracted_words & reference_words) / len(reference_words)
```

- Tokenized to individual words
- Case-insensitive comparison
- Excludes common stopwords

### ROUGE-L (Section-Aware)

Uses longest common subsequence with section-aware matching:

```python
global_score = rouge_l(all_extracted_text, all_reference_text)
section_scores = [rouge_l(ext_section, ref_section) for each pair]
final_score = max(global_score, mean(section_scores))
```

This "forgiving ROUGE" approach accounts for structural reorganization in poster layouts.

### Number Capture

Evaluates preservation of quantitative data:

```python
# Extract all numbers from text
extracted_numbers = extract_numeric_values(extracted_text)
reference_numbers = extract_numeric_values(reference_text)

# Exclude DOIs and publication years from references
reference_numbers = filter_doi_components(reference_numbers)

number_capture = len(extracted_numbers & reference_numbers) / len(reference_numbers)
```

### Field Proportion

Measures structural completeness:

```python
extracted_fields = count_json_fields(extracted_json)
reference_fields = count_json_fields(reference_json)
field_proportion = extracted_fields / reference_fields
```

The extended range (0.50–1.50) accommodates:
- Nested vs flat section structures
- Variable poster layouts
- Optional metadata fields

## Text Normalization

Before comparison, text is normalized:

1. **Unicode normalization** (NFKD)
2. **Whitespace consolidation**
3. **Quote unification** (curly → straight)
4. **Dash normalization** (em/en dash → hyphen)
5. **Case normalization** (lowercase)

## Field Accuracy (v0.10.5)

Field accuracy of poster2json 0.10.5 at default settings on 21 hand-labeled posters (20 PDF, 1 image). Each field is compared with the text printed on the poster using ROUGE-L, where 1.00 means identical. Posters is the number of labeled posters that have the field.

| Field | Posters | Mean ROUGE-L |
|-------|---------|--------------|
| Title | 21 | 0.978 |
| Author names | 21 | 0.898 |
| Given/family split | 12 | 1.000 |
| Affiliations | 21 | 0.953 |
| Author-affiliation assignment | 21 | 0.884 |
| Section text | 21 | 0.839 |
| Figure captions | 13 | 0.975 |
| Table captions | 5 | 1.000 |
| All content (forgiving) | 21 | 0.862 |
| Content, boundary-free F1 | 21 | 0.917 |

How each field is compared:

- Text is normalized (NFKD, accents removed, letters and digits only, lower case) and scored with ROUGE-L with stemming.
- Title, author names, the given/family split, affiliations and author-affiliation assignment are strict: the extracted field against the same labeled field.
- Section text: each labeled section against its best matching extracted passage, so a different heading or placement is not penalized.
- Captions: ROUGE-L recall against all extracted content, so a caption counts when its text is there, wherever it was filed.
- All content (forgiving): every labeled section and caption against its best matching extracted passage.
- Content, boundary-free F1: all labeled section and caption text against all extracted text, ignoring section order and boundaries.

Summaries, keywords and the research field are written or chosen by the model, not copied from the poster, so they are not scored. With 21 posters, differences under about 0.02 on a field are within run-to-run variation.

## Test Set

The validation set includes 21 hand-labeled scientific posters:

- **20 PDF posters**: text read with pdfplumber and the alto layout engine
- **1 image poster**: read with Qwen2-VL OCR

Posters cover diverse domains and formats:
- Biomedical informatics, astronomy, astrophysics, bioinformatics, genetics
- Altmetrics, research data management, research infrastructure, cybersecurity
- Oncology, health economics, fuel cell manufacturing
- Single and multi-column layouts
- Various font sizes and styles
- Tables, figures, and charts
- Multiple languages (English, German)

## Running Validation

Validation runs from the [poster2json-validation](https://github.com/fairdataihub/poster2json-validation) repo (the annotation directory is set in its `config.py`):

```bash
# Validate the full annotated set
python validate_model.py \
    --output-dir ./outputs/run1 \
    --text-extractor pdfplumber

# Validate a subset of posters
python validate_model.py --poster 4446908,8228568 --output-dir ./outputs/canary
```

Output:
- Individual `{poster_id}_extracted.json` files
- `results.json` with all metrics

## Reference Annotations

Ground truth annotations are stored in `manual_poster_annotation/`:

```
manual_poster_annotation/
├── {poster_id}/
│   ├── {poster_id}.pdf         # Source poster
│   ├── {poster_id}_sub-json.json  # Ground truth annotation
│   └── {poster_id}_raw.md      # Extracted raw text
```

## See Also

- [Architecture](architecture.md) - Technical details
- [Overview](index.md) - Quick start and feature summary

