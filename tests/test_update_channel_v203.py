"""Public update channel migration; no network requests."""
import hashlib

import pytest

from pdfmodder import updates_v170 as updates


def manifest():
    payload = b'MZ synthetic installer'
    return {'schema': 1, 'version': '2.0.3',
            'windows': {'filename': 'PDFModder-v2.0.3-Instalar.exe',
                        'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}}


def test_canonical_channel_uses_sat_repository():
    assert updates.REPOSITORY == 'satagrolevante/PDFModder'
    assert updates.RELEASES_URL == 'https://github.com/satagrolevante/PDFModder/releases'
    assert updates.LATEST_URL == 'https://api.github.com/repos/satagrolevante/PDFModder/releases/latest'
    assert updates.LATEST_MANIFEST_URL == (
        'https://github.com/satagrolevante/PDFModder/releases/latest/download/PDFModder-update.json')


def test_portable_manifest_constructs_canonical_installer_url():
    value = manifest()
    result = updates.validate_public_manifest(value)
    assert result == {
        'version': '2.0.3', 'filename': value['windows']['filename'],
        'size': value['windows']['size'], 'sha256': value['windows']['sha256'],
        'url': 'https://github.com/satagrolevante/PDFModder/releases/download/v2.0.3/PDFModder-v2.0.3-Instalar.exe'}
    value['repository'] = updates.REPOSITORY
    value['windows']['url'] = result['url']
    assert updates.validate_public_manifest(value) == result


@pytest.mark.parametrize('repository', ['jfeagpt/PDFModder', 'another/PDFModder'])
def test_rejects_manifest_from_another_repository(repository):
    value = manifest()
    value['repository'] = repository
    with pytest.raises(ValueError, match='dirección'):
        updates.validate_public_manifest(value)
    del value['repository']
    value['windows']['url'] = (
        f'https://github.com/{repository}/releases/download/v2.0.3/PDFModder-v2.0.3-Instalar.exe')
    with pytest.raises(ValueError, match='dirección'):
        updates.validate_public_manifest(value)
