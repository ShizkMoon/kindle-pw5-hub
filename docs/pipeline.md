# EPUB Processing Pipeline

**EPUB is the only format. Any input -> EPUB -> KOReader.**

All processing targets KOReader on a jailbroken KPW5. Amazon formats (KFX/AZW3/MOBI), cloud services (Whispersync/Send to Kindle), and Kindle native reading are out of scope for this pipeline.

---

## Input Format Matrix

| Input | Tool | Command | Notes |
|---|---|---|---|
| TXT (UTF-8) | `charset-normalizer` + pipeline | `python scripts/txt2epub/pipeline.py novel.txt` | Full 7-step web novel pipeline |
| TXT (GBK/GB18030/Big5) | `charset-normalizer` | Auto-detect -> UTF-8, then pipeline | Most common in Chinese web novels |
| MOBI | `ebook-convert` | `ebook-convert input.mobi output.epub` | Single command, metadata preserved |
| AZW3 | `ebook-convert` | `ebook-convert input.azw3 output.epub` | Single command, metadata preserved |
| PDF (text-based) | `ebook-convert` | `ebook-convert input.pdf output.epub --enable-heuristics` | Quality depends on source layout |
| PDF (scanned) | N/A | Use KOReader native PDF reflow | OCR is manual, not in this pipeline |
| HTML | `ebook-convert` | `ebook-convert input.html output.epub --level1-toc //h1` | --level1-toc extracts heading structure |
| DOCX | `ebook-convert` | `ebook-convert input.docx output.epub` | Calibre handles DOCX natively |
| EPUB (raw) | ebooklib | Programmatic fix + CSS audit | Skip format conversion, go to L3+ |

---

## TXT Web Novel Pipeline

TXT input follows a dedicated 7-step pipeline. Other formats start at L5 (assembly).

```
W1: Encoding      W2: Filtering     W3: Chapter       W4: Script
    Detection  ->     (garbage    ->    Detection   ->    Conversion
    (UTF-8)           removal)         (regex+AI)        (OpenCC)
         |                 |                  |                |
         v                 v                  v                v
W5: Typesetting   W6: Metadata      W7: Assembly + Validate + Adapt -> KOReader
```

### W1: Encoding Detection

```python
import charset_normalizer

with open('novel.txt', 'rb') as f:
    raw = f.read()
result = charset_normalizer.from_bytes(raw).best()
text = str(result)  # Auto-converted to UTF-8 str
```

### W2: Garbage Filtering

Remove patterns common in scraped web novels:

- Lines containing URLs (`https?://\S+`)
- Site boilerplate: "记住本站", "手机阅读", "本章未完.*请点击下一页"
- Repeated chapter titles (consecutive duplicates)
- Consecutive symbol-only lines (>= 3 lines of `~~~~~~~`, `=======`, etc.)
- Purely numeric/whitespace lines under 10 chars

### W3: Chapter Detection

**Regex (primary):**

```
Chinese:  第[0-9零一二三四五六七八九十百千万]+[章回卷节部集篇]
English:  ^Chapter\s+\d+[:\s]+  |  ^Part\s+[IVX]+[:\s]+  |  ^Book\s+\d+[:\s]+
Fallback:  No chapters found -> group by blank lines, every ~50 paragraphs = 1 chapter
```

**AI assist (GLM-4.7, ~0.005 CNY/call):** Triggered when regex confidence is low. Agent analyzes first 500 lines and returns JSON with detected chapter pattern, sample matches, and structure hints (volume/prologue/epilogue flags).

### W4: Script Conversion (OpenCC)

| Config | Direction | Use When |
|---|---|---|
| `s2t.json` | Simplified -> Traditional | Default preferred output |
| `s2tw.json` | Simplified -> Taiwan Traditional | Taiwan-specific vocabulary |
| `t2s.json` | Traditional -> Simplified | Source is traditional |

Auto-detect: analyze CJK character ratio. If >70% traditional, apply `s2t.json`. Otherwise preserve original.

```bash
opencc -c s2t.json -i input.txt -o output.txt
```

```python
import opencc
cc = opencc.OpenCC('s2t.json')
text = cc.convert(text)
```

### W5: Typesetting Repair

| Operation | Rule |
|---|---|
| Hard-break merge | Chinese line ending + Chinese line starting -> merge into one paragraph |
| Blank-line normalization | Consecutive blank lines -> single blank line |
| Indent removal | Leading spaces -> handled by CSS `text-indent: 2em` |
| Quote normalization | Optional: `""` -> `「」` |
| Fullwidth conversion | Optional: English punctuation -> Chinese punctuation |

### W6: Metadata Extraction

| Field | Source | Fallback |
|---|---|---|
| Title | Filename (stripped of site prefix) | First non-blank line of body |
| Author | Search first 100 lines for `作者：XXX` | Agent completion |
| Language | `zh` | Auto-detected |
| Cover | Agent-generated | None |

### W7: Assembly -> Validation -> Adaptation

Standard EPUB assembly (L5), EPUBCheck validation (L6), KOReader adaptation (L7). See sections below.

---

## EPUB Quality Standards

### CSS Rules

| Rule | Correct | Wrong | Reason |
|---|---|---|---|
| Font-size unit | `em` / `%` / `rem` | `px` / `pt` / `cm` | KOReader cannot scale absolute units |
| Horizontal margin unit | `%` | `em` | `em` margins grow with font size, squashing content |
| Vertical margin unit | `em` | `%` / `px` | Vertical spacing should scale with text |
| Body alignment | `text-align: justify` | `left` / `right` / `center` | Consistent reading flow |
| Line-height | >= 1.2 | < 1.2 | Values below 1.2 cause clipping on some renderers |
| Line-height placement | `body` only | Individual elements | Per-element line-height overrides user settings |
| Page break | `page-break-after` preferred | Mixing before/after | Consistency; prefer after on chapter endings |
| Small caps | `font-variant-caps: small-caps` | `font-variant: small-caps` | The latter is fake small caps |
| Body font | Leave default (don't set) | Explicit `font-family` / `font-size` | Let KOReader engine control body text |

### Hard Rules

1. **No `px` or `pt` as font-size units.** KOReader's font-size widget only scales relative units.
2. **Do not lock `body`.** No `font-family`, `font-size`, or forced `line-height` on `body`. KOReader users control these through Style Tweaks.
3. **`em` for vertical, `%` for horizontal.** Prevents layout breakage when users adjust font size.
4. **`line-height` on `body` only.** Per-element line-height defeats KOReader's "Enforce steady line heights" tweak.

### Standard CSS Template

```css
/* Base */
body {
  font-family: serif;
  line-height: 1.5;
  text-align: justify;
  margin: 0;
  padding: 0;
  widows: 1;
  orphans: 1;
  hyphens: auto;
  -webkit-hyphens: auto;
  -epub-hyphens: auto;
  font-variant-numeric: oldstyle-nums proportional-nums;
  font-kerning: normal;
}

/* Paragraphs */
p {
  margin-top: 0;
  margin-bottom: 0;
  text-indent: 2em;
}

h1 + p, h2 + p, h3 + p, .section-break + p {
  text-indent: 0;           /* No indent after headings */
}

p + p {
  margin-top: 0.3em;        /* Micro-spacing between adjacent paragraphs */
}

/* Headings */
h1 { text-align: center; font-size: 2em;   margin: 3em 0 1em 0; }   /* Book title */
h2 { text-align: center; font-size: 1.5em; margin: 2em 0 0.5em 0; } /* Volume */
h3 { text-align: left;   font-size: 1.3em; margin: 1.5em 0 0.5em 0; } /* Chapter */

/* Blockquotes */
blockquote {
  margin: 1em 5%;           /* Vertical em, horizontal % */
  font-size: 0.95em;
}

/* Images & Tables */
img  { max-width: 100%; height: auto; }
table { max-width: 100%; border-collapse: collapse; }

/* Small caps (real, not fake) */
.small-caps {
  font-variant-caps: small-caps;
  letter-spacing: 0.05em;
}
```

---

## KOReader Adaptation

### Style Tweaks to Enable

| Tweak | Effect |
|---|---|
| `Ignore publisher font families` | Use KOReader font instead of embedded fonts |
| `Ignore publisher font sizes` | Use KOReader font size (only if source EPUB has messy sizing) |
| `Enforce steady line heights` | Prevent sub/superscript from jittering line spacing |
| `Smaller sub- and superscript` | Shrink sub/sup to 50% for readability |

### Font Strategy

| Category | Approach | Reason |
|---|---|---|
| Body font (serif/sans-serif) | Do NOT embed | KOReader replaces with user font automatically |
| CJK fonts | Do NOT embed | Too large; manage via `koreader/fonts/` folder |
| Symbol/notation fonts | Embed if needed | Math, IPA, special characters (tiny file size) |
| Decorative title fonts | Embed if needed | Only used on h1/h2 (tiny file size) |

### Unit Enforcement

All CSS properties affecting text size MUST use relative units:

| Property | Unit | Note |
|---|---|---|
| `font-size` | `em` | KOReader scales this |
| `margin` (vertical) | `em` | Scales with text |
| `margin` (horizontal) | `%` | Viewport-relative, won't squash |
| `padding` | `em` or `%` | Context-dependent |
| `text-indent` | `em` | Scales naturally |
| `line-height` | Unitless or `em` | Unitless preferred (1.5 not 1.5em) |

---

## Validation

### EPUBCheck Usage

```bash
java -jar epubcheck.jar book.epub
```

Target output: `No errors or warnings detected.`

### Common Errors and Fixes

| Error | EPUBCheck Message | Fix |
|---|---|---|
| Missing OPF entry | `item not in OPF manifest` | `book.add_item()` in ebooklib |
| Broken reference | `referenced resource missing` | Fix `href` or add missing file |
| Invalid date | `date not valid per OPF spec` | Use `YYYY-MM-DD` format |
| CSS parse error | `CSS parsing error` | Agent audit -> regenerate CSS |
| Missing alt text | `alt text missing for image` | Add `alt` attribute to `<img>` |
| Unregistered font | `font not in OPF manifest` | Declare `@font-face` in OPF or remove |

```python
# Programmatic fix entry point
from ebooklib import epub
book = epub.read_epub('input.epub')
# Inspect and fix items, metadata, CSS
epub.write_epub('output.epub', book)
```

---

## Tool Reference

| Tool | Install | Primary CLI Usage | Role |
|---|---|---|---|
| **ebook-convert** (Calibre) | `scoop install calibre` | `ebook-convert input.fmt output.epub` | Format conversion, EPUB normalization |
| **EPUBCheck** | Download JAR from [github.com/w3c/epubcheck](https://github.com/w3c/epubcheck) | `java -jar epubcheck.jar book.epub` | W3C EPUB validation |
| **ebooklib** | `pip install ebooklib` | `epub.read_epub()` / `epub.write_epub()` (Python) | Programmatic EPUB read/write/repair |
| **Sigil** | [sigil-ebook.com](https://sigil-ebook.com) | GUI editor + Automate List plugins | Manual deep repair (GUI-only tool) |
| **OpenCC** | `pip install opencc` | `opencc -c s2t.json -i in.txt -o out.txt` | Chinese script conversion |
| **charset-normalizer** | `pip install charset-normalizer` | `charset_normalizer.from_bytes(raw).best()` (Python) | Encoding detection |

### Common ebook-convert Flags

```
--enable-heuristics           PDF: try to detect structure
--level1-toc //h1             Map H1 to top-level ToC
--level2-toc //h2             Map H2 to second-level ToC
--base-font-size 12           12pt base for relative sizing
--output-profile generic_eink_hd   E Ink optimized
--remove-paragraph-spacing    Strip paragraph margins
--change-justification justify  Force justified text
```

---

## Cloud vs Windows

| Task | Cloud (2C2G) | Windows Laptop |
|---|---|---|
| TXT/MOBI/AZW3/HTML -> EPUB conversion | Yes | Yes |
| EPUB normalization (`ebook-convert`) | Yes | Yes |
| EPUBCheck validation | Yes | Yes |
| ebooklib programmatic fix | Yes | Yes |
| Chapter detection regex | Yes | Yes |
| AI chapter detection (GLM-4.7) | Yes | Yes |
| AI metadata enrichment | Yes | Yes |
| AI CSS audit | Yes | Yes |
| WebDAV upload to KOReader | Yes | Yes |
| Sigil GUI repair | No | Yes |
| Calibre GUI library management | No | Yes |
| KOSyncthing+ peer daemon | No | Yes |
| KOReader highlight ingestion cron | Yes (daily 22:00) | No |

---

## References

- [EPUB 3.4 W3C Specification](https://www.w3.org/TR/epub-34/)
- [Amazon KDP Publishing Guidelines](https://kdp.amazon.com/en_US/help/topic/GH4DRT75GWWAGBTU)
- [Friends of EPUB / BlitzTricks](https://friendsofepub.github.io/eBookTricks/)
- [KOReader User Guide](https://koreader.rocks/user_guide/)
- [Calibre ebook-convert Documentation](https://manual.calibre-ebook.com/generated/en/ebook-convert.html)
- [EPUBCheck (W3C)](https://github.com/w3c/epubcheck)
- [ebooklib](https://github.com/aerkalov/ebooklib)
- [OpenCC](https://github.com/BYVoid/OpenCC)
