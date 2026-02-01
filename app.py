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

DEFAULT_START_DATE = dt.date(2000, 1, 1)


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
          <small>Trackdéchets - registre réglementaire</small>
          <h1>Export BSD pour comptabilité</h1>
          <p>Générez un export réglementaire (XLSX) pour vos clients en quelques clics.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if "companies" not in st.session_state:
        st.session_state.companies = []

    if "last_export" not in st.session_state:
        st.session_state.last_export = {}

    st.caption("Chargement automatique des etablissements accessibles via ce jeton.")

    if token:
        if st.session_state.get("companies_token") != token:
            st.session_state.companies = []
            st.session_state.companies_token = token
        if not st.session_state.companies:
            client = TrackdechetsClient(token)
            try:
                st.session_state.companies = client.list_my_companies()
            except TrackdechetsError as exc:
                st.error(f"Erreur Trackdechets: {exc}")

    company_map = {
        f"{company.name} — {company.siret}": company.siret
        for company in st.session_state.companies
    }
    company_options = list(company_map.keys())
    selected_company = st.selectbox(
        "Établissement (SIRET)",
        options=company_options,
        index=None,
        placeholder="Sélectionner un établissement",
    )
    siret = ""
    if selected_company:
        siret = company_map.get(selected_company, "")

    if token and not st.session_state.companies:
        st.warning("Aucun etablissement trouve pour ce jeton.")

    with st.form("inputs"):
        st.caption("Periode appliquee: depuis le 01/01/2000 jusqu'a aujourd'hui.")
        registry_label = st.selectbox("Registre", list(REGISTRY_TYPES.keys()))
        all_types = st.checkbox("Tous les types de BSD", value=True)
        selected_types = st.multiselect(
            "Selectionner les types",
            BSD_TYPES,
            default=BSD_TYPES,
            disabled=all_types,
        )
        submit_full = st.form_submit_button("Exporter le registre complet")
        submit = st.form_submit_button("Exporter le registre")
    if not token or not siret:
        st.info("Renseignez le jeton puis selectionnez un etablissement pour continuer.")
        return

    if len(siret) != 14 or not siret.isdigit():
        st.error("Le SIRET doit contenir 14 chiffres.")
        return

    client = TrackdechetsClient(token)

    if submit_full:
        all_types = True
        selected_types = BSD_TYPES
        submit = True

    if submit:
        start_date = DEFAULT_START_DATE
        end_date = dt.date.today()
        start_iso = to_iso_datetime(start_date, end_of_day=False)
        end_iso = to_iso_datetime(end_date, end_of_day=True)
        registry_type = REGISTRY_TYPES[registry_label]
        reuse_download = False
        file_bytes = None

        with st.spinner("Génération du registre réglementaire..."):
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
                    last_export = st.session_state.get("last_export", {})
                    if (
                        last_export.get("siret") == siret
                        and last_export.get("registry_type") == registry_type
                        and last_export.get("start") == start_iso
                        and last_export.get("end") == end_iso
                        and last_export.get("id")
                    ):
                        st.info("Export recent detecte. Recuperation du dernier fichier...")
                        try:
                            download_url = client.get_registry_export_download_url(last_export["id"])
                            file_bytes = client.download_file(download_url)
                            reuse_download = True
                        except TrackdechetsError as download_exc:
                            st.warning("Export deja genere il y a moins de 5 minutes. Attendez quelques minutes puis reessayez.")
                            st.error(f"Erreur Trackdechets: {download_exc}")
                            return
                        export = type("Export", (), {"export_id": last_export["id"], "status": "SUCCESSFUL"})
                    else:
                        st.warning("Export deja genere il y a moins de 5 minutes. Attendez quelques minutes puis reessayez.")
                        return
                else:
                    st.error(f"Erreur Trackdechets: {exc}")
                    return

        if not export.export_id:
            st.error("Impossible de lancer l'export.")
            return

        st.session_state.last_export = {
            "id": export.export_id,
            "siret": siret,
            "registry_type": registry_type,
            "start": start_iso,
            "end": end_iso,
        }

        if reuse_download and file_bytes is not None:
            status = "SUCCESSFUL"
        else:
            status_placeholder = st.empty()
            status = export.status
            start_time = time.time()
            timeout_seconds = 180
            while status not in {"SUCCESSFUL", "FAILED", "CANCELED"}:
                if time.time() - start_time > timeout_seconds:
                    st.error("L'export met trop de temps. Reessayez dans quelques minutes.")
                    return
                status_placeholder.info(f"Export en cours... ({status})")
                time.sleep(5)
                try:
                    status = client.get_registry_export_status(export.export_id)
                except TrackdechetsError as exc:
                    st.error(f"Erreur Trackdechets: {exc}")
                    return
            if status in {"FAILED", "CANCELED"}:
                st.error("L'export a echoue cote Trackdechets.")
                return
            try:
                download_url = client.get_registry_export_download_url(export.export_id)
                file_bytes = client.download_file(download_url)
            except TrackdechetsError as exc:
                st.error(f"Erreur Trackdechets: {exc}")
                return

        filename = f"registre_{registry_type.lower()}_{siret}_{start_date}_{end_date}.xlsx"
        filtered_notice = ""
        df = None

        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
        except Exception:
            df = None

        if df is not None and df.empty:
            st.warning("Aucun BSD trouvé sur la période.")

        if not all_types and selected_types and df is not None:
            filtered = filter_by_bsd_type(df, selected_types)
            if len(filtered) != len(df):
                filtered_notice = " (filtré par type de BSD)"
            elif len(filtered) == len(df):
                st.warning("Impossible de filtrer par type: colonne de type BSD non trouvée.")
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                filtered.to_excel(writer, index=False, sheet_name="Registre")
            file_bytes = buffer.getvalue()

        if not file_bytes:
            st.error("Fichier vide. Vérifiez la période ou le SIRET.")
            return

        st.success(f"Export prêt{filtered_notice}.")
        st.download_button(
            label="Télécharger le registre (XLSX)",
            data=file_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
