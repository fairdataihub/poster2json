"""
poster2json CLI

Command-line interface for extracting structured JSON from scientific posters.
"""

import json
import sys
from pathlib import Path

import click
from art import tprint


@click.group(invoke_without_command=True)
@click.version_option(prog_name="poster2json")
@click.pass_context
def main(ctx):
    """
    poster2json - Convert scientific posters to structured JSON metadata.
    
    Extract structured metadata from scientific poster PDFs and images
    using Large Language Models. Output conforms to the poster-json-schema
    (DataCite-based format).
    
    Examples:
    
        # Extract metadata from a poster PDF
        poster2json extract poster.pdf
        
        # Extract to a specific output file
        poster2json extract poster.pdf -o result.json
        
        # Validate extracted JSON
        poster2json validate result.json
        
        # Process multiple posters in a directory
        poster2json batch ./posters/ -o ./output/
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        return


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "-o", "--output",
    type=click.Path(),
    help="Output JSON file path. If not provided, prints to stdout."
)
@click.option(
    "--pretty/--compact",
    default=True,
    help="Pretty-print JSON output (default: pretty)"
)
@click.option(
    "--model",
    "model_id",
    type=str,
    default=None,
    help=(
        "HuggingFace model ID to use for JSON structuring. Overrides the "
        "default Llama-3.1-8B-Instruct. Any instruct model works "
        "(e.g. google/gemma-2-9b-it, Qwen/Qwen2.5-7B-Instruct)."
    )
)
@click.option(
    "--quantization",
    type=click.Choice(["fp16", "8bit", "4bit"], case_sensitive=False),
    default=None,
    help="Precision mode for the JSON model. Defaults to 4bit (NF4)."
)
def extract(input_file: str, output: str, pretty: bool, model_id: str, quantization: str):
    """
    Extract structured JSON from a scientific poster.

    INPUT_FILE: Path to the poster file (PDF, JPG, or PNG)

    Requires a CUDA-capable GPU. The default 4bit quantization fits on
    ~6GB VRAM; use --quantization 8bit or fp16 if you have headroom and
    want slightly better quality. (Image/OCR posters also load a Qwen2-VL
    vision model at bf16 — expect higher peak VRAM on that path.)

    Examples:

        poster2json extract poster.pdf

        poster2json extract poster.jpg -o output.json

        poster2json extract poster.pdf --model google/gemma-2-9b-it --quantization 8bit
    """
    from .extract import extract_poster

    click.echo(f"Extracting metadata from: {input_file}", err=True)
    if model_id:
        click.echo(f"Model: {model_id}", err=True)
    if quantization:
        click.echo(f"Quantization: {quantization}", err=True)

    try:
        result = extract_poster(input_file, model_id=model_id, quantization=quantization)
        
        if "error" in result:
            click.echo(f"Error during extraction: {result['error']}", err=True)
            sys.exit(1)
        
        # Format output
        indent = 2 if pretty else None
        json_output = json.dumps(result, indent=indent, ensure_ascii=False)
        
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            with open(output, "w", encoding="utf-8") as f:
                f.write(json_output)
            click.echo(f"Output saved to: {output}", err=True)
        else:
            click.echo(json_output)
            
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "-v", "--verbose",
    is_flag=True,
    help="Show detailed validation errors"
)
def validate(input_file: str, verbose: bool):
    """
    Validate a poster JSON file against the schema.
    
    INPUT_FILE: Path to the JSON file to validate
    
    Examples:
    
        poster2json validate result.json
        
        poster2json validate result.json --verbose
    """
    from .validate import validate_comprehensive, validate_poster
    
    try:
        with open(input_file, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(f"Invalid JSON file: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error reading file: {e}", err=True)
        sys.exit(1)
    
    if verbose:
        result = validate_comprehensive(data)
        
        if result["valid"]:
            click.echo("✅ Poster JSON is valid")
        else:
            click.echo("❌ Poster JSON has validation errors")
        
        if result["schema_errors"]:
            click.echo("\nSchema Errors:")
            for error in result["schema_errors"]:
                click.echo(f"  - {error['path']}: {error['message']}")
        
        if result["field_issues"]:
            click.echo("\nField Issues:")
            for issue in result["field_issues"]:
                click.echo(f"  - {issue}")
        
        if result["warnings"]:
            click.echo("\nWarnings:")
            for warning in result["warnings"]:
                click.echo(f"  - {warning}")
        
        sys.exit(0 if result["valid"] else 1)
    else:
        is_valid = validate_poster(data, verbose=False)
        if is_valid:
            click.echo("✅ Valid")
            sys.exit(0)
        else:
            click.echo("❌ Invalid (use --verbose for details)")
            sys.exit(1)


@main.command()
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False))
@click.option(
    "-o", "--output-dir",
    type=click.Path(),
    default="./output",
    help="Output directory for extracted JSON files"
)
@click.option(
    "--pattern",
    default="*.pdf,*.jpg,*.png",
    help="File patterns to process (comma-separated)"
)
def batch(input_dir: str, output_dir: str, pattern: str):
    """
    Extract metadata from multiple posters in a directory.
    
    INPUT_DIR: Directory containing poster files
    
    Examples:
    
        poster2json batch ./posters/
        
        poster2json batch ./posters/ -o ./results/
        
        poster2json batch ./posters/ --pattern "*.pdf"
    """
    from .extract import extract_poster, log
    
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Find files matching patterns
    patterns = [p.strip() for p in pattern.split(",")]
    files = []
    for pat in patterns:
        files.extend(input_path.glob(pat))
    files = sorted(set(files))
    
    if not files:
        click.echo(f"No files found matching patterns: {pattern}", err=True)
        sys.exit(1)
    
    click.echo(f"Found {len(files)} files to process", err=True)
    
    results = []
    for i, file_path in enumerate(files, 1):
        click.echo(f"\n[{i}/{len(files)}] Processing: {file_path.name}", err=True)
        
        try:
            result = extract_poster(str(file_path))
            
            # Save output
            output_file = output_path / f"{file_path.stem}_extracted.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            
            success = "error" not in result
            results.append({
                "file": file_path.name,
                "output": str(output_file),
                "success": success,
                "error": result.get("error") if not success else None,
            })
            
            status = "✅" if success else "❌"
            click.echo(f"   {status} Saved to: {output_file}", err=True)
            
        except Exception as e:
            results.append({
                "file": file_path.name,
                "success": False,
                "error": str(e),
            })
            click.echo(f"   ❌ Error: {e}", err=True)
    
    # Summary
    successful = sum(1 for r in results if r["success"])
    click.echo(f"\n{'='*50}", err=True)
    click.echo(f"Completed: {successful}/{len(results)} successful", err=True)
    
    # Save results summary
    summary_file = output_path / "batch_results.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    click.echo(f"Summary saved to: {summary_file}", err=True)


@main.command()
def info():
    """
    Show information about poster2json.
    """
    tprint("poster2json")
    
    click.echo("\nConvert scientific posters to structured JSON metadata.")
    click.echo("\nDocumentation: https://fairdataihub.github.io/poster2json/")
    click.echo("Repository: https://github.com/fairdataihub/poster2json")
    click.echo("\nModels used:")
    click.echo("  - Llama 3.1 8B Poster Extraction (JSON structuring)")
    click.echo("  - Qwen2-VL-7B-Instruct (Vision OCR for images)")
    click.echo("\nRequirements:")
    click.echo("  - CUDA-capable GPU with ≥16GB VRAM")
    click.echo("  - pdfalto (for PDF processing)")


if __name__ == "__main__":
    main()
