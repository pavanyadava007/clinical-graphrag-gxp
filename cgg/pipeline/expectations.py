"""Data-quality expectations for the silver layer.

Each expectation is a Spark SQL boolean expression that must be TRUE for a row to pass.
action = "quarantine": failing rows are moved to the quarantine table with the expectation name.
action = "warn": failing rows stay in silver, the count is reported.
The same idea as Delta Live Tables expectations (expect / expect_or_drop), written in plain PySpark.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Expectation:
    name: str
    sql: str
    action: str  # quarantine | warn
    urs: str


LABEL_EXPECTATIONS = [
    Expectation("set_id_present", "set_id IS NOT NULL AND length(set_id) = 36", "quarantine", "URS-004"),
    Expectation("version_positive", "version IS NOT NULL AND version > 0", "quarantine", "URS-004"),
    Expectation("effective_date_valid", "effective_date IS NOT NULL AND effective_date <= current_date()",
                "quarantine", "URS-004"),
    Expectation("brand_and_generic_present", "brand_name IS NOT NULL AND generic_name IS NOT NULL",
                "quarantine", "URS-004"),
    Expectation("manufacturer_present", "manufacturer IS NOT NULL", "quarantine", "URS-004"),
    Expectation("rx_label", "product_type = 'HUMAN PRESCRIPTION DRUG'", "quarantine", "URS-004"),
    Expectation("epc_in_scope", "size(epc_in_scope) > 0", "quarantine", "URS-004"),
    Expectation("has_indications_section", "array_contains(sections_present, 'indications_and_usage')",
                "warn", "URS-004"),
    Expectation("route_present", "size(routes) > 0", "warn", "URS-004"),
]

SECTION_EXPECTATIONS = [
    Expectation("section_text_not_empty", "text IS NOT NULL AND length(text) >= 20", "quarantine", "URS-004"),
    Expectation("section_text_not_truncated", "length(text) < 400000", "quarantine", "URS-004"),
]


def split_sql(expectations: list[Expectation]) -> tuple[str, str]:
    """Return (quarantine_condition, failed_names_expr) as Spark SQL strings."""
    q = [e for e in expectations if e.action == "quarantine"]
    pass_all = " AND ".join(f"coalesce(({e.sql}), false)" for e in q) or "true"
    names = ", ".join(f"CASE WHEN NOT coalesce(({e.sql}), false) THEN '{e.name}' END" for e in q)
    failed = f"filter(array({names}), x -> x IS NOT NULL)" if q else "array()"
    return pass_all, failed
