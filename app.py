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

col_active = st.sidebar.selectbox(
    "Kolumna ze statusem aktywności (np. 'Aktywny')",
    options=["(brak)"] + df.columns.tolist(),
    index=next((i+1 for i, c in enumerate(df.columns) if c.lower() in {"aktywny", "active", "status"}), 0)
)

# Filtry wartości
cats = sorted(df[col_category].dropna().astype(str).unique().tolist())
selected_cats = st.sidebar.multiselect("Filtr kategorii (pozostaw puste = wszystkie)", options=cats)

active_values_selected = None
if col_active != "(brak)":
    vals, preselect = detect_active_values(df[col_active])
    active_values_selected = st.sidebar.multiselect(
        "Które wartości uznawać za 'Aktywne'?",
        options=vals,
        default=preselect,
        help="Zaznacz, które wartości w tej kolumnie oznaczają aktywne oferty."
    )

# ---------- Filtrowanie wierszy ----------
mask = pd.Series(True, index=df.index)
if selected_cats:
    mask &= df[col_category].astype(str).isin(selected_cats)

if col_active != "(brak)" and active_values_selected is not None:
    # Traktuj puste jako nieaktywne
    active_norm = df[col_active].fillna("").astype(str).str.strip()
    mask &= active_norm.isin([str(v) for v in active_values_selected])

filtered = df.loc[mask].copy()

st.subheader("Wynik po filtrach")
st.caption("Poniżej zobaczysz TYLKO te kolumny, które mają co najmniej jedną niepustą wartość w wyfiltrowanych wierszach.")

if filtered.empty:
    st.warning("Brak wierszy po zastosowaniu filtrów.")
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

st.write(f"Wiersze: **{len(filtered_non_empty):,}** | Kolumny niepuste: **{len(non_empty_cols):,}** / {len(df.columns):,}")
st.dataframe(filtered_non_empty, use_container_width=True, height=520)

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
