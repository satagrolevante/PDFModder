"""Word automation contracts; native PowerShell runs without needing Office."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from pdfmodder import office_conversion_v305 as office


@pytest.mark.parametrize('stage,code,expected',[
    ('open','0x800A1066','abrir la copia'),
    ('export','0x80070005','exportar el PDF'),
    ('start','0x80040154','no está registrada'),
    ('start','0x80080005','servidor de automatización'),
    ('open','0x80010001','Word sigue ocupado'),
])
def test_word_error_has_sanitized_phase_and_code_without_private_text(tmp_path,stage,code,expected):
    path=tmp_path/'diagnostic.json'
    path.write_text(json.dumps(dict(schema=1,stage=stage,code=code,message='PRIVATE DOCUMENT TEXT',
                                   path='PRIVATE DOC PATH')),encoding='utf-8-sig')
    text=office._word_diagnostic_message(path,1)
    assert expected in text and code in text and 'original se conserva' in text
    assert 'PRIVATE' not in text
    if code in ('0x80010001','0x80040154','0x80080005'):
        assert 'esté dañado' not in text


@pytest.mark.parametrize('data',[{}, {'schema':1,'stage':['private'],'code':'PRIVATE CONTENT'},
                                {'schema':1,'stage':'PRIVATE CONTENT','code':'0xNOT_A_CODE'}])
def test_invalid_word_diagnostic_never_exposes_raw_input(tmp_path,data):
    path=tmp_path/'diagnostic.json';path.write_text(json.dumps(data))
    message=office._word_diagnostic_message(path,1)
    assert 'PRIVATE' not in message and 'Código del proceso: 1' in message


def test_process_failure_loads_private_structured_diagnostic_and_keeps_original(tmp_path,monkeypatch):
    source=tmp_path/'source.doc';source.write_bytes(b'unchanged')
    def fail(command,*,env,**kwargs):
        Path(env['PDFMODDER_OFFICE_DIAGNOSTIC']).write_text(json.dumps(dict(schema=1,stage='open',code='0x800A1066')))
        error=office.ConversionError('PRIVATE WORD ERROR');error.returncode=1;raise error
    monkeypatch.setattr(office,'_run',fail)
    with pytest.raises(office.ConversionError,match='abrir la copia.*0x800A1066') as error:
        office._convert_word(source,tmp_path/'out.pdf',{'executable':'powershell'},tmp_path,10,None)
    assert 'PRIVATE' not in str(error.value) and source.read_bytes()==b'unchanged'
    assert not (tmp_path/'out.pdf').exists()


FAKE_WORD = r'''
public class PdfModderFakeOptions {
    public bool UpdateLinksAtOpen = true, UpdateFieldsAtPrint = true, UpdateLinksAtPrint = true;
}
public class PdfModderFakeWord {
    public bool Visible = true, ScreenUpdating = true;
    public int DisplayAlerts = 1, AutomationSecurity = 0, Opens = 0, Exports = 0;
    public int OpenBusy = 0, ExportBusy = 0;
    public string Failure;
    public bool Closed;
    public PdfModderFakeOptions Options = new PdfModderFakeOptions();
    public PdfModderFakeDocuments Documents;
    public PdfModderFakeWord() { Documents = new PdfModderFakeDocuments(this); }
}
public class PdfModderFakeDocuments {
    PdfModderFakeWord word;
    public PdfModderFakeDocuments(PdfModderFakeWord app) { word = app; }
    public PdfModderFakeDocument Open(string filename, bool confirm, bool readOnly, bool recent) {
        word.Opens++;
        if (System.Threading.Thread.CurrentThread.GetApartmentState() != System.Threading.ApartmentState.STA)
            throw new System.Exception("Word requires STA");
        if (word.AutomationSecurity != 3 || word.Options.UpdateLinksAtOpen || word.Options.UpdateFieldsAtPrint || word.Options.UpdateLinksAtPrint)
            throw new System.Exception("Document was opened before macro/link configuration");
        if (!readOnly || confirm || recent || filename != System.Environment.GetEnvironmentVariable("PDFMODDER_OFFICE_SOURCE"))
            throw new System.Exception("Read-only/filename contract changed");
        if (word.OpenBusy-- > 0) throw new System.Runtime.InteropServices.COMException("PRIVATE WORD ERROR", unchecked((int)0x80010001));
        if (word.Failure == "open") throw new System.Runtime.InteropServices.COMException("PRIVATE WORD ERROR", unchecked((int)0x800A1066));
        return new PdfModderFakeDocument(word);
    }
}
public class PdfModderFakeDocument {
    PdfModderFakeWord word;
    public PdfModderFakeDocument(PdfModderFakeWord app) { word = app; }
    public void ExportAsFixedFormat(string filename, int format, bool open, int optimize, int range,
        int from, int to, int item, bool properties, bool irm, int bookmarks, bool tags, bool bitmap, bool pdfa) {
        word.Exports++;
        if (format != 17 || open || range != 0 || !tags || !properties || bookmarks != 1 || !irm || !bitmap || pdfa)
            throw new System.Exception("PDF export options changed");
        if (word.ExportBusy-- > 0) throw new System.Runtime.InteropServices.COMException("PRIVATE WORD ERROR", unchecked((int)0x8001010A));
        if (word.Failure == "export") throw new System.Runtime.InteropServices.COMException("PRIVATE WORD ERROR", unchecked((int)0x80070005));
        System.IO.File.WriteAllText(filename, "EXPORT CONTRACT VERIFIED");
    }
    public void Close(int save) {
        if (save != 0) throw new System.Exception("Document must never be saved");
        word.Closed = true;
    }
}
'''


@pytest.mark.skipif(sys.platform!='win32',reason='Native Windows PowerShell automation contract')
@pytest.mark.parametrize('mode',['success','busy','open','export','busy-exhausted'])
def test_native_powershell_minimal_readonly_open_retry_export_and_cleanup(tmp_path,mode):
    powershell=office._powershell()
    if not powershell:pytest.skip('Windows PowerShell not installed')
    source=tmp_path/"source ' $() Ω.doc";source.write_bytes(b'original must stay unchanged')
    output=tmp_path/'output.pdf';result=tmp_path/'result.json'
    # Parse the complete production script, execute its actual helper functions
    # against a typed Word contract double. This is not a real Office render.
    script="""
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
[void][System.Management.Automation.Language.Parser]::ParseInput([System.IO.File]::ReadAllText($env:PDFMODDER_TEST_SCRIPT),[ref]$tokens,[ref]$errors)
if ($errors.Count -ne 0) { throw 'Production PowerShell syntax error' }
Add-Type -TypeDefinition @'
"""+FAKE_WORD+"""
'@
"""+office._WORD_HELPERS+r'''
$word = New-Object PdfModderFakeWord
if ($env:PDFMODDER_TEST_MODE -eq 'busy') { $word.OpenBusy = 2; $word.ExportBusy = 1 }
if ($env:PDFMODDER_TEST_MODE -eq 'busy-exhausted') { $word.OpenBusy = 20 }
if ($env:PDFMODDER_TEST_MODE -in @('open','export')) { $word.Failure = $env:PDFMODDER_TEST_MODE }
$failed = $false; $code = $null
try { Invoke-PdfModderWordDocument $word } catch { $failed = $true; $code = Get-PdfModderOfficeCode $_.Exception }
@{failed=$failed;code=$code;stage=$script:PdfModderOfficeStage;opens=$word.Opens;exports=$word.Exports;closed=$word.Closed;
  restored=($word.Options.UpdateLinksAtOpen -and $word.Options.UpdateFieldsAtPrint -and $word.Options.UpdateLinksAtPrint)} |
  ConvertTo-Json -Compress | Set-Content -LiteralPath $env:PDFMODDER_TEST_RESULT -Encoding UTF8
'''
    production=tmp_path/'production.ps1';production.write_text(office._WORD_SCRIPT,encoding='utf-8-sig')
    env=dict(os.environ,PDFMODDER_OFFICE_SOURCE=str(source),PDFMODDER_OFFICE_OUTPUT=str(output),
        PDFMODDER_TEST_RESULT=str(result),PDFMODDER_TEST_SCRIPT=str(production),PDFMODDER_TEST_MODE=mode)
    run=subprocess.run(office._powershell_command(powershell,script),env=env,capture_output=True,timeout=20,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    assert run.returncode==0,run.stderr.decode(errors='replace')
    state=json.loads(result.read_text(encoding='utf-8-sig'))
    assert state['restored'] and source.read_bytes()==b'original must stay unchanged'
    if mode in ('success','busy'):
        assert not state['failed'] and state['closed'] and state['stage']=='completed'
        assert state['opens']==(3 if mode=='busy' else 1) and state['exports']==(2 if mode=='busy' else 1)
        assert output.read_text()=='EXPORT CONTRACT VERIFIED'
    else:
        assert state['failed'] and not output.exists()
        assert state['closed']==(mode=='export') and state['stage']==('export' if mode=='export' else 'open')
        assert state['code']=={'open':'0x800A1066','export':'0x80070005','busy-exhausted':'0x80010001'}[mode]
        if mode=='busy-exhausted':assert state['opens']==5
