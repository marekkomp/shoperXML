import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr parametrów wg kategorii / aktywności", layout="wide")
st.title("⚙️ Filtr parametrów wg kategorii / aktywności")
st.caption("Wgraj CSV/XLSX → wybierz kolumnę z kategorią oraz status wg 'Dostępność' → opcjonalnie producent i fraza w nazwie → zobacz pasujące pozycje. Dodatkowo możesz wyświetlać tylko kolumny niepuste.")

# ---------- Helpers ----------
@st.cache_data(show_spinner=False)
def read_any_table(file) -> pd.DataFrame:
    name = file.name.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(file)
    # CSV/TSV — spróbuj autodetekcji separatora
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

# ---------- Sidebar: konfiguracja ----------
st.sidebar.header("Ustawienia")

# Kolumna z kategorią
col_category = st.sidebar.selectbox(
    "Kolumna z kategorią (np. 'Kategoria' / 'Category')",
    options=df.columns.tolist(),
    index=next((i for i, c in enumerate(df.columns) if c.lower() in {"kategoria", "category", "kategoria allegro"}), 0)
)

# Tryb dopasowań / normalizacja
st.sidebar.subheader("Tryb dopasowania")
normalize_case = st.sidebar.checkbox("Ignoruj wielkość liter / spacje (trim)", value=True)
cat_contains = st.sidebar.checkbox("Kategoria: dopasuj 'zawiera' (nie tylko równe)", value=False)
prod_contains = st.sidebar.checkbox("Producent: dopasuj 'zawiera' (nie tylko równe)", value=False)

# Status wg kolumny DOSTĘPNOŚĆ (1 aktywny, 99 nieaktywny)
status_filter = st.sidebar.radio(
    "Status produktu (kolumna 'Dostępność')",
    options=["Wszystkie", "Aktywne (1)", "Nieaktywne (99)"],
    index=1,
    help="Aktywne → Dostępność == 1, Nieaktywne → Dostępność == 99"
)

# Listy wartości dla filtrów
base_cats = df[col_category].dropna().astype(str).str.strip()
if normalize_case:
    base_cats = base_cats.str.casefold()

cats_unique = sorted(base_cats.unique().tolist())
selected_cats = st.sidebar.multiselect(
    "Filtr kategorii (pozostaw puste = wszystkie)",
    options=cats_unique,
    help="Np. wybierz 'laptopy'. Możesz też włączyć dopasowanie 'zawiera'."
)

# Producent
producer_filter_values = None
producer_series = None
if "Producent" in df.columns:
    producer_series = df["Producent"].dropna().astype(str).str.strip()
    if normalize_case:
        producer_series = producer_series.str.casefold()
    producers = sorted(producer_series.unique().tolist())
    producer_filter_values = st.sidebar.multiselect("Filtr Producent (opcjonalnie)", options=producers)

# Szukaj w nazwie
name_query = st.sidebar.text_input("Szukaj w 'Nazwa'", value="", help="Fragment nazwy, bez rozróżniania wielkości liter")

# ---------- Filtrowanie wierszy ----------
mask = pd.Series(True, index=df.index)

# Kategoria
if selected_cats:
    cat_series = df[col_category].astype(str).str.strip()
    if normalize_case:
        cat_series = cat_series.str.casefold()
    if cat_contains:
        m = pd.Series(False, index=df.index)
        for val in selected_cats:
            m |= cat_series.str.contains(str(val), na=False)
        mask &= m
    else:
        mask &= cat_series.isin(selected_cats)

# Producent
if producer_filter_values is not None and len(producer_filter_values) > 0 and producer_series is not None:
    prod_series_full = df["Producent"].astype(str).str.strip()
    series_cmp = prod_series_full.str.casefold() if normalize_case else prod_series_full
    if prod_contains:
        m = pd.Series(False, index=df.index)
        for val in producer_filter_values:
            m |= series_cmp.str.contains(str(val), na=False)
        mask &= m
    else:
        mask &= series_cmp.isin(producer_filter_values)

# Status wg 'Dostępność'
if "Dostępność" in df.columns and status_filter != "Wszystkie":
    dost = pd.to_numeric(df["Dostępność"], errors="coerce")
    if "Aktywne" in status_filter:
        mask &= (dost == 1)
    elif "Nieaktywne" in status_filter:
        mask &= (dost == 99)

# Szukaj po nazwie
if name_query.strip() and "Nazwa" in df.columns:
    names = df["Nazwa"].astype(str)
    mask &= names.str.contains(name_query.strip(), case=False, na=False)

filtered = df.loc[mask].copy()

# ---------- Diagnostyka ----------
with st.expander("🔎 Diagnostyka filtrów"):
    st.write({
        "wybrane_kategorie": selected_cats,
        "producent_wybrane": producer_filter_values,
        "status": status_filter,
        "zapytanie_nazwa": name_query,
        "pozostalo_wierszy": int(len(filtered)),
    })
    st.write("Przykładowe wartości kolumn:")
    st.write({
        "Kategoria_top10": df[col_category].dropna().astype(str).str.strip().unique()[:10],
        "Producent_top10": (df["Producent"].dropna().astype(str).str.strip().unique()[:10] if "Producent" in df.columns else []),
        "Dostepnosc_top10": (pd.to_numeric(df["Dostępność"], errors="coerce").dropna().unique()[:10] if "Dostępność" in df.columns else []),
    })

if filtered.empty:
    st.warning("Brak wierszy po zastosowaniu filtrów.")
    st.info("Spróbuj: wyłączyć filtr Producent, sprawdzić dokładne brzmienie kategorii (włącz 'zawiera'), lub zmienić status Aktywne/Nieaktywne.")
    st.stop()

# ---------- Kolumny niepuste i widok ----------
# Definicja "puste": NaN lub pusty string po trimie
non_empty_cols = []
for c in filtered.columns:
    s = filtered[c]
    has_value = s.notna() & ~s.astype(str).str.strip().eq("")
    if has_value.any():
        non_empty_cols.append(c)

preferred_cols = [
    "ID","Nazwa","SKU","EAN","Producent","Kategoria","Cena","Dostępność","Stan","URL"
]
available_defaults = [c for c in preferred_cols if c in filtered.columns and c in non_empty_cols]

st.subheader("Wynik")
show_only_nonempty = st.checkbox("Pokaż tylko kolumny niepuste", value=True)
cols_source = non_empty_cols if show_only_nonempty else filtered.columns.tolist()

selected_cols_show = st.multiselect(
    "Kolumny do pokazania",
    options=cols_source,
    default=available_defaults if available_defaults else cols_source[:min(25, len(cols_source))]
)

view_df = filtered[selected_cols_show] if selected_cols_show else filtered[cols_source]

st.write(f"Wiersze: **{len(view_df):,}** | Kolumny widoczne: **{len(view_df.columns):,}**")
st.dataframe(view_df, use_container_width=True, height=560)

# ---------- Pobieranie ----------
st.divider()
st.subheader("Pobierz wynik")

c1, c2, c3 = st.columns(3)
with c1:
    csv_bytes = view_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="⬇️ CSV – widok (bieżące kolumny)",
        data=csv_bytes,
        file_name="oferty_widok.csv",
        mime="text/csv",
    )
with c2:
    xlsx_bytes = to_excel_bytes(view_df)
    st.download_button(
        label="⬇️ XLSX – widok (bieżące kolumny)",
        data=xlsx_bytes,
        file_name="oferty_widok.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with c3:
    xlsx_full = to_excel_bytes(filtered)
    st.download_button(
        label="⬇️ XLSX – pełne kolumny (po filtrach)",
        data=xlsx_full,
        file_name="oferty_pelne_po_filtrach.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.caption("Aplikacja nie modyfikuje oryginalnego pliku. Wszystkie wcięcia w kodzie to spacje (4) – bez tabulatorów.")
