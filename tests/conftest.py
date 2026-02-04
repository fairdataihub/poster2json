"""Integration tests configuration file.

Tests that require a GPU (e.g. extraction with LLMs) should be marked with
@pytest.mark.gpu so they are skipped in CI (make test runs with -m 'not gpu').
Run them locally with: pytest -m gpu
"""
