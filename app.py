import io
import re
import json
import zipfile
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
st.caption("Checks: Typographical errors • Terminology consistency • Extra spaces • Duplicated footnote numbers • Downloadable reports (CSV/XLSX/ZIP)")

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

        # If any missing, show a quick UI to map (preferred is required)
        if not c_pref:
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


def context_snippet(text: str, start: int, length: int, pad: int = 32) -> str:
    s = max(0, start - pad)
    e = min(len(text), start + length + pad)
    return text[s:e].replace("\n", " ")


def check_extra_spaces(text):
    # CJK U+4E00–U+9FFF with ASCII/half-width spaces
    pattern = re.compile(r"([\u4e00-\u9fff])[ \t]+([\u4e00-\u9fff])")
    findings = [(m.start(0), len(m.group(0)), m.group(0)) for m in pattern.finditer(text)]
    # Full‑width space U+3000 between CJK
    fw = re.compile(r"([\u4e00-\u9fff])\u3000+([\u4e00-\u9fff])")
    findings += [(m.start(0), len(m.group(0)), m.group(0)) for m in fw.finditer(text)]
    return findings


def check_typos(text):
    issues = []
    # ASCII punctuation inside CJK context
    ascii_punct = r",\.;:!\?\)\(\[\]\{\}\"'"
    pattern = re.compile(fr"([\u4e00-\u9fff])([{ascii_punct}])([\u4e00-\u9fff])")
    for m in pattern.finditer(text):
        issues.append((m.start(2), 1, m.group(2), "ASCII punctuation between CJK characters"))
    # repeated CJK punctuation (e.g., 。。 or ！！)
    rep = re.compile(r"([，。；：？！、])\1+")
    for m in rep.finditer(text):
        issues.append((m.start(0), len(m.group(0)), m.group(0), "Repeated punctuation"))
    # mismatched brackets (simple heuristic)
    pairs = {"（": "）", "《": "》", "「": "」", "『": "』", "【": "】", "(": ")", "[": "]", "{": "}"}
    opens, closes = set(pairs.keys()), set(pairs.values())
    stack = []
    for i, ch in enumerate(text):
        if ch in opens:
            stack.append((ch, i))
        elif ch in closes:
            if not stack or pairs.get(stack[-1][0]) != ch:
                issues.append((i, 1, ch, "Unexpected closing bracket/quote"))
            else:
                stack.pop()
    for ch, pos in stack:
        issues.append((pos, 1, ch, "Unclosed opening bracket/quote"))
    # zero-width / BOM
    for zw in ["\u200b", "\u200c", "\u200d", "\ufeff"]:
        for m in re.finditer(zw, text):
            issues.append((m.start(0), 1, zw, "Zero-width/BOM character"))
    return issues


def check_duplicate_footnotes(text):
    pattern = re.compile(r"\((\d{1,3})\)|（(\d{1,3})）|\[(\d{1,3})\]")
    found = {}
    duplicates = []
    for m in pattern.finditer(text):
        num = m.group(1) or m.group(2) or m.group(3)
        if num in found:
            duplicates.append((m.start(0), len(m.group(0)), num))
        else:
            found[num] = m.start(0)
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
                duplicates.append((i, j-i, key))
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


def context_df(label, text, items):
    # items are tuples (start, length, token/frag/num, optional note)
    rows = []
    for tup in items:
        if len(tup) == 3:
            pos, length, token = tup
            note = ""
        else:
            pos, length, token, note = tup
        rows.append({
            "issue": label,
            "detail": note or token,
            "start": pos,
            "end": pos + length,
            "context": context_snippet(text, pos, length),
        })
    return pd.DataFrame(rows)


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

    st.subheader("📝 Detailed Results & Downloads")

    df_spaces = context_df("Extra space", target_text, spaces)
    df_typos = context_df("Typographical", target_text, typos)
    df_foot = context_df("Duplicated footnote", target_text, duplicates)
    df_terms = pd.DataFrame(inconsistencies)

    with st.expander("Extra spaces (details)", expanded=bool(len(df_spaces))):
        st.dataframe(df_spaces, use_container_width=True)
        csv_spaces = df_spaces.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", data=csv_spaces, file_name="extra_spaces.csv")

    with st.expander("Typographical issues (details)", expanded=False):
        st.dataframe(df_typos, use_container_width=True)
        csv_typos = df_typos.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", data=csv_typos, file_name="typographical_issues.csv")

    with st.expander("Duplicated footnotes (details)", expanded=False):
        st.dataframe(df_foot, use_container_width=True)
        csv_foot = df_foot.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download CSV", data=csv_foot, file_name="duplicated_footnotes.csv")

    with st.expander("Terminology inconsistencies (details)", expanded=False):
        if glossary_df.empty:
            st.info("No glossary uploaded, skipping terminology check.")
            csv_terms = b""
        else:
            st.dataframe(df_terms, use_container_width=True)
            csv_terms = df_terms.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ Download CSV", data=csv_terms, file_name="terminology_inconsistencies.csv")

    # Combined XLSX
    with io.BytesIO() as bio:
        with pd.ExcelWriter(bio, engine="openpyxl") as xw:
            df_spaces.to_excel(xw, index=False, sheet_name="ExtraSpaces")
            df_typos.to_excel(xw, index=False, sheet_name="TypoIssues")
            df_foot.to_excel(xw, index=False, sheet_name="Footnotes")
            df_terms.to_excel(xw, index=False, sheet_name="Terminology")
        xlsx_bytes = bio.getvalue()
        st.download_button(
            "⬇️ Download ALL findings (XLSX)",
            data=xlsx_bytes,
            file_name="zhTW_QA_findings.xlsx",
            use_container_width=True,
        )

    # ZIP export (CSVs + XLSX + previews + metadata)
    with io.BytesIO() as zbio:
        with zipfile.ZipFile(zbio, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # CSVs
            zf.writestr("findings/extra_spaces.csv", csv_spaces)
            zf.writestr("findings/typographical_issues.csv", csv_typos)
            zf.writestr("findings/duplicated_footnotes.csv", csv_foot)
            if csv_terms:
                zf.writestr("findings/terminology_inconsistencies.csv", csv_terms)
            # XLSX
            zf.writestr("findings/zhTW_QA_findings.xlsx", xlsx_bytes)
            # Previews (limit large text to ~100k chars)
            zf.writestr("previews/source_preview.txt", (source_text or "")[0:100000])
            zf.writestr("previews/target_preview.txt", (target_text or "")[0:100000])
            # Metadata
            meta = {
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "source_name": getattr(source_file, "name", None),
                "target_name": getattr(target_file, "name", None),
                "glossary_name": getattr(glossary_file, "name", None),
                "counts": results,
            }
            zf.writestr("metadata.json", json.dumps(meta, ensure_ascii=False, indent=2))
        st.download_button(
            "⬇️ Download ZIP (CSVs + XLSX + previews + metadata)",
            data=zbio.getvalue(),
            file_name="zhTW_QA_package.zip",
            use_container_width=True,
        )

else:
    st.info("⬅️ Upload your English source, Traditional Chinese target, and optional glossary (CSV/XLSX). Then click Run QA.")
