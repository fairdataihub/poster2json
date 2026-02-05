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

### Current Performance

**Overall**: 10/10 (100%) passing

| Poster ID | Word | ROUGE-L | Numbers | Fields | Source | Status |
|-----------|------|---------|---------|--------|--------|--------|
| 10890106 | 0.98 | 0.85 | 1.00 | 0.89 | pdfalto | ✅ |
| 15963941 | 0.98 | 0.93 | 1.00 | 0.84 | pdfalto | ✅ |
| 16083265 | 0.90 | 0.90 | 0.82 | 0.92 | pdfalto | ✅ |
| 17268692 | 1.00 | 0.83 | 1.00 | 1.70 | pdfalto | ✅ |
| 42 | 0.99 | 0.88 | 1.00 | 0.85 | pdfalto | ✅ |
| 4737132 | 0.94 | 0.79 | 0.96 | 1.22 | qwen_vision | ✅ |
| 5128504 | 0.99 | 1.00 | 1.00 | 1.04 | pdfalto | ✅ |
| 6724771 | 0.89 | 0.95 | 0.85 | 0.96 | pdfalto | ✅ |
| 8228476 | 0.94 | 0.87 | 0.89 | 0.91 | pdfalto | ✅ |
| 8228568 | 0.99 | 0.91 | 0.82 | 0.79 | pdfalto | ✅ |

### Aggregate Metrics

| Metric | Average Score |
|--------|---------------|
| Word Capture | 0.96 |
| ROUGE-L | 0.89 |
| Number Capture | 0.93 |
| Field Proportion | 0.99 |

## Test Set

The validation set includes 10 manually annotated scientific posters:

- **9 PDF posters**: Processed via pdfalto
- **1 image poster**: Processed via Qwen2-VL

Posters cover diverse formats:
- Single and multi-column layouts
- Various font sizes and styles
- Tables, figures, and charts
- Multiple languages

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

