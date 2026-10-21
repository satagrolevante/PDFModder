"""Retire older releases only after validating the public update channel.

By default this only writes a plan. --apply deletes release objects and their
assets in the fixed canonical repository; Git history, tags and branches are
never modified. Public download requests use a separate, unauthenticated
session. No Qt or application dependencies are needed in the publishing job.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

import requests


REPOSITORY = 'satagrolevante/PDFModder'
API = f'https://api.github.com/repos/{REPOSITORY}'
RELEASES = f'https://github.com/{REPOSITORY}/releases'
MANIFEST_NAME = 'PDFModder-update.json'
PUBLIC_MANIFEST = f'{RELEASES}/latest/download/{MANIFEST_NAME}'
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PACKAGE_BYTES = 1024 * 1024 * 1024
TAG_PATTERN = re.compile(r'v(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\Z')
SHA_PATTERN = re.compile(r'[0-9a-fA-F]{64}\Z')
DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


def version_key(tag):
    match = TAG_PATTERN.fullmatch(tag) if isinstance(tag, str) else None
    return tuple(map(int, match.groups())) if match else None


def _positive_int(value):
    return type(value) is int and value > 0


def _get_json(session, url, **kwargs):
    response = session.get(url, timeout=30, allow_redirects=False, **kwargs)
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError('GitHub devolvió una respuesta distinta de 200.')
    return response.json()


def _asset(release, filename, keep):
    assets = release.get('assets')
    if not isinstance(assets, list):
        raise ValueError('La publicación conservada no contiene una lista de archivos válida.')
    matches = [item for item in assets if isinstance(item, dict) and item.get('name') == filename]
    if len(matches) != 1:
        raise ValueError(f'Falta un único archivo de actualización: {filename}.')
    asset = matches[0]
    if (asset.get('state') != 'uploaded' or not _positive_int(asset.get('id'))
            or not _positive_int(asset.get('size'))
            or asset.get('browser_download_url') != f'{RELEASES}/download/{keep}/{filename}'):
        raise ValueError(f'El archivo publicado no está completo o no corresponde a la versión: {filename}.')
    return asset


def _public_manifest(session, keep):
    # Never use an API-provided URL or send the publishing token to downloads.
    with session.get(PUBLIC_MANIFEST, timeout=30, stream=True) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError('El manifiesto público no está disponible.')
        for item in [*response.history, response]:
            parts = urlsplit(item.url)
            if (parts.scheme != 'https' or parts.hostname not in DOWNLOAD_HOSTS
                    or parts.port not in (None, 443) or parts.username or parts.password
                    or parts.fragment or (parts.hostname == 'github.com' and
                        item.url not in (PUBLIC_MANIFEST, f'{RELEASES}/download/{keep}/{MANIFEST_NAME}'))):
                raise ValueError('El manifiesto se ha redirigido a un destino no autorizado.')
        raw = bytearray()
        started = time.monotonic()
        for chunk in response.iter_content(chunk_size=8192):
            raw.extend(chunk)
            if len(raw) > MAX_MANIFEST_BYTES or time.monotonic() - started > 45:
                raise ValueError('El manifiesto supera el tamaño o tiempo permitido.')
    return bytes(raw)


def validate_current_release(api_session, public_session, keep):
    """Verify precisely the release and manifest seen by Buscar actualizaciones."""
    release = _get_json(api_session, f'{API}/releases/latest')
    if (not isinstance(release, dict) or release.get('tag_name') != keep
            or release.get('draft') is not False or release.get('prerelease') is not False
            or not _positive_int(release.get('id'))):
        raise ValueError('La última publicación estable no es exactamente la versión que se debe conservar.')
    filename = f'PDFModder-{keep}-Instalar.exe'
    installer = _asset(release, filename, keep)
    manifest_asset = _asset(release, MANIFEST_NAME, keep)
    if manifest_asset['size'] > MAX_MANIFEST_BYTES:
        raise ValueError('El tamaño publicado del manifiesto supera el límite permitido.')
    raw = _public_manifest(public_session, keep)
    if (len(raw) != manifest_asset['size'] or manifest_asset.get('digest') !=
            'sha256:' + hashlib.sha256(raw).hexdigest()):
        raise ValueError('El tamaño o SHA-256 del manifiesto público no coincide con GitHub.')
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or type(manifest.get('schema')) is not int
            or manifest['schema'] != 1 or manifest.get('version') != keep[1:]):
        raise ValueError('El formato o la versión del manifiesto no coincide con la publicación.')
    windows = manifest.get('windows')
    if (not isinstance(windows, dict) or windows.get('filename') != filename
            or not _positive_int(windows.get('size')) or windows['size'] > MAX_PACKAGE_BYTES
            or not isinstance(windows.get('sha256'), str)
            or not SHA_PATTERN.fullmatch(windows['sha256'])
            or ('repository' in manifest and manifest['repository'] != REPOSITORY)
            or ('url' in windows and windows['url'] != installer['browser_download_url'])):
        raise ValueError('El manifiesto no contiene un instalador de Windows válido para este repositorio.')
    if (installer['size'] != windows['size'] or
            installer.get('digest') != 'sha256:' + windows['sha256'].lower()):
        raise ValueError('El tamaño o SHA-256 del instalador no coincide con el manifiesto.')
    return {
        'id': release['id'], 'tag': keep,
        'installer_id': installer['id'], 'installer_size': installer['size'],
        'installer_sha256': windows['sha256'].lower(),
        'manifest_id': manifest_asset['id'], 'manifest_size': len(raw),
        'manifest_sha256': hashlib.sha256(raw).hexdigest(),
    }


def list_releases(session):
    releases, seen = [], set()
    for page in range(1, 1001):
        items = _get_json(session, f'{API}/releases', params={'per_page': 100, 'page': page})
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError('GitHub no ha devuelto una página de publicaciones válida.')
        for item in items:
            if (not isinstance(item, dict) or not _positive_int(item.get('id'))
                    or item['id'] in seen or not isinstance(item.get('tag_name'), str)):
                raise ValueError('La lista de publicaciones contiene identificadores o etiquetas no válidos.')
            seen.add(item['id'])
            releases.append(item)
        if len(items) < 100:
            return releases
    raise ValueError('La lista de publicaciones supera el límite de paginación permitido.')


def _release_summary(release):
    assets = release.get('assets')
    if not isinstance(assets, list) or any(
            not isinstance(asset, dict) or type(asset.get('size')) is not int or asset['size'] < 0
            for asset in assets):
        raise ValueError('No se puede calcular el tamaño de los archivos de una publicación anterior.')
    return {'id': release['id'], 'tag': release['tag_name'], 'asset_count': len(assets),
            'asset_bytes': sum(asset['size'] for asset in assets)}


def cleanup_releases(api_session, public_session, *, keep, apply=False, report=None):
    """Plan once, revalidate before every DELETE and retain partial failure evidence."""
    report = report if report is not None else {}
    report.update({'repository': REPOSITORY, 'keep': keep, 'apply': apply, 'ok': False,
                   'planned_releases': [], 'deleted_releases': [],
                   'planned_remote_asset_bytes': 0, 'freed_remote_asset_bytes': 0,
                   'history_tags_branches_preserved': True,
                   'space_scope': 'GitHub release assets; not local PC disk space'})
    try:
        keep_key = version_key(keep)
        if keep_key is None:
            raise ValueError('--keep debe ser una etiqueta numérica como v3.0.6.')
        repository = _get_json(api_session, API)
        if (not isinstance(repository, dict) or repository.get('full_name') != REPOSITORY
                or repository.get('private') is not False):
            raise ValueError('El repositorio canónico no es público.')
        verified = validate_current_release(api_session, public_session, keep)
        report['verified_release'] = verified
        releases = list_releases(api_session)
        if not any(item['id'] == verified['id'] and item['tag_name'] == keep for item in releases):
            raise ValueError('La versión conservada no figura en la lista de publicaciones.')
        planned = sorted((item for item in releases
                          if version_key(item['tag_name']) is not None
                          and version_key(item['tag_name']) < keep_key
                          and item['id'] != verified['id']),
                         key=lambda item: (version_key(item['tag_name']), item['id']))
        report['planned_releases'] = [_release_summary(item) for item in planned]
        report['planned_remote_asset_bytes'] = sum(item['asset_bytes'] for item in report['planned_releases'])
        if apply:
            for item in report['planned_releases']:
                if validate_current_release(api_session, public_session, keep) != verified:
                    raise ValueError('La versión conservada o sus archivos han cambiado; se detiene la limpieza.')
                response = api_session.delete(f"{API}/releases/{item['id']}", timeout=30,
                                              allow_redirects=False)
                response.raise_for_status()
                if response.status_code != 204:
                    raise ValueError('GitHub no ha confirmado el borrado de la publicación.')
                report['deleted_releases'].append(dict(item))
                report['freed_remote_asset_bytes'] += item['asset_bytes']
            if validate_current_release(api_session, public_session, keep) != verified:
                raise ValueError('La comprobación final de la versión conservada no coincide.')
            remaining = list_releases(api_session)
            remaining_ids = {item['id'] for item in remaining}
            if verified['id'] not in remaining_ids or any(item['id'] in remaining_ids for item in planned):
                raise ValueError('GitHub no ha confirmado la lista final de publicaciones conservadas.')
            report['remaining_releases'] = [{'id': item['id'], 'tag': item['tag_name']} for item in remaining]
        else:
            report['remaining_releases'] = [{'id': item['id'], 'tag': item['tag_name']} for item in releases]
        report['ok'] = True
        return report
    except Exception as error:
        report['error'] = str(error)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep', required=True, help='Public stable release to keep, e.g. v3.0.6')
    parser.add_argument('--apply', action='store_true', help='Delete older release objects and their assets')
    parser.add_argument('--report', type=Path, required=True, help='Write the plan and actual outcome as JSON')
    arguments = parser.parse_args(argv)
    report = {}
    try:
        token = os.environ.get('GITHUB_TOKEN', '').strip()
        if arguments.apply and not token:
            raise ValueError('GITHUB_TOKEN es obligatorio para aplicar la limpieza; no se ha borrado nada.')
        with requests.Session() as api_session, requests.Session() as public_session:
            api_session.headers.update({'Accept': 'application/vnd.github+json',
                                        'X-GitHub-Api-Version': '2026-03-10',
                                        'User-Agent': 'PDFModder-release-cleanup'})
            if token:
                api_session.headers['Authorization'] = f'Bearer {token}'
            public_session.headers.update({'User-Agent': 'PDFModder-release-cleanup',
                                           'Cache-Control': 'no-cache'})
            public_session.max_redirects = 4
            cleanup_releases(api_session, public_session, keep=arguments.keep,
                             apply=arguments.apply, report=report)
        print(json.dumps({'ok': True, 'apply': arguments.apply,
                          'planned_releases': len(report['planned_releases']),
                          'deleted_releases': len(report['deleted_releases']),
                          'freed_remote_asset_bytes': report['freed_remote_asset_bytes']}))
        return 0
    except Exception as error:
        report.update({'ok': False, 'error': str(error)})
        print(f'Limpieza de publicaciones detenida: {error}', file=sys.stderr)
        return 1
    finally:
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = arguments.report.with_suffix(arguments.report.suffix + '.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(arguments.report)


if __name__ == '__main__':
    raise SystemExit(main())
