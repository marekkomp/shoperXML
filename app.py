import io
from io import BytesIO
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Filtr parametrów wg kategorii", layout="wide")
st.title("⚙️ Filtr parametrów wg kategorii / aktywności")
st.caption("Wgraj CSV/XLSX → wybierz kolumnę z kategorią i statusem aktywności → zobacz TYLKO te kolumny, które nie są puste dla wyfiltrowanych wierszy. Następnie pobierz wynik (CSV/XLSX).")

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

@st.cache_data(show_spinner=False)
def detect_active_values(series: pd.Series):
    # Zgromadź unikalne wartości tekstowe (niepuste)
    vals = (
        series.dropna()
        .astype(str)
        .str.strip()
        .replace({"True": "1", "False": "0"}, regex=False)
        .unique()
        .tolist()
    )
    # Podpowiedzi najczęściej spotykane jako AKTYWNE
    common_active = {"1", "TAK", "Tak", "tak", "true", "True", "ACTIVE", "Active", "aktywny", "Aktywny"}
    preselect = [v for v in vals if str(v) in common_active]
    # jeśli nic nie pasuje, domyślnie wybierz wszystkie niepuste
    if not preselect:
        preselect = vals
    return vals, preselect

# ---------- UI: Upload ----------
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

# ---------- Sidebar: konfiguracja kolumn ----------
st.sidebar.header("Ustawienia")
col_category = st.sidebar.selectbox(
    "Kolumna z kategorią (np. 'Kategoria' / 'Category')",
    options=df.columns.tolist(),
    index=next((i for i, c in enumerate(df.columns) if c.lower() in {"kategoria", "category", "kategoria allegro"}), 0)
)

# --- Status wg kolumny "Dostępność" (1 = aktywny, 99 = nieaktywny)
status_filter = st.sidebar.radio(
    "Status produktu (kolumna 'Dostępność')",
    options=["Wszystkie", "Aktywne (1)", "Nieaktywne (99)"],
    index=1,
    help="Aktywne → Dostępność == 1, Nieaktywne → Dostępność == 99"
)

# Tryb dopasowania
st.sidebar.subheader("Tryb dopasowania")
normalize_case = st.sidebar.checkbox("Ignoruj wielkość liter / spacje (trim)", value=True)
cat_contains = st.sidebar.checkbox("Kategoria: dopasuj 'zawiera' (nie tylko równe)", value=False)
prod_contains = st.sidebar.checkbox("Producent: dopasuj 'zawiera' (nie tylko równe)", value=False)

# Filtry wartości
base_cats = df[col_category].dropna().astype(str).str.strip()
if normalize_case:
    base_cats = base_cats.str.casefold()

cats_unique = sorted(base_cats.unique().tolist())
selected_cats = st.sidebar.multiselect(
    "Filtr kategorii (pozostaw puste = wszystkie)",
    options=cats_unique,
    help="Np. wybierz 'laptopy'. Użyj przełączników powyżej, by włączyć dopasowanie 'zawiera'."
)

# Filtr PRODUCENT (jeśli kolumna istnieje)
producer_filter_values = None
producer_series = None
if "Producent" in df.columns:
    producer_series = df["Producent"].dropna().astype(str).str.strip()
    if normalize_case:
        producer_series = producer_series.str.casefold()
    producers = sorted(producer_series.unique().tolist())
    producer_filter_values = st.sidebar.multiselect(
        "Filtr Producent (opcjonalnie)", options=producers
    )

# Szukaj po nazwie (substring)
name_query = st.sidebar.text_input("Szukaj w 'Nazwa'", value="", help="Wpisz fragment nazwy (bez rozróżniania wielkości liter)"),
        help="Domyślnie dla kolumny 'Stan': 1=aktywne, 0=niedostępne."
    )

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
if name_query.strip():
    names = df["Nazwa"].astype(str)
    mask &= names.str.contains(name_query.strip(), case=False, na=False)

filtered = df.loc[mask].copy()

# Diagnostyka
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

st.subheader("Wynik po filtrach")
st.caption("Poniżej zobaczysz TYLKO te kolumny, które mają co najmniej jedną niepustą wartość w wyfiltrowanych wierszach.")

if filtered.empty:
    st.warning("Brak wierszy po zastosowaniu filtrów.")
    st.info(f"Spróbuj: wyłączyć filtr Producent, sprawdzić dokładne brzmienie kategorii (użyj 'zawiera'), albo tymczasowo odznaczyć aktywność.")
    st.stop()

# ---------- Wybór kolumn niepustych ----------
# Definicja "puste": NaN lub ciąg pusty/whitespace po konwersji do stringa
non_empty_cols = []
for c in filtered.columns:
    s = filtered[c]
    # True jeśli istnieje jakakolwiek niepusta wartość w kolumnie
    has_value = s.notna() & ~s.astype(str).str.strip().eq("")
    if has_value.any():
        non_empty_cols.append(c)

filtered_non_empty = filtered[non_empty_cols]

# Wybór kolumn do wyświetlenia
preferred_cols = [
    "ID","Nazwa","SKU","EAN","Producent","Kategoria","Cena","Dostępność","Stan","URL"
]
available_defaults = [c for c in preferred_cols if c in filtered_non_empty.columns]
selected_cols_show = st.sidebar.multiselect(
    "Kolumny do pokazania",
    options=non_empty_cols,
    default=available_defaults if available_defaults else non_empty_cols[:min(20, len(non_empty_cols))]
)

view_df = filtered_non_empty[selected_cols_show] if selected_cols_show else filtered_non_empty

st.write(f"Wiersze: **{len(view_df):,}** | Kolumny widoczne: **{len(view_df.columns):,}** (z niepustych: {len(non_empty_cols):,} / {len(df.columns):,})")
st.dataframe(view_df, use_container_width=True, height=520)

# ---------- Pobieranie ----------
st.divider()
st.subheader("Pobierz wynik")

c1, c2, c3 = st.columns(3)

with c1:
    csv_bytes = filtered_non_empty.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="⬇️ CSV – tylko kolumny niepuste",
        data=csv_bytes,
        file_name="oferty_niepuste_kolumny.csv",
        mime="text/csv",
    )

with c2:
    xlsx_bytes = to_excel_bytes(filtered_non_empty)
    st.download_button(
        label="⬇️ XLSX – tylko kolumny niepuste",
        data=xlsx_bytes,
        file_name="oferty_niepuste_kolumny.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

with c3:
    # pełny widok: oryginalne kolumny, ale tylko wyfiltrowane wiersze
    xlsx_full = to_excel_bytes(filtered)
    st.download_button(
        label="⬇️ XLSX – pełne kolumny (filtrowane wiersze)",
        data=xlsx_full,
        file_name="oferty_pelne_kolumny_filtrowane.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

# ---------- Dodatkowe opcje ----------
with st.expander("Zaawansowane: ustawienia 'pustości' i numerów/zer"):
    st.markdown(
        """
        **Definicja pustej komórki** w tej aplikacji to: `NaN` **lub** pusty ciąg / same spacje po konwersji do tekstu.
        Wartość `0` (zero) **nie** jest traktowana jako pusta.
        Jeśli potrzebujesz innej logiki (np. traktować `0` jako puste w kolumnie *Cena promocyjna*), daj znać – łatwo dodać przełącznik per kolumnę.
        """
    )

st.caption("Autor: szablon do GitHub/Streamlit Cloud. Nie modyfikuje źródłowego pliku – działa tylko na widoku/eksporcie.")
