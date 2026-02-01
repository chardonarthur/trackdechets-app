from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


GRAPHQL_ENDPOINT = "https://api.trackdechets.beta.gouv.fr"


class TrackdechetsError(RuntimeError):
    pass


@dataclass
class CompanyInfo:
    name: str
    address: str
    siret: str
    is_registered: Optional[bool]


@dataclass
class CompanySearchResult:
    name: str
    siret: str
    etat_administratif: Optional[str]


@dataclass
class RegistryExport:
    export_id: str
    status: str


@dataclass
class CompanyAccess:
    name: str
    siret: str


class TrackdechetsClient:
    def __init__(self, token: str) -> None:
        self._token = token.strip()

    def _post(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "variables": variables}
        response = requests.post(GRAPHQL_ENDPOINT, json=payload, headers=headers, timeout=60)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            snippet = response.text.strip()
            if len(snippet) > 500:
                snippet = snippet[:500] + "..."
            raise TrackdechetsError(
                f"HTTP error: {exc} | status={response.status_code} | body={snippet}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            snippet = response.text.strip()
            if len(snippet) > 500:
                snippet = snippet[:500] + "..."
            raise TrackdechetsError(f"Réponse non-JSON: {snippet}") from exc
        if "errors" in data and data["errors"]:
            messages = "; ".join(error.get("message", "Unknown error") for error in data["errors"])
            raise TrackdechetsError(messages)

        return data.get("data", {})

    def company_infos(self, siret: str) -> Optional[CompanyInfo]:
        query = """
        query CompanyInfos($siret: String!) {
          companyInfos(siret: $siret) {
            name
            address
            siret
            isRegistered
          }
        }
        """
        data = self._post(query, {"siret": siret})
        info = data.get("companyInfos")
        if not info:
            return None
        return CompanyInfo(
            name=info.get("name") or "",
            address=info.get("address") or "",
            siret=info.get("siret") or siret,
            is_registered=info.get("isRegistered"),
        )

    def search_company(self, siret: str) -> Optional[CompanySearchResult]:
        query = """
        query SearchCompanies($clue: String!) {
          searchCompanies(clue: $clue) {
            name
            siret
            etatAdministratif
          }
        }
        """
        data = self._post(query, {"clue": siret})
        companies = data.get("searchCompanies") or []
        for company in companies:
            if company.get("siret") == siret:
                return CompanySearchResult(
                    name=company.get("name") or "",
                    siret=company.get("siret") or "",
                    etat_administratif=company.get("etatAdministratif"),
                )
        return None

    def list_my_companies(self) -> List[CompanyAccess]:
        query = """
        query MyCompanies {
          me {
            companies {
              name
              siret
            }
          }
        }
        """
        data = self._post(query, {})
        me = data.get("me") or {}
        companies = me.get("companies") or []
        results: List[CompanyAccess] = []
        for company in companies:
            siret = company.get("siret") or ""
            if not siret:
                continue
            results.append(
                CompanyAccess(
                    name=company.get("name") or "",
                    siret=siret,
                )
            )
        results.sort(key=lambda item: (item.name.lower(), item.siret))
        return results

    def generate_registry_export(
        self,
        registry_type: str,
        siret: str,
        start_date: str,
        end_date: str,
        format_: str = "XLSX",
    ) -> RegistryExport:
        mutation = """
        mutation GenerateRegistryV2Export(
          $registryType: RegistryV2ExportType!,
          $format: RegistryExportFormat!,
          $siret: String!,
          $dateRange: DateFilter!
        ) {
          generateRegistryV2Export(
            registryType: $registryType,
            format: $format,
            siret: $siret,
            dateRange: $dateRange
          ) {
            id
            status
          }
        }
        """
        variants = [
            {"gte": start_date, "lte": end_date},
            {"_gte": start_date, "_lte": end_date},
        ]
        last_error: Optional[Exception] = None
        for date_range in variants:
            variables = {
                "registryType": registry_type,
                "format": format_,
                "siret": siret,
                "dateRange": date_range,
            }
            try:
                data = self._post(mutation, variables)
            except TrackdechetsError as exc:
                last_error = exc
                continue
            export = data.get("generateRegistryV2Export") or {}
            return RegistryExport(export_id=export.get("id", ""), status=export.get("status", ""))
        if last_error:
            raise last_error
        raise TrackdechetsError("Impossible de lancer l'export.")

    def get_registry_export_status(self, export_id: str) -> str:
        query = """
        query RegistryV2Export($id: ID!) {
          registryV2Export(id: $id) {
            id
            status
          }
        }
        """
        data = self._post(query, {"id": export_id})
        export = data.get("registryV2Export") or {}
        return export.get("status", "")

    def get_registry_export_download_url(self, export_id: str) -> str:
        query = """
        query RegistryV2ExportDownloadSignedUrl($exportId: String!) {
          registryV2ExportDownloadSignedUrl(exportId: $exportId) {
            signedUrl
          }
        }
        """
        data = self._post(query, {"exportId": export_id})
        payload = data.get("registryV2ExportDownloadSignedUrl") or {}
        return payload.get("signedUrl", "")

    def download_file(self, url: str) -> bytes:
        response = requests.get(url, timeout=120)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise TrackdechetsError(f"Download error: {exc}") from exc
        return response.content
