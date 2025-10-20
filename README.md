# Traditional Chinese Translation QA (GitHub + Streamlit Cloud)


A Streamlit app to **QA Traditional Chinese translations** (e.g., Taiwan Ministry of Justice documents) translated from English.


### Checks included
1. **Typographical errors** (ASCII punctuation inside CJK, mismatched brackets/quotes, repeated punctuation, zero-width/invalid chars, mixed-width digits)
2. **Inconsistent terminology** (via optional glossary CSV — preferred vs. variant translations)
3. **Extra spaces between characters** (CJK<space>CJK, spaces around brackets/punctuation, full-width spaces)
4. **Duplicated footnote numbers** (e.g., `[12]`, `(12)`, `（12）`, superscripts `¹²³` → same number used multiple times)


### Inputs supported
- **.docx**, **.txt** (recommended)
- **.pdf** (best-effort text extraction via PyPDF; scanned PDFs won’t work)
- **Glossary CSV (optional)** with columns:
- `en` (English term — optional)
- `zh_pref` (preferred Traditional Chinese)
- `zh_variants` (pipe-separated alternative zh terms, e.g., `委託|受託|委任`)


### Quick start
1. Push these files to a GitHub repo.
2. Deploy on Streamlit Cloud → choose `app.py`.
3. Upload your document (and optional glossary CSV) → run checks → download the findings as CSV/XLSX.


### Local dev
```bash
python -m venv .venv && source .venv/bin/activate # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```


---


## Notes
- This tool is heuristic and **does not replace human review**; it surfaces likely issues with locations and context.
- For PDFs, consider converting to DOCX/TXT for best results.
