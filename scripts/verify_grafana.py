from __future__ import annotations

import json
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:3001"
EXPECTED_UIDS = {
    "jobs-overview",
    "jobs-technology-demand",
    "jobs-geography",
    "jobs-candidate-fit",
    "jobs-vacancy-explorer",
}


def request(path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def main() -> None:
    health = request("/api/health")
    assert health["database"] == "ok", health

    datasource = request("/api/datasources/uid/jobs-sqlite")
    assert datasource["type"] == "frser-sqlite-datasource", datasource
    assert datasource["jsonData"]["path"] == "/data/jobs.db", datasource

    search = request(f"/api/search?{urlencode({'query': 'Jobs ·'})}")
    uids = {item["uid"] for item in search if item.get("type") == "dash-db"}
    assert uids == EXPECTED_UIDS, {"expected": sorted(EXPECTED_UIDS), "actual": sorted(uids)}

    sql = "SELECT COUNT(*) AS vacancies FROM europe_jobs"
    result = request(
        "/api/ds/query",
        {
            "from": "0",
            "to": "9999999999999",
            "queries": [
                {
                    "refId": "A",
                    "datasource": {
                        "type": "frser-sqlite-datasource",
                        "uid": "jobs-sqlite",
                    },
                    "queryType": "table",
                    "queryText": sql,
                    "rawQueryText": sql,
                }
            ],
        },
    )
    frame = result["results"]["A"]["frames"][0]
    fields = frame["schema"]["fields"]
    values = frame["data"]["values"]
    field_index = next(index for index, field in enumerate(fields) if field["name"] == "vacancies")
    vacancy_count = values[field_index][0]
    assert vacancy_count > 0, vacancy_count

    for uid in sorted(EXPECTED_UIDS):
        dashboard = request(f"/api/dashboards/uid/{uid}")["dashboard"]
        assert dashboard["uid"] == uid
        assert dashboard["panels"]

    print(
        json.dumps(
            {
                "status": "ok",
                "grafana": health["version"],
                "datasource": datasource["name"],
                "dashboards": len(uids),
                "vacancies": vacancy_count,
                "overview": f"{BASE_URL}/d/jobs-overview",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
