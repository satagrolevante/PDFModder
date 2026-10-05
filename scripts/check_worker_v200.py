"""Short deterministic worker check without pytest's restricted-ACL temp folders."""
from pathlib import Path
import json
import sys
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymupdf as fitz
from pdfmodder.model import EditError
from pdfmodder.recovery_v200 import list_recovery
from pdfmodder.worker import Session,dispatch
import pdfmodder.worker as worker

root=Path(__file__).resolve().parents[1]/'output'/('check-worker-'+uuid.uuid4().hex)
root.mkdir(parents=True)
source=root/'source.pdf'
with fitz.open() as doc:
    doc.new_page().insert_text((60,80),'Original selectable text')
    source.write_bytes(doc.tobytes())
reading=Session(source,reading=True,recovery_root=root/'recovery')
assert not reading.history.root.exists()
models=[reading.page(0,zoom=z)['model'] for z in (.5,1.,1.25)]
assert models[0] is models[2]
old_hash=worker.hashlib.sha256
worker.hashlib.sha256=lambda *args:(_ for _ in ()).throw(AssertionError('Unnecessary revision hash'))
started=time.perf_counter()
for _ in range(200):reading.state()
state_ms=(time.perf_counter()-started)*1000/200
worker.hashlib.sha256=old_hash
assert not reading.history.root.exists();reading.close()
session=Session(source,recovery_root=root/'recovery',config_path=root/'fonts.json')
original=session.original
with fitz.open(stream=original,filetype='pdf') as doc:
    doc[0].insert_text((60,110),'Accepted change');changed=doc.tobytes()
session._put_preview(changed,{'operation':'check'});session.commit()
session.store_draft({'kind':'legacy','page':0,'ids':[0],
    'revision':session.history.revision,'text':'Draft not accepted','password':'never persist'},
    {'page':0,'zoom':1.2})
assert list_recovery(root/'recovery')['entries']==[]
try:Session.recover(session.recovery_id,recovery_root=root/'recovery')
except EditError:pass
else:raise AssertionError('Live lock must block duplicate recovery')
session.history._lock.close();session.history._lock=None;session._close_documents()
assert list_recovery(root/'recovery')['entries'][0]['draft']
restored=Session.recover(session.recovery_id,recovery_root=root/'recovery',config_path=root/'fonts.json')
assert restored.history.current==changed and restored.original==original
assert restored.state()['recovered_draft']['text']=='Draft not accepted'
assert 'never persist' not in (restored.history.root/'session.json').read_text(encoding='utf-8')
restored.cancel();restored.navigate_history();assert restored.history.current==original
restored.navigate_history(True);assert restored.history.current==changed
restored.close()
options={'history_dir':str(root),'reading':True}
first=dispatch('open',{'path':str(source),**options})['state']['session_id']
second=dispatch('open',{'path':str(source),'retain_existing':True,**options})['state']['session_id']
assert len(dispatch('list_sessions')['sessions'])==2
assert dispatch('activate_session',{'session_id':first})['state']['session_id']==first
assert worker._sessions[second].history._current is None
dispatch('close_all')
result={'passed':True,'checks':['lazy_reader','zoom_model_reuse','zero_state_hashes',
    'live_lock','draft_recovery','exact_undo_redo','original_preservation','multidocument_suspension'],
    'state_average_ms_200_calls':round(state_ms,6),'measurement':'Synthetic one-page PDF; excludes render and IPC'}
(root.parent/'worker-v200-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
