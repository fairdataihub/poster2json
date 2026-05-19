# Architecture

Technical architecture and methodology for poster2json.

## Pipeline Overview

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Input Poster   │────▶│  Raw Text       │────▶│  Structured     │
│  (PDF/Image)    │     │  Extraction     │     │  JSON Output    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │                        │
                    ┌─────────┴─────────┐    ┌────────┴────────┐
                    │                   │    │                 │
               [PDF Files]        [Image Files]    [Transformers]
                    │                   │         Llama 3.1 8B
               [pdfalto]         [Qwen2-VL-7B]   Section-aware
               XML Layout        Vision OCR      JSON Generation
```

## Models

### Llama 3.1 8B Instruct (default JSON structuring model)

**Model**: [fairdataihub/Llama-3.1-8B-Poster-Extraction](https://huggingface.co/fairdataihub/Llama-3.1-8B-Poster-Extraction) — a verbatim mirror of Meta's `Llama-3.1-8B-Instruct`. The repo name has historical reasons; the weights themselves are not fine-tuned.

Any HuggingFace instruct model works; pass `--model <repo-id>` to swap (e.g. `google/gemma-2-9b-it`, `Qwen/Qwen2.5-7B-Instruct`). The default loads at 4-bit NF4 quantization (~6GB VRAM); use `--quantization 8bit` or `fp16` for higher precision.

- 8B parameters
- 128K context window
- Strong section identification

### Qwen2-VL-7B-Instruct

**Model**: [Qwen/Qwen2-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2-VL-7B-Instruct)

Vision-language model for image-based poster OCR:

- 7B parameters
- Direct pixel-to-text extraction
- Multi-language support
- Layout-aware text recognition

## Stage 1: Raw Text Extraction

### PDF Processing (pdfalto)

For PDF files, the pipeline uses `pdfalto` to:

1. Convert PDF to ALTO XML format
2. Preserve layout structure and spatial coordinates
3. Extract text blocks maintaining reading order
4. Handle multi-column layouts

```python
# Simplified extraction flow
pdf_path → pdfalto → ALTO XML → parse_text_blocks() → raw_text
```

### Image Processing (Qwen2-VL)

For image files (JPG, PNG), the pipeline uses Qwen2-VL:

1. Load image directly into vision-language model
2. Generate text transcription via multimodal inference
3. Preserve section headers and content structure

```python
# Simplified extraction flow
image_path → load_image() → Qwen2-VL → raw_text
```

## Stage 2: JSON Structuring

Raw text is structured into JSON using Llama 3.1 8B with section-aware prompting.

### Prompt Engineering

The prompt explicitly:
- Enumerates common poster sections (Abstract, Introduction, Methods, Results, Discussion, Conclusions, References)
- Distinguishes semantically similar sections (e.g., "Key Findings" vs "References")
- Instructs verbatim text preservation

### Adaptive Token Management

1. **Initial attempt**: 18,000 output tokens
2. **If truncated**: Retry with 24,000 tokens
3. **If still truncating**: Switch to condensed prompt format

### JSON Repair

Post-processing handles common LLM output issues:

- Unescaped quotes in scientific notation
- Trailing commas in arrays/objects
- Unicode encoding errors
- Truncated JSON completion

## Post-Processing

After JSON extraction, the pipeline applies:

1. **Schema validation**: Ensures output matches poster-json-schema
2. **Caption normalization**: Converts to `captions` array format
3. **Section deduplication**: Removes duplicate content
4. **Unicode cleaning**: Removes bidirectional characters
5. **Table/chart data cleaning**: Removes axis labels from section content

## Normalization and Enrichment

After post-processing, the pipeline runs a series of normalization and enrichment steps that add or clean up metadata fields beyond what the LLM produces.

### Identifier extraction

DOIs, arXiv IDs, and other identifiers are extracted from the raw poster text using regex patterns. PDF link annotations are also parsed to find embedded URLs and DOIs. These populate the top-level `identifiers[]` and `relatedIdentifiers[]` arrays. The LLM prompt does not ask for identifiers; they come entirely from pattern matching.

Each identifier's `identifierType` is auto-classified based on its format (DOI, arXiv, URL, etc.).

### ORCID enrichment

ORCIDs are extracted from poster text via regex, then matched to the appropriate creator. If an ORCID is found, the `nameIdentifiers` array is populated with the ORCID value, and `nameIdentifierScheme` and `schemeURI` are set automatically.

### ROR enrichment

Affiliation names are looked up against the [ROR API](https://ror.org). When a match is found, `affiliationIdentifier`, `affiliationIdentifierScheme`, and `schemeUri` are populated.

### Publisher enrichment

If a publisher name is extracted, it is also looked up against ROR to populate `publisherIdentifier`, `publisherIdentifierScheme`, and `schemeURI`.

### Language detection

The `language` field is detected from the raw poster text using `langdetect`, overwriting any value the LLM may have produced. The result is an ISO 639-3 code (e.g., "eng").

### Description type

The LLM prompt instructs the model to classify `descriptionType` based on poster content. It defaults to "Abstract" for poster summaries, but the model can choose from the full set of DataCite description types (Abstract, Methods, SeriesInformation, TableOfContents, TechnicalInfo, Other).

### Rights normalization

License strings from the LLM are canonicalized to SPDX form. This includes alias matching, Creative Commons URL parsing, and fuzzy matching (Levenshtein distance 1). Junk entries like funding acknowledgments or boilerplate text are filtered out.

### Funding normalization

Award numbers are cleaned (whitespace normalization, punctuation stripping, uppercasing). Invalid URIs in `awardUri` and `schemeUri` are removed. Funder identifiers are cross-referenced against the Crossref Funder Registry.

### Subject normalization

Keywords go through Unicode NFKC normalization, whitespace collapsing, and case-insensitive deduplication.

## Memory Management

### GPU Memory Optimization

- Models loaded one at a time to minimize VRAM usage
- Automatic 8-bit quantization for GPUs with <16GB VRAM
- Model unloading between stages

### Automatic GPU Selection

```python
def get_best_gpu():
    # Select GPU with most available memory
    # Accounts for other processes using GPU
    # Falls back to CPU if no GPU available
```

## Output Schema

Outputs conform to [poster-json-schema](https://github.com/fairdataihub/poster-json-schema):

```json
{
  "$schema": "https://posters.science/schema/v0.2/poster_schema.json",
  "creators": [...],
  "titles": [...],
  "content": {
    "sections": [
      {"sectionTitle": "...", "sectionContent": "..."}
    ]
  },
  "imageCaptions": [
    {"caption": "Figure 1. Description"}
  ],
  "tableCaptions": [
    {"captions": ["Table 1.", "Description"]}
  ]
}
```

## File Structure

```
poster2json/
├── poster_extraction.py    # Main pipeline
│   ├── get_raw_text()      # Stage 1: Text extraction
│   ├── extract_json_with_retry()  # Stage 2: JSON structuring
│   ├── postprocess_json()  # Post-processing
│   └── calculate_metrics() # Evaluation
├── api.py                  # Flask REST API
├── Dockerfile              # Container definition
└── docker-compose.yml      # Orchestration
```

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `PDFALTO_PATH` | Path to pdfalto binary |
| `CUDA_VISIBLE_DEVICES` | GPU device(s) to use |

### Model Configuration

```python
JSON_MODEL_ID = "fairdataihub/Llama-3.1-8B-Poster-Extraction"
VISION_MODEL_ID = "Qwen/Qwen2-VL-7B-Instruct"
MAX_JSON_TOKENS = 18000
MAX_RETRY_TOKENS = 24000
```

## See Also

- [Evaluation](EVALUATION.md) - Validation metrics and results
- [API Reference](API.md) - REST API documentation
- [Installation](INSTALLATION.md) - Setup instructions

