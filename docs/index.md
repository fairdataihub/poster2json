# poster2json

Convert scientific posters (PDF/images) to structured JSON metadata using Large Language Models.

## Overview

**poster2json** extracts structured metadata from scientific conference posters into machine-actionable JSON conforming to the [poster-json-schema](https://github.com/fairdataihub/poster-json-schema).

## Features

- **PDF Processing**: Layout-aware text extraction via pdfalto
- **Image Processing**: Vision-based OCR via Qwen2-VL-7B
- **JSON Structuring**: Fine-tuned Llama 3.1 8B for poster-specific metadata
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
   - PDF files → pdfalto (layout-aware XML)
   - Image files → Qwen2-VL-7B (vision OCR)

2. **JSON Structuring**
   - Raw text → Llama 3.1 8B → Structured JSON

See [Architecture](architecture.md) for technical details.

## Performance

Validated on 10 manually annotated scientific posters with 100% pass rate.

See [Evaluation](evaluation.md) for detailed metrics.

## Requirements

- NVIDIA GPU with ≥16GB VRAM
- Python 3.10+
- pdfalto (for PDF processing)

## Links

- [GitHub Repository](https://github.com/fairdataihub/poster2json)
- [PyPI Package](https://pypi.org/project/poster2json)
- [poster-json-schema](https://github.com/fairdataihub/poster-json-schema)
- [posters.science](https://posters.science)
