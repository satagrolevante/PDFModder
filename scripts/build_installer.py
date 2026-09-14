"""Instalador offline .NET Framework para el ZIP ya verificado de Windows.

No recompila ni altera el motor. Incluye el ZIP completo y una tabla SHA-256
de cada archivo; el instalador los verifica antes de publicar la carpeta.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,subprocess,zipfile

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def build():
    source=ROOT/'releases/v0.8/PDFModder-v0.8-Windows-x64.zip'
    meta=json.loads((source.parent/'VERSION.json').read_text(encoding='utf-8'))
    assert meta['frozen_verified'] and sha(source)==meta['archive_sha256']
    staging=ROOT/'build/installer';staging.mkdir(parents=True,exist_ok=True)
    payload=staging/'PDFModderPayload.zip'
    # Add the corresponding installer source and build instructions to the
    # existing application's source offer without changing executable/DLLs.
    extras=[ROOT/'installer/PdfModderInstaller.cs',ROOT/'installer/asInvoker.manifest',
            Path(__file__),ROOT/'scripts/verify_installer.py',ROOT/'scripts/verify_installer_ui.ps1',ROOT/'docs/INSTALACION_WINDOWS.md']
    with zipfile.ZipFile(source) as existing,zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        assert existing.testzip() is None
        for item in existing.infolist():output.writestr(item,existing.read(item.filename))
        for path in extras:
            output.write(path,'PDFModder/_internal/source/PDFModder/'+path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(payload) as archive:
        names=archive.namelist();assert len(names)==len(set(names))
        rows=[]
        for name in names:
            assert name.startswith('PDFModder/') and '..' not in Path(name).parts and '\\' not in name and '\t' not in name and '\n' not in name
            content=archive.read(name)
            rows.append(hashlib.sha256(content).hexdigest()+'\t'+str(len(content))+'\t'+name)
        assert hashlib.sha256(archive.read('PDFModder/PDFModder.exe')).hexdigest()==meta['exe_sha256']
        assert 'PDFModder/_internal/shiboken6/Shiboken.pyd' in names
        assert 'PDFModder/_internal/shiboken6/shiboken6.abi3.dll' in names
    manifest=staging/'PDFModderPayload.tsv';manifest.write_text('\n'.join(rows)+'\n',encoding='utf-8')
    compiler=Path(os.environ.get('SystemRoot','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():raise RuntimeError('No se encuentra el compilador .NET Framework de Windows.')
    target=source.parent/'PDFModder-v0.8-Instalar.exe'
    args=[str(compiler),'/nologo','/target:winexe','/platform:x64','/optimize+',
          '/out:'+str(target),'/win32manifest:'+str(ROOT/'installer/asInvoker.manifest'),
          '/resource:'+str(payload)+',PDFModderPayload.zip',
          '/resource:'+str(manifest)+',PDFModderPayload.tsv',
          '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll',
          '/reference:System.IO.Compression.dll','/reference:System.IO.Compression.FileSystem.dll',
          '/reference:System.Web.Extensions.dll',str(ROOT/'installer/PdfModderInstaller.cs')]
    subprocess.run(args,check=True,cwd=ROOT)
    report={'application':'PDF Modder 0.8.0','installer_revision':1,
            'created_utc':datetime.now(timezone.utc).isoformat(),
            'installer_sha256':sha(target),'installer_bytes':target.stat().st_size,
            'source_archive_sha256':meta['archive_sha256'],'exe_sha256':meta['exe_sha256'],
            'payload_sha256':sha(payload),'manifest_files':len(rows),'tested':False,
            'note':'El ejecutable y las dependencias del PDF son los de la entrega verificada. Este JSON registra la construcción; las pruebas del instalador se documentan aparte.'}
    target.with_suffix('.exe.sha256').write_text(sha(target)+'  '+target.name+'\n',encoding='ascii')
    (target.parent/'INSTALADOR.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'installer':str(target),**report},ensure_ascii=False,indent=2))


if __name__=='__main__':build()
