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

### Llama 3.1 8B Poster Extraction

**Model**: [jimnoneill/Llama-3.1-8B-Poster-Extraction](https://huggingface.co/jimnoneill/Llama-3.1-8B-Poster-Extraction)

Fine-tuned version of Meta's Llama 3.1 8B Instruct for scientific poster metadata extraction:

- 8B parameters
- 128K context window
- Optimized for structured JSON output
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
  "$schema": "https://posters.science/schema/v0.1/poster_schema.json",
  "creators": [...],
  "titles": [...],
  "posterContent": {
    "sections": [
      {"sectionTitle": "...", "sectionContent": "..."}
    ]
  },
  "imageCaptions": [
    {"captions": ["Figure 1.", "Description"]}
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
| `HF_TOKEN` | HuggingFace API token |

### Model Configuration

```python
JSON_MODEL_ID = "jimnoneill/Llama-3.1-8B-Poster-Extraction"
VISION_MODEL_ID = "Qwen/Qwen2-VL-7B-Instruct"
MAX_JSON_TOKENS = 18000
MAX_RETRY_TOKENS = 24000
```

## See Also

- [Evaluation](EVALUATION.md) - Validation metrics and results
- [API Reference](API.md) - REST API documentation
- [Installation](INSTALLATION.md) - Setup instructions

