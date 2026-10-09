# Test fixtures

Synthetic only. No real personal names, credentials, or production documents.

| File | Purpose |
|---|---|
| `sample.pdf` | Minimal PDF with the words "Sample Report" |
| `sample.docx` | Short Word doc generated with python-docx |
| `sample.xlsx` | Two-row spreadsheet (`widget` / `gadget`) |
| `sample.pptx` | One slide titled "Sample Report" |
| `sample.html` | Small HTML page with a heading and list |
| `sample.csv` | Two-column CSV |
| `sample.txt` | Short Markdown-ish text |

Unsupported/corrupt denial cases build temporary bytes inside the test
process (not checked into the tree), so the install security scan stays clear
of binary fixtures.

Regenerate Office fixtures from a clean venv if needed:

```bash
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install 'markitdown[pdf,docx,pptx,xlsx,xls]>=0.1.0,<0.2' python-docx
python -c "from docx import Document; ..."
```
