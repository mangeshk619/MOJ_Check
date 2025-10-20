import io
import re
from datetime import datetime
import pandas as pd
import streamlit as st

# ── Page config
st.set_page_config(page_title="Translation QA for Traditional Chinese", page_icon="🈶", layout="wide")

# ── Sidebar
st.sidebar.title("⚙️ Upload Files")
source_file = st.sidebar.file_uploader("Upload Source File (English)", type=["txt", "docx", "pdf"])
target_file = st.sidebar.file_uploader("Upload Target File (Traditional Chinese)", type=["txt", "docx", "pdf"])
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
            return data.decode("utf-8", errors="ignore")
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

def check_extra_spaces(text):
    pattern = re.compile(r"([\u4e00-\u9fff])[ \t]+([\u4e00-\u9fff])")
    return [(m.start(), m.group()) for m in pattern.finditer(text)]

def check_typos(text):
    issues = []
    ascii_punct = r",\.;:!\?\)\(\[\]\{\}\"'"
    pattern = re.compile(fr"([\u4e00-\u9fff])([{ascii_punct}])([\u4e00-\u9fff])")
    for m in pattern.finditer(text):
        issues.append((m.start(), m.group(2)))
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
    return duplicates

def check_terminology_inconsistency(source, target):
    inconsistencies = []
    terms = ["委託", "受託", "契約", "合同"]  # Example key terms for demo
    for term in terms:
        count = target.count(term)
        if count > 1:
            inconsistencies.append((term, count))
    return inconsistencies

# ── Main Execution
if run:
    if not source_file or not target_file:
        st.warning("Please upload both Source and Target files.")
        st.stop()

    source_text = extract_text(source_file)
    target_text = extract_text(target_file)

    st.subheader("📘 Source Text (English)")
    st.text_area("Source Preview", source_text[:2000], height=150)

    st.subheader("📗 Target Text (Traditional Chinese)")
    st.text_area("Target Preview", target_text[:2000], height=150)

    st.markdown("---")

    st.subheader("🔎 QA Checks")
    spaces = check_extra_spaces(target_text)
    typos = check_typos(target_text)
    duplicates = check_duplicate_footnotes(target_text)
    inconsistencies = check_terminology_inconsistency(source_text, target_text)

    results = {
        "Extra Spaces": len(spaces),
        "Typographical Errors": len(typos),
        "Duplicated Footnotes": len(duplicates),
        "Terminology Inconsistencies": len(inconsistencies),
    }
    st.write(pd.DataFrame.from_dict(results, orient="index", columns=["Count"]))

    st.markdown("---")

    st.subheader("📝 Detailed Results")
    st.write("**Extra Spaces Found:**", spaces[:10])
    st.write("**Typographical Issues:**", typos[:10])
    st.write("**Duplicate Footnotes:**", duplicates[:10])
    st.write("**Terminology Inconsistencies:**", inconsistencies[:10])

else:
    st.info("⬅️ Upload your English source and Traditional Chinese target files to start QA.")
