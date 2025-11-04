import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr ofert – CSV lub XML", layout="wide")
st.title("⚙️ Filtr ofert – CSV/XLSX lub XML")
st.caption("Najpierw wybierz tryb. Obie ścieżki używają wspólnej logiki filtrowania i eksportu.")

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
        stock = (o.get("stock") or "").strip()

        cat  = (o.findtext("cat") or "").strip()
        name = (o.findtext("name") or "").strip()

        # atrybuty z <attrs>
        producent = ""
        extra = {}
        attrs_el = o.find("attrs")
        if attrs_el is not None:
            for a in attrs_el.findall("a"):
                k = (a.get("name") or "").strip()
                v = (a.text or "").strip()
                if k:
                    extra[k] = v
                    if k.lower() == "producent":
                        producent = v

        row = {
            "Kategoria": cat,
            "Producent": producent,
            "Nazwa": name,
            "Cena": price.replace(",", "."),
            "Dostępność": 1 if avail in {"1","true","True","tak","TAK"} else 99,
            "Liczba sztuk": stock,
            "ID": oid,
            "URL": ourl,
        }
        for k, v in extra.items():
            if k not in row:
                row[k] = v

        rows.append(row)

    df = pd.DataFrame(rows)

    # typy liczbowe
    for c in ("Cena","Dostępność","Liczba sztuk"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # mapowanie pod filtry zaawansowane
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

    if "przekatna_ekranu" in df.columns:
        df["przekatna_ekranu"] = (
            df["przekatna_ekranu"].astype(str).str.replace('"','').str.replace(",",".", regex=False)
        )
        df["przekatna_ekranu"] = pd.to_numeric(df["przekatna_ekranu"], errors="coerce")
    if "ilosc_rdzeni" in df.columns:
        df["ilosc_rdzeni"] = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").astype("Int64")

    return df

# ---------- Wspólna logika UI (filtry + widok + export) ----------
def render_app(df: pd.DataFrame, source_label: str):
    if df.empty:
        st.error("Plik został wczytany, ale tabela jest pusta.")
        st.stop()

    required = ["Kategoria", "Producent", "Nazwa", "Cena", "Dostępność"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Brak wymaganych kolumn: {', '.join(missing)}")
        st.stop()

    st.success(f"Wczytano: {source_label} • Wiersze: {len(df):,} • Kolumny: {len(df.columns):,}")

    # przygotowanie serii
    cat_series  = df["Kategoria"].astype(str).str.strip()
    prod_series = df["Producent"].astype(str).str.strip()
    name_series = df["Nazwa"].astype(str)
    price       = pd.to_numeric(df["Cena"], errors="coerce")

    # Sidebar: filtry główne
    st.sidebar.header("Ustawienia filtrowania")
    status_choice = st.sidebar.radio("Status produktu (kolumna 'Dostępność')",
                                     options=["Wszystkie", "Aktywne", "Nieaktywne"], index=1)

    cats_options = sorted(df["Kategoria"].dropna().astype(str).str.strip().unique().tolist())
    selected_cats = st.sidebar.multiselect("Kategoria", options=cats_options)

    prod_options = sorted(df["Producent"].dropna().astype(str).str.strip().unique().tolist())
    selected_prods = st.sidebar.multiselect("Producent", options=prod_options)

    min_price = float(price.min(skipna=True)) if price.notna().any() else 0.0
    max_price = float(price.max(skipna=True)) if price.notna().any() else 0.0
    c1, c2 = st.sidebar.columns(2)
    with c1:
        price_from = st.number_input("Cena od", value=min_price, min_value=0.0, step=1.0, format="%.2f")
    with c2:
        price_to = st.number_input("Cena do", value=max_price, min_value=0.0, step=1.0, format="%.2f")

    # Stan liczbowy (jeśli istnieje i jest numeryczny)
    stan_range = None
    if "Stan" in df.columns:
        stan_num = pd.to_numeric(df["Stan"], errors="coerce")
        if stan_num.notna().any():
            stan_min, stan_max = float(stan_num.min()), float(stan_num.max())
            c1, c2 = st.sidebar.columns(2)
            with c1:
                stan_from = st.number_input("Stan od", value=stan_min, min_value=0.0, step=1.0, format="%.0f")
            with c2:
                stan_to = st.number_input("Stan do", value=stan_max, min_value=0.0, step=1.0, format="%.0f")
            if stan_from <= stan_to:
                stan_range = (stan_from, stan_to)

    # Ilość sztuk (z XML; jeśli jest)
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

    name_query = st.sidebar.text_input("Szukaj w 'Nazwa'", value="")

    # Filtry zaawansowane (laptopy)
    with st.sidebar.expander("Filtry zaawansowane (laptopy)", expanded=False):
        ekr_sel = rdzenie_sel = kond_sel = proc_sel = rodz_gpu_sel = rozdz_sel = stan_ob_sel = typ_ram_sel = None
        if "ekran_dotykowy" in df.columns:
            opts = sorted(df["ekran_dotykowy"].dropna().astype(str).str.strip().unique(), key=str.lower)
            ekr_sel = st.multiselect("ekran_dotykowy", options=opts, default=[])
        if "ilosc_rdzeni" in df.columns:
            rdz = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").dropna().astype(int)
            if not rdz.empty:
                rdzenie_sel = st.multiselect("ilosc_rdzeni", options=sorted(rdz.unique().tolist()), default=[])
        if "kondycja_sprzetu" in df.columns:
            opts = sorted(df["kondycja_sprzetu"].dropna().astype(str).str.strip().unique(), key=str.lower)
            kond_sel = st.multiselect("kondycja_sprzetu", options=opts, default=[])
        if "procesor" in df.columns:
            opts = sorted(df["procesor"].dropna().astype(str).str.strip().unique(), key=str.lower)
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
        if "rodzaj_karty_graficznej" in df.columns:
            opts = sorted(df["rodzaj_karty_graficznej"].dropna().astype(str).str.strip().unique(), key=str.lower)
            rodz_gpu_sel = st.multiselect("rodzaj_karty_graficznej", options=opts, default=[])
        if "rozdzielczosc_ekranu" in df.columns:
            opts = sorted(df["rozdzielczosc_ekranu"].dropna().astype(str).str.strip().unique(), key=str.lower)
            rozdz_sel = st.multiselect("rozdzielczosc_ekranu", options=opts, default=[])
        if "stan_obudowy" in df.columns:
            opts = sorted(df["stan_obudowy"].dropna().astype(str).str.strip().unique(), key=str.lower)
            stan_ob_sel = st.multiselect("stan_obudowy", options=opts, default=[])
        if "typ_pamieci_ram" in df.columns:
            opts = sorted(df["typ_pamieci_ram"].dropna().astype(str).str.strip().unique(), key=str.lower)
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

    if 'przek_range' in locals() and przek_range is not None and "przekatna_ekranu" in df.columns:
        p_all = pd.to_numeric(df["przekatna_ekranu"], errors="coerce")
        mask &= p_all.between(przek_range[0], przek_range[1], inclusive="both")

    filtered = df.loc[mask].copy()
    if filtered.empty:
        st.warning("Brak wierszy po zastosowaniu filtrów.")
        st.stop()

    non_empty_cols = [c for c in filtered.columns if (filtered[c].notna() & ~filtered[c].astype(str).str.strip().eq("")).any()]
    view_df = filtered[non_empty_cols]

    st.subheader("Wynik")
    st.write(f"Wiersze: **{len(view_df):,}** | Kolumny (niepuste): **{len(view_df.columns):,}** / {len(df.columns):,}")
    st.dataframe(view_df, use_container_width=True, height=560)

    st.divider()
    st.subheader("Pobierz wynik")
    c1, c2 = st.columns(2)
    with c1:
        csv_bytes = view_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ CSV – widok (kolumny niepuste)", csv_bytes, "oferty_widok_niepuste.csv", "text/csv")
    with c2:
        xlsx_bytes = to_excel_bytes(view_df)
        st.download_button("⬇️ XLSX – widok (kolumny niepuste)", xlsx_bytes, "oferty_widok_niepuste.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.caption("Normalizacja (trim + case-insensitive) jest zawsze aktywna. Widok ukrywa kolumny bez wartości w aktualnym wyniku.")

# ---------- Tryb CSV ----------
def run_csv_mode():
    st.sidebar.subheader("Tryb: CSV/XLSX")
    upload = st.file_uploader("Wgraj plik (CSV/XLSX/XLS/XLSM)", type=["csv","xlsx","xls","xlsm"])
    slug = st.sidebar.text_input("Slug / hasło (ostatni fragment URL CSV API)", value="", placeholder="np. 1234")
    if st.sidebar.button("Pobierz CSV z API"):
        if not slug.strip():
            st.sidebar.error("Podaj slug/hasło.")
            st.stop()
        url = f"https://kompre.esolu-hub.pl/api/feed/{slug.strip()}"
        with st.spinner("Pobieranie CSV..."):
            try:
                df_url = pd.read_csv(url, sep=None, engine="python")
                st.session_state["df_csv"] = df_url
                st.session_state["label_csv"] = f"URL:CSV:{slug.strip()}"
            except Exception:
                st.sidebar.error("Nie udało się pobrać CSV (zły slug/hasło lub brak pliku).")
                st.stop()

    if upload is not None:
        with st.spinner("Wczytywanie pliku..."):
            df = read_any_table(upload)
        render_app(df, upload.name)
    elif "df_csv" in st.session_state:
        render_app(st.session_state["df_csv"], st.session_state.get("label_csv","URL:CSV"))
    else:
        st.info("Wgraj plik lub pobierz CSV z API.")

# ---------- Tryb XML ----------
def run_xml_mode():
    st.sidebar.subheader("Tryb: XML")
    # nie pokazujemy pełnego linku — budujemy z hasła/nazwy pliku
    base = "https://marekkomp.github.io/nowe_repo10.2025_allegrocsv_na_XML/output/"
    xml_pass = st.sidebar.text_input("Hasło (nazwa pliku .xml)", value="", placeholder="np. morele")
    if st.sidebar.button("Pobierz XML"):
        if not xml_pass.strip():
            st.sidebar.error("Podaj hasło (nazwę pliku).")
            st.stop()
        xml_url = f"{base}{xml_pass.strip()}.xml"
        with st.spinner("Pobieranie i parsowanie XML..."):
            try:
                df_xml = read_morele_xml(xml_url)
                st.session_state["df_xml"] = df_xml
                st.session_state["label_xml"] = f"URL:XML:{xml_pass.strip()}.xml"
            except Exception:
                st.sidebar.error("Brak dostępu lub plik nie istnieje (złe hasło/nazwa pliku).")
                st.stop()

    if "df_xml" in st.session_state:
        render_app(st.session_state["df_xml"], st.session_state.get("label_xml","URL:XML"))
    else:
        st.info("Podaj hasło (nazwę pliku) i pobierz XML.")

# ---------- Ekran wyboru ----------
mode = st.sidebar.radio("Wybierz tryb aplikacji", ["CSV/XLSX", "XML"], index=0, horizontal=True)
if mode == "CSV/XLSX":
    run_csv_mode()
else:
    run_xml_mode()
