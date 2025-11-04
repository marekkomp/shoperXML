import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr ofert – CSV/XLSX lub XML", layout="wide")
st.title("⚙️ Filtr ofert – CSV/XLSX lub XML")
st.caption("Wybierz tryb na górze. CSV/XLSX – pełne filtry (tak jak dotychczas). XML – tylko filtry podstawowe.")

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
def read_xml_build_df(url: str) -> pd.DataFrame:
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
        cat   = (o.findtext("cat")  or "").strip()
        name  = (o.findtext("name") or "").strip()

        # --- Opis HTML (zachowaj tagi) ---
        desc_html = ""
        desc_el = o.find("desc")
        if desc_el is not None:
            # zbuduj HTML z dzieci <desc> (unikamy owijającego <desc>)
            desc_html = "".join(
                ET.tostring(child, encoding="unicode", method="xml")
                for child in list(desc_el)
            ).strip()
            # jeśli <desc> miało tylko tekst (bez dzieci), weź tekst
            if not desc_html:
                # to będzie czysty tekst bez tagów, ale lepsze to niż pusto
                desc_html = (desc_el.text or "").strip()

        # --- Zdjęcia ---
        main_img = ""
        images = []
        imgs_el = o.find("imgs")
        if imgs_el is not None:
            main_el = imgs_el.find("main")
            if main_el is not None:
                main_img = (main_el.get("url") or "").strip()
                if main_img:
                    images.append(main_img)
            for i_el in imgs_el.findall("i"):
                u = (i_el.get("url") or "").strip()
                if u:
                    images.append(u)
        imgs_joined = ";".join(images) if images else ""

        # Atrybuty z <attrs>
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
            "Dostępność": 1 if avail in {"1","true","True","tak","TAK"} else 99,
            "Liczba sztuk": stock,
            "ID": oid,
            "URL": ourl,
            "Opis HTML": desc_html,
            "Zdjęcie główne": main_img,
            "Zdjęcia": imgs_joined,
        }
        # dołącz pozostałe atrybuty jako kolumny
        for k, v in extra.items():
            if k not in row:
                row[k] = v

        rows.append(row)

    df = pd.DataFrame(rows)
    for c in ("Cena","Dostępność","Liczba sztuk"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ---------- Wspólne UI (filtry + widok + export) ----------
def render_app(df: pd.DataFrame, source_label: str, show_advanced: bool):
    if df.empty:
        st.error("Plik został wczytany, ale tabela jest pusta.")
        st.stop()

    required = ["Kategoria", "Producent", "Nazwa", "Cena", "Dostępność"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.error(f"Brak wymaganych kolumn: {', '.join(missing)}")
        st.stop()

    st.success(f"Wczytano: {source_label} • Wiersze: {len(df):,} • Kolumny: {len(df.columns):,}")

    cat_series  = df["Kategoria"].astype(str).str.strip()
    prod_series = df["Producent"].astype(str).str.strip()
    name_series = df["Nazwa"].astype(str)
    price       = pd.to_numeric(df["Cena"], errors="coerce")

    # --- Filtry podstawowe ---
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

    # Stan liczbowy (jeśli istnieje)
    stan_range = None
    if "Stan" in df.columns:
        stan_num = pd.to_numeric(df["Stan"], errors="coerce")
        if stan_num.notna().any():
            smin, smax = float(stan_num.min()), float(stan_num.max())
            c1, c2 = st.sidebar.columns(2)
            with c1:
                stan_from = st.number_input("Stan od", value=smin, min_value=0.0, step=1.0, format="%.0f")
            with c2:
                stan_to = st.number_input("Stan do", value=smax, min_value=0.0, step=1.0, format="%.0f")
            if stan_from <= stan_to:
                stan_range = (stan_from, stan_to)

    # Ilość sztuk (z XML; jeśli istnieje)
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

    # --- Filtry zaawansowane (tylko w CSV) ---
    if show_advanced:
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

    # Filtry zaawansowane tylko kiedy są włączone
    if show_advanced:
        for col, sel in {
            "ekran_dotykowy": locals().get("ekr_sel"),
            "kondycja_sprzetu": locals().get("kond_sel"),
            "procesor": locals().get("proc_sel"),
            "rodzaj_karty_graficznej": locals().get("rodz_gpu_sel"),
            "rozdzielczosc_ekranu": locals().get("rozd_sel"),
            "stan_obudowy": locals().get("stan_ob_sel"),
            "typ_pamieci_ram": locals().get("typ_ram_sel"),
        }.items():
            if sel and col in df.columns:
                cmp = df[col].astype(str).str.strip().str.casefold()
                target = pd.Series(sel).astype(str).str.strip().str.casefold().tolist()
                mask &= cmp.isin(target)
        rdzenie_sel = locals().get("rdzenie_sel")
        if rdzenie_sel and "ilosc_rdzeni" in df.columns:
            r_all = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").astype("Int64")
            mask &= r_all.isin(rdzenie_sel)
        przek_range = locals().get("przek_range")
        if przek_range is not None and "przekatna_ekranu" in df.columns:
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

    st.caption("Widok ukrywa kolumny bez wartości w aktualnym wyniku.")

# ---------- Tryb CSV ----------
def run_csv_mode():
    st.sidebar.subheader("Tryb: CSV/XLSX")
    upload = st.file_uploader("Wgraj plik (CSV/XLSX/XLS/XLSM)", type=["csv","xlsx","xls","xlsm"])

    slug = st.sidebar.text_input("Slug / hasło do CSV API (ostatni fragment URL)", value="", placeholder="np. 1234")
    if st.sidebar.button("Pobierz CSV z API"):
        if not slug.strip():
            st.sidebar.error("Podaj slug/hasło.")
            st.stop()
        url = f"https://kompre.esolu-hub.pl/api/feed/{slug.strip()}"
        with st.spinner("Pobieranie CSV..."):
            try:
                df_url = pd.read_csv(url, sep=None, engine="python")
                st.session_state["df_csv"] = df_url
            except Exception:
                st.sidebar.error("Nie udało się pobrać CSV (zły slug/hasło lub brak pliku).")
                st.stop()

    if upload is not None:
        with st.spinner("Wczytywanie pliku..."):
            df = read_any_table(upload)
        render_app(df, upload.name, show_advanced=True)
    elif "df_csv" in st.session_state:
        render_app(st.session_state["df_csv"], "URL:CSV", show_advanced=True)
    else:
        st.info("Wgraj plik albo pobierz CSV z API.")

# ---------- Tryb XML ----------
def run_xml_mode():
    st.sidebar.subheader("Tryb: XML")

    # Użytkownik podaje wyłącznie klucz/nazwę pliku; my budujemy pełny URL
    base_url = "https://marekkomp.github.io/nowe_repo10.2025_allegrocsv_na_XML/output/"
    key = st.sidebar.text_input("Nazwa pliku XML (bez .xml)", value="", placeholder="np. nazwa_pliku")
    if st.sidebar.button("Pobierz XML"):
        if not key.strip():
            st.sidebar.error("Podaj nazwę pliku.")
            st.stop()
        xml_url = f"{base_url}{key.strip()}.xml"
        with st.spinner("Pobieranie i parsowanie XML..."):
            try:
                df_xml = read_xml_build_df(xml_url)
                st.session_state["df_xml"] = df_xml
            except Exception:
                st.sidebar.error("Brak dostępu lub plik nie istnieje (zła nazwa pliku).")
                st.stop()

    if "df_xml" in st.session_state:
        # show_advanced=False dla XML → brak filtrów zaawansowanych
        render_app(st.session_state["df_xml"], "URL:XML", show_advanced=False)
    else:
        st.info("Podaj nazwę pliku (bez .xml) i pobierz.")

# ---------- Ekran wyboru ----------
mode = st.sidebar.radio("Wybierz tryb aplikacji", ["CSV/XLSX", "XML"], index=0, horizontal=True)
if mode == "CSV/XLSX":
    run_csv_mode()
else:
    run_xml_mode()
