# Process indicator statistics

This package computes student-level process indicators from an event log and compares two performance-based student profiles.

It can read either:

- a CSV file, or
- an XES file.

The script is configured through a configuraction file, i.e. `config/example-config.json`, so it can be reused with logs that use different column names, XES keys, profile thresholds, or event labels.

## Files and directories

- `process_indicator_stats.py`: Python script.
- `config/example-config.json`: configuration file with field names, profile rules and event aliases.
- `data/example-dataset.csv`: example dataset in CSV format.
- `outputs/`: output directory for the generated CSV files.

## Input log structure

The script expects four logical fields:

- `case_id`: anonymised student/session identifier.
- `event`: event/action name.
- `timestamp`: timestamp or ordering value.
- `grade_er`: grade used to define performance profiles.

The actual column/key names can be changed in `config.json`:

```json
"fields": {
  "case_id": "case_id",
  "event": "event",
  "timestamp": "timestamp",
  "grade_er": "grade_er"
}
```

For XES, these names correspond to XES attribute keys. `case_id` and `grade_er` may be stored as trace attributes, while `event` and `timestamp` are normally event attributes.

## Running the script

```bash
python3 process_indicator_stats.py data/example-dataset.csv --config config/example-config.json --output-dir outputs/output-1
```

The input format is inferred from the file extension. It can also be set explicitly:

```bash
python3 process_indicator_stats.py data/my_log.xes --input-format xes --config config/example-config.json --output-dir outputs/output-1
```

## Profile rules

Student profiles and exclusion rules are defined in the used `config.json` file. The configuration file allows users to set:

- the grade threshold for the high-performing group;
- the grade threshold for the low-performing group;
- the minimum number of events required to retain low-performing traces.

These values can be changed here:

```json
"profile_rules": {
  "outstanding_grade_gt": 5,
  "underperforming_grade_lt": 1,
  "min_underperforming_events": 66
}
```

## Event aliases

The `event_aliases` section maps process indicators to one or more event labels. For example:

```json
"add_attribute": ["add attrib.", "add attribute"]
```

This means that both labels are counted as `add_attribute`.

## Outputs

The script creates four CSV files:

- `raw_events.csv`: standardised event log with only `case_id`, `timestamp`, `event_order`, `event`, and `grade_er`.
- `student_indicators.csv`: one row per student/session with computed process indicators.
- `statistics_summary.csv`: group comparison table using medians, quartiles, Mann--Whitney U and Cliff's delta.
- `variable_guide.csv`: explanation of the selected variables.

## Local files and outputs

The directories `data/`, `config/`, and `outputs/` are ignored by Git. They are intended for local datasets, custom configuration files, and generated results, respectively. This allows users to run tests without creating untracked changes in the repository.

Example datasets and default configuration files that should be versioned are kept outside these ignored directories.

## Statistical notes

The Mann--Whitney U test is computed using a two-sided normal approximation with tie correction. Cliff's delta is reported so that positive values indicate larger values for underperforming students, while negative values indicate larger values for outstanding students.

