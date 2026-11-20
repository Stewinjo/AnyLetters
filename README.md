# AnyLetters – a variable-length word game

## Features

- **Variable word lengths**: Play with words of any length
- **Multiple languages**: Support for any language with .dic/.aff dictionary files (German, English, etc.)
- **Variable difficulty**: easy reveals a letter; medium uses the same lemmas; hard keeps irregular inflections; chaos also allows generated forms such as plurals
- **Dictionary validation**: Uses Hunspell-compatible .dic/.aff files for word validation
- **Custom solutions**: Use your own solution word lists or fall back to dictionary words
- **Standalone builds**: Package a single executable with baked language, length, difficulty, and solution lists

## Installation

1. **Clone or download this repository**

2. **Initialize the dictionaries submodule** (required for dictionary validation):
   ```bash
   git submodule update --init --recursive
   ```
   > If you downloaded a ZIP archive, manually clone [wooorm/dictionaries](https://github.com/wooorm/dictionaries) into `external/dictionaries`.

3. **Install Python 3.8+**

4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Optional developer tools** (formatters, lint, pre-commit):
   ```bash
   pip install -r requirements-dev.txt
   pre-commit install
   ```

## Usage

### Basic Usage

```bash
# Play with defaults from defaults.json (stock: English US, 6 letters, medium)
python main.py

# Play in English GB with 6 letters
python main.py --lang en-gb

# Play German words with 8 letters
python main.py --lang de --length 8
```

### Command Line Arguments

- `-h, --help`: Show detailed help message with examples
- `--lang CODE`: Language code for dictionaries and solutions
  - Examples: `de` for German, `de-at` for Austrian German, `en-gb` for British English
- `--length N`: Word length to play with
- `--list`: Print all available language codes (including regional variants) from the dictionaries submodule
- `-d, --difficulty DIFFICULTY`: Select easy, medium, hard, or chaos
  - **easy**: reveal one letter; secrets are dictionary lemmas without obvious inflections
  - **medium**: the same lemma list, with no revealed letter
  - **hard**: lemmas, including irregular inflected entries the dictionary lists on their own
  - **chaos**: lemmas plus generated inflections such as regular plurals
  - Names, countries, and profanity stay out of every difficulty. `--disable-solution-filters` turns those lists off.
- `--disable-solution-filters`: Skip language-based filtering when generating dictionary fallback solutions
- `--hide-secret` / `--show-secret`: When secrets are hidden (default), logs only the length. `--show-secret` (or bake `hide_secret: false`) prints the chosen word in the console on generation
- `--clear-cache`: Delete cached validator words and filtered solutions. Provide a language code to only remove that language's cache.

## Adding Your Own Solutions

1. Create a text file in the `solutions/` folder with the naming pattern:
   ```
   solutions/<language-code><length>.txt
   ```
   Examples:
   - `solutions/de6.txt` - German 6-letter words
   - `solutions/en-gb6.txt` - British English 6-letter words
   - `solutions/en8.txt` - General English 8-letter words
   - `solutions/fr5.txt` - French 5-letter words

2. Add one word per line:
   ```
   aardvark
   aardwolf
   abalone
   abandon
   ...
   ```

3. The game will automatically use your solutions file when you run:
   ```bash
   python main.py --lang <lang> --length <length>
   ```

> Note: `solutions/` is gitignored by default. Keep your private word lists locally, then bake them into an executable as shown below.

## Building an Executable

You need Python and the project dependencies **only on the machine that builds**. The output under `dist/` is a standalone binary (no Python install required to play).

### What gets packaged

`AnyLetters.spec` bundles:

- `defaults.json` – baked language / length / difficulty / filter defaults
- `solutions/` – any `solutions/<lang><length>.txt` files present at build time
- `external/dictionaries/dictionaries/` – Hunspell dictionaries
- `filters/` – country / name / company blacklists
- `assets/` – fonts, when that folder exists

### Plain build (stock defaults)

```bash
# Windows
build_exe.bat

# Unix / macOS / Linux
chmod +x build_exe.sh
./build_exe.sh
```

Output:

- Windows: `dist/AnyLetters.exe`
- Unix: `dist/AnyLetters`

### Baking arguments and solutions into the build

Edit `defaults.json`, or pass bake flags to the build scripts. Flags are forwarded to `bake_defaults.py`, which updates `defaults.json` before PyInstaller runs.

```bash
# Windows – German, 6 letters, easy, require solutions/de6.txt, custom exe name
build_exe.bat --lang de --length 6 --difficulty easy --require-solutions --exe-name AnyLettersDE

# Unix / macOS / Linux
./build_exe.sh --lang de --length 6 --difficulty easy --require-solutions --exe-name AnyLettersDE
```

Useful bake flags:

| Flag | Effect |
| --- | --- |
| `--lang CODE` | Default language when the exe is started with no CLI args |
| `--length N` | Default word length |
| `--difficulty easy\|medium\|hard\|chaos` | Default difficulty |
| `--exe-name NAME` | Output binary name (`dist/NAME` / `dist/NAME.exe`) |
| `--disable-solution-filters` | Bake filters off |
| `--enable-solution-filters` | Bake filters on |
| `--hide-secret` | Bake `hide_secret=true` (do not log the secret) |
| `--show-secret` | Bake `hide_secret=false` (log the secret on generation) |
| `--require-solutions` | Fail the build unless `solutions/<lang><length>.txt` exists |
| `--print` | Print current defaults without writing (run via `python bake_defaults.py --print`) |

Workflow for a private German party build:

1. Put your words in `solutions/de6.txt` (one word per line).
2. Run:
   ```bash
   build_exe.bat --lang de --length 6 --difficulty easy --require-solutions --exe-name AnyLettersDE
   ```
3. Ship `dist/AnyLettersDE.exe`. Double-clicking it starts German / length 6 / easy with your list. Players can still override with CLI flags if needed:
   ```bash
   AnyLettersDE.exe --difficulty hard
   ```

You can also edit `defaults.json` by hand, then run `build_exe.bat` / `./build_exe.sh` with no bake flags.

### Smoke tests after a build

The build scripts run a short smoke test (`--list`, and a `--help` defaults check). CI also builds on Linux and Windows and verifies a baked German binary.

## Development

### Tests

```bash
python -m unittest discover -s tests -v
```

### Pre-commit

Installed hooks (see `.pre-commit-config.yaml`):

- trailing whitespace and end-of-file fixes
- JSON / YAML / merge-conflict checks
- mixed line endings (LF; `.bat` excluded)
- **Black** formatter
- **pylint** (errors only on `main.py`, `filter.py`, `style.py`, `bake_defaults.py`)

```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files
```

### Continuous integration

`.github/workflows/test.yml` runs:

- pylint (errors only)
- unit tests on Linux and Windows
- cache smoke tests
- pre-commit on all files
- plain Linux / Windows executable builds
- a **baked** Linux / Windows build (`--lang de --length 6 --require-solutions`) that asserts the packaged binary’s `--help` defaults

## How Dictionary Validation Works

The game uses Hunspell-compatible dictionary files (.dic and .aff):

- **.dic files**: Contain base word forms
- **.aff files**: Contain affix rules (prefixes and suffixes)

For example, with the word "running":

- Base form: "run" (in .dic)
- Suffix rule: "+ing" (in .aff)
- Game expands "run" + "ing" → "running"

This allows the game to validate thousands of word forms from a compact dictionary.

## Troubleshooting

**"No matching .aff/.dic pairs found"**:

- Ensure the dictionaries submodule is initialized (`git submodule update --init --recursive`)
- Check that dictionary files exist in `external/dictionaries/dictionaries/<lang>/` with both `index.aff` and `index.dic`

**"No solutions file found"**:

- This is fine for normal play; the game uses dictionary words instead
- For a baked build with `--require-solutions`, create `solutions/<lang><length>.txt` first

**"No dictionary words available"**:

- Check that dictionary files exist and are valid
- Try a different word length (some lengths may have no dictionary words)
- Check the console logs for detailed error messages

**Game won't start**:

- Ensure Python 3.8+ is installed
- Check that tkinter is available (usually included with Python)
- On Linux, you may need: `sudo apt-get install python3-tk`

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International Public License** (CC BY-NC-ND 4.0).

This means:

- ✅ You can **share** and use the project
- ✅ You must provide **attribution** to the original author
- ❌ You **cannot** use it for **commercial purposes**
- ❌ You **cannot** distribute **modified versions** or derivatives

See [LICENSE.txt](LICENSE.txt) for the full license text.

## Contributing

Feel free to submit issues, suggestions, or pull requests. Please install pre-commit and run the unit tests before opening a PR.
