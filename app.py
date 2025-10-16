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
    index=next((i+1 for i, c in enumerate(df.columns) if c.lower() in {"stan", "aktywny", "active", "status"}), 0)
)

# Filtry wartości
cats = sorted(df[col_category].dropna().astype(str).unique().tolist())
selected_cats = st.sidebar.multiselect(
    "Filtr kategorii (pozostaw puste = wszystkie)",
    options=cats,
    help="Np. wybierz 'laptopy'."
)

# Filtr PRODUCENT (jeśli kolumna istnieje)
producer_filter_values = None
if "Producent" in df.columns:
    producers = sorted(df["Producent"].dropna().astype(str).unique().tolist())
    producer_filter_values = st.sidebar.multiselect(
        "Filtr Producent (opcjonalnie)",
        options=producers
    )

active_values_selected = None
if col_active != "(brak)":
    vals, preselect = detect_active_values(df[col_active])
    # Jeżeli kolumna to dokładnie 'Stan' (0 = niedostępny), domyślnie wybierz '1' jako aktywne
    if col_active.lower() == "stan":
        preselect = [v for v in vals if str(v).strip() == "1"] or preselect
    active_values_selected = st.sidebar.multiselect(
        "Które wartości uznawać za 'Aktywne'?",
        options=vals,
        default=preselect,
        help="Domyślnie dla kolumny 'Stan': 1=aktywne, 0=niedostępne."
    )
