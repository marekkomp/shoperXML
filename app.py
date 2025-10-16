import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr ofert – kategoria / producent / status / cena / nazwa", layout="wide")
st.title("⚙️ Filtr ofert – kategoria / producent / status / cena / nazwa")
st.caption("Wgraj CSV/XLSX → wybierz status (Dostępność), kategorię, producenta, zakres cen i/lub frazę w nazwie. Widok zawsze pokazuje tylko kolumny niepuste dla wyniku.")

# ---------- Helpers ----------
@st.cache_data(show_spinner=False)
def read_any_table(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(file)
    # CSV/TSV — autodetekcja separatora
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

# Normalizacja pomocnicza (bez kontrolek – zawsze aktywna)
cat_series_orig = df["Kategoria"].astype(str).str.strip()
prod_series_orig = df["Producent"].astype(str).str.strip()
name_series_orig = df["Nazwa"].astype(str)

cat_series_norm = cat_series_orig.str.casefold()
prod_series_norm = prod_series_orig.str.casefold()

# Cena na float (kropka w danych)
price = pd.to_numeric(df["Cena"], errors="coerce")

# ---------- Sidebar: filtry ----------
st.sidebar.header("Ustawienia filtrowania")

# Status wg Dostępność: 1 aktywny, 99 nieaktywny
status_choice = st.sidebar.radio(
    "Status produktu (kolumna 'Dostępność')",
    options=["Wszystkie", "Aktywne (1)", "Nieaktywne (99)"],
    index=1,
)

# Kategoria – bez wyboru kolumny, z unikalnych wartości
cats_options = sorted(cat_series_orig.unique().tolist())
selected_cats = st.sidebar.multiselect("Kategoria", options=cats_options)

# Producent
prod_options = sorted(prod_series_orig.unique().tolist())
selected_prods = st.sidebar.multiselect("Producent", options=prod_options)

# Zakres cen (od–do)
min_price = float(pd.Series(price).min(skipna=True)) if price.notna().any() else 0.0
max_price = float(pd.Series(price).max(skipna=True)) if price.notna().any() else 0.0
c1, c2 = st.sidebar.columns(2)
with c1:
    price_from = st.number_input("Cena od", value=min_price, min_value=0.0, step=1.0, format="%.2f")
with c2:
    price_to = st.number_input("Cena do", value=max_price, min_value=0.0, step=1.0, format="%.2f")
if price_from > price_to:
    st.sidebar.warning("'Cena od' nie może być większa niż 'Cena do'.")

# Szukaj po nazwie
name_query = st.sidebar.text_input("Szukaj w 'Nazwa'", value="")

# ---------- Filtrowanie ----------
mask = pd.Series(True, index=df.index)

# Status
if status_choice != "Wszystkie":
    d = pd.to_numeric(df["Dostępność"], errors="coerce")
    if "Aktywne" in status_choice:
        mask &= (d == 1)
    else:
        mask &= (d == 99)

# Kategoria (normalizacja case/trim w porównaniu)
if selected_cats:
    selected_norm = pd.Series(selected_cats).astype(str).str.strip().str.casefold().tolist()
    mask &= cat_series_norm.isin(selected_norm)

# Producent
if selected_prods:
    selected_p_norm = pd.Series(selected_prods).astype(str).str.strip().str.casefold().tolist()
    mask &= prod_series_norm.isin(selected_p_norm)

# Cena
if price.notna().any():
    mask &= price.between(price_from, price_to, inclusive="both")

# Nazwa (substring, case-insensitive)
if name_query.strip():
    mask &= name_series_orig.str.contains(name_query.strip(), case=False, na=False)

filtered = df.loc[mask].copy()

# ---------- Wynik i widok (zawsze tylko kolumny niepuste) ----------
if filtered.empty:
    st.warning("Brak wierszy po zastosowaniu filtrów.")
    st.stop()

# Lista kolumn z co najmniej jedną niepustą wartością
non_empty_cols = []
for c in filtered.columns:
    s = filtered[c]
    has_value = s.notna() & ~s.astype(str).str.strip().eq("")
    if has_value.any():
        non_empty_cols.append(c)

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
    st.download_button(
        label="⬇️ CSV – widok (kolumny niepuste)",
        data=csv_bytes,
        file_name="oferty_widok_niepuste.csv",
        mime="text/csv",
    )
with c2:
    xlsx_bytes = to_excel_bytes(view_df)
    st.download_button(
        label="⬇️ XLSX – widok (kolumny niepuste)",
        data=xlsx_bytes,
        file_name="oferty_widok_niepuste.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.caption("Normalizacja (trim + case-insensitive) jest zawsze aktywna. Widok ukrywa kolumny bez wartości w aktualnym wyniku.")
