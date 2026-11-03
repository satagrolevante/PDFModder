from dataclasses import replace
from io import BytesIO

import pymupdf as fitz
import pytest

from pdfmodder.engine import atomic_save
from pdfmodder.model import EditError
from pdfmodder.validation_evidence_v318 import (
    ValidationEvidenceCacheV318, validation_scope_v318,
    remember_validated_snapshot_v318, validated_snapshot_v318,
    has_validated_snapshot_v318, canonical_snapshot_v318,
)


def pdf():
    with fitz.open() as doc:
        doc.new_page().insert_text((40, 60), 'exact validated snapshot')
        return doc.tobytes()


def test_proofs_require_exact_bytes_identity_and_originating_scope():
    data = pdf()
    a, b = ValidationEvidenceCacheV318(), ValidationEvidenceCacheV318()
    with validation_scope_v318(a):
        proof = remember_validated_snapshot_v318(data, 1)
        assert has_validated_snapshot_v318(data, proof)
        assert not has_validated_snapshot_v318(data + b'\n', proof)
        assert not has_validated_snapshot_v318(data, replace(proof))
        assert not has_validated_snapshot_v318(data, {'verified': True})
    with validation_scope_v318(b):
        assert not has_validated_snapshot_v318(data, proof)
    assert not has_validated_snapshot_v318(data, proof)


def test_eviction_and_policy_invalidation():
    cache = ValidationEvidenceCacheV318(max_entries=1)
    with validation_scope_v318(cache):
        data = pdf()
        proof = remember_validated_snapshot_v318(data, 1)
        assert not has_validated_snapshot_v318(data, replace(proof, policy='future-policy'))
        remember_validated_snapshot_v318(data + b'\n', 1)
        assert not has_validated_snapshot_v318(data, proof)
        cache.clear()
        assert validated_snapshot_v318(data) is None


def test_save_proof_skips_only_completed_structural_checks(tmp_path, monkeypatch):
    import pdfmodder.validation as validation
    import pdfmodder.engine as engine
    data = pdf()
    with validation_scope_v318(ValidationEvidenceCacheV318()):
        # The initial save performs the full authoritative validation.
        atomic_save(data, tmp_path / 'full.pdf')
        proof = validated_snapshot_v318(data)
        assert proof is not None
        def redundant(*args, **kwargs):
            pytest.fail('An exact proven snapshot must not repeat the structural scan')
        monkeypatch.setattr(validation, 'assert_text_object_structure', redundant)
        target = tmp_path / 'exact.pdf'
        atomic_save(data, target, validation_proof=proof)
        assert target.read_bytes() == data
        # Even a valid proof may not skip checking bytes actually written.
        original_replace = engine.os.replace
        def corrupt_replace(source, destination):
            # Hash check runs BEFORE this call; ensure it was not skipped below
            return original_replace(source, destination)
        monkeypatch.setattr(engine.os, 'replace', corrupt_replace)
        original_fsync = engine.os.fsync
        def corrupt_written(fd):
            import os
            original_fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, b'BROKEN')
        monkeypatch.setattr(engine.os, 'fsync', corrupt_written)
        with pytest.raises(EditError):
            atomic_save(data, tmp_path / 'corrupt.pdf', validation_proof=proof)
        assert not (tmp_path / 'corrupt.pdf').exists()


def test_canonical_cache_is_bounded_exact_and_scope_local():
    calls = []
    def prepare():
        calls.append(1)
        return b'canonical bytes'
    cache = ValidationEvidenceCacheV318(canonical_budget=20)
    with validation_scope_v318(cache):
        assert canonical_snapshot_v318(b'source', prepare) == b'canonical bytes'
        canonical_snapshot_v318(b'source', prepare)
        assert len(calls) == 1
        canonical_snapshot_v318(b'another revision', prepare)
        assert cache.canonical_bytes <= 20
        canonical_snapshot_v318(b'source', prepare)
        assert len(calls) == 3


def test_metadata_only_export_does_not_authorize_restricted_content_save(tmp_path):
    from pdfmodder.document_ops_v170 import update_document_metadata
    with fitz.open() as document:
        document.new_page().insert_text((40, 60), 'XFA metadata control')
        packet = document.get_new_xref()
        document.update_object(packet, '<<>>')
        document.update_stream(packet, b'<xdp/>')
        form = document.get_new_xref()
        document.update_object(form, f'<< /Fields [] /XFA {packet} 0 R >>')
        document.xref_set_key(document.pdf_catalog(), 'AcroForm', f'{form} 0 R')
        source = document.tobytes()
    with validation_scope_v318(ValidationEvidenceCacheV318()):
        candidate, _ = update_document_metadata(source, {'title': 'Metadata only'})
        assert candidate != source
        assert validated_snapshot_v318(candidate) is None
        with pytest.raises(EditError, match='XFA'):
            atomic_save(candidate, tmp_path / 'content-export.pdf',
                        validation_proof=validated_snapshot_v318(candidate))


def test_complete_operation_decorator_never_mints_noop_evidence():
    from pdfmodder.validation_evidence_v318 import validated_result_v318
    @validated_result_v318
    def cheap_noop(data):
        return data, {'verified': True}
    data = pdf()
    with validation_scope_v318(ValidationEvidenceCacheV318()):
        cheap_noop(data)
        assert validated_snapshot_v318(data) is None
