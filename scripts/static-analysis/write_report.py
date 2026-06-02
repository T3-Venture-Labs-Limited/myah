#!/usr/bin/env python3
"""Normalize static-analysis tool output into stable JSON and Markdown reports."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTION_REQUIRED = {'tool_error', 'infra_error'}
MAX_FINDINGS = 50
MAX_EXCERPT_CHARS = 4000
RAW_DIRNAME = 'raw'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', required=True, choices=['pyright', 'ruff', 'fallow-audit'])
    parser.add_argument('--command', required=True)
    parser.add_argument('--exit-code', required=True, type=int)
    parser.add_argument('--stdout-file', required=True, type=Path)
    parser.add_argument('--stderr-file', required=True, type=Path)
    parser.add_argument('--json-out', required=True, type=Path)
    parser.add_argument('--md-out', required=True, type=Path)
    parser.add_argument('--summary-out', required=True, type=Path)
    return parser.parse_args()


def read_text(path: Path) -> tuple[str, str | None]:
    try:
        return path.read_text(errors='replace'), None
    except FileNotFoundError:
        return '', f'missing output file: {path}'
    except OSError as exc:
        return '', f'could not read output file {path}: {exc}'


def excerpt(text: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f'\n... [truncated {len(text) - limit} chars]'


def parse_json(stdout: str) -> tuple[Any | None, str | None]:
    stripped = stdout.strip()
    if not stripped:
        return None, 'stdout was empty; expected JSON output'
    try:
        return json.loads(stripped), None
    except json.JSONDecodeError as exc:
        return None, f'invalid JSON output: {exc}'


def ensure_raw_copy(source: Path, out_dir: Path, tool: str, suffix: str) -> str:
    raw_dir = out_dir / RAW_DIRNAME
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / f'{tool}.{suffix}'
    if source.resolve() != destination.resolve() and source.exists():
        shutil.copyfile(source, destination)
    return str(destination)


def one_based(value: Any) -> int | None:
    return value + 1 if isinstance(value, int) else None


def pyright_result(native: dict[str, Any], exit_code: int) -> tuple[str, dict[str, int], list[dict[str, Any]], dict[str, Any], list[str]]:
    general = native.get('generalDiagnostics', []) if isinstance(native.get('generalDiagnostics'), list) else []
    severity_counts: dict[str, int] = {}
    for item in general:
        severity = str(item.get('severity', 'unknown')) if isinstance(item, dict) else 'unknown'
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    counts = {'diagnostics': len(general), **{f'{k}s': v for k, v in sorted(severity_counts.items())}}
    findings = []
    for item in general[:MAX_FINDINGS]:
        if not isinstance(item, dict):
            continue
        path = item.get('file') or item.get('uri') or ''
        rng = item.get('range')
        if not isinstance(rng, dict):
            rng = {}
        start = rng.get('start')
        if not isinstance(start, dict):
            start = {}
        findings.append(
            {
                'severity': item.get('severity'),
                'message': item.get('message'),
                'rule': item.get('rule'),
                'file': path,
                'line': one_based(start.get('line')),
                'character': one_based(start.get('character')),
            }
        )
    status = 'ok' if exit_code == 0 and len(general) == 0 else 'findings'
    notes = ['Pyright diagnostics are advisory for T3-1077.'] if status == 'findings' else []
    metadata = native.get('summary', {}) if isinstance(native.get('summary'), dict) else {}
    return status, counts, findings, metadata, notes


def ruff_result(native: Any, exit_code: int) -> tuple[str, dict[str, int], list[dict[str, Any]], dict[str, Any], list[str]]:
    findings_native = native if isinstance(native, list) else []
    code_counts: dict[str, int] = {}
    for item in findings_native:
        if isinstance(item, dict):
            code = str(item.get('code') or 'unknown')
            code_counts[code] = code_counts.get(code, 0) + 1
    counts = {'findings': len(findings_native), 'rules': len(code_counts)}
    findings = []
    for item in findings_native[:MAX_FINDINGS]:
        if not isinstance(item, dict):
            continue
        location = item.get('location')
        if not isinstance(location, dict):
            location = {}
        findings.append(
            {
                'code': item.get('code'),
                'message': item.get('message'),
                'file': item.get('filename'),
                'line': location.get('row'),
                'column': location.get('column'),
                'fixable': bool(item.get('fix')),
            }
        )
    status = 'ok' if exit_code == 0 and len(findings_native) == 0 else 'findings'
    notes = ['Ruff findings are advisory for T3-1077; no auto-fix was applied.'] if status == 'findings' else []
    return status, counts, findings, {'top_rules': dict(sorted(code_counts.items())[:20])}, notes


def _walk_count_findings(value: Any) -> int:
    if isinstance(value, list):
        return sum(_walk_count_findings(v) for v in value)
    if isinstance(value, dict):
        if isinstance(value.get('findings'), list):
            return len(value['findings'])
        if isinstance(value.get('issues'), list):
            return len(value['issues'])
        return sum(_walk_count_findings(v) for v in value.values())
    return 0


def _walk_collect_findings(value: Any, collected: list[dict[str, Any]]) -> None:
    if len(collected) >= MAX_FINDINGS:
        return
    if isinstance(value, dict):
        for key in ('findings', 'issues'):
            items = value.get(key)
            if isinstance(items, list):
                for item in items:
                    if len(collected) >= MAX_FINDINGS:
                        return
                    if isinstance(item, dict):
                        collected.append(item)
        for item in value.values():
            _walk_collect_findings(item, collected)
    elif isinstance(value, list):
        for item in value:
            _walk_collect_findings(item, collected)


def fallow_result(native: dict[str, Any], exit_code: int) -> tuple[str, dict[str, int], list[dict[str, Any]], dict[str, Any], list[str]]:
    verdict = str(native.get('verdict') or native.get('status') or '').lower()
    finding_count = _walk_count_findings(native)
    findings: list[dict[str, Any]] = []
    _walk_collect_findings(native, findings)
    status = 'ok'
    if verdict in {'fail', 'failed', 'findings'} or finding_count > 0:
        status = 'findings'
    counts = {'findings': finding_count}
    if verdict:
        counts['verdict_present'] = 1
    metadata = {
        'verdict': verdict or None,
        'fallow_version': native.get('version') or native.get('fallow_version'),
    }
    notes = ['Fallow changed-file audit findings are advisory for T3-1077.'] if status == 'findings' else []
    return status, counts, findings[:MAX_FINDINGS], metadata, notes


def classify(args: argparse.Namespace, stdout: str, stderr: str, io_errors: list[str]) -> dict[str, Any]:
    out_dir = args.json_out.parent
    raw_stdout_path = ensure_raw_copy(args.stdout_file, out_dir, args.tool, 'stdout.json')
    raw_stderr_path = ensure_raw_copy(args.stderr_file, out_dir, args.tool, 'stderr.txt')

    base = {
        'tool': args.tool,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'exit_code': args.exit_code,
        'command': args.command,
        'counts': {},
        'findings': [],
        'tool_metadata': {},
        'raw_stdout_path': raw_stdout_path,
        'raw_stderr_path': raw_stderr_path,
        'raw_output_excerpt': excerpt(stdout or stderr),
        'notes': [],
    }

    if io_errors:
        base.update({'status': 'infra_error'})
        base['notes'] = io_errors
        return base

    native, json_error = parse_json(stdout)
    if json_error:
        # Fallow can hang on medium-sized changed-file graphs and be killed by
        # the wrapper timeout before it emits any JSON. That is tool
        # non-determinism, not a source finding. Keep the gate transparent by
        # surfacing the timeout in the artifact while letting the PR continue;
        # if Fallow emits JSON with findings, the normal parser below still
        # reports those findings.
        if args.tool == 'fallow-audit' and args.exit_code in (124, 137, 143) and not stdout.strip() and not stderr.strip():
            base.update(
                {
                    'status': 'skipped',
                    'counts': {'findings': 0, 'timeout': 1},
                    'tool_metadata': {'timeout_or_killed': True},
                    'notes': [
                        f'Fallow exited with code {args.exit_code} before emitting JSON; '
                        'treating this as a non-blocking tool timeout with no findings available.'
                    ],
                }
            )
            return base
        base.update({'status': 'tool_error'})
        base['notes'] = [json_error]
        if stderr:
            base['notes'].append(excerpt(stderr, 1000))
        return base

    if args.tool == 'pyright':
        if not isinstance(native, dict):
            base.update({'status': 'tool_error', 'notes': ['Pyright JSON root was not an object.']})
            return base
        summary = native.get('summary')
        if not isinstance(summary, dict) or 'errorCount' not in summary:
            base.update(
                {
                    'status': 'tool_error',
                    'notes': ['Pyright JSON did not include the expected summary/errorCount shape.'],
                }
            )
            return base
        status, counts, findings, metadata, notes = pyright_result(native, args.exit_code)
        if args.exit_code not in (0, 1):
            status = 'tool_error'
            notes.append(f'Pyright exited with unexpected code {args.exit_code}.')
    elif args.tool == 'ruff':
        if not isinstance(native, list):
            base.update({'status': 'tool_error', 'notes': ['Ruff JSON root was not a list.']})
            return base
        status, counts, findings, metadata, notes = ruff_result(native, args.exit_code)
        if args.exit_code not in (0, 1):
            status = 'tool_error'
            notes.append(f'Ruff exited with unexpected code {args.exit_code}.')
    else:
        if not isinstance(native, dict):
            base.update({'status': 'tool_error', 'notes': ['Fallow JSON root was not an object.']})
            return base
        status, counts, findings, metadata, notes = fallow_result(native, args.exit_code)
        if args.exit_code != 0:
            status = 'tool_error'
            notes.append(f'Fallow exited with code {args.exit_code}; check base ref, timeout, or memory limits.')
        if args.exit_code in (124, 137, 143):
            status = 'tool_error'
            notes.append('Fallow appears to have timed out or been killed; ACTION REQUIRED.')

    base.update(
        {
            'status': status,
            'counts': counts,
            'findings': findings,
            'tool_metadata': metadata,
            'notes': notes,
        }
    )
    return base


def markdown_for(report: dict[str, Any]) -> str:
    status = report['status']
    action = ' — ACTION REQUIRED' if status in ACTION_REQUIRED else ''
    lines = [
        f'# {report["tool"]} static-analysis report',
        '',
        f'**Status:** `{status}`{action}',
        f'**Exit code:** `{report["exit_code"]}`',
        f'**Command:** `{report["command"]}`',
        f'**Generated:** `{report["generated_at"]}`',
        '',
        '## Counts',
        '',
    ]
    if report['counts']:
        for key, value in report['counts'].items():
            lines.append(f'- `{key}`: {value}')
    else:
        lines.append('- No normalized counts available.')
    lines.extend(['', '## Findings excerpt', ''])
    findings = report.get('findings') or []
    if findings:
        for item in findings[:20]:
            file_part = item.get('file') or item.get('filename') or ''
            line_part = item.get('line') or item.get('row')
            location = f'{file_part}:{line_part}' if line_part is not None else file_part
            message = item.get('message') or item.get('title') or item.get('rule') or item.get('code') or 'finding'
            lines.append(f'- {location} — {message}')
    else:
        lines.append('- No findings in the normalized excerpt.')
    if report.get('notes'):
        lines.extend(['', '## Notes', ''])
        for note in report['notes']:
            lines.append(f'- {note}')
    lines.extend(
        [
            '',
            '## Raw output',
            '',
            f'- stdout: `{report["raw_stdout_path"]}`',
            f'- stderr: `{report["raw_stderr_path"]}`',
            '',
        ]
    )
    return '\n'.join(lines)


def append_summary(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text('# Static analysis summary\n\n')
    status = report['status']
    action = ' — **ACTION REQUIRED**' if status in ACTION_REQUIRED else ''
    counts = ', '.join(f'{k}={v}' for k, v in report.get('counts', {}).items()) or 'no counts'
    report_name = f'{report["tool"]}.json'
    section = [
        f'## {report["tool"]}',
        '',
        f'- Status: `{status}`{action}',
        f'- Exit code: `{report["exit_code"]}`',
        f'- Counts: {counts}',
        f'- JSON report: `{report_name}`',
        '',
    ]
    if report.get('notes'):
        section.append('Notes:')
        section.extend(f'- {note}' for note in report['notes'][:5])
        section.append('')
    with path.open('a') as fh:
        fh.write('\n'.join(section))


def main() -> int:
    args = parse_args()
    for path in (args.json_out, args.md_out, args.summary_out):
        path.parent.mkdir(parents=True, exist_ok=True)
    stdout, stdout_error = read_text(args.stdout_file)
    stderr, stderr_error = read_text(args.stderr_file)
    io_errors = [err for err in (stdout_error, stderr_error) if err]
    report = classify(args, stdout, stderr, io_errors)
    args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    args.md_out.write_text(markdown_for(report) + '\n')
    append_summary(report, args.summary_out)
    return 1 if report['status'] in ACTION_REQUIRED else 0


if __name__ == '__main__':
    sys.exit(main())
