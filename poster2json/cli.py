"""Example CLI for poster2json."""

import click


@click.command()
def main():
    """CLI entrypoint - example command."""
    click.echo("poster2json")
    click.echo("Refer to the documentation for usage instructions.")


if __name__ == "__main__":  # pragma: no cover
    main()  # pylint: disable=no-value-for-parameter
