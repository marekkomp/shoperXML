import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr ofert – kategoria / producent / status / cena / nazwa / stan", layout="wide")
st.title("⚙️ Filtr ofert – kategoria / producent / status / cena / nazwa / stan")
st.caption("Wgraj CSV/XLSX lub pobierz CSV/XML → wybierz filtry. Widok zawsze pokazuje tylko kolumny niepuste dla wyniku.")

# ---------- Helpers ----------
@st.cache_data(show_spinner=False)
def read_any_table(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(file)
    try:
        df = pd.read_csv(file, sep=None, engine="python")
    except Exception:
        file.seek(0)
        df = pd.read_csv(file, sep=",", engine="python")
    return df

@st.cache_data(show_spinner=False)
def to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="dane")
    return output.getvalue()

@st.cache_data(show_spinner=False)
def read_morele_xml(url: str) -> pd.DataFrame:
    """Parser XML: <offers><o ...><cat/><name/><attrs><a name=...>...</a></attrs></o>...</offers>"""
    import xml.etree.ElementTree as ET
    from urllib.request import urlopen

    raw = urlopen(url).read()
    root = ET.fromstring(raw)

    rows = []
    for o in root.findall(".//o"):
        oid   = (o.get("id") or "").strip()
        ourl  = (o.get("url") or "").strip()
        price = (o.get("price") or "").strip()
        avail = (o.get("avail") or "").strip()
        stock = (o.get("stock") or "").strip()  # ilość sztuk

        cat  = (o.findtext("cat") or "").strip()
        name = (o.findtext("name") or "").strip()

        # Atrybuty z <attrs>
        attrs = {}
        attrs_el = o.find("attrs")
        if attrs_el is not None:
            for a in attrs_el.findall("a"):
                key = (a.get("name") or "").strip()
                val = (a.text or "").strip()
                if key:
                    attrs[key] = val

        row = {
            "Kategoria": cat,
            "Producent": attrs.get("Producent", "").strip(),
            "Nazwa": name,
            "Cena": price.replace(",", "."),
            "Dostępność": 1 if avail in {"1","true","True","tak","TAK"} else 99,
            "Liczba sztuk": stock,
            "ID": oid,
            "URL": ourl,
        }

        # Dołącz resztę atrybutów jako dodatkowe kolumny
        for k, v in attrs.items():
            if k not in row:
                row[k] = v

        rows.append(row)

    df = pd.DataFrame(rows)

    # Konwersje liczbowe
    if "Cena" in df.columns:
        df["Cena"] = pd.to_numeric(df["Cena"], errors="coerce")
    if "Liczba sztuk" in df.columns:
        df["Liczba sztuk"] = pd.to_numeric(df["Liczba sztuk"], errors="coerce")
    if "Dostępność" in df.columns:
        df["Dostępność"] = pd.to_numeric(df["Dostępność"], errors="coerce")

    # Mapowanie nazw pod Twoje filtry zaawansowane
    COLMAP = {
        "Ekran dotykowy": "ekran_dotykowy",
        "Liczba rdzeni procesora": "ilosc_rdzeni",
        "Rodzaj karty graficznej": "rodzaj_karty_graficznej",
        "Rozdzielczość": "rozdzielczosc_ekranu",
        "Stan obudowy": "stan_obudowy",
        "Typ pamięci RAM": "typ_pamieci_ram",
        "Przekątna ekranu": "przekatna_ekranu",
        "Procesor": "procesor",
    }
    df = df.rename(columns={k: v for k, v in COLMAP.items() if k in df.columns})

    # Normalizacja kilku pól technicznych
    if "przekatna_ekranu" in df.columns:
        df["przekatna_ekranu"] = (
            df["przekatna_ekranu"].astype(str)
            .str.replace('"', '')
            .str.replace(",", ".", regex=False)
        )
        df["przekatna_ekranu"] = pd.to_numeric(df["przekatna_ekranu"], errors="coerce")
    if "ilosc_rdzeni" in df.columns:
        df["ilosc_rdzeni"] = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").astype("Int64")

    return df

# ---------- Upload lub pobranie na żądanie ----------
st.sidebar.subheader("Wczytaj dane")

# CSV z esolu-hub
slug = st.sidebar.text_input("Nazwa źródła (ostatni fragment URL)", value="", placeholder="np. 1234")
fetch_clicked = st.sidebar.button("Pobierz plik z URL (CSV)")

# XML z hasłem
st.sidebar.markdown("---")
xml_url = st.sidebar.text_input(
    "Link do XML",
    value="https://marekkomp.github.io/nowe_repo10.2025_allegrocsv_na_XML/output/morele.xml",
    placeholder="https://.../morele.xml",
)
xml_pwd = st.sidebar.text_input("Hasło do XML", type="password", placeholder="wpisz: morele")
xml_fetch = st.sidebar.button("Pobierz XML")

df = None
source_label = None

# Pobierz CSV
if fetch_clicked:
    if not slug.strip():
        st.sidebar.error("Podaj nazwę źródła (slug).")
    else:
        full_url = "https://kompre.esolu-hub.pl/api/feed/" + slug.strip()
        with st.spinner("Pobieranie CSV z URL..."):
            try:
                df_url = pd.read_csv(full_url, sep=None, engine="python")
                st.session_state["df_from_url"] = df_url
                st.session_state["df_source_label"] = f"URL:CSV:{slug.strip()}"
            except Exception:
                st.sidebar.error("Nie udało się pobrać pliku (sprawdź slug).")
                st.stop()

# Pobierz XML (z hasłem)
if xml_fetch:
    if xml_pwd != "morele":
        st.sidebar.error("Nieprawidłowe hasło do XML.")
        st.stop()
    with st.spinner("Pobieranie i parsowanie XML..."):
        try:
            df_xml = read_morele_xml(xml_url.strip())
            st.session_state["df_from_xml"] = df_xml
            st.session_state["df_source_label"] = "URL:XML:morele"
        except Exception as e:
            st.sidebar.error(f"Nie udało się pobrać/parsować XML: {e}")
            st.stop()

# priorytet: upload ręczny > XML > CSV
upload = st.file_uploader("Wgraj plik z ofertami (CSV lub XLSX)", type=["csv", "xlsx", "xls", "xlsm"])

if upload is not None:
    with st.spinner("Wczytywanie pliku..."):
        df = read_any_table(upload)
    source_label = upload.name
elif "df_from_xml" in st.session_state:
    df = st.session_state["df_from_xml"]
    source_label = st.session_state.get("df_source_label", "URL:XML")
elif "df_from_url" in st.session_state:
    df = st.session_state["df_from_url"]
    source_label = st.session_state.get("df_source_label", "URL:CSV")

if df is None:
    st.info("Wgraj plik albo użyj jednej z opcji pobierania (CSV lub XML).")
    st.stop()

if df.empty:
    st.error("Plik został wczytany, ale tabela jest pusta.")
    st.stop()

st.success(f"Wczytano: {source_label} • Wiersze: {len(df):,} • Kolumny: {len(df.columns):,}")

# ---------- Kolumny wymagane ----------
missing = [c for c in ["Kategoria", "Producent", "Nazwa", "Cena", "Dostępność"] if c not in df.columns]
if missing:
    st.error(f"Brak wymaganych kolumn: {', '.join(missing)}")
    st.stop()

# Normalizacja pomocnicza
cat_series = df["Kategoria"].astype(str).str.strip()
prod_series = df["Producent"].astype(str).str.strip()
name_series = df["Nazwa"].astype(str)
price = pd.to_numeric(df["Cena"], errors="coerce")

# Opcje do multiselectów
cat_options_base = df["Kategoria"].dropna().astype(str).str.strip()
prod_options_base = df["Producent"].dropna().astype(str).str.strip()

# ---------- Sidebar: filtry główne ----------
st.sidebar.header("Ustawienia filtrowania")

status_choice = st.sidebar.radio(
    "Status produktu (kolumna 'Dostępność')",
    options=["Wszystkie", "Aktywne", "Nieaktywne"],
    index=1,
)

cats_options = sorted(cat_options_base.unique().tolist())
selected_cats = st.sidebar.multiselect("Kategoria", options=cats_options)

prod_options = sorted(prod_options_base.unique().tolist())
selected_prods = st.sidebar.multiselect("Producent", options=prod_options)

min_price = float(price.min(skipna=True)) if price.notna().any() else 0.0
max_price = float(price.max(skipna=True)) if price.notna().any() else 0.0
c1, c2 = st.sidebar.columns(2)
with c1:
    price_from = st.number_input("Cena od", value=min_price, min_value=0.0, step=1.0, format="%.2f")
with c2:
    price_to = st.number_input("Cena do", value=max_price, min_value=0.0, step=1.0, format="%.2f")

# Stan (zakres liczbowy, jeśli kolumna Stan jest numeryczna)
stan_range = None
if "Stan" in df.columns:
    stan_num = pd.to_numeric(df["Stan"], errors="coerce")
    if stan_num.notna().any():
        stan_min = float(stan_num.min())
        stan_max = float(stan_num.max())
        c1, c2 = st.sidebar.columns(2)
        with c1:
            stan_from = st.number_input("Stan od", value=stan_min, min_value=0.0, step=1.0, format="%.0f")
        with c2:
            stan_to = st.number_input("Stan do", value=stan_max, min_value=0.0, step=1.0, format="%.0f")
        if stan_from <= stan_to:
            stan_range = (stan_from, stan_to)

name_query = st.sidebar.text_input("Szukaj w 'Nazwa'", value="")

# (Opcjonalnie) filtr po ilości sztuk ze stock
qty_range = None
if "Liczba sztuk" in df.columns:
    qty = pd.to_numeric(df["Liczba sztuk"], errors="coerce")
    if qty.notna().any():
        qmin, qmax = float(qty.min()), float(qty.max())
        c1, c2 = st.sidebar.columns(2)
        with c1:
            q_from = st.number_input("Ilość od", value=qmin, min_value=0.0, step=1.0, format="%.0f")
        with c2:
            q_to = st.number_input("Ilość do", value=qmax, min_value=0.0, step=1.0, format="%.0f")
        if q_from <= q_to:
            qty_range = (q_from, q_to)

# ---------- Filtry zaawansowane (laptopy) ----------
with st.sidebar.expander("Filtry zaawansowane (laptopy)", expanded=False):
    ekr_sel = None
    if "ekran_dotykowy" in df.columns:
        ekr_vals = df["ekran_dotykowy"].dropna().astype(str).str.strip()
        ekr_opts = sorted(ekr_vals.unique().tolist(), key=lambda x: str(x).lower())
        ekr_sel = st.multiselect("ekran_dotykowy", options=ekr_opts, default=[])

    rdzenie_sel = None
    if "ilosc_rdzeni" in df.columns:
        rdz = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").dropna().astype(int)
        if not rdz.empty:
            rd_opts = sorted(rdz.unique().tolist())
            rdzenie_sel = st.multiselect("ilosc_rdzeni", options=rd_opts, default=[])

    kond_sel = None
    if "kondycja_sprzetu" in df.columns:
        v = df["kondycja_sprzetu"].dropna().astype(str).str.strip()
        opts = sorted(v.unique().tolist(), key=lambda x: str(x).lower())
        kond_sel = st.multiselect("kondycja_sprzetu", options=opts, default=[])

    proc_sel = None
    if "procesor" in df.columns:
        v = df["procesor"].dropna().astype(str).str.strip()
        opts = sorted(v.unique().tolist(), key=lambda x: str(x).lower())
        proc_sel = st.multiselect("procesor", options=opts, default=[])

    przek_range = None
    if "przekatna_ekranu" in df.columns:
        pe = pd.to_numeric(df["przekatna_ekranu"], errors="coerce")
        if pe.notna().any():
            pmin, pmax = float(pe.min()), float(pe.max())
            c1, c2 = st.columns(2)
            with c1:
                p_from = st.number_input("Przekątna od", value=pmin, min_value=0.0, step=0.1, format="%.1f")
            with c2:
                p_to = st.number_input("Przekątna do", value=pmax, min_value=0.0, step=0.1, format="%.1f")
            if p_from <= p_to:
                przek_range = (p_from, p_to)

    rodz_gpu_sel = None
    if "rodzaj_karty_graficznej" in df.columns:
        v = df["rodzaj_karty_graficznej"].dropna().astype(str).str.strip()
        opts = sorted(v.unique().tolist(), key=lambda x: str(x).lower())
        rodz_gpu_sel = st.multiselect("rodzaj_karty_graficznej", options=opts, default=[])

    rozdz_sel = None
    if "rozdzielczosc_ekranu" in df.columns:
        v = df["rozdzielczosc_ekranu"].dropna().astype(str).str.strip()
        opts = sorted(v.unique().tolist(), key=lambda x: str(x).lower())
        rozdz_sel = st.multiselect("rozdzielczosc_ekranu", options=opts, default=[])

    stan_ob_sel = None
    if "stan_obudowy" in df.columns:
        v = df["stan_obudowy"].dropna().astype(str).str.strip()
        opts = sorted(v.unique().tolist(), key=lambda x: str(x).lower())
        stan_ob_sel = st.multiselect("stan_obudowy", options=opts, default=[])

    typ_ram_sel = None
    if "typ_pamieci_ram" in df.columns:
        v = df["typ_pamieci_ram"].dropna().astype(str).str.strip()
        opts = sorted(v.unique().tolist(), key=lambda x: str(x).lower())
        typ_ram_sel = st.multiselect("typ_pamieci_ram", options=opts, default=[])

# ---------- Filtrowanie ----------
mask = pd.Series(True, index=df.index)

if status_choice != "Wszystkie":
    d = pd.to_numeric(df["Dostępność"], errors="coerce")
    mask &= (d == 1) if "Aktywne" in status_choice else (d == 99)

if selected_cats:
    mask &= cat_series.isin(selected_cats)

if selected_prods:
    mask &= prod_series.isin(selected_prods)

if price.notna().any():
    mask &= price.between(price_from, price_to, inclusive="both")

if stan_range is not None and "Stan" in df.columns:
    stan_num_all = pd.to_numeric(df["Stan"], errors="coerce")
    mask &= stan_num_all.between(stan_range[0], stan_range[1], inclusive="both")

if qty_range is not None and "Liczba sztuk" in df.columns:
    qty_all = pd.to_numeric(df["Liczba sztuk"], errors="coerce")
    mask &= qty_all.between(qty_range[0], qty_range[1], inclusive="both")

if name_query.strip():
    mask &= name_series.str.contains(name_query.strip(), case=False, na=False)

# --- Filtry zaawansowane (laptopy) ---
for col, sel in {
    "ekran_dotykowy": ekr_sel,
    "kondycja_sprzetu": kond_sel,
    "procesor": proc_sel,
    "rodzaj_karty_graficznej": rodz_gpu_sel,
    "rozdzielczosc_ekranu": rozdz_sel,
    "stan_obudowy": stan_ob_sel,
    "typ_pamieci_ram": typ_ram_sel,
}.items():
    if sel and col in df.columns:
        cmp = df[col].astype(str).str.strip().str.casefold()
        target = pd.Series(sel).astype(str).str.strip().str.casefold().tolist()
        mask &= cmp.isin(target)

if 'rdzenie_sel' in locals() and rdzenie_sel and "ilosc_rdzeni" in df.columns:
    r_all = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").astype("Int64")
    mask &= r_all.isin(rdzenie_sel)

if przek_range is not None and "przekatna_ekranu" in df.columns:
    p_all = pd.to_numeric(df["przekatna_ekranu"], errors="coerce")
    mask &= p_all.between(przek_range[0], przek_range[1], inclusive="both")

filtered = df.loc[mask].copy()

# ---------- Wynik ----------
if filtered.empty:
    st.warning("Brak wierszy po zastosowaniu filtrów.")
    st.stop()

non_empty_cols = [c for c in filtered.columns if (filtered[c].notna() & ~filtered[c].astype(str).str.strip().eq("")).any()]
view_df = filtered[non_empty_cols]

st.subheader("Wynik")
st.write(f"Wiersze: **{len(view_df):,}** | Kolumny (niepuste): **{len(view_df.columns):,}** / {len(df.columns):,}")
st.dataframe(view_df, use_container_width=True, height=560)

# ---------- Pobieranie ----------
st.divider()
st.subheader("Pobierz wynik")

c1, c2 = st.columns(2)
with c1:
    csv_bytes = view_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇️ CSV – widok (kolumny niepuste)", csv_bytes, "oferty_widok_niepuste.csv", "text/csv")
with c2:
    xlsx_bytes = to_excel_bytes(view_df)
    st.download_button("⬇️ XLSX – widok (kolumny niepuste)", xlsx_bytes, "oferty_widok_niepuste.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

st.caption("Normalizacja (trim + case-insensitive) jest zawsze aktywna. Widok ukrywa kolumny bez wartości w aktualnym wyniku.")
