"""Release retirement uses simulated HTTP only; no credentials or network."""
from copy import deepcopy
import hashlib
import json

import pytest
import requests

from scripts import cleanup_previous_releases as cleanup


KEEP = 'v3.0.6'


class Response:
    def __init__(self, data=None, *, status=200, raw=b'', url=cleanup.PUBLIC_MANIFEST):
        self.data = data
        self.status_code = status
        self.raw = raw
        self.url = url
        self.history = []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f'HTTP {self.status_code}')

    def json(self):
        return deepcopy(self.data)

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.raw), chunk_size):
            yield self.raw[offset:offset + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def old_release(identifier, tag, size=100, **kwargs):
    return {'id': identifier, 'tag_name': tag,
            'assets': [{'size': size}], 'draft': False, 'prerelease': False, **kwargs}


def publication(manifest_change=None):
    payload = b'MZ synthetic complete installer'
    manifest = {'schema': 1, 'version': '3.0.6',
                'windows': {'filename': f'PDFModder-{KEEP}-Instalar.exe',
                            'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}}
    if manifest_change:
        manifest_change(manifest)
    raw = json.dumps(manifest).encode('utf-8')
    assets = []
    for identifier, name, contents in [
            (100, f'PDFModder-{KEEP}-Instalar.exe', payload),
            (101, cleanup.MANIFEST_NAME, raw)]:
        assets.append({'id': identifier, 'name': name, 'state': 'uploaded', 'size': len(contents),
                       'digest': 'sha256:' + hashlib.sha256(contents).hexdigest(),
                       'browser_download_url': f'{cleanup.RELEASES}/download/{KEEP}/{name}'})
    return {'id': 306, 'tag_name': KEEP, 'draft': False, 'prerelease': False, 'assets': assets}, raw


class API:
    def __init__(self, release, previous=()):
        self.release = release
        self.releases = [release, *previous]
        self.calls = []
        self.headers = {}
        self.latest_calls = 0
        self.change_latest_at = None
        self.delete_failure = None
        self.ignore_delete = False

    def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        assert kwargs['allow_redirects'] is False
        if url == cleanup.API:
            return Response({'full_name': cleanup.REPOSITORY, 'private': False})
        if url == f'{cleanup.API}/releases/latest':
            self.latest_calls += 1
            release = deepcopy(self.release)
            if self.change_latest_at == self.latest_calls:
                release['tag_name'] = 'v3.0.7'
            return Response(release)
        assert url == f'{cleanup.API}/releases'
        params = kwargs['params']
        assert params['per_page'] == 100
        offset = (params['page'] - 1) * 100
        return Response(self.releases[offset:offset + 100])

    def delete(self, url, **kwargs):
        self.calls.append(('DELETE', url, kwargs))
        assert kwargs['allow_redirects'] is False
        identifier = int(url.rsplit('/', 1)[-1])
        if identifier == self.delete_failure:
            return Response(status=403)
        if not self.ignore_delete:
            self.releases = [item for item in self.releases if item['id'] != identifier]
        return Response(status=204)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class Public:
    def __init__(self, raw):
        self.raw = raw
        self.calls = []
        self.headers = {}
        self.url = cleanup.PUBLIC_MANIFEST

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert url == cleanup.PUBLIC_MANIFEST
        assert kwargs['stream'] is True
        assert 'Authorization' not in self.headers
        return Response(raw=self.raw, url=self.url)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def clients(previous=(), manifest_change=None):
    release, raw = publication(manifest_change)
    return API(release, previous), Public(raw)


def deletes(api):
    return [call[1] for call in api.calls if call[0] == 'DELETE']


def test_dry_run_keeps_newer_and_unknown_tags_but_plans_older_drafts_and_prereleases():
    previous = [old_release(1, 'v2.0.0', 200), old_release(2, 'v3.0.5', 300, draft=True),
                old_release(3, 'v3.0.4', 400, prerelease=True), old_release(4, 'v3.0.10'),
                old_release(5, 'backup'), old_release(6, 'v3.0.6-custom')]
    api, public = clients(previous)
    report = cleanup.cleanup_releases(api, public, keep=KEEP)
    assert report['ok'] is True
    assert [item['id'] for item in report['planned_releases']] == [1, 3, 2]
    assert report['planned_remote_asset_bytes'] == 900
    assert report['freed_remote_asset_bytes'] == 0
    assert report['deleted_releases'] == []
    assert deletes(api) == []


def test_apply_deletes_only_planned_release_objects_rechecks_latest_and_retains_history():
    api, public = clients([old_release(1, 'v3.0.4', 40), old_release(2, 'v3.0.5', 50),
                           old_release(9, 'v3.0.10', 100), old_release(10, 'notes', 20)])
    report = cleanup.cleanup_releases(api, public, keep=KEEP, apply=True)
    assert deletes(api) == [f'{cleanup.API}/releases/1', f'{cleanup.API}/releases/2']
    assert api.latest_calls == 4  # initial, before each deletion, final verification
    assert len(public.calls) == 4
    assert report['freed_remote_asset_bytes'] == 90
    assert [item['id'] for item in report['remaining_releases']] == [306, 9, 10]
    assert report['history_tags_branches_preserved'] is True
    assert report['ok'] is True
    assert all('/git/' not in url and '/tags' not in url for _, url, _ in api.calls)


def test_pagination_does_not_miss_releases_after_first_hundred():
    previous = [old_release(number, f'v2.0.{number}') for number in range(1, 102)]
    api, public = clients(previous)
    report = cleanup.cleanup_releases(api, public, keep=KEEP)
    pages = [kwargs['params']['page'] for _, url, kwargs in api.calls
             if url == f'{cleanup.API}/releases']
    assert pages == [1, 2]
    assert len(report['planned_releases']) == 101
    assert deletes(api) == []


@pytest.mark.parametrize('field,value', [
    ('tag_name', 'v3.0.5'), ('draft', True), ('prerelease', True), ('id', True)])
def test_unpublished_or_wrong_latest_never_deletes(field, value):
    api, public = clients([old_release(1, 'v3.0.5')])
    api.release[field] = value
    report = {}
    with pytest.raises(ValueError):
        cleanup.cleanup_releases(api, public, keep=KEEP, apply=True, report=report)
    assert deletes(api) == []
    assert report['ok'] is False
    assert report['deleted_releases'] == []


@pytest.mark.parametrize('asset_index,field,value', [
    (0, 'state', 'new'), (1, 'state', 'new'), (0, 'size', 999),
    (0, 'digest', 'sha256:' + '0' * 64), (0, 'digest', None),
    (1, 'size', 1000), (1, 'digest', 'sha256:' + '0' * 64),
    (1, 'digest', None), (0, 'id', True),
    (0, 'browser_download_url', 'https://github.com/other/project/releases/download/v3.0.6/app.exe')])
def test_incomplete_or_inconsistent_assets_never_delete(asset_index, field, value):
    api, public = clients([old_release(1, 'v3.0.5')])
    api.release['assets'][asset_index][field] = value
    with pytest.raises(ValueError):
        cleanup.cleanup_releases(api, public, keep=KEEP, apply=True)
    assert deletes(api) == []


@pytest.mark.parametrize('change', [
    lambda value: value.update(schema=True),
    lambda value: value.update(version='3.0.5'),
    lambda value: value.update(repository='other/PDFModder'),
    lambda value: value['windows'].update(filename='unexpected.exe'),
    lambda value: value['windows'].update(size=True),
    lambda value: value['windows'].update(size=0),
    lambda value: value['windows'].update(size=cleanup.MAX_PACKAGE_BYTES + 1),
    lambda value: value['windows'].update(sha256='invalid'),
    lambda value: value['windows'].update(url='https://example.org/app.exe'),
])
def test_invalid_manifest_never_deletes_even_when_its_public_digest_matches(change):
    api, public = clients([old_release(1, 'v3.0.5')], manifest_change=change)
    with pytest.raises(ValueError):
        cleanup.cleanup_releases(api, public, keep=KEEP, apply=True)
    assert deletes(api) == []


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'oversized', 'redirect'])
def test_manifest_download_or_inventory_failures_never_delete(fault):
    api, public = clients([old_release(1, 'v3.0.5')])
    if fault == 'missing':
        api.release['assets'].pop()
    elif fault == 'duplicate':
        api.release['assets'].append(deepcopy(api.release['assets'][0]))
    elif fault == 'oversized':
        public.raw = b' ' * (cleanup.MAX_MANIFEST_BYTES + 1)
    else:
        public.url = 'https://example.org/manifest.json'
    with pytest.raises(ValueError):
        cleanup.cleanup_releases(api, public, keep=KEEP, apply=True)
    assert deletes(api) == []


def test_changed_latest_aborts_before_next_delete_and_records_partial_progress():
    api, public = clients([old_release(1, 'v3.0.4', 40), old_release(2, 'v3.0.5', 50)])
    api.change_latest_at = 3
    report = {}
    with pytest.raises(ValueError):
        cleanup.cleanup_releases(api, public, keep=KEEP, apply=True, report=report)
    assert deletes(api) == [f'{cleanup.API}/releases/1']
    assert report['freed_remote_asset_bytes'] == 40
    assert [item['id'] for item in report['deleted_releases']] == [1]
    assert report['ok'] is False
    assert 'error' in report


def test_delete_failure_stops_without_touching_later_releases():
    api, public = clients([old_release(1, 'v3.0.3', 30), old_release(2, 'v3.0.4', 40),
                           old_release(3, 'v3.0.5', 50)])
    api.delete_failure = 2
    report = {}
    with pytest.raises(requests.HTTPError):
        cleanup.cleanup_releases(api, public, keep=KEEP, apply=True, report=report)
    assert deletes(api) == [f'{cleanup.API}/releases/1', f'{cleanup.API}/releases/2']
    assert report['freed_remote_asset_bytes'] == 30
    assert [item['id'] for item in report['deleted_releases']] == [1]
    assert report['ok'] is False


def test_final_inventory_must_confirm_deletions():
    api, public = clients([old_release(1, 'v3.0.5')])
    api.ignore_delete = True
    with pytest.raises(ValueError, match='lista final'):
        cleanup.cleanup_releases(api, public, keep=KEEP, apply=True)


def test_main_requires_ci_token_for_apply_and_still_writes_error_report(tmp_path, monkeypatch):
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.setattr(cleanup.requests, 'Session', lambda: pytest.fail('No network session expected'))
    destination = tmp_path / 'report.json'
    assert cleanup.main(['--keep', KEEP, '--apply', '--report', str(destination)]) == 1
    assert json.loads(destination.read_text())['ok'] is False


def test_main_public_download_has_no_token_and_report_contains_no_credentials(tmp_path, monkeypatch, capsys):
    api, public = clients([old_release(1, 'v3.0.5')])
    sessions = iter([api, public])
    monkeypatch.setattr(cleanup.requests, 'Session', lambda: next(sessions))
    monkeypatch.setenv('GITHUB_TOKEN', 'synthetic-secret-must-stay-private')
    destination = tmp_path / 'report.json'
    assert cleanup.main(['--keep', KEEP, '--report', str(destination)]) == 0
    assert api.headers['Authorization'] == 'Bearer synthetic-secret-must-stay-private'
    assert 'Authorization' not in public.headers
    assert 'synthetic-secret' not in destination.read_text()
    assert 'synthetic-secret' not in str(capsys.readouterr())
    assert deletes(api) == []
