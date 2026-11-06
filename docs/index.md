# poster2json

Convert scientific posters (PDF/images) to structured JSON metadata using Large Language Models.

## Overview

**poster2json** extracts structured metadata from scientific conference posters into machine-actionable JSON conforming to the [poster-json-schema](https://github.com/fairdataihub/poster-json-schema).

## Features

- **PDF Processing**: Layout-aware text extraction via pdfplumber
- **Image Processing**: Vision-based OCR via Qwen2-VL-7B
- **JSON Structuring**: Llama 3.1 8B (instruct) for poster-specific metadata
- **Schema Validation**: Built-in validation against poster-json-schema
- **CLI & Python API**: Flexible usage options

## Quick Start

### Installation

```bash
pip install poster2json
```

### CLI Usage

```bash
# Extract metadata from a poster
poster2json extract poster.pdf -o result.json

# Validate extracted JSON
poster2json validate result.json
```

### Python API

```python
from poster2json import extract_poster, validate_poster

# Extract metadata
result = extract_poster("poster.pdf")
print(result["titles"][0]["title"])

# Validate
is_valid = validate_poster(result)
```

## Architecture

The pipeline processes posters in two stages:

1. **Raw Text Extraction**
   - PDF files → pdfplumber (layout-aware text)
   - Image files → Qwen2-VL-7B (vision OCR)

2. **JSON Structuring**
   - Raw text → Llama 3.1 8B → Structured JSON

See [Architecture](architecture.md) for technical details, and [Extraction Prompt: Design and History](prompt-design.md) for why the LLM prompt asks for what it does.

## Performance

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

See [Evaluation](evaluation.md) for how each field is compared.

## Requirements

- NVIDIA GPU with ≥16GB VRAM
- Python 3.10+

## Links

- [GitHub Repository](https://github.com/fairdataihub/poster2json)
- [PyPI Package](https://pypi.org/project/poster2json)
- [poster-json-schema](https://github.com/fairdataihub/poster-json-schema)
- [posters.science](https://posters.science)
