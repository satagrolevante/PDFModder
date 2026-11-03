"""Local, bounded handwritten signatures; no certificate or PDF operation."""
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
import warnings

from PIL import Image


MAX_SIGNATURE_BYTES = 4 * 1024 * 1024
MAX_SIGNATURE_PIXELS = 8_000_000
MAX_SIGNATURE_SIDE = 4096
MAX_SIGNATURES = 128
MAX_MANIFEST_BYTES = 128 * 1024
MAX_LIBRARY_BYTES = 32 * 1024 * 1024
_IDENTIFIER = re.compile(r'^[a-f0-9]{32}$')


def normalise_manual_signature_png_v317(data):
    """Return cropped black RGBA artwork without carrying image metadata.

    Alpha is preserved, including antialiased edges. An opaque image is not
    interpreted as handwriting: the library only accepts transparent artwork.
    Limits apply before decoding pixels, both for saved and incoming artwork.
    """
    if not isinstance(data, (bytes, bytearray)) or not 0 < len(data) <= MAX_SIGNATURE_BYTES:
        raise ValueError('La firma debe ser una imagen PNG de hasta 4 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                width, height = source.size
                if (source.format != 'PNG' or getattr(source, 'n_frames', 1) != 1
                        or not 0 < width <= MAX_SIGNATURE_SIDE
                        or not 0 < height <= MAX_SIGNATURE_SIDE
                        or width * height > MAX_SIGNATURE_PIXELS):
                    raise ValueError()
                source.load()
                image = source.convert('RGBA')
        alpha = image.getchannel('A')
        low, high = alpha.getextrema()
        bounds = alpha.getbbox()
        if not bounds or high == 0:
            raise ValueError('Dibuja una firma antes de guardarla.')
        if low == 255:
            raise ValueError('La firma debe tener fondo transparente.')
        alpha = alpha.crop(bounds)
        # Give narrow strokes a little space without retaining a white canvas.
        width, height = alpha.size
        if width + 8 > MAX_SIGNATURE_SIDE or height + 8 > MAX_SIGNATURE_SIDE:
            raise ValueError('La firma supera las dimensiones admitidas.')
        result = Image.new('RGBA', (width + 8, height + 8), (0, 0, 0, 0))
        ink = Image.new('RGBA', alpha.size, (0, 0, 0, 255))
        ink.putalpha(alpha)
        result.paste(ink, (4, 4))
        output = BytesIO()
        result.save(output, format='PNG')
        return output.getvalue()
    except ValueError as exc:
        if str(exc):
            raise
        raise ValueError('La imagen de firma no es un PNG transparente compatible.') from None
    except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('No se puede leer la imagen de firma.') from None


# The shorter American-spelling alias is shared with the certificate appearance.
normalize_signature_png_v317 = normalise_manual_signature_png_v317


def _name(value):
    if not isinstance(value, str):
        raise ValueError('Escribe un nombre para la firma.')
    value = ' '.join(value.split())
    if not value or len(value) > 100 or any(ord(char) < 32 for char in value):
        raise ValueError('El nombre de la firma debe tener entre 1 y 100 caracteres.')
    return value


def _identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError('La firma seleccionada no es válida.')
    return value


def _atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.signature-', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class SignatureLibraryV317:
    """A per-user directory with named, transparent, reusable signatures.

    Only validated identifiers produce artwork paths. A broken manifest is
    reported instead of silently overwriting the user's existing collection.
    """
    def __init__(self, directory):
        self.directory = Path(directory)
        self.manifest = self.directory / 'signatures.json'

    def _records(self):
        if not self.manifest.exists():
            return []
        try:
            if self.manifest.is_symlink() or self.manifest.stat().st_size > MAX_MANIFEST_BYTES:
                raise ValueError()
            value = json.loads(self.manifest.read_text(encoding='utf-8'))
            records = value['signatures']
            if value.get('schema') != 1 or not isinstance(records, list) or len(records) > MAX_SIGNATURES:
                raise ValueError()
            result, seen = [], set()
            for record in records:
                identifier = _identifier(record['id'])
                name = _name(record['name'])
                if identifier in seen:
                    raise ValueError()
                seen.add(identifier)
                result.append({'id': identifier, 'name': name})
            return result
        except (OSError, UnicodeError, ValueError, KeyError, TypeError):
            raise ValueError('No se puede leer la biblioteca de firmas; sus archivos se conservan.') from None

    def _write(self, records):
        data = json.dumps({'schema': 1, 'signatures': records}, ensure_ascii=False, indent=2)
        _atomic_bytes(self.manifest, (data + '\n').encode('utf-8'))

    def _entry(self, record):
        path = self.directory / (_identifier(record['id']) + '.png')
        try:
            if path.is_symlink() or path.stat().st_size > MAX_SIGNATURE_BYTES:
                raise ValueError()
            png = normalise_manual_signature_png_v317(path.read_bytes())
            with Image.open(BytesIO(png)) as image:
                width, height = image.size
            return dict(record, png=png, width_px=width, height_px=height)
        except (OSError, ValueError):
            raise ValueError('No se puede leer la firma «' + record['name'] + '»; sus archivos se conservan.') from None

    def entries(self):
        result, total = [], 0
        for record in self._records():
            entry = self._entry(record)
            total += len(entry['png'])
            if total > MAX_LIBRARY_BYTES:
                raise ValueError('La biblioteca de firmas supera el límite de 32 MB.')
            result.append(entry)
        return result

    def get(self, identifier):
        _identifier(identifier)
        record = next((record for record in self._records() if record['id'] == identifier), None)
        if record is None:
            raise ValueError('La firma seleccionada ya no está en la biblioteca.')
        return self._entry(record)

    def add(self, name, png):
        name = _name(name)
        png = normalise_manual_signature_png_v317(png)
        records = self._records()
        if len(records) >= MAX_SIGNATURES:
            raise ValueError('La biblioteca admite hasta 128 firmas. Elimina una antes de añadir otra.')
        total = sum(len(entry['png']) for entry in self.entries())
        if total + len(png) > MAX_LIBRARY_BYTES:
            raise ValueError('La biblioteca de firmas admite hasta 32 MB. Elimina una antes de añadir otra.')
        record = {'id': uuid.uuid4().hex, 'name': name}
        path = self.directory / (record['id'] + '.png')
        _atomic_bytes(path, png)
        try:
            self._write([*records, record])
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self._entry(record)

    def rename(self, identifier, name):
        identifier, name = _identifier(identifier), _name(name)
        records = self._records()
        record = next((record for record in records if record['id'] == identifier), None)
        if record is None:
            raise ValueError('La firma seleccionada ya no está en la biblioteca.')
        record['name'] = name
        self._write(records)
        return self._entry(record)

    def remove(self, identifier):
        identifier = _identifier(identifier)
        records = self._records()
        if not any(record['id'] == identifier for record in records):
            raise ValueError('La firma seleccionada ya no está en la biblioteca.')
        self._write([record for record in records if record['id'] != identifier])
        (self.directory / (identifier + '.png')).unlink(missing_ok=True)
