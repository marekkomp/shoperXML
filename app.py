import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr ofert – kategoria / producent / status / cena / nazwa / stan", layout="wide")
st.title("⚙️ Filtr ofert – kategoria / producent / status / cena / nazwa / stan")
st.caption("Wgraj CSV/XLSX → wybierz status (Dostępność), kategorię, producenta, zakres cen, stan i/lub frazę w nazwie. Widok zawsze pokazuje tylko kolumny niepuste dla wyniku.")

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

# ---------- Upload ----------
upload = st.file_uploader("Wgraj plik z ofertami (CSV lub XLSX)", type=["csv", "xlsx", "xls", "xlsm"])
if not upload:
    st.info("Wgraj plik, aby kontynuować.")
    st.stop()

with st.spinner("Wczytywanie pliku..."):
    df = read_any_table(upload)

if df.empty:
    st.error("Plik został wczytany, ale tabela jest pusta.")
    st.stop()

st.success(f"Wczytano: {upload.name} • Wiersze: {len(df):,} • Kolumny: {len(df.columns):,}")

# ---------- Kolumny wymagane ----------
missing = [c for c in ["Kategoria", "Producent", "Nazwa", "Cena", "Dostępność"] if c not in df.columns]
if missing:
    st.error(f"Brak wymaganych kolumn: {', '.join(missing)}")
    st.stop()

# Normalizacja pomocnicza
df_cols = {c.lower(): c for c in df.columns}
cat_series = df[df_cols.get("kategoria", "Kategoria")].astype(str).str.strip()
prod_series = df[df_cols.get("producent", "Producent")].astype(str).str.strip()
name_series = df[df_cols.get("nazwa", "Nazwa")].astype(str)
price = pd.to_numeric(df[df_cols.get("cena", "Cena")], errors="coerce")

# ---------- Sidebar: filtry główne ----------
st.sidebar.header("Ustawienia filtrowania")

status_choice = st.sidebar.radio(
    "Status produktu (kolumna 'Dostępność')",
    options=["Wszystkie", "Aktywne (1)", "Nieaktywne (99)"],
    index=1,
)

cats_options = sorted(cat_series.unique().tolist())
selected_cats = st.sidebar.multiselect("Kategoria", options=cats_options)

prod_options = sorted(prod_series.unique().tolist())
selected_prods = st.sidebar.multiselect("Producent", options=prod_options)

min_price = float(price.min(skipna=True)) if price.notna().any() else 0.0
max_price = float(price.max(skipna=True)) if price.notna().any() else 0.0
c1, c2 = st.sidebar.columns(2)
with c1:
    price_from = st.number_input("Cena od", value=min_price, min_value=0.0, step=1.0, format="%.2f")
with c2:
    price_to = st.number_input("Cena do", value=max_price, min_value=0.0, step=1.0, format="%.2f")

# Stan (zakres liczbowy w głównych filtrach)
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

# ---------- Filtry zaawansowane (laptopy) ----------
with st.sidebar.expander("Filtry zaawansowane (laptopy)", expanded=False):
    ekr_sel = None
    if "ekran_dotykowy" in df.columns:
        ekr_vals = df["ekran_dotykowy"].dropna().astype(str).str.strip()
        ekr_opts = sorted(ekr_vals.unique().tolist(), key=lambda x: str(x).lower())
        ekr_sel = st.multiselect("ekran_dotykowy", options=ekr_opts, default=[])

    rdzenie_range = None
    if "ilosc_rdzeni" in df.columns:
        rdz = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce")
        if rdz.notna().any():
            rmin, rmax = int(rdz.min()), int(rdz.max())
            c1, c2 = st.columns(2)
            with c1:
                rd_from = st.number_input("Rdzenie od", value=float(rmin), min_value=0.0, step=1.0, format="%.0f")
            with c2:
                rd_to = st.number_input("Rdzenie do", value=float(rmax), min_value=0.0, step=1.0, format="%.0f")
            if rd_from <= rd_to:
                rdzenie_range = (int(rd_from), int(rd_to))

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
    if sel:
        cmp = df[col].astype(str).str.strip().str.casefold()
        target = pd.Series(sel).astype(str).str.strip().str.casefold().tolist()
        mask &= cmp.isin(target)

if rdzenie_range is not None and "ilosc_rdzeni" in df.columns:
    r_all = pd.to_numeric(df["ilosc_rdzeni"], errors="coerce")
    mask &= r_all.between(rdzenie_range[0], rdzenie_range[1], inclusive="both")

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
