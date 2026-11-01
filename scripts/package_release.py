#!/usr/bin/env python3
"""Package the built, standalone ExpObserver application using only the standard library."""
from __future__ import annotations

import argparse
import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    'README.md', 'README.zh-CN.md', 'INSTALL.md', 'CONTRIBUTING.md', 'LICENSE',
    'THIRD_PARTY_NOTICES.md', 'licenses/elkjs-LICENSE.md', 'licenses/frontend-notices.txt',
    'docs/contract.md', 'docs/observation-test.md', 'docs/screenshots/research.png', 'docs/screenshots/comparison.png',
    'docs/usage.md', 'docs/usage.zh-CN.md', 'docs/screenshots/research-workspace.png', 'docs/screenshots/node-details.png',
    'docs/screenshots/har-study-details.png',
    'docs/screenshots/platform-workspace.en.png', 'docs/screenshots/platform-details.en.png',
    'docs/screenshots/platform-compare.en.png',
    'public/assets/app-icon.svg', 'public/assets/app-icon.png', 'public/assets/favicon.ico', 'public/assets/apple-touch-icon.png',
    'examples/real-study/report.md', 'examples/real-study/continuation-review.md', 'examples/real-study/study.py',
    'examples/har-study/README.md', 'examples/har-study/load_example.py', 'examples/har-study/verify_predictions.py',
    'examples/har-study/project.en.json', 'examples/har-study/translation.en.json', 'examples/har-study/provenance.json',
    'examples/har-study/evidence/final-metrics.json', 'examples/har-study/evidence/test-predictions.csv',
    'examples/har-study/evidence/validation-comparison.csv', 'examples/har-study/evidence/inference-cost.csv',
    'examples/har-study/evidence/test-results.png', 'examples/har-study/evidence/confusion-matrices.png',
    'start.py', 'start.bat', 'start.command',
    'backend/__init__.py', 'backend/server.py', 'backend/store.py', 'backend/layout.py', 'backend/seed.py', 'backend/recovery.py', 'backend/work_sessions.py', 'backend/external_tasks.py', 'backend/question_origins.py', 'backend/host_usage.py', 'backend/execution_usage.py', 'backend/codex_usage.py',
    'skills/exp-observer/SKILL.md',
    'skills/exp-observer/agents/openai.yaml',
    'skills/exp-observer/references/records.md',
    'skills/exp-observer/scripts/exp_observer.py',
    'skills/exp-observer/scripts/bootstrap.py',
)
BUNDLED_RUNTIME = 'skills/exp-observer/assets/platform.zip'
ASSET_SUFFIXES = {'.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
                  '.avif', '.ico', '.woff', '.woff2', '.ttf', '.otf', '.wasm'}


def checked_file(root, relative):
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError(f'Release inputs must not be symlinks: {relative}')
        current = current.parent
    if not path.is_file():
        raise ValueError(f'Missing release input: {relative}. Build the frontend first with npm run build.')
    return path


def release_inputs(root):
    root = Path(root).resolve()
    inputs = {relative: checked_file(root, relative) for relative in FILES}
    inputs['dist/index.html'] = checked_file(root, 'dist/index.html')
    assets = root / 'dist' / 'assets'
    if assets.is_symlink() or not assets.is_dir():
        raise ValueError('Missing or symlinked dist/assets. Build the frontend first with npm run build.')
    for path in sorted((root / 'dist').rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f'Release inputs must not be symlinks: {relative}')
        parts = path.relative_to(root / 'dist').parts
        if any(part.startswith('.') or part in {'node_modules', '__pycache__'} for part in parts):
            raise ValueError(f'Unexpected build output: {relative}')
        if path.is_dir():
            if parts[0] != 'assets':
                raise ValueError(f'Unexpected build output: {relative}')
            continue
        if relative == 'dist/index.html':
            continue
        if not path.is_file() or parts[0] != 'assets' or path.suffix.lower() not in ASSET_SUFFIXES:
            raise ValueError(f'Unexpected build output: {relative}')
        inputs[relative] = checked_file(root, relative)
    html = inputs['dist/index.html'].read_text(encoding='utf-8')
    references = re.findall(r'''(?:src|href)=["'](/assets/[^"']+)["']''', html)
    if not any(PurePosixPath(reference).suffix == '.js' for reference in references):
        raise ValueError('dist/index.html does not reference a built JavaScript asset. Run npm run build.')
    for reference in references:
        if '..' in PurePosixPath(reference).parts or 'dist' + reference not in inputs:
            raise ValueError(f'Missing or invalid frontend asset: {reference}')
    return inputs


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def package_release(root, output):
    inputs = release_inputs(root)
    runtime = io.BytesIO()
    with zipfile.ZipFile(runtime, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, source in sorted(inputs.items()):
            if relative == 'start.py' or relative.startswith(('backend/', 'dist/', 'skills/exp-observer/', 'licenses/')) or relative in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
                archive.writestr('exp-observer/' + relative, source.read_bytes())
    runtime_bytes = runtime.getvalue()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.exp-observer-release-', suffix='.zip', dir=output.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, source in sorted(inputs.items()):
                entry = zipfile.ZipInfo('exp-observer/' + relative)
                entry.create_system = 3  # Preserve Unix permissions even when built on Windows.
                permissions = 0o755 if relative in ('start.py', 'start.command') else 0o644
                entry.external_attr = (stat.S_IFREG | permissions) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, source.read_bytes())
            archive.writestr('exp-observer/' + BUNDLED_RUNTIME, runtime_bytes)
            archive.writestr('exp-observer/' + BUNDLED_RUNTIME.replace('.zip', '.sha256'), hashlib.sha256(runtime_bytes).hexdigest() + '\n')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    output.with_name('SHA256SUMS').write_text(f'{sha256(output)}  {output.name}\n', encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.context/release/exp-observer.zip')
    args = parser.parse_args()
    try:
        output = package_release(ROOT, args.output)
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f'Cannot package ExpObserver: {error}\n')
    print(f'Created {output}')
    print(f'Checksum: {output.with_name("SHA256SUMS")}')


if __name__ == '__main__':
    main()
