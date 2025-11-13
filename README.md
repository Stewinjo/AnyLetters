# AnyLetters – a variable-length word game

## Features

- **Variable word lengths**: Play with words of any length
- **Multiple languages**: Support for any language with .dic/.aff dictionary files (German, English, etc.)
- **Variable difficulty**: Set the game to easy, starting with a letter revealed, or play in chaos where all word variants e.g. plurals are allowed too
- **Dictionary validation**: Uses Hunspell-compatible .dic/.aff files for word validation
- **Custom solutions**: Use your own solution word lists or fall back to dictionary words

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

## Usage

### Basic Usage

```bash
# Play with default settings (English US, 6 letters)
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
- `-d, --difficulty DIFFICULTY`: Select any of the difficulties easy, medium, hard or chaos
- `--disable-solution-filters`: Skip language-based filtering when generating dictionary fallback solutions
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

## Building an Executable

### Windows
```bash
build_exe.bat
```
Output: `dist/AnyLetters.exe`

### Unix/Mac/Linux
```bash
chmod +x build_exe.sh
./build_exe.sh
```
Output: `dist/AnyLetters`

The executable includes all necessary files (dictionaries, solutions) and can be distributed as a standalone application.

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
- This is fine! The game will use dictionary words instead
- To create a solutions file, see "Adding Your Own Solutions" above

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

Feel free to submit issues, suggestions, or pull requests!
