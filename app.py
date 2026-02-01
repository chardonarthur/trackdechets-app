from __future__ import annotations

import datetime as dt
import io
import os
import time
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd
import streamlit as st

from trackdechets_client import TrackdechetsClient, TrackdechetsError


BSD_TYPES = [
    "BSDD",
    "BSDA",
    "BSFF",
    "BSVHU",
    "BSDASRI",
    "BSPAOH",
]

REGISTRY_TYPES = {
    "Registre sortant (émetteur)": "OUTGOING",
    "Registre entrant (réception)": "INCOMING",
}

BSD_TYPE_COLUMN_CANDIDATES = [
    "bsdtype",
    "bsd_type",
    "type de bordereau",
    "type de bsd",
    "type bordereau",
    "type de déchet",
    "type",
]

DEFAULT_START_DATE = dt.date(2001, 1, 1)


def default_date_range() -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    start = today.replace(day=1)
    return start, today


def to_iso_datetime(date_value: dt.date, end_of_day: bool) -> str:
    if end_of_day:
        dt_value = dt.datetime.combine(date_value, dt.time(23, 59, 59))
    else:
        dt_value = dt.datetime.combine(date_value, dt.time(0, 0, 0))
    return dt_value.isoformat() + "Z"


def normalize_header(header: str) -> str:
    return header.strip().lower()


def find_bsd_type_column(columns: Iterable[str]) -> Optional[str]:
    normalized = {normalize_header(col): col for col in columns}
    for candidate in BSD_TYPE_COLUMN_CANDIDATES:
        if candidate in normalized:
            return normalized[candidate]
    return None


def filter_by_bsd_type(df: pd.DataFrame, selected_types: List[str]) -> pd.DataFrame:
    column = find_bsd_type_column(df.columns)
    if not column:
        return df
    return df[df[column].astype(str).isin(selected_types)]


def require_password() -> bool:
    app_password = os.getenv("APP_PASSWORD", "")
    if not app_password:
        return True
    if "auth_ok" not in st.session_state:
        st.session_state.auth_ok = False
    if st.session_state.auth_ok:
        return True
    st.subheader("Acces securise")
    entered = st.text_input("Mot de passe", type="password")
    if st.button("Se connecter"):
        if entered == app_password:
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    st.stop()


def app_style() -> None:
    st.markdown(
        """
        <style>
          @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600&family=Source+Sans+3:wght@400;600&display=swap');
          html, body, [class*="css"]  {
            font-family: "Source Sans 3", "Segoe UI", "Arial", sans-serif;
          }
          h1, h2, h3, h4 {
            font-family: "Source Serif 4", "Georgia", serif;
          }
          [data-testid="stHeader"], [data-testid="stToolbar"], footer {
            visibility: hidden;
            height: 0;
          }
          .block-container {
            padding-top: 2.5rem;
            padding-bottom: 2rem;
          }
          .hero {
            background: linear-gradient(115deg, #f5f0ea 0%, #f8faf4 100%);
            border: 1px solid #e6dfd7;
            border-radius: 16px;
            padding: 1.5rem 1.75rem;
            margin-bottom: 1.5rem;
          }
          .hero small {
            color: #6b5f55;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }
          .hero h1 {
            margin-top: 0.5rem;
            margin-bottom: 0.4rem;
          }
          .hero p {
            margin: 0;
            color: #4f463f;
          }
          .status-card {
            background: #ffffff;
            border-radius: 12px;
            border: 1px solid #ece6df;
            padding: 1rem 1.2rem;
            margin-top: 0.8rem;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )





def main() -> None:
    st.set_page_config(page_title="Export BSD", layout="centered")
    app_style()

    if not require_password():
        return

    st.markdown(
        """
        <div class="hero">
          <small>Trackdechets - registre reglementaire</small>
          <h1>Export BSD pour comptabilite</h1>
          <p>Generez un export reglementaire (XLSX) pour vos clients en quelques clics.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    token = st.text_input("Jeton Trackdechets (Bearer)", type="password")
    if not token:
        st.info("Renseignez le jeton pour continuer.")
        return

    if "companies" not in st.session_state:
        st.session_state.companies = []
    if "companies_token" not in st.session_state:
        st.session_state.companies_token = ""
    if "registry_cache" not in st.session_state:
        st.session_state.registry_cache = {}
    if "last_export_by_type" not in st.session_state:
        st.session_state.last_export_by_type = {}

    st.subheader("Etablissement")
    st.caption("Liste chargee automatiquement depuis votre jeton.")

    if st.session_state.companies_token != token:
        st.session_state.companies = []
        st.session_state.registry_cache = {}
        st.session_state.companies_token = token

    if not st.session_state.companies:
        client = TrackdechetsClient(token)
        try:
            st.session_state.companies = client.list_my_companies()
        except TrackdechetsError as exc:
            st.error(f"Erreur Trackdechets: {exc}")
            return

    company_map = {
        f"{company.name} - {company.siret}": company.siret
        for company in st.session_state.companies
    }
    company_options = list(company_map.keys())
    selected_company = st.selectbox(
        "Etablissement (SIRET)",
        options=company_options,
        index=None,
        placeholder="Selectionner un etablissement",
    )
    siret = ""
    if selected_company:
        siret = company_map.get(selected_company, "")

    if not siret:
        st.info("Selectionnez un etablissement pour continuer.")
        return

    if len(siret) != 14 or not siret.isdigit():
        st.error("Le SIRET doit contenir 14 chiffres.")
        return

    client = TrackdechetsClient(token)

    full_start = DEFAULT_START_DATE
    full_end = dt.date.today()
    start_iso = to_iso_datetime(full_start, end_of_day=False)
    end_iso = to_iso_datetime(full_end, end_of_day=True)
    cache_prefix = f"{siret}|{start_iso}|{end_iso}"

    def fetch_registry(registry_type: str) -> dict:
        cache_key = f"{cache_prefix}|{registry_type}"
        if cache_key in st.session_state.registry_cache:
            return st.session_state.registry_cache[cache_key]

        label = "entrant" if registry_type == "INCOMING" else "sortant"
        file_bytes = None
        reuse_download = False

        with st.spinner(f"Preparation du registre {label}..."):
            try:
                export = client.generate_registry_export(
                    registry_type=registry_type,
                    siret=siret,
                    start_date=start_iso,
                    end_date=end_iso,
                )
            except TrackdechetsError as exc:
                message = str(exc)
                if "moins de 5 minutes" in message:
                    last_export = st.session_state.last_export_by_type.get(registry_type, {})
                    if (
                        last_export.get("siret") == siret
                        and last_export.get("start") == start_iso
                        and last_export.get("end") == end_iso
                        and last_export.get("id")
                    ):
                        st.info("Export recent detecte. Recuperation du fichier...")
                        try:
                            download_url = client.get_registry_export_download_url(last_export["id"])
                            file_bytes = client.download_file(download_url)
                            reuse_download = True
                            export = type("Export", (), {"export_id": last_export["id"], "status": "SUCCESSFUL"})
                        except TrackdechetsError as download_exc:
                            st.error(f"Erreur Trackdechets: {download_exc}")
                            return {"error": True}
                    else:
                        st.warning("Export deja genere il y a moins de 5 minutes. Attendez puis reessayez.")
                        return {"error": True}
                else:
                    st.error(f"Erreur Trackdechets: {exc}")
                    return {"error": True}

        if not export.export_id:
            st.error("Impossible de lancer l'export.")
            return {"error": True}

        st.session_state.last_export_by_type[registry_type] = {
            "id": export.export_id,
            "siret": siret,
            "start": start_iso,
            "end": end_iso,
        }

        if not reuse_download:
            status_placeholder = st.empty()
            status = export.status
            start_time = time.time()
            timeout_seconds = 180
            while status not in {"SUCCESSFUL", "FAILED", "CANCELED"}:
                if time.time() - start_time > timeout_seconds:
                    st.error("L'export met trop de temps. Reessayez dans quelques minutes.")
                    return {"error": True}
                status_placeholder.info("Export en cours sur Trackdechets...")
                time.sleep(5)
                try:
                    status = client.get_registry_export_status(export.export_id)
                except TrackdechetsError as exc:
                    st.error(f"Erreur Trackdechets: {exc}")
                    return {"error": True}
            if status in {"FAILED", "CANCELED"}:
                st.error("L'export a echoue cote Trackdechets.")
                return {"error": True}
            try:
                download_url = client.get_registry_export_download_url(export.export_id)
                file_bytes = client.download_file(download_url)
            except TrackdechetsError as exc:
                st.error(f"Erreur Trackdechets: {exc}")
                return {"error": True}

        df = None
        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
        except Exception:
            df = None

        rows = len(df) if df is not None else 0
        payload = {
            "bytes": file_bytes,
            "rows": rows,
            "registry_type": registry_type,
            "df": df,
        }
        st.session_state.registry_cache[cache_key] = payload
        return payload

    st.subheader("Registres")
    col_in, col_out = st.columns(2)

    with col_in:
        incoming = fetch_registry("INCOMING")
        if incoming.get("error"):
            st.error("Registre entrant indisponible.")
        else:
            st.metric("Registre entrant", incoming.get("rows", 0))

    with col_out:
        outgoing = fetch_registry("OUTGOING")
        if outgoing.get("error"):
            st.error("Registre sortant indisponible.")
        else:
            st.metric("Registre sortant", outgoing.get("rows", 0))

    if incoming.get("error") or outgoing.get("error"):
        return

    st.subheader("Export")
    export_start, export_end = st.date_input(
        "Periode d'export",
        value=(full_start, full_end),
        format="DD/MM/YYYY",
    )

    if export_start > export_end:
        st.error("La date de debut doit preceder la date de fin.")
        return

    def filter_by_date(df: pd.DataFrame, start_date: dt.date, end_date: dt.date) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        candidates = [
            "date",
            "date de creation",
            "date de reception",
            "date de prise en charge",
            "date d'envoi",
            "date d'emission",
            "createdat",
            "date creation",
        ]
        normalized = {col.strip().lower(): col for col in df.columns}
        date_col = None
        for candidate in candidates:
            if candidate in normalized:
                date_col = normalized[candidate]
                break
        if not date_col:
            return df
        series = pd.to_datetime(df[date_col], errors="coerce")
        mask = (series.dt.date >= start_date) & (series.dt.date <= end_date)
        return df.loc[mask]

    col_in_exp, col_out_exp = st.columns(2)

    with col_in_exp:
        df_in = incoming.get("df")
        filtered_in = filter_by_date(df_in, export_start, export_end)
        filename = f"registre_entrant_{siret}_{export_start}_{export_end}.xlsx"
        buffer = io.BytesIO()
        if filtered_in is not None:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                filtered_in.to_excel(writer, index=False, sheet_name="Registre")
        st.download_button(
            label="Exporter registre entrant",
            data=buffer.getvalue(),
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with col_out_exp:
        df_out = outgoing.get("df")
        filtered_out = filter_by_date(df_out, export_start, export_end)
        filename = f"registre_sortant_{siret}_{export_start}_{export_end}.xlsx"
        buffer = io.BytesIO()
        if filtered_out is not None:
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                filtered_out.to_excel(writer, index=False, sheet_name="Registre")
        st.download_button(
            label="Exporter registre sortant",
            data=buffer.getvalue(),
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
