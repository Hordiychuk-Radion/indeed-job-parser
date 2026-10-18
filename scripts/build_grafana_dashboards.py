from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "grafana" / "dashboards"
DS = {"type": "frser-sqlite-datasource", "uid": "jobs-sqlite"}
COUNTRY_FILTER = "(${country:sqlstring} = '__all' OR e.country_code = ${country:sqlstring})"
REQUIREMENT_FILTER = "(${requirement:sqlstring} = '__all' OR jt.requirement_type = ${requirement:sqlstring})"
ELIGIBILITY_FILTER = "(${eligibility:sqlstring} = '__all' OR e.scope_eligibility = ${eligibility:sqlstring})"
REMOTE_FILTER = "(${remote:sqlstring} = '__all' OR CAST(e.is_remote AS TEXT) = ${remote:sqlstring})"
FIT_FILTER = """(
    lower(e.title) NOT LIKE '%junior%'
    AND lower(e.title) NOT LIKE '%lead%'
    AND lower(e.title) NOT LIKE '%principal%'
    AND lower(e.title) NOT LIKE '%staff%'
    AND lower(e.title) NOT LIKE '%manager%'
    AND lower(e.title) NOT LIKE '%director%'
    AND (lower(e.title) NOT LIKE '%senior%' OR e.scope_eligibility = 'eligible')
)""".replace("\n", " ")


def target(query: str, ref: str = "A") -> dict[str, Any]:
    query = query.strip()
    return {
        "datasource": DS,
        "queryText": query,
        "rawQueryText": query,
        "queryType": "table",
        "refId": ref,
    }


def panel(
    panel_id: int,
    title: str,
    kind: str,
    query: str,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    options: dict[str, Any] | None = None,
    overrides: list[dict[str, Any]] | None = None,
    unit: str | None = None,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "color": {"mode": "palette-classic"},
        "mappings": [],
        "thresholds": {
            "mode": "absolute",
            "steps": [{"color": "green", "value": None}],
        },
    }
    if unit:
        defaults["unit"] = unit
    return {
        "id": panel_id,
        "title": title,
        "type": kind,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": options or {},
        "targets": [target(query)],
    }


def stat(panel_id: int, title: str, query: str, x: int, y: int, w: int = 6, unit: str | None = None) -> dict[str, Any]:
    return panel(
        panel_id,
        title,
        "stat",
        query,
        x,
        y,
        w,
        4,
        unit=unit,
        options={
            "colorMode": "value",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "textMode": "auto",
        },
    )


def bar(panel_id: int, title: str, query: str, x: int, y: int, w: int, h: int = 9) -> dict[str, Any]:
    return panel(
        panel_id,
        title,
        "barchart",
        query,
        x,
        y,
        w,
        h,
        options={
            "orientation": "horizontal",
            "xTickLabelRotation": 0,
            "xTickLabelSpacing": 0,
            "showValue": "always",
            "stacking": "none",
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    )


def table(panel_id: int, title: str, query: str, x: int, y: int, w: int, h: int, overrides: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return panel(
        panel_id,
        title,
        "table",
        query,
        x,
        y,
        w,
        h,
        overrides=overrides,
        options={
            "cellHeight": "sm",
            "showHeader": True,
            "sortBy": [],
        },
    )


def country_variable() -> dict[str, Any]:
    return query_variable(
        "country",
        "Country",
        "SELECT DISTINCT country_code AS __text, country_code AS __value "
        "FROM europe_jobs ORDER BY country_code",
    )


def query_variable(name: str, label: str, query: str) -> dict[str, Any]:
    full_query = (
        "SELECT 'All' AS __text, '__all' AS __value "
        f"UNION ALL SELECT * FROM ({query})"
    )
    return {
        "name": name,
        "label": label,
        "type": "query",
        "datasource": DS,
        "query": full_query,
        "definition": full_query,
        "includeAll": False,
        "multi": False,
        "refresh": 1,
        "current": {"text": "All", "value": "__all"},
    }


def dashboard(uid: str, title: str, panels: list[dict[str, Any]], variables: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": None,
        "uid": uid,
        "title": f"Jobs · {title}",
        "tags": ["indeed", "data-engineer", "europe"],
        "timezone": "browser",
        "schemaVersion": 41,
        "version": 1,
        "refresh": "",
        "editable": True,
        "graphTooltip": 1,
        "links": [
            {"title": "Overview", "type": "link", "url": "/d/jobs-overview"},
            {"title": "Technology Demand", "type": "link", "url": "/d/jobs-technology-demand"},
            {"title": "Geography", "type": "link", "url": "/d/jobs-geography"},
            {"title": "Candidate Fit", "type": "link", "url": "/d/jobs-candidate-fit"},
            {"title": "Vacancy Explorer", "type": "link", "url": "/d/jobs-vacancy-explorer"},
        ],
        "templating": {"list": variables},
        "time": {"from": "now-30d", "to": "now"},
        "timepicker": {},
        "annotations": {"list": []},
        "panels": panels,
    }


def build() -> dict[str, dict[str, Any]]:
    url_override = {
        "matcher": {"id": "byName", "options": "URL"},
        "properties": [
            {
                "id": "links",
                "value": [{"title": "Open vacancy", "url": "${__value.raw}", "targetBlank": True}],
            }
        ],
    }

    overview = dashboard(
        "jobs-overview",
        "Overview",
        [
            stat(1, "Active vacancies", f"SELECT COUNT(*) AS Vacancies FROM europe_jobs e WHERE {COUNTRY_FILTER}", 0, 0),
            stat(2, "Technologies tracked", f"SELECT COUNT(DISTINCT jt.technology) AS Technologies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER}", 6, 0),
            stat(3, "Vacancies requiring tools", f"SELECT COUNT(DISTINCT jt.job_id) AS Vacancies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND jt.requirement_type = 'required'", 12, 0),
            stat(4, "Required-tool coverage", f"SELECT ROUND(100.0 * COUNT(DISTINCT CASE WHEN jt.requirement_type = 'required' THEN e.id END) / COUNT(DISTINCT e.id), 1) AS Coverage FROM europe_jobs e LEFT JOIN job_technologies jt ON jt.job_id = e.id WHERE {COUNTRY_FILTER}", 18, 0, unit="percent"),
            bar(5, "Top technologies", f"SELECT jt.technology AS Technology, COUNT(DISTINCT jt.job_id) AS Vacancies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} GROUP BY jt.technology ORDER BY Vacancies DESC LIMIT 20", 0, 4, 10, 12),
            bar(6, "Requirement mix by technology", f"SELECT jt.technology AS Technology, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'required' THEN jt.job_id END) AS Required, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'preferred' THEN jt.job_id END) AS Preferred, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'alternative' THEN jt.job_id END) AS Alternative, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'mentioned' THEN jt.job_id END) AS Mentioned FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} GROUP BY jt.technology ORDER BY Required DESC, Preferred DESC, Mentioned DESC LIMIT 15", 10, 4, 14, 12),
            bar(7, "Demand by tool category", f"SELECT jt.category AS Category, COUNT(DISTINCT jt.job_id) AS Vacancies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} GROUP BY jt.category ORDER BY Vacancies DESC", 0, 16, 8, 11),
            bar(8, "Engineering concepts", f"SELECT jc.concept AS Concept, COUNT(DISTINCT jc.job_id) AS Vacancies FROM job_concepts jc JOIN europe_jobs e ON e.id = jc.job_id WHERE {COUNTRY_FILTER} GROUP BY jc.concept ORDER BY Vacancies DESC LIMIT 15", 8, 16, 8, 11),
            table(9, "Common required tool pairs", f"WITH required_tools AS (SELECT DISTINCT jt.job_id, jt.technology FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND jt.requirement_type = 'required') SELECT a.technology || ' + ' || b.technology AS Pair, COUNT(DISTINCT a.job_id) AS Vacancies FROM required_tools a JOIN required_tools b ON a.job_id = b.job_id AND a.technology < b.technology GROUP BY a.technology, b.technology ORDER BY Vacancies DESC, Pair LIMIT 20", 16, 16, 8, 11),
        ],
        [country_variable()],
    )

    technology = dashboard(
        "jobs-technology-demand",
        "Technology Demand",
        [
            stat(1, "Unique technologies", f"SELECT COUNT(DISTINCT jt.technology) AS Technologies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND {REQUIREMENT_FILTER}", 0, 0),
            stat(2, "Required signals", f"SELECT COUNT(*) AS Required FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND jt.requirement_type = 'required'", 6, 0),
            stat(3, "Preferred signals", f"SELECT COUNT(*) AS Preferred FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND jt.requirement_type = 'preferred'", 12, 0),
            stat(4, "Alternatives", f"SELECT COUNT(*) AS Alternatives FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND jt.requirement_type = 'alternative'", 18, 0),
            bar(5, "Top technologies", f"SELECT jt.technology AS Technology, COUNT(DISTINCT jt.job_id) AS Vacancies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND {REQUIREMENT_FILTER} GROUP BY jt.technology ORDER BY Vacancies DESC LIMIT 20", 0, 4, 12, 11),
            bar(6, "Demand by category", f"SELECT jt.category AS Category, COUNT(DISTINCT jt.job_id) AS Vacancies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND {REQUIREMENT_FILTER} GROUP BY jt.category ORDER BY Vacancies DESC", 12, 4, 12, 11),
            table(7, "Requirement mix", f"SELECT jt.technology AS Technology, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'required' THEN jt.job_id END) AS Required, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'preferred' THEN jt.job_id END) AS Preferred, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'alternative' THEN jt.job_id END) AS Alternative, COUNT(DISTINCT CASE WHEN jt.requirement_type = 'mentioned' THEN jt.job_id END) AS Mentioned FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} GROUP BY jt.technology ORDER BY Required DESC, Preferred DESC LIMIT 30", 0, 15, 14, 12),
            table(8, "Evidence samples", f"SELECT jt.technology AS Technology, jt.requirement_type AS Type, e.title AS Vacancy, e.company AS Company, jt.section AS Section, jt.evidence_text AS Evidence, e.canonical_url AS URL FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND {REQUIREMENT_FILTER} ORDER BY CASE jt.requirement_type WHEN 'required' THEN 1 WHEN 'preferred' THEN 2 WHEN 'alternative' THEN 3 ELSE 4 END, e.published_at DESC LIMIT 100", 14, 15, 10, 12, [url_override]),
        ],
        [
            country_variable(),
            query_variable("requirement", "Requirement", "SELECT DISTINCT requirement_type AS __text, requirement_type AS __value FROM job_technologies ORDER BY requirement_type"),
        ],
    )

    geography = dashboard(
        "jobs-geography",
        "Geography",
        [
            stat(1, "Countries with vacancies", f"SELECT COUNT(DISTINCT country_code) AS Countries FROM europe_jobs e WHERE {COUNTRY_FILTER}", 0, 0),
            stat(2, "Locations", f"SELECT COUNT(DISTINCT location) AS Locations FROM europe_jobs e WHERE {COUNTRY_FILTER}", 6, 0),
            stat(3, "Companies", f"SELECT COUNT(DISTINCT company) AS Companies FROM europe_jobs e WHERE {COUNTRY_FILTER}", 12, 0),
            stat(4, "Remote share", f"SELECT ROUND(100.0 * SUM(CASE WHEN is_remote = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS 'Remote %' FROM europe_jobs e WHERE {COUNTRY_FILTER}", 18, 0, unit="percent"),
            table(5, "Country summary", f"SELECT country_code AS Country, COUNT(*) AS Vacancies, COUNT(DISTINCT company) AS Companies, SUM(CASE WHEN is_remote = 1 THEN 1 ELSE 0 END) AS Remote, ROUND(100.0 * SUM(CASE WHEN is_remote = 1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS 'Remote %', SUM(CASE WHEN scope_eligibility = 'eligible' THEN 1 ELSE 0 END) AS 'Confirmed ≤5y', SUM(CASE WHEN scope_eligibility = 'unknown' THEN 1 ELSE 0 END) AS 'Needs review' FROM europe_jobs e WHERE {COUNTRY_FILTER} GROUP BY country_code ORDER BY Vacancies DESC", 0, 4, 12, 13),
            bar(6, "Remote vacancies by country", f"SELECT country_code AS Country, SUM(CASE WHEN is_remote = 1 THEN 1 ELSE 0 END) AS Remote FROM europe_jobs e WHERE {COUNTRY_FILTER} GROUP BY country_code HAVING Remote > 0 ORDER BY Remote DESC", 12, 4, 12, 13),
            table(7, "Leading technology by country", f"WITH ranked AS (SELECT e.country_code, jt.technology, COUNT(DISTINCT jt.job_id) AS vacancies, ROW_NUMBER() OVER (PARTITION BY e.country_code ORDER BY COUNT(DISTINCT jt.job_id) DESC, jt.technology) AS rn FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} GROUP BY e.country_code, jt.technology) SELECT country_code AS Country, technology AS 'Top technology', vacancies AS Vacancies FROM ranked WHERE rn = 1 ORDER BY Vacancies DESC", 0, 17, 10, 10),
            table(8, "Technology concentration", f"SELECT e.country_code AS Country, jt.technology AS Technology, COUNT(DISTINCT jt.job_id) AS Vacancies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} GROUP BY e.country_code, jt.technology ORDER BY Vacancies DESC LIMIT 100", 10, 17, 14, 10),
        ],
        [country_variable()],
    )

    candidate = dashboard(
        "jobs-candidate-fit",
        "Candidate Fit",
        [
            stat(1, "Confirmed ≤5 years", f"SELECT COUNT(*) AS Confirmed FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {FIT_FILTER} AND scope_eligibility = 'eligible'", 0, 0),
            stat(2, "Needs experience review", f"SELECT COUNT(*) AS Unknown FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {FIT_FILTER} AND scope_eligibility = 'unknown'", 6, 0),
            stat(3, "Remote matches", f"SELECT COUNT(*) AS Remote FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {FIT_FILTER} AND {ELIGIBILITY_FILTER} AND is_remote = 1", 12, 0),
            stat(4, "Companies hiring", f"SELECT COUNT(DISTINCT company) AS Companies FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {FIT_FILTER} AND {ELIGIBILITY_FILTER}", 18, 0),
            bar(5, "Eligibility by country", f"SELECT country_code AS Country, SUM(CASE WHEN scope_eligibility = 'eligible' THEN 1 ELSE 0 END) AS Confirmed, SUM(CASE WHEN scope_eligibility = 'unknown' THEN 1 ELSE 0 END) AS 'Needs review' FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {FIT_FILTER} GROUP BY country_code ORDER BY Confirmed DESC, 'Needs review' DESC", 0, 4, 12, 10),
            bar(6, "Required technologies in matching vacancies", f"SELECT jt.technology AS Technology, COUNT(DISTINCT jt.job_id) AS Vacancies FROM job_technologies jt JOIN europe_jobs e ON e.id = jt.job_id WHERE {COUNTRY_FILTER} AND {FIT_FILTER} AND {ELIGIBILITY_FILTER} AND jt.requirement_type = 'required' GROUP BY jt.technology ORDER BY Vacancies DESC LIMIT 20", 12, 4, 12, 10),
            table(7, "Candidate shortlist", f"SELECT e.title AS Title, e.company AS Company, e.country_code AS Country, e.location AS Location, CASE WHEN e.is_remote = 1 THEN 'Remote' ELSE 'On-site' END AS Mode, COALESCE(CAST(e.required_experience_years AS TEXT), 'Unknown') AS 'Years required', e.scope_eligibility AS Eligibility, e.published_at AS Published, e.canonical_url AS URL FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {FIT_FILTER} AND {ELIGIBILITY_FILTER} AND {REMOTE_FILTER} ORDER BY CASE e.scope_eligibility WHEN 'eligible' THEN 1 ELSE 2 END, e.is_remote DESC, e.published_at DESC LIMIT 250", 0, 14, 24, 14, [url_override]),
        ],
        [
            country_variable(),
            query_variable("eligibility", "Experience status", "SELECT DISTINCT scope_eligibility AS __text, scope_eligibility AS __value FROM europe_jobs ORDER BY scope_eligibility"),
            query_variable("remote", "Work mode", "SELECT 'Remote' AS __text, '1' AS __value UNION ALL SELECT 'On-site', '0'"),
        ],
    )

    explorer_query = f"""
        SELECT
            e.title AS Title,
            e.company AS Company,
            e.country_code AS Country,
            e.location AS Location,
            CASE WHEN e.is_remote = 1 THEN 'Remote' ELSE 'On-site' END AS Mode,
            e.scope_eligibility AS Eligibility,
            COALESCE(CAST(e.required_experience_years AS TEXT), 'Unknown') AS Experience,
            e.published_at AS Published,
            COALESCE((SELECT GROUP_CONCAT(x.technology, ', ') FROM (SELECT technology FROM job_technologies WHERE job_id = e.id AND requirement_type = 'required' ORDER BY technology) x), '') AS required_stack,
            COALESCE((SELECT GROUP_CONCAT(x.technology, ', ') FROM (SELECT technology FROM job_technologies WHERE job_id = e.id AND requirement_type = 'preferred' ORDER BY technology) x), '') AS preferred_stack,
            COALESCE((SELECT GROUP_CONCAT(x.technology, ', ') FROM (SELECT technology FROM job_technologies WHERE job_id = e.id AND requirement_type = 'alternative' ORDER BY technology) x), '') AS alternatives,
            COALESCE((SELECT GROUP_CONCAT(x.evidence_text, ' | ') FROM (SELECT DISTINCT evidence_text FROM job_technologies WHERE job_id = e.id AND requirement_type IN ('required', 'preferred', 'alternative') ORDER BY evidence_text) x), '') AS evidence,
            e.canonical_url AS URL
        FROM europe_jobs e
        WHERE {COUNTRY_FILTER} AND {ELIGIBILITY_FILTER} AND {REMOTE_FILTER}
        ORDER BY CASE e.scope_eligibility WHEN 'eligible' THEN 1 ELSE 2 END, e.published_at DESC
        LIMIT 500
    """
    explorer = dashboard(
        "jobs-vacancy-explorer",
        "Vacancy Explorer",
        [
            stat(1, "Visible vacancies", f"SELECT COUNT(*) AS Vacancies FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {ELIGIBILITY_FILTER} AND {REMOTE_FILTER}", 0, 0),
            stat(2, "Remote", f"SELECT COUNT(*) AS Remote FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {ELIGIBILITY_FILTER} AND {REMOTE_FILTER} AND is_remote = 1", 6, 0),
            stat(3, "Confirmed ≤5 years", f"SELECT COUNT(*) AS Confirmed FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {ELIGIBILITY_FILTER} AND {REMOTE_FILTER} AND scope_eligibility = 'eligible'", 12, 0),
            stat(4, "Companies", f"SELECT COUNT(DISTINCT company) AS Companies FROM europe_jobs e WHERE {COUNTRY_FILTER} AND {ELIGIBILITY_FILTER} AND {REMOTE_FILTER}", 18, 0),
            table(5, "Vacancies", explorer_query, 0, 4, 24, 20, [url_override]),
        ],
        [
            country_variable(),
            query_variable("eligibility", "Experience status", "SELECT DISTINCT scope_eligibility AS __text, scope_eligibility AS __value FROM europe_jobs ORDER BY scope_eligibility"),
            query_variable("remote", "Work mode", "SELECT 'Remote' AS __text, '1' AS __value UNION ALL SELECT 'On-site', '0'"),
        ],
    )

    return {
        "overview.json": overview,
        "technology-demand.json": technology,
        "geography.json": geography,
        "candidate-fit.json": candidate,
        "vacancy-explorer.json": explorer,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, payload in build().items():
        (OUT / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
