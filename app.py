import io
import re
from datetime import datetime
import pandas as pd
import streamlit as st

# ── Page config
st.set_page_config(page_title="Translation QA for Traditional Chinese", page_icon="🈶", layout="wide")

# ── Sidebar
st.sidebar.title("⚙️ Upload Files")
source_file = st.sidebar.file_uploader("Upload Source File (English)", type=["txt", "docx", "pdf"], key="src")
target_file = st.sidebar.file_uploader("Upload Target File (Traditional Chinese)", type=["txt", "docx", "pdf"], key="tgt")

glossary_file = st.sidebar.file_uploader(
    "Upload Terminology List (CSV/XLSX, optional)",
    type=["csv", "xlsx", "xls"],
    key="gloss",
)
run = st.sidebar.button("Run QA", type="primary")

st.title("🈶 Translation QA – Traditional Chinese")
st.caption("Checks: Typographical errors • Terminology consistency • Extra spaces • Duplicated footnote numbers")

# ── Helper functions

def extract_text(uploaded_file):
    if uploaded_file is None:
        return ""
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    try:
        if name.endswith(".txt"):
            # try a few encodings
            for enc in ("utf-8", "utf-16", "big5", "cp950", "latin-1"):
                try:
                    return data.decode(enc)
                except Exception:
                    continue
            return data.decode("utf-8", errors="replace")
        elif name.endswith(".docx"):
            from docx import Document
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs)
        elif name.endswith(".pdf"):
            from pypdf import PdfReader
            pdf = PdfReader(io.BytesIO(data))
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
        else:
            return ""
    except Exception as e:
        st.error(f"Error reading file: {e}")
        return ""


def _auto_map_columns(df: pd.DataFrame):
    """Heuristically map columns to en / zh_pref / zh_variants."""
    lc = {c.lower(): c for c in df.columns}
    # common header alternatives
    en_keys = ["en", "english", "source term", "source", "term_en"]
    zh_pref_keys = ["zh_pref", "preferred", "tc", "tw", "traditional chinese", "chinese", "term_zh", "zh-tw", "zh_trad"]
    zh_var_keys = ["zh_variants", "variants", "alt", "alternatives", "synonyms"]

    def pick(keys):
        for k in keys:
            if k in lc:
                return lc[k]
        return None

    return pick(en_keys), pick(zh_pref_keys), pick(zh_var_keys)


def load_glossary(file):
    if file is None:
        return pd.DataFrame(columns=["en", "zh_pref", "zh_variants"])
    try:
        if file.name.lower().endswith(".csv"):
            df = pd.read_csv(file)
        else:
            # Excel
            try:
                df = pd.read_excel(file, engine="openpyxl")
            except Exception:
                # fall back to default engine
                df = pd.read_excel(file)
        # try auto-map
        c_en, c_pref, c_var = _auto_map_columns(df)
        if not c_en and "en" in df.columns: c_en = "en"
        if not c_pref and "zh_pref" in df.columns: c_pref = "zh_pref"
        if not c_var and "zh_variants" in df.columns: c_var = "zh_variants"

        # If any missing, show a quick UI to map
        if not all([c_pref]):
            st.info("Map glossary columns below (only preferred zh term is required).")
            c_en = st.selectbox("Column for English term (optional)", [None] + list(df.columns), index=(list(df.columns).index(c_en) + 1) if c_en in df.columns else 0, key="map_en")
            c_pref = st.selectbox("Column for Preferred zh‑TW term (required)", list(df.columns), index=list(df.columns).index(c_pref) if c_pref in df.columns else 0, key="map_pref")
            c_var = st.selectbox("Column for Variant zh terms (optional)", [None] + list(df.columns), index=(list(df.columns).index(c_var) + 1) if c_var in df.columns else 0, key="map_var")
        # build normalized frame
        out = pd.DataFrame()
        out["en"] = df[c_en] if c_en else ""
        out["zh_pref"] = df[c_pref]
        if c_var:
            out["zh_variants"] = df[c_var].fillna("")
        else:
            out["zh_variants"] = ""
        return out.fillna("")
    except Exception as e:
        st.error(f"Error loading glossary: {e}")
        return pd.DataFrame(columns=["en", "zh_pref", "zh_variants"])


def check_extra_spaces(text):
    # CJK U+4E00–U+9FFF with ASCII/half-width spaces
    pattern = re.compile(r"([\u4e00-\u9fff])[ \t]+([\u4e00-\u9fff])")
    findings = [(m.start(), m.group()) for m in pattern.finditer(text)]
    # Full‑width space U+3000 between CJK
    fw = re.compile(r"([\u4e00-\u9fff])\u3000+([\u4e00-\u9fff])")
    findings += [(m.start(), m.group()) for m in fw.finditer(text)]
    return findings


def check_typos(text):
    issues = []
    # ASCII punctuation inside CJK context
    ascii_punct = r",\.;:!\?\)\(\[\]\{\}\"'"
    pattern = re.compile(fr"([\u4e00-\u9fff])([{ascii_punct}])([\u4e00-\u9fff])")
    for m in pattern.finditer(text):
        issues.append((m.start(), m.group(2)))
    # mismatched brackets (simple heuristic)
    pairs = {"（": "）", "《": "》", "「": "」", "『": "』", "【": "】", "(": ")", "[": "]", "{": "}"}
    opens, closes = set(pairs.keys()), set(pairs.values())
    stack = []
    for i, ch in enumerate(text):
        if ch in opens:
            stack.append(ch)
        elif ch in closes:
            if not stack or pairs.get(stack[-1], None) != ch:
                issues.append((i, f"unexpected '{ch}'"))
            else:
                stack.pop()
    for ch in stack:
        issues.append((len(text), f"unclosed '{ch}'"))
    return issues


def check_duplicate_footnotes(text):
    pattern = re.compile(r"\((\d{1,3})\)|（(\d{1,3})）|\[(\d{1,3})\]")
    found = {}
    duplicates = []
    for m in pattern.finditer(text):
        num = m.group(1) or m.group(2) or m.group(3)
        if num in found:
            duplicates.append((num, m.start()))
        else:
            found[num] = m.start()
    # superscript ¹²³
    supmap = {"⁰":0,"¹":1,"²":2,"³":3,"⁴":4,"⁵":5,"⁶":6,"⁷":7,"⁸":8,"⁹":9}
    i = 0
    while i < len(text):
        if text[i] in supmap:
            j=i; val=0
            while j < len(text) and text[j] in supmap:
                val = val*10 + supmap[text[j]]
                j+=1
            key = str(val)
            if key in found:
                duplicates.append((key, i))
            else:
                found[key] = i
            i=j
        else:
            i+=1
    return duplicates


def check_terminology_inconsistency(target, glossary_df):
    inconsistencies = []
    if glossary_df.empty:
        return inconsistencies
    for _, row in glossary_df.iterrows():
        pref = str(row.get("zh_pref", "")).strip()
        variants_str = str(row.get("zh_variants", "")).strip()
        variants = [v.strip() for v in variants_str.split("|") if v.strip()]
        if not pref and not variants:
            continue
        used = {}
        for term in [pref] + variants:
            if term:
                used[term] = target.count(term)
        used_terms = {k: v for k, v in used.items() if v > 0}
        if len(used_terms) > 1:
            inconsistencies.append({
                "preferred": pref,
                "found": ", ".join(f"{k} ({v})" for k, v in used_terms.items())
            })
    return inconsistencies

# ── Main Execution
if run:
    if not source_file or not target_file:
        st.warning("Please upload both Source and Target files.")
        st.stop()

    source_text = extract_text(source_file)
    target_text = extract_text(target_file)
    glossary_df = load_glossary(glossary_file)

    st.subheader("📘 Source Text (English)")
    st.text_area("Source Preview", source_text[:2000], height=150)

    st.subheader("📗 Target Text (Traditional Chinese)")
    st.text_area("Target Preview", target_text[:2000], height=150)

    st.markdown("---")

    st.subheader("🔎 QA Checks")
    spaces = check_extra_spaces(target_text)
    typos = check_typos(target_text)
    duplicates = check_duplicate_footnotes(target_text)
    inconsistencies = check_terminology_inconsistency(target_text, glossary_df)

    results = {
        "Extra Spaces": len(spaces),
        "Typographical Errors": len(typos),
        "Duplicated Footnotes": len(duplicates),
        "Terminology Inconsistencies": len(inconsistencies),
    }
    st.write(pd.DataFrame.from_dict(results, orient="index", columns=["Count"]))

    st.markdown("---")

    st.subheader("📝 Detailed Results")
    st.write("**Extra Spaces Found:**", spaces[:20])
    st.write("**Typographical Issues:**", typos[:20])
    st.write("**Duplicate Footnotes:**", duplicates[:20])
    if glossary_df.empty:
        st.info("No glossary uploaded, skipping terminology check.")
    else:
        st.write("**Terminology Inconsistencies:**", inconsistencies[:20])

else:
    st.info("⬅️ Upload your English source, Traditional Chinese target, and optional glossary (CSV/XLSX). Then click Run QA.")
