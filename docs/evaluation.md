# Evaluation

Validation methodology and results for poster2json.

## Metrics

The pipeline is validated using four complementary metrics:

| Metric | Description | Threshold | Rationale |
|--------|-------------|-----------|-----------|
| **Word Capture (w)** | Proportion of reference vocabulary in extracted text | ≥0.75 | Measures lexical completeness |
| **ROUGE-L (r)** | Longest common subsequence similarity | ≥0.75 | Captures sequential text preservation |
| **Number Capture (n)** | Proportion of numeric values preserved | ≥0.75 | Validates quantitative data integrity |
| **Field Proportion (f)** | Ratio of extracted to reference JSON elements | 0.50–2.00 | Accommodates layout variability |

### Pass Criteria

A poster passes validation if ALL conditions are met:
- Word Capture ≥ 0.75
- ROUGE-L ≥ 0.75
- Number Capture ≥ 0.75
- Field Proportion between 0.50 and 2.00

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

The extended range (0.50–2.00) accommodates:
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

### Current Performance (v0.1.5)

**Overall**: 19/20 (95%) passing

| Poster ID | Word | ROUGE-L | Numbers | Fields | Source | Status |
|-----------|------|---------|---------|--------|--------|--------|
| 10890106 | 0.94 | 0.75 | 1.00 | 0.80 | pdfalto | ✅ |
| 15963941 | 0.95 | 0.91 | 0.97 | 0.76 | pdfalto | ✅ |
| 16083265 | 0.90 | 0.87 | 0.96 | 0.71 | pdfalto | ✅ |
| 17268692 | 0.97 | 0.99 | 0.91 | 0.83 | pdfalto | ✅ |
| 42 | 0.97 | 0.87 | 0.97 | 0.77 | pdfalto | ✅ |
| 4446908 | 0.95 | 0.91 | 0.90 | 0.98 | pdfalto | ✅ |
| 4448680 | 0.79 | 0.81 | 0.69 | 0.97 | pdfalto | ❌ |
| 4519718 | 0.98 | 0.99 | 0.89 | 0.78 | pdfalto | ✅ |
| 4552067 | 0.94 | 0.92 | 1.00 | 0.75 | pdfalto | ✅ |
| 4560930 | 0.96 | 0.91 | 0.96 | 0.92 | pdfalto | ✅ |
| 4564017 | 0.94 | 0.97 | 0.85 | 0.83 | pdfalto | ✅ |
| 4607450 | 0.95 | 0.93 | 0.93 | 0.89 | pdfalto | ✅ |
| 4737132 | 0.91 | 0.81 | 0.93 | 0.83 | qwen_vision | ✅ |
| 5128504 | 0.97 | 0.99 | 0.92 | 0.88 | pdfalto | ✅ |
| 6724771 | 0.93 | 0.95 | 0.82 | 0.91 | pdfalto | ✅ |
| 8228476 | 0.94 | 0.88 | 0.90 | 0.75 | pdfalto | ✅ |
| 8228568 | 0.97 | 0.82 | 0.92 | 0.68 | pdfalto | ✅ |
| AISec2025-poster | 0.92 | 0.80 | 0.89 | 1.98 | pdfalto | ✅ |
| aysaekanger | 0.95 | 0.85 | 0.80 | 1.09 | pdfalto | ✅ |
| isporeu2023ee359130949 | 0.96 | 0.79 | 0.98 | 1.45 | pdfalto | ✅ |

### Aggregate Metrics

| Metric | Average Score |
|--------|---------------|
| Word Capture | 0.94 |
| ROUGE-L | 0.89 |
| Number Capture | 0.91 |
| Field Proportion | 0.93 |

### Failure Analysis

| Poster ID | Failing Metric | Score | Root Cause |
|-----------|----------------|-------|------------|
| 4448680 | Number Capture | 0.69 | Model misses numeric data from the Systems subsection of this multi-component SOFC poster |

## Test Set

The validation set includes 20 manually annotated scientific posters:

- **19 PDF posters**: Processed via pdfalto
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

```bash
python poster_extraction.py \
    --annotation-dir ./manual_poster_annotation \
    --output-dir ./test_results
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

- [Architecture](ARCHITECTURE.md) - Technical details
- [API Reference](API.md) - REST API documentation

