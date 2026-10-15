"""Original underlines retain their separate logical and physical ownership."""
from dataclasses import replace
from io import BytesIO
import copy

import pymupdf as fitz
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, BooleanObject, ContentStream, DictionaryObject, FloatObject, NameObject, NumberObject, TextStringObject

from pdfmodder.clipping import _serialize, operator_glyph_map
from pdfmodder.engine import extract_page, full_write
from pdfmodder.model import EditError
from pdfmodder.source_decorations_v304 import prepare_source_decorations, SourceDecorationPolicy
from pdfmodder.tagged import analyze_readonly


def dictionary(**items):
    return DictionaryObject({NameObject('/'+key):value for key,value in items.items()})


def fixture(*, duplicate=False, other_container=False, extra_text=False, frame=False,
            actual_text=False, bbox=False, clipping=False):
    source=fitz.open();page=source.new_page(width=400,height=300)
    page.insert_text((50,100),'abc123',fontsize=12,color=(0,0,1))
    width=fitz.get_text_length('abc123',fontsize=12,fontname='helv')
    page.draw_rect((50,101.3,50+width-.1,102.1),fill=(0,0,1),color=None)
    if duplicate:page.draw_rect((50,101.3,50+width-.1,102.1),fill=(0,0,1),color=None)
    if frame:
        page.draw_rect((49.7,85,50.3,101.7),fill=(0,0,1),color=None)
        page.draw_rect((50+width-.4,85,50+width+.2,101.7),fill=(0,0,1),color=None)
        page.draw_rect((50,84.7,50+width-.1,85.3),fill=(0,0,1),color=None)
    if extra_text:page.insert_text((200,100),'OTHER',fontsize=12,color=(0,0,1))
    page.insert_text((50,170),'Control',fontsize=12)
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source.tobytes())))
    p=writer.pages[0];streams=list(p['/Contents']);root=dictionary(Type=NameObject('/StructTreeRoot'));root_ref=writer._add_object(root)
    writer.root_object[NameObject('/StructTreeRoot')]=root_ref
    writer.root_object[NameObject('/MarkInfo')]=dictionary(Marked=BooleanObject(True))
    def node(role,parent,k=None):
        value=dictionary(Type=NameObject('/StructElem'),S=NameObject('/'+role),P=parent,Pg=p.indirect_reference)
        if k is not None:value[NameObject('/K')]=NumberObject(k)
        return writer._add_object(value)
    document=node('Document',root_ref);root[NameObject('/K')]=document
    paragraph=node('P',document);span=node('Span',paragraph,0)
    span.get_object()[NameObject('/A')]=dictionary(O=NameObject('/Layout'),TextDecorationType=NameObject('/Underline'),TextDecorationColor=ArrayObject([NumberObject(0),NumberObject(0),NumberObject(0)]))
    if actual_text:span.get_object()[NameObject('/ActualText')]=TextStringObject('abc123')
    artifact=node('Artifact',paragraph,1);paragraph.get_object()[NameObject('/K')]=ArrayObject([span,artifact]);owners=[span,artifact];document_kids=[paragraph]
    if bbox:
        artifact.get_object()[NameObject('/A')]=dictionary(O=NameObject('/Layout'),BBox=ArrayObject([FloatObject(v) for v in (50,197.9,50+width-.1,198.7)]))
    if other_container:
        outside=node('P',document);artifact.get_object()[NameObject('/P')]=outside
        paragraph.get_object()[NameObject('/K')]=span;outside.get_object()[NameObject('/K')]=artifact;document_kids.append(outside)
    decorated_indices=[0];output=[]
    def wrap(index,mcid,role='Span'):
        original=ContentStream(streams[index],writer).operations
        ops=[([NameObject('/'+role),dictionary(MCID=NumberObject(mcid))],b'BDC'),*original,([],b'EMC')]
        if clipping and index==1:ops=[([],b'q'),([NumberObject(45),NumberObject(185),NumberObject(48),NumberObject(30)],b're'),([],b'W'),([],b'n'),*ops,([],b'Q')]
        content=ContentStream(None,writer);content.operations=ops;return writer._add_object(content)
    output.append(wrap(0,0));output.append(wrap(1,1,'Artifact'));stream_index=2
    if duplicate:
        art=node('Artifact',paragraph,len(owners));paragraph.get_object()['/K'].append(art)
        output.append(wrap(stream_index,len(owners),'Artifact'));owners.append(art);stream_index+=1
    if frame:
        for _ in range(3):
            art=node('Artifact',paragraph,len(owners));paragraph.get_object()['/K'].append(art)
            output.append(wrap(stream_index,len(owners),'Artifact'));owners.append(art);stream_index+=1
    if extra_text:
        extra=node('Span',paragraph,len(owners));paragraph.get_object()['/K'].append(extra)
        # Place the unrelated text immediately BEFORE the original line.
        output.insert(1,wrap(stream_index,len(owners)));owners.append(extra);stream_index+=1
    control_p=node('P',document);control=node('Span',control_p,len(owners));control_p.get_object()[NameObject('/K')]=control;document_kids.append(control_p)
    output.append(wrap(stream_index,len(owners)));owners.append(control)
    document.get_object()[NameObject('/K')]=ArrayObject(document_kids)
    p[NameObject('/Contents')]=ArrayObject(output);p[NameObject('/StructParents')]=NumberObject(0)
    root[NameObject('/ParentTree')]=writer._add_object(dictionary(Nums=ArrayObject([NumberObject(0),ArrayObject(owners)])))
    root[NameObject('/ParentTreeNextKey')]=NumberObject(1)
    buffer=BytesIO();writer.write(buffer);return buffer.getvalue()


def prepared(source, *, partial=False):
    with fitz.open(stream=source,filetype='pdf') as document:model=extract_page(document,0,source)
    structure=analyze_readonly(source);contexts=structure.glyph_contexts(0,model)
    selected=[g for g in model.glyphs if contexts[g.id]==0]
    if partial:selected=selected[2:4]
    _,operations,_,mapping=operator_glyph_map(source,0,model)
    return prepare_source_decorations(source,0,model,selected,structure,operations,mapping),model,selected,structure,operations


def rewritten(source,policy,operations):
    operations=copy.deepcopy(operations);policy.apply_operations(operations,{i:i for i in range(len(operations))})
    with fitz.open(stream=source,filetype='pdf') as document:
        stream=document.get_new_xref();document.update_object(stream,'<<>>');document.update_stream(stream,_serialize(operations));document[0].set_contents(stream)
        policy.apply_structure(document);return full_write(document)


def test_unique_original_rectangle_preserves_source_style_and_separate_artifact():
    source=fixture();policy,model,selected,structure,operations=prepared(source)
    assert isinstance(policy,SourceDecorationPolicy)
    planned=[replace(g,bbox=(g.bbox[0],g.bbox[1],g.bbox[2]+(.2 if i==len(selected)-1 else 0),g.bbox[3])) for i,g in enumerate(selected)]
    policy.plan(planned)
    assert policy.matches_source(structure,0,model,selected,planned)
    assert policy.allows_decoration(policy.paths[0],selected,planned)
    assert policy.new_shapes[0]['rect'][2]-policy.old_shapes[0]['rect'][2]==pytest.approx(.2)
    assert policy.new_shapes[0]['rect'][1::2]==policy.old_shapes[0]['rect'][1::2]
    output=rewritten(source,policy,operations)
    assert policy.validate(output)['original_artifact_preserved']
    assert analyze_readonly(source).semantic()==analyze_readonly(output).semantic()


def test_partial_owner_edit_keeps_the_prefix_suffix_and_whole_line():
    source=fixture();policy,model,selected,structure,operations=prepared(source,partial=True)
    policy.plan([])
    assert policy.new_shapes==policy.old_shapes
    full=[g for g in model.glyphs if g.id in policy.owner_ids]
    expected=[g for g in full if g.id not in policy.selected_ids]
    assert policy.allows_decoration(policy.paths[0],full,expected)
    assert not policy.allows_decoration(policy.paths[0],selected,[])
    assert policy.validate(rewritten(source,policy,operations))['verified']


def test_full_deletion_keeps_an_empty_original_mark_without_visible_line():
    source=fixture();policy,_,_,_,operations=prepared(source);policy.plan([])
    assert policy.new_shapes[0]['rect'][0]==policy.new_shapes[0]['rect'][2]
    output=rewritten(source,policy,operations)
    assert policy.validate(output)['verified']
    assert analyze_readonly(source).semantic()==analyze_readonly(output).semantic()


def test_exact_owned_artifact_bbox_is_updated_and_semantic_expectation_matches():
    source=fixture(bbox=True);policy,_,selected,structure,operations=prepared(source)
    assert policy
    planned=[replace(g,bbox=(g.bbox[0],g.bbox[1],g.bbox[2]+(2 if i==len(selected)-1 else 0),g.bbox[3])) for i,g in enumerate(selected)]
    policy.plan(planned);expected=policy.expected_structure(copy.deepcopy(structure.semantic()))
    output=rewritten(source,policy,operations)
    assert analyze_readonly(output).semantic()==expected
    assert policy.validate(output)['verified']


@pytest.mark.parametrize('options',[{'duplicate':True},{'other_container':True},{'extra_text':True},{'actual_text':True}])
def test_ambiguous_unrelated_or_semantic_decorations_are_not_bound(options):
    assert prepared(fixture(**options))[0] is None


@pytest.mark.parametrize('field,value',[('size',13),('font','Courier'),('color',(1,0,0)),('origin',(50,101))])
def test_new_typography_or_baseline_does_not_gain_a_decoration_exception(field,value):
    policy,_,selected,_,_=prepared(fixture())
    planned=list(selected);planned[0]=replace(planned[0],**{field:value})
    with pytest.raises(EditError,match='conservar'):policy.plan(planned)


def test_clipped_line_cannot_grow_outside_its_original_clip():
    policy,_,selected,_,_=prepared(fixture(clipping=True));assert policy
    planned=[replace(g,bbox=(g.bbox[0],g.bbox[1],g.bbox[2]+100,g.bbox[3])) for g in selected]
    with pytest.raises(EditError,match='recorte'):policy.plan(planned)


def test_rewrite_requires_every_original_artifact_operator_and_contiguous_mapping():
    policy,_,selected,_,operations=prepared(fixture());policy.plan(selected)
    tampered=copy.deepcopy(operations);tampered[policy.rect_operation][0][2]=FloatObject(12)
    with pytest.raises(EditError,match='cambiaron'):policy.apply_operations(tampered,{i:i for i in range(len(operations))})
    mapping={i:i for i in range(len(operations))};mapping[policy.rect_operation]+=1
    with pytest.raises(EditError):policy.apply_operations(copy.deepcopy(operations),mapping)


def test_validation_rejects_changed_color_or_an_unrelated_decoration_path():
    source=fixture();policy,_,selected,_,operations=prepared(source);policy.plan(selected)
    assert not policy.allows_decoration(('tree',),selected,selected)
    output=rewritten(source,policy,operations)
    structure=analyze_readonly(output);ops=copy.deepcopy(structure.operations[0]);mark=structure.marks[0][1]
    color=next(i for i in range(mark.start,mark.end) if ops[i][1]==b'rg');ops[color]=([NumberObject(1),NumberObject(0),NumberObject(0)],b'rg')
    with fitz.open(stream=output,filetype='pdf') as document:
        stream=document.get_new_xref();document.update_object(stream,'<<>>');document.update_stream(stream,_serialize(ops));document[0].set_contents(stream);tampered=full_write(document)
    with pytest.raises(EditError,match='operador ajeno'):policy.validate(tampered)


def test_public_class_cannot_be_constructed_without_preparation():
    with pytest.raises(TypeError):SourceDecorationPolicy(None)


def test_policy_is_bound_to_the_original_selection_and_exact_current_plan():
    policy,model,selected,structure,_=prepared(fixture());policy.plan(selected)
    assert policy.matches_source(structure,0,model,selected,selected)
    changed=list(selected);changed[0]=replace(changed[0],text='z')
    assert not policy.matches_source(structure,0,model,changed,selected)
    assert not policy.matches_source(structure,0,model,selected,changed)
    assert not policy.matches_source(structure,1,model,selected,selected)
    assert not policy.allows_decoration(policy.paths[0],selected,changed)


def scaled_artifact(source, *, local_bbox=False):
    writer=PdfWriter(clone_from=PdfReader(BytesIO(source)));page=writer.pages[0]
    content=ContentStream(page.get_contents(),writer);operations=[];inside=False
    for args,operator in content.operations:
        if operator==b'BDC' and args[1].get('/MCID')==1:
            operations.extend([([],b'q'),([NumberObject(2),NumberObject(0),NumberObject(0),NumberObject(2),NumberObject(0),NumberObject(0)],b'cm')]);inside=True
        if inside and operator==b're':args=[FloatObject(float(v)/2) for v in args]
        operations.append((args,operator))
        if inside and operator==b'EMC':operations.append(([],b'Q'));inside=False
    content.operations=operations;page.replace_contents(content)
    if local_bbox:
        artifact=writer.root_object['/StructTreeRoot']['/K']['/K'][0]['/K'][1]
        artifact['/A'][NameObject('/BBox')]=ArrayObject([FloatObject(float(v)/2) for v in artifact['/A']['/BBox']])
    output=BytesIO();writer.write(output);return output.getvalue()


def test_layout_bbox_uses_default_user_space_under_nonidentity_ctm():
    source=scaled_artifact(fixture(bbox=True));policy,_,selected,structure,operations=prepared(source)
    assert policy
    planned=[replace(g,bbox=(g.bbox[0],g.bbox[1],g.bbox[2]+(2 if i==len(selected)-1 else 0),g.bbox[3])) for i,g in enumerate(selected)]
    policy.plan(planned)
    expected=policy.expected_structure(copy.deepcopy(structure.semantic()))
    output=rewritten(source,policy,operations)
    assert analyze_readonly(output).semantic()==expected
    assert policy.validate(output)['verified']
    bbox=analyze_readonly(output).nodes[policy.artifact_path]['/A']['/BBox']
    assert list(map(float,bbox))==pytest.approx((50,197.9,91.26,198.7))
    assert prepared(scaled_artifact(fixture(bbox=True),local_bbox=True))[0] is None


def rich_edit(source,text,*,partial=False):
    from pdfmodder.native_panel import _replace_runs
    from pdfmodder.richmodels import RichTextRequest
    from pdfmodder.richtext import selection_payload,edit_rich_pdf
    _,model,selected,_,_=prepared(source,partial=partial)
    ids=[g.id for g in selected];payload=selection_payload(source,0,ids)
    request=RichTextRequest(0,ids,_replace_runs(copy.deepcopy(payload['runs']),text),
        rect=payload['rect'],revision=model.revision,auto_width=bool(text),allow_overlap=True)
    return edit_rich_pdf(source,request)


@pytest.mark.parametrize('text',['abc','abc123abc123',''])
def test_actual_rich_editor_jointly_shortens_extends_or_deletes_the_line(text):
    source=fixture();output,report=rich_edit(source,text)
    assert report['verified'] and report['source_decoration']['verified']
    assert analyze_readonly(source).semantic()==analyze_readonly(output).semantic()
    with fitz.open(stream=output,filetype='pdf') as document:
        contexts=analyze_readonly(output).glyph_contexts(0,extract_page(document,0,output))
        glyphs=extract_page(document,0,output).glyphs
        assert ''.join(g.text for g in glyphs if contexts[g.id]==0)==text
        assert 'Control' in document[0].get_text()


def test_actual_partial_edit_and_reopened_second_edit_rebind_the_original_line():
    source=fixture();first,report=rich_edit(source,'c1c',partial=True)
    # An interior replacement retains the existing whole-owner extent and
    # therefore preserves its line through the ordinary related-object proof.
    assert report['verified']
    with fitz.open(stream=first,filetype='pdf') as document:
        model=extract_page(document,0,first);contexts=analyze_readonly(first).glyph_contexts(0,model)
        assert ''.join(g.text for g in model.glyphs if contexts[g.id]==0)=='abc1c23'
    second,again=rich_edit(first,'abc123abc')
    assert again['source_decoration']['verified']
    assert analyze_readonly(first).semantic()==analyze_readonly(second).semantic()


def test_actual_joint_edit_updates_owned_bbox_with_scaled_graphic():
    source=scaled_artifact(fixture(bbox=True));output,report=rich_edit(source,'abc123abc123')
    assert report['verified'] and report['source_decoration']['verified']
    assert report['source_decoration']['attribute_box_updated']


def test_closed_frame_bottom_border_cannot_be_adopted_as_a_text_underline():
    assert prepared(fixture(frame=True))[0] is None


def test_nested_semantic_scope_in_graphics_is_not_a_plain_owned_underline():
    writer=PdfWriter(clone_from=PdfReader(BytesIO(fixture())))
    page=writer.pages[0];content=ContentStream(page.get_contents(),writer);ops=[];inside=False
    for args,operator in content.operations:
        if operator==b'BDC' and args[1].get('/MCID')==1:
            inside=True;ops.append((args,operator));ops.append(([NameObject('/Span'),dictionary(ActualText=TextStringObject('Described rule'))],b'BDC'));continue
        if operator==b'EMC' and inside:ops.append(([],b'EMC'));inside=False
        ops.append((args,operator))
    content.operations=ops;page.replace_contents(content);output=BytesIO();writer.write(output)
    assert prepared(output.getvalue())[0] is None


def test_color_change_with_identical_extent_retains_existing_line_and_is_allowed():
    from pdfmodder.richtext import selection_payload,edit_rich_pdf
    from pdfmodder.richmodels import RichTextRequest
    source=fixture();policy,model,selected,_,_=prepared(source)
    planned=[replace(g,color=(.6,.1,.2)) for g in selected]
    assert not policy.needs_update(planned)
    payload=selection_payload(source,0,[g.id for g in selected]);runs=copy.deepcopy(payload['runs'])
    for run in runs:run['color']=(.6,.1,.2)
    output,report=edit_rich_pdf(source,RichTextRequest(0,[g.id for g in selected],runs,rect=payload['rect'],revision=model.revision))
    assert report['verified'] and 'source_decoration' not in report
    with fitz.open(stream=source,filetype='pdf') as before,fitz.open(stream=output,filetype='pdf') as after:
        assert before[0].get_drawings()==after[0].get_drawings()


@pytest.mark.parametrize('text',['abc123','abc123abc123'])
def test_requesting_underline_does_not_duplicate_the_proven_original_line(text):
    from pdfmodder.native_panel import _replace_runs
    from pdfmodder.richtext import selection_payload,edit_rich_pdf
    from pdfmodder.richmodels import RichTextRequest
    source=fixture();_,model,selected,_,_=prepared(source);ids=[g.id for g in selected]
    payload=selection_payload(source,0,ids);runs=_replace_runs(copy.deepcopy(payload['runs']),text)
    for run in runs:run['underline']=True
    output,report=edit_rich_pdf(source,RichTextRequest(0,ids,runs,rect=payload['rect'],revision=model.revision,auto_width=True))
    assert report['verified']
    with fitz.open(stream=output,filetype='pdf') as document:
        rules=[d for d in document[0].get_drawings() if d['type']=='f' and d.get('fill')==(0.,0.,1.)]
        assert len(rules)==1
        # Future edits must continue to bind the original Artifact, rather
        # than treating it as several private per-character lines.
        assert prepared(output)[0] is not None
