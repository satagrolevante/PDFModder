"""Exercise production C# association methods under an isolated HKCU root."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
using System;
using System.IO;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using Microsoft.Win32;
class AssociationHarness {
    [DllImport("advapi32.dll")] static extern int RegOverridePredefKey(IntPtr key, IntPtr replacement);
    static BindingFlags Flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
    static RegistryKey Root;
    static Type Installer, Cleaner, Result;
    static List<object> Cases = new List<object>();
    static void Check(bool condition, string name) { if(!condition) throw new Exception(name); }
    static void Pass(string name) { Cases.Add(new {name=name, passed=true}); }
    static void Put(string path, string name, string value) { using(var key=Root.CreateSubKey(path)) key.SetValue(name,value); }
    static string Get(string path, string name) { using(var key=Root.OpenSubKey(path)) return key==null ? null : key.GetValue(name,null) as string; }
    static bool Exists(string path) { using(var key=Root.OpenSubKey(path)) return key!=null; }
    static bool Register(string path) {
        object result=Activator.CreateInstance(Result,true);
        return (bool)Installer.GetMethod("RegisterPdfAssociations",Flags).Invoke(null,new object[]{path,result});
    }
    static void Remove(string path) {
        var warnings=new List<string>();
        Cleaner.GetMethod("RemovePdfAssociations",Flags).Invoke(null,new object[]{path,warnings});
        Check(warnings.Count==0,"Unexpected uninstall warning");
    }
    static int Main(string[] args) {
        string temporary=args[0], work=args[1], report=args[4];
        var outcome=new Dictionary<string,object>(); bool overridden=false; int code=0;
        Check(temporary.StartsWith(@"Software\PDFModderAssociationTests\",StringComparison.Ordinal),"Unsafe test key");
        try {
            Root=Registry.CurrentUser.CreateSubKey(temporary);
            Check(RegOverridePredefKey(new IntPtr(unchecked((int)0x80000001)),Root.Handle.DangerousGetHandle())==0,"HKCU override failed");
            overridden=true;
            var install=Assembly.LoadFile(Path.GetFullPath(args[2]));
            var uninstall=Assembly.LoadFile(Path.GetFullPath(args[3]));
            Installer=install.GetType("PdfModderInstallation.Installer",true);
            Result=install.GetType("PdfModderInstallation.Result",true);
            Cleaner=uninstall.GetType("PdfModderUninstallation.RegistryCleaner",true);
            Installer.GetField("UserRegistryRoot",Flags).SetValue(null,Root);
            Cleaner.GetField("UserRegistryRoot",Flags).SetValue(null,Root);
            string old=Path.Combine(work,"versión anterior 1.8.1"), current=Path.Combine(work,"versión nueva á 2.0.2");
            Directory.CreateDirectory(old); Directory.CreateDirectory(current);
            File.WriteAllText(Path.Combine(old,"PDFModder.exe"),"fixture");
            File.WriteAllText(Path.Combine(current,"PDFModder.exe"),"fixture");
            string app=@"Software\Classes\Applications\PDFModder.exe";
            string doc=@"Software\Classes\PDFModder.Document";
            string open=@"Software\Classes\.pdf\OpenWithProgids";
            string cap=@"Software\PDFModder\Capabilities";
            string registered=@"Software\RegisteredApplications";
            string choice=@"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice";
            string command="\""+Path.Combine(current,"PDFModder.exe")+"\" \"%1\"";
            Put(app+@"\shell\open\command","","\""+Path.Combine(old,"PDFModder.exe")+"\" \"%1\"");
            Put(choice,"ProgId","OtherReader.PDF"); Put(choice,"Hash","unchanged-hash");
            Put(@"Software\Classes\.pdf","","OtherReader.PDF");
            Put(@"Software\Classes\OtherReader.PDF\shell\open\command","","other-reader-command");
            Put(open,"OtherReader.PDF",""); Put(registered,"Other Reader","OtherCapabilities");
            Check(Register(current),"Registration failed");
            Check(Get(app+@"\shell\open\command","")==command && Get(doc+@"\shell\open\command","")==command,"Stale command");
            Check(Get(app,"FriendlyAppName")=="PDF Modder" && Get(app+@"\SupportedTypes",".pdf")=="","Open With missing");
            Check(Get(doc+@"\DefaultIcon","")=="\""+Path.Combine(current,"PDFModder.exe")+"\",0","Icon missing");
            Check(Get(open,"PDFModder.Document")=="" && Get(cap+@"\FileAssociations",".pdf")=="PDFModder.Document","PDF capability missing");
            Check(Get(cap,"ApplicationName")=="PDF Modder" && Get(cap,"ApplicationDescription")!=null && Get(registered,"PDF Modder")==cap,"Settings registration missing");
            Pass("legacy_command_updated_with_spaces_accents_and_capabilities");
            Check(Get(choice,"ProgId")=="OtherReader.PDF" && Get(choice,"Hash")=="unchanged-hash","UserChoice changed");
            Check(Get(@"Software\Classes\.pdf","")=="OtherReader.PDF" && Get(@"Software\Classes\OtherReader.PDF\shell\open\command","")=="other-reader-command","Other reader changed");
            Pass("other_default_reader_and_userchoice_preserved");
            Put(choice,"ProgId",@"Applications\PDFModder.exe");
            Check(Register(current) && Get(choice,"ProgId")==@"Applications\PDFModder.exe" && Get(choice,"Hash")=="unchanged-hash","Legacy default changed");
            Pass("existing_pdfmodder_default_keeps_its_progid");
            Remove(old);
            Check(Get(app+@"\shell\open\command","")==command && Get(doc+@"\shell\open\command","")==command && Get(registered,"PDF Modder")==cap,"Old uninstall removed current registration");
            Pass("older_uninstaller_preserves_new_registration");
            using(var closed=Root.CreateSubKey("ClosedFixture")) {
                closed.Close(); Installer.GetField("UserRegistryRoot",Flags).SetValue(null,closed);
                Check(!Register(current),"Closed registry reported success");
            }
            Installer.GetField("UserRegistryRoot",Flags).SetValue(null,Root);
            Check(Get(app+@"\shell\open\command","")==command,"Failed registration changed previous command");
            Pass("registration_failure_is_reported_without_losing_previous_command");
            Put(cap,"Unrelated","keep"); Put(cap+@"\FileAssociations",".txt","OtherText");
            Remove(current);
            Check(!Exists(app) && !Exists(doc) && Get(registered,"PDF Modder")==null && Get(open,"PDFModder.Document")==null,"Owned registrations not removed");
            Check(Get(cap,"Unrelated")=="keep" && Get(cap+@"\FileAssociations",".txt")=="OtherText" && Get(registered,"Other Reader")=="OtherCapabilities" && Get(open,"OtherReader.PDF")=="","Foreign registration removed");
            Check(Get(choice,"ProgId")==@"Applications\PDFModder.exe" && Get(choice,"Hash")=="unchanged-hash","Uninstall changed UserChoice");
            Pass("own_uninstaller_removes_only_own_associations");
            outcome["ok"]=true;
        } catch(Exception ex) { outcome["ok"]=false; outcome["error"]=ex.ToString(); code=1; }
        finally {
            if(overridden) Check(RegOverridePredefKey(new IntPtr(unchecked((int)0x80000001)),IntPtr.Zero)==0,"Could not restore HKCU");
            if(Root!=null) Root.Dispose();
            Registry.CurrentUser.DeleteSubKeyTree(temporary,false);
            outcome["scenarios"]=Cases; outcome["temporary_registry_removed"]=true;
            File.WriteAllText(report,new JavaScriptSerializer().Serialize(outcome));
        }
        return code;
    }
}
'''


@pytest.mark.skipif(os.name != 'nt', reason='Requires the Windows registry and Framework compiler')
def test_production_pdf_associations_in_isolated_registry():
    import winreg

    def snapshot(path):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            return None
        with key:
            children, values, _ = winreg.QueryInfoKey(key)
            return (tuple(sorted(winreg.EnumValue(key, i) for i in range(values))),
                    tuple((name, snapshot(path + '\\' + name)) for name in sorted(winreg.EnumKey(key, i) for i in range(children))))

    paths = (r'Software\Classes\Applications\PDFModder.exe', r'Software\Classes\PDFModder.Document',
             r'Software\Classes\.pdf', r'Software\PDFModder\Capabilities', r'Software\RegisteredApplications',
             r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\UserChoice')
    before = [snapshot(p) for p in paths]
    work = ROOT / 'tmp' / ('association-v202-' + uuid.uuid4().hex)
    work.mkdir(parents=True)
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    flags = ['/nologo', '/platform:x64', '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
             '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll']

    def run(args):
        result = subprocess.run([str(a) for a in args], cwd=work, capture_output=True, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr

    hashes = {}
    libraries = []
    for kind, name in (('installer', 'PdfModderInstaller.cs'), ('uninstaller', 'PdfModderUninstaller.cs')):
        source = ROOT / 'installer' / name
        hashes[kind] = hashlib.sha256(source.read_bytes()).hexdigest()
        generated = work / name
        generated.write_text(source.read_text(encoding='utf-8-sig').replace('1.7.0', '2.0.2'), encoding='utf-8-sig')
        library = work / (kind + '.dll')
        run([compiler, *flags, '/target:library', '/out:' + str(library), generated])
        libraries.append(library)
    harness = work / 'Harness.cs'
    harness.write_text(HARNESS, encoding='utf-8-sig')
    executable = work / 'Harness.exe'
    run([compiler, *flags, '/target:exe', '/out:' + str(executable), harness])
    temporary_key = 'Software\\PDFModderAssociationTests\\' + uuid.uuid4().hex
    report_path = work / 'result.json'
    try:
        run([executable, temporary_key, work, *libraries, report_path])
        report = json.loads(report_path.read_text(encoding='utf-8-sig'))
        assert report['ok'] and len(report['scenarios']) == 6 and all(case['passed'] for case in report['scenarios'])
        after = [snapshot(p) for p in paths]
        assert before == after, 'The test changed the real PDF registrations'
        assert snapshot(temporary_key) is None
        installer_source = (ROOT / 'installer/PdfModderInstaller.cs').read_text(encoding='utf-8-sig')
        assert 'if (installationRegistered && associationsRegistered) RetirePrevious' in installer_source
        report.update(real_registry_unchanged=True, source_sha256=hashes,
                      compiled_harness_sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
        (ROOT / 'output').mkdir(exist_ok=True)
        (ROOT / 'output/associations-v202.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    finally:
        # A fixed namespace and UUID generated by this test own this key exclusively.
        def remove_tree(path):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
                    names = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
                for name in names:
                    remove_tree(path + '\\' + name)
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
        remove_tree(temporary_key)
