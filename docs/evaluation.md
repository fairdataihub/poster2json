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

## Validation Results

### Current Performance (v0.8.0, pdfplumber)

**Overall**: 19/20 (95%) passing

| Poster ID | Word | ROUGE-L | Numbers | Fields | Source | Status |
|-----------|------|---------|---------|--------|--------|--------|
| 10890106 | 0.84 | 0.77 | 0.91 | 0.84 | pdfplumber | ✅ |
| 15963941 | 0.89 | 0.78 | 0.96 | 0.86 | pdfplumber | ✅ |
| 16083265 | 0.91 | 0.90 | 1.00 | 0.76 | pdfplumber | ✅ |
| 17268692 | 0.92 | 0.94 | 0.88 | 1.02 | pdfplumber | ✅ |
| 42 | 0.96 | 0.97 | 1.00 | 0.88 | pdfplumber | ✅ |
| 4446908 | 0.92 | 0.79 | 0.97 | 0.80 | pdfplumber | ✅ |
| 4448680 | 0.92 | 0.85 | 1.00 | 0.83 | pdfplumber | ✅ |
| 4519718 | 0.92 | 0.82 | 0.94 | 0.78 | pdfplumber | ✅ |
| 4552067 | 0.92 | 0.99 | 1.00 | 0.77 | pdfplumber | ✅ |
| 4560930 | 0.87 | 0.86 | 0.96 | 0.90 | pdfplumber | ✅ |
| 4564017 | 0.93 | 0.87 | 0.99 | 0.75 | pdfplumber | ✅ |
| 4607450 | 0.94 | 0.86 | 0.85 | 1.00 | pdfplumber | ✅ |
| 4737132 | 0.91 | 0.89 | 1.00 | 0.93 | qwen_vision | ✅ |
| 5128504 | 0.97 | 0.91 | 1.00 | 0.83 | pdfplumber | ✅ |
| 6724771 | 0.89 | 0.85 | 0.96 | 0.82 | pdfplumber | ✅ |
| 8228476 | 0.94 | 0.84 | 1.00 | 0.91 | pdfplumber | ✅ |
| 8228568 | 0.98 | 0.89 | 1.00 | 0.82 | pdfplumber | ✅ |
| AISec2025-poster | 0.90 | 0.81 | 0.99 | 1.35 | pdfplumber | ✅ |
| aysaekanger | 0.83 | 0.71 | 1.00 | 1.00 | pdfplumber | ❌ |
| isporeu2023ee359130949 | 0.94 | 0.80 | 1.00 | 0.80 | pdfplumber | ✅ |

### Aggregate Metrics

| Metric | Average Score |
|--------|---------------|
| Word Capture | 0.92 |
| ROUGE-L | 0.85 |
| Number Capture | 0.97 |
| Field Proportion | 0.88 |

### Failure Analysis

| Poster ID | Failing Metric | Score | Root Cause |
|-----------|----------------|-------|------------|
| aysaekanger | ROUGE-L | 0.71 | Dense table/flowchart poster. The reference annotation splits one visual region into many fine-grained, row-aligned sections; the section-averaged ROUGE-L then penalizes the longer merged generated sections on precision. Word capture (0.83) and number capture (1.00) both pass — the text is fully extracted, only the section segmentation differs from the annotator's. |

## Test Set

The validation set includes 20 manually annotated scientific posters:

- **19 PDF posters**: Processed via pdfplumber
- **1 image poster**: Processed via Qwen2-VL

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

