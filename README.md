# rmdedit

Small command line helper for rendering RMarkdown (`.Rmd`) files to PDF with
R, Pandoc and LuaLaTeX.

`rmdedit` intentionally stays small: no Quarto dependency, no project database,
no background service. It is a thin wrapper around `rmarkdown::render()` with
template discovery, incremental rebuilds and optional RPM requirement checks.

## Features

- Render one `.Rmd` file, multiple files, or all `.Rmd` files in a directory.
- Use local or external LaTeX template roots.
- Rebuild only when source files, templates or assets changed.
- Pass template-specific asset/font/logo paths to Pandoc.
- Optionally check RPM package requirements declared in YAML frontmatter.
- Keep private templates and assets outside the public base repository.

## Requirements

`rmdedit` does not install system dependencies. You need:

- Python 3 for the CLI
- `Rscript`
- `rmarkdown::render()`
- Pandoc
- LuaLaTeX

On Fedora/RHEL-like systems this is typically:

```bash
sudo dnf install python3 R pandoc
Rscript -e 'install.packages(c("rmarkdown", "knitr", "tinytex"), repos = "https://cloud.r-project.org")'
Rscript -e 'tinytex::install_tinytex()'
```

On Debian/Ubuntu-like systems this is typically:

```bash
sudo apt install python3 r-base pandoc
Rscript -e 'install.packages(c("rmarkdown", "knitr", "tinytex"), repos = "https://cloud.r-project.org")'
Rscript -e 'tinytex::install_tinytex()'
```

Depending on your templates, additional LaTeX packages may be required, for
example `fontspec`, `unicode-math`, `babel`, `microtype`, `tikz`, `fancyhdr`,
`lastpage`, `tabularx`, `longtable`, `booktabs`, `hyperref` or `ragged2e`.

## Quickstart

```bash
pipx install git+https://github.com/mawirth/rmdedit.git
rmdedit --help
git clone https://github.com/mawirth/rmdedit.git
cd rmdedit
rmdedit examples/beispiel-notiz-neutral.Rmd --force
```

The rendered PDF is written next to the input file by default.
Update an existing `pipx` installation with:

```bash
pipx upgrade rmdedit
```

You can also render all `.Rmd` files in the current directory:

```bash
rmdedit
```

From a source checkout, the compatibility wrapper still works:

```bash
python3 rmdedit.py examples/beispiel-notiz-neutral.Rmd --force
```

## Repository Boundary

This repository is meant to stay publishable. It should contain only generic
rendering logic, generic example templates and freely shareable placeholder
content.

Do not put these things into this repository:

- protected logos or brand assets,
- licensed fonts that cannot be redistributed freely,
- organization-specific, private or customer-specific LaTeX templates,
- internal text blocks, case files or operational data.

Such content can be connected as external template roots, for example via
`rmdedit.template: organisation/report`, while staying in separate private
repositories or installed packages.

## Usage

```bash
rmdedit examples/beispiel-notiz-neutral.Rmd --force
```

Rebuild only if the `.Rmd`, selected template or assets are newer than the PDF:

```bash
rmdedit examples/beispiel-notiz-neutral.Rmd
```

Remove temporary LaTeX files but keep the generated PDF:

```bash
rmdedit examples/beispiel-notiz-neutral.Rmd --clean
```

Write to an explicit PDF output path:

```bash
rmdedit examples/beispiel-notiz-neutral.Rmd --output /tmp/beispiel.pdf
```

`--output` is only valid with exactly one `.Rmd` input file.

## YAML Template Selection

The preferred way is `rmdedit.template` in YAML frontmatter:

```yaml
---
title: "Technical Note"
rmdedit:
  template: notiz-neutral
---
```

Namespaced templates are supported:

```yaml
---
title: "Report"
rmdedit:
  template: organisation/report
---
```

The legacy form is still supported:

```yaml
---
rmdedit_template: notiz-neutral
---
```

If no template is specified, `rmdedit` uses `notiz-neutral`.

## Config Files

There are three optional config levels:

1. User-local: `~/.config/rmdedit/config.json`
2. Project-local: `./rmdedit.json`
3. System-wide: `/etc/rmdedit/config.json` and `/etc/rmdedit/config.d/*.json`

The project-local file takes precedence because its template roots are searched
first. Relative paths are resolved relative to the config file they appear in.

Without a config file, `rmdedit` uses the templates and assets installed with
the Python package:

```json
{
  "template_roots": [
    {
      "name": "base",
      "path": "<package>/templates",
      "assets": "<package>/assets"
    }
  ]
}
```

A sample config file is available as `rmdedit.json.example`.

## RPM Requirements in YAML

Rmd files can declare required RPM packages in YAML frontmatter. This is useful
for internal template or helper packages once they are installed as RPMs.

```yaml
---
title: "Report"
rmdedit:
  template: organisation/report
  requires:
    - rmdedit >= 0.1.0
    - organisation-templates >= 0.1.0
---
```

Structured entries are also supported:

```yaml
rmdedit:
  requires:
    - name: rmdedit
      version: ">= 0.1.0"
```

Each entry needs a package name, comparison operator and version. `rmdedit`
checks installed RPM package versions with `rpm` and `rpmdev-vercmp` before
rendering the document. For local development without installed RPMs, skip this
check with `--skip-requirements`.

## External Template Roots

Project-specific, organization-specific or customer-specific templates should
live outside this base repository. A typical structure:

```text
workspace/
├── rmdedit/
└── custom-templates/
    ├── templates/
    └── assets/
```

Example local config:

```json
{
  "template_roots": [
    {
      "name": "custom",
      "path": "../custom-templates/templates",
      "assets": "../custom-templates/assets"
    }
  ]
}
```

Then a document can use `rmdedit.template: custom/report`, for example. The
namespace before the slash limits lookup to the template root with the matching
`name`.

External roots may contain protected or licensed content. That content belongs
in the external environment, not in this base repository.

## Fonts, Assets and Text Blocks

Each template root can have an asset directory:

```text
assets/
├── fonts/
└── logos/
```

During rendering, these Pandoc variables are set:

- `rmdedit-assets`
- `rmdedit-fonts`
- `rmdedit-logos`

If a template root contains a `textbausteine/` directory, `rmdedit` also sets
`RMDEDIT_TEXTBLOCKS`. If `assets/textbausteine/` exists,
`RMDEDIT_TEXTBLOCK_ASSETS` is set as well. External packages or filters can use
these environment variables to find text blocks and related assets.

Fonts are not installed by `rmdedit`. Templates reference font files by path,
for example from an external `assets/fonts/` directory.

## Incremental Builds

`rmdedit` rebuilds a PDF if:

- the PDF does not exist yet,
- the `.Rmd` file is newer than the PDF,
- local asset directories next to the `.Rmd` are newer than the PDF:
  `assets/`, `bilder/`, `anlagen/`,
- a file in the selected template root is newer than the PDF,
- a file in the selected asset root is newer than the PDF,
- `--force` is set.

With `--output`, freshness is checked against the specified PDF path.

Only the selected template and asset root are considered.

## Troubleshooting

If `Rscript` is missing, you will see:

```text
Rscript nicht gefunden. Bitte R installieren oder Rscript in PATH aufnehmen.
```

If `rmarkdown`, Pandoc or LaTeX components are missing, `rmdedit` prints the
last error lines from the R, Pandoc or LaTeX process. Useful diagnostics:

```bash
Rscript --version
Rscript -e 'packageVersion("rmarkdown")'
pandoc --version
lualatex --version
```

If LaTeX packages are missing, TinyTeX can often install them directly:

```r
tinytex::tlmgr_install("package-name")
```

`rmdedit` disables TinyTeX's automatic package installation while rendering.
Missing LaTeX packages therefore fail fast instead of waiting on CTAN mirror
lookups during every build.

## License and Repository Separation

This base repository is intended to stay publishable. It should contain:

- generic templates,
- freely shareable example content,
- freely shareable assets with clear licensing.

Do not put these things here:

- protected logos,
- organization-specific templates,
- confidential documents,
- licensed fonts,
- confidential assets.

Such content should be connected through local config files and external
template roots.
