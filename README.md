<div align="center">

<img src="https://raw.githubusercontent.com/fairdataihub/poster2json/main/logo.svg" alt="logo" width="200" height="auto" />

<br />

<h1>poster2json</h1>

<p>
Python package for the FAIR tools of fairhub.io
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
    <img src="https://img.shields.io/pypi/l/poster2json.svg" alt="PyPI License" />
  </a>
  <a href="https://pypi.org/project/poster2json">
    <img src="https://img.shields.io/pypi/v/poster2json.svg" alt="PyPI Version" />
  </a>
  <a href="https://pypistats.org/packages/poster2json">
    <img src="https://img.shields.io/pypi/dm/poster2json.svg?color=orange" alt="PyPI Downloads" />
  </a>
</p>

<h4>
    <a href="https://fairdataihub.github.io/poster2json/">Documentation</a>
  <span> · </span>
    <a href="https://fairdataihub.github.io/poster2json/about/changelog/">Changelog</a>
  <span> · </span>
    <a href="https://github.com/fairdataihub/poster2json/issues/">Report Bug</a>
  <span> · </span>
    <a href="#">Request Feature</a>
  </h4>
</div>

<br />

---

## Description

xxx

## Getting started

### Prerequisites/Dependencies

You will need the following installed on your system:

- [Python](<[https://www.python.org/](https://www.python.org/)>)

- [Pip](<[https://pip.pypa.io/en/stable/](https://pip.pypa.io/en/stable/)>)

- [Poetry](<[https://poetry.eustace.io/](https://poetry.eustace.io/)>)

### Installing

Install it directly into an activated virtual environment:

```bash

pip install poster2json

```

or add it to your [Poetry](<[https://poetry.eustace.io/](https://poetry.eustace.io/)>) project:

```bash

poetry add poster2json

```

### Usage

After installation, the package can be imported:

```bash

$ python

>>> import poster2json

>>> poster2json.__version__

```

### Inputs and Outputs

xxx

## Standards followed

xxx

## Contributing

<a href="[https://github.com/fairdataihub/poster2json/graphs/contributors](https://github.com/fairdataihub/poster2json/graphs/contributors)">

  <img src="[https://contrib.rocks/image?repo=fairdataihub/poster2json](https://contrib.rocks/image?repo=fairdataihub/poster2json)" alt="Contributors" />

</a>

Contributions are always welcome!

If you are interested in reporting/fixing issues and contributing directly to the code base, please see [[CONTRIBUTING.md](http://CONTRIBUTING.md)](<[CONTRIBUTING.md](http://CONTRIBUTING.md)>) for more information on what we're looking for and how to get started.

## Issues and Feedback

To report any issues with the software, suggest improvements, or request a new feature, please open a new issue via the [Issues](<[https://github.com/fairdataihub/poster2json/issues](https://github.com/fairdataihub/poster2json/issues)>) tab. Provide adequate information (operating system, steps leading to error, screenshots) so we can help you efficiently.

### Setup

If you would like to update the package, please follow the instructions below.

1. Create a local virtual environment and activate it:

   ```bash

   python -m venv .venv

   source .venv/bin/activate

   ```

   If you are using Anaconda, you can create a virtual environment with:

   ```bash

   conda create -n poster2json-env python

   conda activate poster2json-env

   ```

2. Install the dependencies for this package. We use [Poetry](<[https://poetry.eustace.io/](https://poetry.eustace.io/)>) to manage the dependencies:

   ```bash

   pip install poetry==1.3.2

   poetry install

   ```

   You can also use version 1.2.0 of Poetry, but you will need to run `poetry lock` after installing the dependencies.

3. Add your modifications and run the tests. You can also use the command `poe test` for running the tests.

   ```bash

   poetry run pytest

   ```

   If you need to add new python packages, you can use Poetry to add them:

   ```bash

    poetry add <package-name>

   ```

4. Format the code:

   ```bash

   poe format

   ```

5. Check the code quality:

   ```bash

   poetry run flake8 poster2json tests

   ```

6. Run the tests and check the code coverage:

   ```bash

   poe test

   poe test --cov=poster2json

   ```

7. Build the package:

   Update the version number in `pyproject.toml` and `poster2json/__init__.py` and then run:

   ```text

   poetry build

   ```

8. Publish the package:

   ```bash

   poetry publish

   ```

   Set your API token for PyPI in your environment variables:

   ```bash

   poetry config pypi-token.pypi your-api-token

   ```

## License

This work is licensed under

[MIT](<[https://opensource.org/licenses/mit](https://opensource.org/licenses/mit)>). See [LICENSE](<[https://github.com/fairdataihub/poster2json/blob/main/LICENSE](https://github.com/fairdataihub/poster2json/blob/main/LICENSE)>) for more information.

## How to cite

If you are using this package or reusing the source code from this repository for any purpose, please cite:

```text

    Coming soon...

```

## Acknowledgements

Add any other acknowledgements here.
