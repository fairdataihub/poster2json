<div align="center">

<img src="https://cdn.posters.science/logos/poster-fairy.png" alt="logo" width="200" height="auto" />

<br />

<h1>poster2json</h1>

<p>
Convert scientific posters (PDF/images) to structured JSON metadata using Large Language Models.
</p>

<br />

<p>
  <a href="https://github.com/fairdataihub/poster2json/graphs/contributors">
    <img src="https://img.shields.io/github/contributors/fairdataihub/poster2json.svg?style=flat-square" alt="contributors" />
  </a>
  <a href="https://github.com/fairdataihub/poster2json/stargazers">
    <img src="https://img.shields.io/github/stars/fairdataihub/poster2json.svg?style=flat-square" alt="stars" />
  </a>
  <a href="https://github.com/fairdataihub/poster2json/issues/">
    <img src="https://img.shields.io/github/issues/fairdataihub/poster2json.svg?style=flat-square" alt="open issues" />
  </a>
  <a href="https://github.com/fairdataihub/poster2json/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/fairdataihub/poster2json.svg?style=flat-square" alt="license" />
  </a>
</p>
<p>
  <a href="https://pypi.org/project/poster2json">
    <img src="https://img.shields.io/pypi/v/poster2json.svg" alt="PyPI Version" />
  </a>
  <a href="https://pypistats.org/packages/poster2json">
    <img src="https://img.shields.io/pypi/dm/poster2json.svg?color=orange" alt="PyPI Downloads" />
  </a>
  <a href="https://zenodo.org/badge/latestdoi/1105067405">
    <img src="https://zenodo.org/badge/1105067405.svg" alt="DOI" />
  </a>
</p>

<h4>
    <a href="https://fairdataihub.github.io/poster2json/">Documentation</a>
  <span> · </span>
    <a href="https://fairdataihub.github.io/poster2json/about/changelog/">Changelog</a>
  <span> · </span>
    <a href="https://github.com/fairdataihub/poster2json/issues/">Report Bug</a>
  <span> · </span>
    <a href="https://github.com/fairdataihub/poster2json/issues/">Request Feature</a>
</h4>
</div>

<br />

---

## Description

**poster2json** extracts structured metadata from scientific conference posters (PDF or image format) into machine-actionable JSON conforming to the [poster-json-schema](https://github.com/fairdataihub/poster-json-schema).

The pipeline uses:

- **Llama 3.1 8B** (fine-tuned) for JSON structuring
- **Qwen2-VL-7B** for vision-based OCR of image posters
- **pdfalto** for layout-aware PDF text extraction

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

# Process multiple posters
poster2json batch ./posters/ -o ./output/
```

### Python API

```python
from poster2json import extract_poster, validate_poster

# Extract metadata
result = extract_poster("poster.pdf")
print(result["titles"][0]["title"])

# Validate the result
is_valid = validate_poster(result)
```

## Output Format

Output conforms to the [poster-json-schema](https://github.com/fairdataihub/poster-json-schema) (DataCite-based):

```json
{
  "$schema": "https://posters.science/schema/v0.1/poster_schema.json",
  "creators": [
    {
      "name": "Garcia, Sofia",
      "givenName": "Sofia",
      "familyName": "Garcia",
      "affiliation": ["University"]
    }
  ],
  "titles": [
    { "title": "Machine Learning Approaches to Diabetic Retinopathy Detection" }
  ],
  "posterContent": {
    "sections": [
      { "sectionTitle": "Abstract", "sectionContent": "..." },
      { "sectionTitle": "Methods", "sectionContent": "..." },
      { "sectionTitle": "Results", "sectionContent": "..." }
    ]
  },
  "imageCaptions": [{ "captions": ["Figure 1.", "ROC curves showing..."] }],
  "tableCaptions": [{ "captions": ["Table 1.", "Performance metrics"] }]
}
```

## System Requirements

| Requirement | Specification                    |
| ----------- | -------------------------------- |
| GPU         | NVIDIA CUDA-capable, ≥16GB VRAM  |
| RAM         | ≥32GB recommended                |
| Python      | 3.10+                            |
| OS          | Linux, macOS, Windows (via WSL2) |

## Performance

Validated on 10 manually annotated scientific posters:

| Metric           | Score | Threshold |
| ---------------- | ----- | --------- |
| Word Capture     | 0.96  | ≥0.75     |
| ROUGE-L          | 0.89  | ≥0.75     |
| Number Capture   | 0.93  | ≥0.75     |
| Field Proportion | 0.99  | 0.30–2.50 |

**Pass Rate**: 10/10 (100%)

## Documentation

| Document                             | Description                     |
| ------------------------------------ | ------------------------------- |
| [Architecture](docs/architecture.md) | Technical details & methodology |
| [Evaluation](docs/evaluation.md)     | Validation metrics & results    |

## Development Setup

```bash
# Clone the repository
git clone https://github.com/fairdataihub/poster2json.git
cd poster2json

# Create a virtual environment
python -m venv .venv

# Activate the virtual environment
source venv/bin/activate
.venv\Scripts\activate # On Windows

# Install poetry
pip install poetry

# Install dependencies
poetry install

# Run tests
poe test

# Format code
poe format
```

If you are on windows and have multiple python versions, you can use the following commands:

```bash
py -0p # list all python versions

py -3.12 -m venv .venv
```

## License

MIT License - see [LICENSE](LICENSE.md) for details.

## Citation

```bibtex
@software{poster2json2026,
  title = {poster2json: Scientific Poster to JSON Metadata Extraction},
  author = {O'Neill, James and Soundarajan, Sanjay and Portillo, Dorian and Patel, Bhavesh},
  year = {2026},
  url = {https://github.com/fairdataihub/poster2json},
  doi = {10.5281/zenodo.18320010}
}
```

## Acknowledgements

- [FAIR Data Innovations Hub](https://fairdataihub.org/)
- Meta AI for Llama 3.1
- Alibaba Cloud for Qwen2-VL
- Part of the [posters.science](https://posters.science) platform

## Contributing

Contributions welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
