#!/usr/bin/env python3
"""
Compute student-level process indicators and basic statistical comparisons
from a CSV or XES event log.

The script is configured through config.json so it can be reused with logs
that use different field names or event labels.

Outputs CSV files that can be opened with LibreOffice/Excel:
  - raw_events.csv
  - student_indicators.csv
  - statistics_summary.csv
  - variable_guide.csv

The script uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

DEFAULT_VARIABLE_DESCRIPTIONS = {
    "total_events": (
        "Total number of logged events for the student session.",
        "Controls for overall activity; differences in specific actions may partly reflect more interactions overall.",
    ),
    "add_attribute": (
        "Number of attribute creation events.",
        "Directly linked to the claim that underperforming students over-produce or repeatedly add attributes.",
    ),
    "del_attribute": (
        "Number of attribute deletion events.",
        "Checks whether attribute identification involved revision or indecision.",
    ),
    "del_relation": (
        "Number of relation deletion events.",
        "Captures revision of relationship design, a possible source of uncertainty.",
    ),
    "cardinality_1": (
        "Number of cardinality = 1 assignments.",
        "Supports analysis of uncertainty around relationship constraints.",
    ),
    "cardinality_N": (
        "Number of cardinality = N assignments.",
        "Complements cardinality_1 for the 1/N cardinality reasoning pattern.",
    ),
    "cardinality_actions": (
        "Total cardinality actions: 0, 1, N and null.",
        "Provides an aggregate measure of cardinality editing.",
    ),
    "cardinality_switches_1N": (
        "Number of consecutive switches between cardinality 1 and N within a trace.",
        "Approximates repeated alternation between cardinality values, linked to uncertainty.",
    ),
    "link_attribute_relation": (
        "Number of links created between attributes and relations.",
        "Relevant because relationship attributes are required in the task and are discussed in the models.",
    ),
    "del_entity": (
        "Number of entity deletion events.",
        "Included for transparency because it is not consistently higher in underperforming students.",
    ),
}


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    required = ["fields", "profile_rules", "event_aliases", "selected_indicators"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"Missing required config keys: {missing}")
    for k in ["case_id", "event", "timestamp", "grade_er"]:
        if k not in cfg["fields"]:
            raise ValueError(f"Missing fields.{k} in config")
    return cfg


def local_name(tag: str) -> str:
    return tag.split("}")[-1]


def parse_xes_value(child: ET.Element) -> Any:
    value = child.attrib.get("value", "")
    tag = local_name(child.tag)
    if tag == "int":
        try:
            return int(value)
        except ValueError:
            return value
    if tag == "float":
        try:
            return float(value)
        except ValueError:
            return value
    return value


def normalise_event(raw: Dict[str, Any], fields: Dict[str, str], event_order: int = 0) -> Dict[str, Any]:
    """Return a standardised event row with canonical field names."""
    return {
        "case_id": raw.get(fields["case_id"], ""),
        "timestamp": raw.get(fields["timestamp"], ""),
        "event": raw.get(fields["event"], ""),
        "grade_er": raw.get(fields["grade_er"], ""),
        "event_order": event_order,
    }


def read_csv_events(path: str, fields: Dict[str, str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV file has no header row")
        missing = [field_name for field_name in fields.values() if field_name not in reader.fieldnames]
        if missing:
            raise ValueError(f"CSV is missing configured columns: {missing}. Available columns: {reader.fieldnames}")
        counters: Dict[str, int] = defaultdict(int)
        for raw in reader:
            case_id = str(raw.get(fields["case_id"], ""))
            order = counters[case_id]
            counters[case_id] += 1
            events.append(normalise_event(raw, fields, order))
    return events


def read_xes_events(path: str, fields: Dict[str, str]) -> List[Dict[str, Any]]:
    """Read XES as standardised event rows.

    XES has trace-level attributes (case attributes) and event-level attributes.
    To make configuration reusable, each trace attribute is exposed in three ways:
      - its original key (e.g. ``grade_er``),
      - ``case:<key>`` (e.g. ``case:grade_er``),
      - ``trace:<key>`` (e.g. ``trace:grade_er``).

    This is useful because some tools, such as pm4py data frames, prefix case
    attributes with ``case:``. Event-level attributes keep their original keys
    (e.g. ``concept:name`` and ``time:timestamp``). If a trace and an event
    share the same key, the event-level value takes precedence for the original
    key, but the prefixed case/trace aliases remain available.
    """
    events: List[Dict[str, Any]] = []
    for _, trace in ET.iterparse(path, events=("end",)):
        if local_name(trace.tag) != "trace":
            continue

        trace_attrs: Dict[str, Any] = {}
        order = 0
        for child in trace:
            name = local_name(child.tag)
            if name == "event":
                raw = dict(trace_attrs)
                for echild in child:
                    key = echild.attrib.get("key")
                    if key:
                        raw[key] = parse_xes_value(echild)
                events.append(normalise_event(raw, fields, order))
                order += 1
            else:
                key = child.attrib.get("key")
                if key:
                    value = parse_xes_value(child)
                    trace_attrs[key] = value
                    trace_attrs[f"case:{key}"] = value
                    trace_attrs[f"trace:{key}"] = value
        trace.clear()
    return events


def read_events(path: str, input_format: str, fields: Dict[str, str]) -> List[Dict[str, Any]]:
    fmt = input_format.lower()
    if fmt == "auto":
        ext = os.path.splitext(path.lower())[1]
        if ext == ".xes":
            fmt = "xes"
        elif ext == ".csv":
            fmt = "csv"
        else:
            raise ValueError("Could not infer input format from extension. Use --input-format csv or xes.")
    if fmt == "xes":
        return read_xes_events(path, fields)
    if fmt == "csv":
        return read_csv_events(path, fields)
    raise ValueError("Unsupported input format. Use csv, xes, or auto.")


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def profile_from_grade(grade: Any, n_events: int, rules: Dict[str, Any]) -> str:
    grade_f = to_float(grade)
    if grade_f is None:
        return "middle_or_unclassified"
    if grade_f > float(rules["outstanding_grade_gt"]):
        return "outstanding"
    if grade_f < float(rules["underperforming_grade_lt"]):
        if n_events >= int(rules["min_underperforming_events"]):
            return "underperforming"
        return "underperforming_excluded_short_trace"
    return "middle_or_unclassified"


def aggregate_indicators(events: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    aliases = {k: set(map(str, v)) for k, v in cfg["event_aliases"].items()}
    rules = cfg["profile_rules"]

    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ev in events:
        case_id = str(ev.get("case_id", ""))
        if case_id:
            grouped[case_id].append(ev)

    rows: List[Dict[str, Any]] = []
    for case_id, evs in sorted(grouped.items()):
        evs.sort(key=lambda e: (str(e.get("timestamp", "")), int(e.get("event_order", 0))))
        counts = Counter(str(e.get("event", "")) for e in evs)

        row: Dict[str, Any] = {
            "case_id": case_id,
            "profile": "",
            "grade_er": evs[0].get("grade_er", ""),
            "total_events": len(evs),
        }
        for var, event_names in aliases.items():
            row[var] = sum(counts[name] for name in event_names)

        # Derived indicators used in this study. They are only added if their source indicators exist.
        row["cardinality_actions"] = sum(
            row.get(v, 0) for v in ["cardinality_0", "cardinality_1", "cardinality_N", "cardinality_null"]
        )
        card_seq: List[str] = []
        for ev in evs:
            name = str(ev.get("event", ""))
            if name in aliases.get("cardinality_1", set()):
                card_seq.append("1")
            elif name in aliases.get("cardinality_N", set()):
                card_seq.append("N")
        row["cardinality_switches_1N"] = sum(1 for a, b in zip(card_seq, card_seq[1:]) if a != b)
        row["profile"] = profile_from_grade(row["grade_er"], row["total_events"], rules)
        rows.append(row)
    return rows


def percentile(sorted_values: List[float], p: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def median_q1_q3(values: List[float]) -> Tuple[float, float, float]:
    vals = sorted(float(v) for v in values)
    return (percentile(vals, 0.5), percentile(vals, 0.25), percentile(vals, 0.75))


def ranks_with_ties(values: List[float]) -> Tuple[List[float], List[int]]:
    indexed = sorted((v, i) for i, v in enumerate(values))
    ranks = [0.0] * len(values)
    tie_sizes: List[int] = []
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][0] == indexed[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for _, original_idx in indexed[i:j]:
            ranks[original_idx] = avg_rank
        if j - i > 1:
            tie_sizes.append(j - i)
        i = j
    return ranks, tie_sizes


def mann_whitney_u_p(x: List[float], y: List[float]) -> Tuple[float, float]:
    """Two-sided Mann-Whitney U with normal approximation and tie correction."""
    n1, n2 = len(x), len(y)
    if n1 == 0 or n2 == 0:
        return float("nan"), float("nan")
    combined = list(map(float, x)) + list(map(float, y))
    ranks, tie_sizes = ranks_with_ties(combined)
    r1 = sum(ranks[:n1])
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mean_u = n1 * n2 / 2.0
    n = n1 + n2
    if n <= 1:
        return u1, float("nan")
    tie_term = sum(t**3 - t for t in tie_sizes)
    variance = n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1)))
    if variance <= 0:
        return u1, float("nan")
    z = (u1 - mean_u) / math.sqrt(variance)
    p = math.erfc(abs(z) / math.sqrt(2.0))
    return u1, p


def cliffs_delta(x: List[float], y: List[float]) -> float:
    """Cliff's delta. Positive here means y tends to be larger than x."""
    if not x or not y:
        return float("nan")
    greater = 0
    lower = 0
    for xv in x:
        for yv in y:
            if yv > xv:
                greater += 1
            elif yv < xv:
                lower += 1
    return (greater - lower) / (len(x) * len(y))


def build_statistics(rows: List[Dict[str, Any]], indicators: List[str]) -> List[Dict[str, Any]]:
    if not rows:
        raise ValueError(
            "No student/case rows were produced. Check the configured case_id field. "
            "For XES files, trace attributes can be referenced as case:<key>, "
            "for example case:concept:name or case:case_id."
        )
    out_rows = [r for r in rows if r["profile"] == "outstanding"]
    under_rows = [r for r in rows if r["profile"] == "underperforming"]
    stats_rows: List[Dict[str, Any]] = []
    for ind in indicators:
        if ind not in rows[0]:
            raise ValueError(f"Selected indicator '{ind}' is not available in student indicators")
        x = [float(r[ind]) for r in out_rows]
        y = [float(r[ind]) for r in under_rows]
        med_x, q1_x, q3_x = median_q1_q3(x)
        med_y, q1_y, q3_y = median_q1_q3(y)
        u, p = mann_whitney_u_p(x, y)
        delta = cliffs_delta(x, y)
        stats_rows.append({
            "indicator": ind,
            "outstanding_n": len(x),
            "underperforming_n": len(y),
            "outstanding_median": med_x,
            "outstanding_q1": q1_x,
            "outstanding_q3": q3_x,
            "underperforming_median": med_y,
            "underperforming_q1": q1_y,
            "underperforming_q3": q3_y,
            "mann_whitney_u": u,
            "mann_whitney_p_two_sided_normal_approx": p,
            "cliffs_delta_positive_underperforming": delta,
        })
    return stats_rows


def write_csv(path: str, rows: List[Dict[str, Any]], fieldnames: List[str] | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if fieldnames is None:
        keys: List[str] = []
        seen = set()
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    keys.append(k)
                    seen.add(k)
        fieldnames = keys
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def build_variable_guide(indicators: List[str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for ind in indicators:
        meaning, why = DEFAULT_VARIABLE_DESCRIPTIONS.get(ind, ("Configured indicator.", "Included because it was selected in config.json."))
        rows.append({"variable": ind, "meaning": meaning, "why_included": why})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute process indicators and basic profile comparisons from CSV or XES logs.")
    parser.add_argument("input_log", help="Path to the input event log (.csv or .xes)")
    parser.add_argument("--config", default="config.json", help="Path to configuration JSON (default: config.json)")
    parser.add_argument("--input-format", choices=["auto", "csv", "xes"], default="auto", help="Input format (default: auto)")
    parser.add_argument("--output-dir", default="statistical_validation_outputs", help="Directory for CSV outputs")
    args = parser.parse_args()

    cfg = load_config(args.config)
    events = read_events(args.input_log, args.input_format, cfg["fields"])
    if not events:
        raise ValueError("No events were read from the input log")

    rows = aggregate_indicators(events, cfg)
    stats_rows = build_statistics(rows, cfg["selected_indicators"])

    raw_fields = ["case_id", "timestamp", "event_order", "event", "grade_er"]
    write_csv(os.path.join(args.output_dir, "raw_events.csv"), events, raw_fields)

    all_indicator_fields = list(cfg["event_aliases"].keys()) + ["cardinality_actions", "cardinality_switches_1N"]
    student_fields = ["case_id", "profile", "grade_er", "total_events"] + all_indicator_fields
    write_csv(os.path.join(args.output_dir, "student_indicators.csv"), rows, student_fields)

    stats_fields = [
        "indicator", "outstanding_n", "underperforming_n",
        "outstanding_median", "outstanding_q1", "outstanding_q3",
        "underperforming_median", "underperforming_q1", "underperforming_q3",
        "mann_whitney_u", "mann_whitney_p_two_sided_normal_approx",
        "cliffs_delta_positive_underperforming",
    ]
    write_csv(os.path.join(args.output_dir, "statistics_summary.csv"), stats_rows, stats_fields)
    write_csv(os.path.join(args.output_dir, "variable_guide.csv"), build_variable_guide(cfg["selected_indicators"]), ["variable", "meaning", "why_included"])

    print(f"Read {len(events)} events and {len(rows)} traces/students")
    print(f"Outstanding: {sum(1 for r in rows if r['profile'] == 'outstanding')}")
    print(f"Underperforming (after short-trace filter): {sum(1 for r in rows if r['profile'] == 'underperforming')}")
    print(f"Underperforming excluded as short traces: {sum(1 for r in rows if r['profile'] == 'underperforming_excluded_short_trace')}")
    print(f"Middle/unclassified: {sum(1 for r in rows if r['profile'] == 'middle_or_unclassified')}")
    print(f"CSV outputs written to: {args.output_dir}")


if __name__ == "__main__":
    main()
