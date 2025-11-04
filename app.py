# app_secure_xml.py
# -*- coding: utf-8 -*-
import io, base64
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr XML – tryby chronione", layout="wide")
st.title("⚙️ Filtr danych XML")
st.caption("Dwa tryby: 1️⃣ Dostęp chroniony (hasło)  2️⃣ Dostęp z kluczem (nazwa pliku)")

# ---------- Helpers ----------
@st.cache_data(show_spinner=False)
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="dane")
    return buf.getvalue()


@st.cache_data(show_spinner=False)
def read_xml_build_df(url: str) -> pd.DataFrame:
    import xml.etree.ElementTree as ET
    from urllib.request import urlopen

    raw = urlopen(url).read()
    root = ET.fromstring(raw)

    rows, max_imgs = [], 0

    for o in root.findall(".//o"):
        oid   = (o.get("id") or "").strip()
        ourl  = (o.get("url") or "").strip()
        price = (o.get("price") or "").strip()
        avail = (o.get("avail") or "").strip()
        stock = (o.get("stock") or "").strip()
        cat   = (o.findtext("cat")  or "").strip()
        name  = (o.findtext("name") or "").strip()

        # opis
        desc_el = o.find("desc")
        desc_html = (desc_el.text or "").strip() if desc_el is not None else ""

        # zdjęcia
        images = []
        imgs_el = o.find("imgs")
        if imgs_el is not None:
            main_el = imgs_el.find("main")
            if main_el is not None and (main_el.get("url") or "").strip():
                images.append((main_el.get("url") or "").strip())
            for i_el in imgs_el.findall("i"):
                u = (i_el.get("url") or "").strip()
                if u:
                    images.append(u)
        max_imgs = max(max_imgs, len(images))

        # atrybuty
        producent = ""
        extra = {}
        attrs_el = o.find("attrs")
        if attrs_el is not None:
            for a in attrs_el.findall("a"):
                k = (a.get("name") or "").strip()
                v = (a.text or "").strip()
                if not k:
                    continue
                extra[k] = v
                if k.lower() == "producent":
                    producent = v

        row = {
            "Kategoria": cat,
            "Producent": producent,
            "Nazwa": name,
            "Cena": price.replace(",", "."),
            "Dostępność": 1 if avail.strip() in {"1","true","True","tak","TAK"} else 99,
            "Liczba sztuk": stock,
            "ID": oid,
            "URL": ourl,
            "Opis": desc_html,
        }
        for i, img in enumerate(images, start=1):
            row[f"Zdjęcie {i}"] = img
        for k, v in extra.items():
            if k not in row:
                row[k] = v

        rows.append(row)

    df = pd.DataFrame(rows)
    for i in range(1, max_imgs + 1):
        col = f"Zdjęcie {i}"
        if col not in df.columns:
            df[col] = ""
    for c in ("Cena","Dostępność","Liczba sztuk"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def decode_url(code: str) -> str:
    """prosty base64 decode, żeby ukryć adresy"""
    return base64.b64decode(code.encode()).decode().strip()


# ---------- Tryb 1 – chroniony (hasło) ----------
def run_protected_mode():
    st.sidebar.subheader("Tryb chroniony (hasło)")
    pwd = st.sidebar.text_input("Hasło", type="password", placeholder="wpisz hasło")
    if st.sidebar.button("Pobierz dane"):
        if (pwd or "").strip().lower() != "kompre":
            st.sidebar.error("Błędne hasło.")
            st.stop()
        with st.spinner("Wczytywanie..."):
            # zakodowany URL kompre.xml
            encoded = "aHR0cHM6Ly9rb21wcmUuZXNvbHUtaHViLnBsL3N0b3JhZ2UvZmVlZHMva29tcHJlLnhtbA=="
            st.session_state["df_secure1"] = read_xml_build_df(decode_url(encoded))

    if "df_secure1" in st.session_state:
        render_view(st.session_state["df_secure1"], "Źródło 1")
    else:
        st.info("Podaj hasło i pobierz dane.")


# ---------- Tryb 2 – plik z kluczem ----------
def run_key_mode():
    st.sidebar.subheader("Tryb z nazwą pliku")
    base = "aHR0cHM6Ly9tYXJla2tvbXAua2l0aHViLmlvL25vd2VfcmVwbzEwLjIwMjVfYWxsZWdyb2Nzdn9fbmFfWE1ML291dHB1dC8="
    key = st.sidebar.text_input("Nazwa pliku (bez .xml)", placeholder="np. feed123")
    if st.sidebar.button("Pobierz plik"):
        if not key.strip():
            st.sidebar.error("Podaj nazwę pliku.")
            st.stop()
        full = decode_url(base) + f"{key.strip()}.xml"
        with st.spinner("Wczytywanie..."):
            try:
                st.session_state["df_secure2"] = read_xml_build_df(full)
            except Exception:
                st.sidebar.error("Brak dostępu lub błędna nazwa pliku.")
                st.stop()

    if "df_secure2" in st.session_state:
        render_view(st.session_state["df_secure2"], "Źródło 2")
    else:
        st.info("Podaj nazwę pliku i kliknij „Pobierz plik”.")


# ---------- Widok i eksport ----------
def render_view(df: pd.DataFrame, label: str):
    st.success(f"Wczytano: {label} • {len(df):,} wierszy")
    st.dataframe(df, use_container_width=True, height=580)
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8-sig"), "dane.csv")
    with c2:
        st.download_button("⬇️ XLSX", to_excel_bytes(df), "dane.xlsx")


# ---------- Wybór trybu ----------
mode = st.sidebar.radio("Wybierz tryb", ["Chroniony (hasło)", "Plik z kluczem"], index=0, horizontal=True)
if mode.startswith("Chroniony"):
    run_protected_mode()
else:
    run_key_mode()
