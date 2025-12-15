import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr ofert – CSV/XLSX lub XML", layout="wide")
st.title("⚙️ Filtr ofert – CSV/XLSX lub XML")
st.caption("Wybierz tryb na górze. CSV/XLSX – pełne filtry (włączane przełącznikiem). XML – filtry podstawowe lub automatyczne filtry zaawansowane z atrybutów.")

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

@st.cache_data(show_spinner=False, ttl=1800)  # 30 minut
def read_xml_build_df(url: str) -> pd.DataFrame:
    import xml.etree.ElementTree as ET
    from urllib.request import urlopen

    raw = urlopen(url).read()
    root = ET.fromstring(raw)

    rows = []
    max_imgs = 0  # maks liczba zdjęć

    for o in root.findall(".//o"):
        oid   = (o.get("id") or "").strip()
        ourl  = (o.get("url") or "").strip()
        price = (o.get("price") or "").strip()
        avail = (o.get("avail") or "").strip()
        stock = (o.get("stock") or "").strip()
        cat   = (o.findtext("cat")  or "").strip()
        subcat = (o.findtext("subcat") or "").strip()   # <── DODANE
        name  = (o.findtext("name") or "").strip()

        # --- Opis HTML ---
        desc_html = ""
        desc_el = o.find("desc")
        if desc_el is not None:
            desc_html = "".join(
                ET.tostring(child, encoding="unicode", method="xml")
                for child in list(desc_el)
            ).strip() or (desc_el.text or "").strip()

        # --- Zdjęcia ---
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

        max_imgs = max(max_imgs, len(images))

        # --- Atrybuty ---
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
            "Podkategoria": subcat,                      # <── DODANE
            "Producent": producent,
            "Nazwa": name,
            "Cena": price.replace(",", "."),
            "Dostępność": 1 if avail in {"1","true","True","tak","TAK"} else 99,
            "Liczba sztuk": stock,
            "ID": oid,
            "URL": ourl,
            "Opis HTML": desc_html,
        }

        for i, img in enumerate(images):
            row[f"Zdjęcie {i+1}"] = img

        for k, v in extra.items():
            if k not in row:
                row[k] = v

        rows.append(row)

    df = pd.DataFrame(rows)

    # Ujednolicenie liczby kolumn zdjęć
    for i in range(1, max_imgs + 1):
        col = f"Zdjęcie {i}"
        if col not in df.columns:
            df[col] = ""

    # Typy liczbowe
    for c in ("Cena", "Dostępność", "Liczba sztuk"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    return df

def _numeric_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")

def _is_probably_numeric(s: pd.Series, min_ratio: float = 0.6) -> bool:
    sn = _numeric_series(s)
    ratio = sn.notna().mean() if len(s) else 0.0
    return ratio >= min_ratio

def _auto_advanced_filters(df: pd.DataFrame, excluded_cols: set):
    """
    Generuje UI i zwraca maskę na podstawie automatycznych filtrów:
    - dla kolumn liczbowych: zakres
    - dla tekstowych/kateg.: multiselect (jeśli liczba unikalnych <= 100)
    """
    mask = pd.Series(True, index=df.index)
    enable_adv = st.sidebar.checkbox("🔧 Włącz filtry zaawansowane (XML)", value=False)
    if not enable_adv:
        return mask

    with st.sidebar.expander("Filtry zaawansowane (XML – z atrybutów)", expanded=True):
        for col in [c for c in df.columns if c not in excluded_cols]:
            series = df[col]
            # Pomiń kolumny całkiem puste
            if not (series.astype(str).str.strip() != "").any():
                continue

            # Zbyt duża liczba kategorii -> pomiń (by nie zamulać UI)
            uniques = series.dropna().astype(str).str.strip().unique()
            if _is_probably_numeric(series):
                sn = _numeric_series(series)
                if sn.notna().any():
                    mn, mx = float(sn.min()), float(sn.max())
                    c1, c2 = st.columns(2)
                    with c1:
                        v_from = st.number_input(f"{col} od", value=mn, step=1.0, format="%.2f", key=f"{col}_from")
                    with c2:
                        v_to = st.number_input(f"{col} do", value=mx, step=1.0, format="%.2f", key=f"{col}_to")
                    if v_from <= v_to:
                        mask &= sn.between(v_from, v_to, inclusive="both")
            else:
                # Tekst/kategoria
                # Przytnij do rozsądnej liczby opcji
                if len(uniques) == 0:
                    continue
                if len(uniques) > 100:
                    # Zbyt dużo – oferuj pole tekstowe „zawiera”
                    query = st.text_input(f"{col} zawiera", value="", key=f"{col}_contains")
                    if query.strip():
                        cmp = series.astype(str).str.contains(query.strip(), case=False, na=False)
                        mask &= cmp
                else:
                    opts = sorted([str(u) for u in uniques], key=str.lower)
                    sel = st.multiselect(col, options=opts, key=f"{col}_multi")
                    if sel:
                        cmp = series.astype(str).str.strip()
                        mask &= cmp.isin(sel)

    return mask

# ---------- Wspólne UI (filtry + widok + export) ----------
def render_app(df: pd.DataFrame, source_label: str, adv_strategy: str = "csv"):
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
    status_choice = st.sidebar.radio(
        "Status produktu (kolumna 'Dostępność')",
        options=["Wszystkie", "Aktywne", "Nieaktywne"],
        index=1,
    )

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

    # Ilość sztuk (jeśli istnieje)
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

    # ---------- Filtrowanie podstawowe ----------
    mask = pd.Series(True, index=df.index)

    d = pd.to_numeric(df["Dostępność"], errors="coerce")
    if status_choice in {"Aktywne", "Nieaktywne"}:
        target = 1 if status_choice == "Aktywne" else 99
        mask &= d == target


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

        # --- DIAGNOSTYKA PO ID ---
    check_id = st.sidebar.text_input("Sprawdź ID rekordu", value="")

    def _why_excluded(row: dict) -> list:
        reasons = []

        # Status
        d = pd.to_numeric(row.get("Dostępność"), errors="coerce")
        if status_choice == "Aktywne" and d != 1:
            reasons.append("status≠1")
        if status_choice == "Nieaktywne" and d != 99:
            reasons.append("status≠99")

        # Kategoria / Producent
        if selected_cats and str(row.get("Kategoria","")).strip() not in selected_cats:
            reasons.append("kategoria nie na liście")
        if selected_prods and str(row.get("Producent","")).strip() not in selected_prods:
            reasons.append("producent nie na liście")

        # Cena
        pr = pd.to_numeric(row.get("Cena"), errors="coerce")
        if price.notna().any() and not (pd.isna(pr) or (price_from <= pr <= price_to)):
            reasons.append(f"cena poza [{price_from}, {price_to}]")

        # Stan (jeśli aktywny)
        if stan_range is not None and "Stan" in df.columns:
            stn = pd.to_numeric(row.get("Stan"), errors="coerce")
            if not (pd.isna(stn) or (stan_range[0] <= stn <= stan_range[1])):
                reasons.append(f"stan poza [{stan_range[0]}, {stan_range[1]}]")

        # Ilość (jeśli aktywna)
        if qty_range is not None and "Liczba sztuk" in df.columns:
            qv = pd.to_numeric(row.get("Liczba sztuk"), errors="coerce")
            if not (pd.isna(qv) or (qty_range[0] <= qv <= qty_range[1])):
                reasons.append(f"ilość poza [{qty_range[0]}, {qty_range[1]}]")

        # Nazwa
        if name_query.strip() and name_query.strip().lower() not in str(row.get("Nazwa","")).lower():
            reasons.append("nazwa nie zawiera frazy")

        return reasons

    if check_id.strip():
        row_df = df[df["ID"].astype(str) == check_id.strip()]
        if row_df.empty:
            st.sidebar.warning("Brak rekordu o podanym ID w surowych danych.")
        else:
            r = row_df.iloc[0].to_dict()
            reasons = _why_excluded(r)
            st.sidebar.write(f"ID {check_id}:")
            st.sidebar.write(
                f"Kategoria={r.get('Kategoria')} | Producent={r.get('Producent')} | "
                f"Cena={r.get('Cena')} | Dostępność={r.get('Dostępność')} | Sztuk={r.get('Liczba sztuk')}"
            )
            if reasons:
                st.sidebar.error("🚫 Wycięty przez: " + ", ".join(reasons))
            else:
                st.sidebar.success("✅ Przechodzi wszystkie filtry")



    # ---------- Filtry zaawansowane ----------
    if adv_strategy == "csv":
        ekr_sel = rdzenie_sel = kond_sel = proc_sel = rodz_gpu_sel = rozdz_sel = stan_ob_sel = typ_ram_sel = None
        przek_range = None
        enable_adv = st.sidebar.checkbox("🔧 Włącz filtry zaawansowane (CSV)", value=False)
        if enable_adv:
            with st.sidebar.expander("Filtry zaawansowane (laptopy)", expanded=True):
                if "ekran_dotykowy" in df.columns:
                    opts = sorted(df["ekran_dotykowy"].dropna().astype(str).str.strip().unique(), key=str.lower)
                    ekr_sel = st.multiselect("Ekran dotykowy", options=opts)

                if "ilosc_rdzeni" in df.columns:
                    rdz = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").dropna().astype(int)
                    if not rdz.empty:
                        rdzenie_sel = st.multiselect("Liczba rdzeni", options=sorted(rdz.unique().tolist()))

                if "kondycja_sprzetu" in df.columns:
                    opts = sorted(df["kondycja_sprzetu"].dropna().astype(str).str.strip().unique(), key=str.lower)
                    kond_sel = st.multiselect("Kondycja sprzętu", options=opts)

                if "procesor" in df.columns:
                    opts = sorted(df["procesor"].dropna().astype(str).str.strip().unique(), key=str.lower)
                    proc_sel = st.multiselect("Procesor", options=opts)

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
                    rodz_gpu_sel = st.multiselect("Rodzaj karty graficznej", options=opts)

                if "rozdzielczosc_ekranu" in df.columns:
                    opts = sorted(df["rozdzielczosc_ekranu"].dropna().astype(str).str.strip().unique(), key=str.lower)
                    rozdz_sel = st.multiselect("Rozdzielczość ekranu", options=opts)

                if "stan_obudowy" in df.columns:
                    opts = sorted(df["stan_obudowy"].dropna().astype(str).str.strip().unique(), key=str.lower)
                    stan_ob_sel = st.multiselect("Stan obudowy", options=opts)

                if "typ_pamieci_ram" in df.columns:
                    opts = sorted(df["typ_pamieci_ram"].dropna().astype(str).str.strip().unique(), key=str.lower)
                    typ_ram_sel = st.multiselect("Typ pamięci RAM", options=opts)

            # zastosowanie CSV-owych filtrów
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

            if 'ilosc_rdzeni' in df.columns:
                r_all = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce").astype("Int64")
                if 'rdzenie_sel' in locals() and rdzenie_sel:
                    mask &= r_all.isin(rdzenie_sel)

            if 'przekatna_ekranu' in df.columns and 'przek_range' in locals():
                pass  # utrzymane dla czytelności

            if "przekatna_ekranu" in df.columns and 'przek_range' in locals():
                p_all = pd.to_numeric(df["przekatna_ekranu"], errors="coerce")
                if 'przek_range' in locals() and przek_range is not None:
                    mask &= p_all.between(przek_range[0], przek_range[1], inclusive="both")

    elif adv_strategy == "auto":
        # z atrybutów XML
        excluded = {
            "Kategoria","Producent","Nazwa","Cena","Dostępność","Liczba sztuk","ID","URL","Opis HTML"
        }
        excluded.update([c for c in df.columns if str(c).startswith("Zdjęcie ")])
        mask &= _auto_advanced_filters(df, excluded)

    # ---------- Widok ----------
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
        render_app(df, upload.name, adv_strategy="csv")
    elif "df_csv" in st.session_state:
        render_app(st.session_state["df_csv"], "URL:CSV", adv_strategy="csv")
    else:
        st.info("Wgraj plik albo pobierz CSV z API.")

# ---------- Tryb XML ----------
def run_xml_mode():
    st.sidebar.subheader("Tryb: XML")

    source = st.sidebar.radio("Źródło XML", ["GitHub (output)", "Esolu Hub (storage/feeds)"], index=0, horizontal=True)

    if source == "GitHub (output)":
        base_url = "https://marekkomp.github.io/nowe_repo10.2025_allegrocsv_na_XML/output/"
        key = st.sidebar.text_input("Nazwa pliku XML (bez .xml)", value="", placeholder="np. nazwa_pliku")
        if st.sidebar.button("Pobierz XML z GitHub"):
            if not key.strip():
                st.sidebar.error("Podaj nazwę pliku.")
                st.stop()
            xml_url = f"{base_url}{key.strip()}.xml"
            with st.spinner("Pobieranie i parsowanie XML..."):
                try:
                    df_xml = read_xml_build_df(xml_url)
                    st.session_state["df_xml"] = df_xml
                    st.session_state["xml_label"] = "URL:XML (GitHub)"
                except Exception:
                    st.sidebar.error("Brak dostępu lub plik nie istnieje (zła nazwa pliku).")
                    st.stop()
    else:
        base_url2 = "https://kompre.esolu-hub.pl/storage/feeds/"
        key2 = st.sidebar.text_input("Nazwa pliku (bez .xml)", value="", placeholder="np. nazwa_pliku")
        if st.sidebar.button("Pobierz XML z Esolu Hub"):
            if not key2.strip():
                st.sidebar.error("Podaj nazwę pliku.")
                st.stop()
            xml_url2 = f"{base_url2}{key2.strip()}.xml"
            with st.spinner("Pobieranie i parsowanie XML..."):
                try:
                    df_xml = read_xml_build_df(xml_url2)
                    st.session_state["df_xml"] = df_xml
                    st.session_state["xml_label"] = "URL:XML (Esolu Hub)"
                except Exception:
                    st.sidebar.error("Brak dostępu lub plik nie istnieje (zła nazwa pliku).")
                    st.stop()

    if "df_xml" in st.session_state:
        # adv_strategy="auto" → automatyczne filtry z atrybutów XML (z możliwością włączenia/wyłączenia)
        render_app(st.session_state["df_xml"], st.session_state.get("xml_label","URL:XML"), adv_strategy="auto")
    else:
        st.info("Wybierz źródło, podaj nazwę pliku (bez .xml) i pobierz.")

# ---------- Ekran wyboru ----------
mode = st.sidebar.radio("Wybierz tryb aplikacji", ["CSV/XLSX", "XML"], index=0, horizontal=True)
if mode == "CSV/XLSX":
    run_csv_mode()
else:
    run_xml_mode()
