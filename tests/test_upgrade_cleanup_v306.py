"""Exercise the production Windows upgrade cleanup in isolated HKCU and folders."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Requires Windows and Framework C# compiler')

# The actual production uninstaller is compiled with this entry point. The
# temporary copy it launches executes this wrapper again, retaining isolation.
UNINSTALL_ENTRY = r'''
using System;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;
class UpgradeUninstallEntry {
    [STAThread] static int Main(string[] args) {
        string path=Environment.GetEnvironmentVariable("PDFMODDER_UPGRADE_TEST_KEY");
        if(path==null || !path.StartsWith(@"Software\PDFModderUpgradeTests\",StringComparison.Ordinal)) return 99;
        using(var root=Registry.CurrentUser.OpenSubKey(path,true)) {
            if(root==null) return 98;
            PdfModderUninstallation.RegistryCleaner.UserRegistryRoot=root;
            var options=PdfModderUninstallation.Options.Parse(args);
            if(!options.Worker) { PdfModderUninstallation.SelfRelaunch.Start(options); return 0; }
            PdfModderUninstallation.SelfRelaunch.ValidateWorkerLocation();
            PdfModderUninstallation.SelfRelaunch.WaitForParent(options);
            try {
                using(var report=PdfModderUninstallation.Reports.Reserve(options)) {
                    var result=PdfModderUninstallation.Uninstaller.Run(options,delegate {});
                    PdfModderUninstallation.Reports.Write(report,result);
                    return result.ok?0:1;
                }
            } finally {
                // The harness removes this exact generated worker after exit.
                // Do not schedule any system-wide "delete at reboot" operation.
                File.WriteAllText(options.Report+".worker-path",Application.ExecutablePath);
            }
        }
    }
}
'''

HARNESS = r'''
using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using Microsoft.Win32;
class UpgradeCleanupHarness {
    const string Id="PDFModder.Windows.PerUser", Marker=".pdfmodder-installation.json", Manifest=".pdfmodder-files.tsv";
    const string Uninstall=@"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFModder-";
    static readonly BindingFlags Flags=BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic;
    static readonly BindingFlags Fields=BindingFlags.Instance|BindingFlags.Public;
    static RegistryKey Root;
    static Type Installer,Result,Options;
    static string Work, Binaries, Current;
    static List<object> Cases=new List<object>();
    static void Check(bool value,string message) { if(!value) throw new Exception(message); }
    static void Pass(string name) { Cases.Add(new {name=name,passed=true}); }
    static object Call(string name,params object[] args) { return Installer.GetMethod(name,Flags).Invoke(null,args); }
    static object Get(object obj,string name) { return obj.GetType().GetField(name,Fields).GetValue(obj); }
    static void Set(object obj,string name,object value) { obj.GetType().GetField(name,Fields).SetValue(obj,value); }
    static object NewResult() { return Activator.CreateInstance(Result,true); }
    static object NewOptions(bool remove) { object value=Activator.CreateInstance(Options,true); Set(value,"RemovePrevious",remove); return value; }
    static string Hash(string path) {
        using(var algorithm=SHA256.Create()) using(var stream=File.OpenRead(path))
            return BitConverter.ToString(algorithm.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
    }
    static void Put(string path,string name,string value) { using(var key=Root.CreateSubKey(path)) key.SetValue(name,value); }
    static string Reg(string path,string name) { using(var key=Root.OpenSubKey(path)) return key==null?null:key.GetValue(name,null) as string; }
    static bool Exists(string path) { using(var key=Root.OpenSubKey(path)) return key!=null; }
    static void Register(string suffix,string directory,string version,string owner) {
        string key=Uninstall+suffix;
        Put(key,"InstallLocation",directory); Put(key,"DisplayVersion",version); Put(key,"PDFModderApplicationId",owner);
        Put(key,"UninstallString","\""+Path.Combine(directory,"Desinstalar.exe")+"\" --dir \""+directory+"\"");
    }
    static string Fixture(string relative,string version,string owner) {
        string root=Path.Combine(Work,relative); Directory.CreateDirectory(root);
        File.Copy(Path.Combine(Binaries,"Uninstall-"+(version=="3.0.0"||version=="3.0.1"||version=="3.0.2"||version=="3.0.4"?version:"3.0.5")+".exe"),Path.Combine(root,"Desinstalar.exe"));
        File.WriteAllText(Path.Combine(root,"PDFModder.exe"),"original executable "+version);
        File.WriteAllText(Path.Combine(root,"PDFModderShellActions.exe"),"shell actions "+version);
        File.WriteAllText(Path.Combine(root,"settings.ini"),"original configuration "+version);
        File.WriteAllText(Path.Combine(root,Marker),new JavaScriptSerializer().Serialize(new {application_id=owner,version=version}),new UTF8Encoding(false));
        var manifest=new StringBuilder();
        foreach(string name in new[]{"PDFModder.exe","PDFModderShellActions.exe","Desinstalar.exe","settings.ini"}) {
            string path=Path.Combine(root,name);
            manifest.Append(Hash(path)).Append('\t').Append(new FileInfo(path).Length).Append('\t').Append(name).Append('\n');
        }
        File.WriteAllText(Path.Combine(root,Manifest),manifest.ToString(),new UTF8Encoding(false));
        File.WriteAllText(Path.Combine(root,"settings.ini"),"user modified configuration "+version);
        Directory.CreateDirectory(Path.Combine(root,"documentos"));
        File.WriteAllText(Path.Combine(root,"documentos","personal.pdf"),"personal document "+version);
        return root;
    }
    static HashSet<string> Locations(object previous) {
        var paths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(object value in (IEnumerable)previous) Check(paths.Add((string)Get(value,"Directory")),"Duplicate previous directory");
        return paths;
    }
    static Dictionary<string,long> FilesUnder(IEnumerable<string> roots) {
        var files=new Dictionary<string,long>(StringComparer.OrdinalIgnoreCase);
        foreach(string root in roots) foreach(string path in Directory.GetFiles(root,"*",SearchOption.AllDirectories)) files[path]=new FileInfo(path).Length;
        return files;
    }
    static long MissingBytes(Dictionary<string,long> files) {
        long total=0; foreach(var pair in files) if(!File.Exists(pair.Key)) total+=pair.Value; return total;
    }
    static void Clean(object options,object previous,object result,bool registered,bool associated) {
        Action<int,string> progress=delegate {};
        Call("CleanupPreviousInstallations",options,previous,Current,result,registered,associated,progress);
    }
    static void RemoveFixture(RegistryKey parent,string path) {
        using(var key=parent.OpenSubKey(path,true)) {
            if(key==null) return;
            foreach(string child in key.GetSubKeyNames()) RemoveFixture(key,child);
        }
        parent.DeleteSubKey(path,false);
    }
    [STAThread] static int Main(string[] args) {
        string keyPath=args[0],report=args[4]; Work=args[1]; Binaries=args[3]; int code=0;
        var outcome=new Dictionary<string,object>();
        Check(keyPath.StartsWith(@"Software\PDFModderUpgradeTests\",StringComparison.Ordinal),"Unsafe test key");
        try {
            Root=Registry.CurrentUser.CreateSubKey(keyPath);
            Environment.SetEnvironmentVariable("PDFMODDER_UPGRADE_TEST_KEY",keyPath);
            var assembly=Assembly.LoadFile(Path.GetFullPath(args[2]));
            Installer=assembly.GetType("PdfModderInstallation.Installer",true);
            Result=assembly.GetType("PdfModderInstallation.Result",true); Options=assembly.GetType("PdfModderInstallation.Options",true);
            string known=Path.Combine(Work,"known"),cache=Path.Combine(Work,"updates"); Directory.CreateDirectory(known); Directory.CreateDirectory(cache);
            Installer.GetField("UserRegistryRoot",Flags).SetValue(null,Root);
            Installer.GetField("PreviousInstallationsRoot",Flags).SetValue(null,known);
            Installer.GetField("UpdateCacheRoot",Flags).SetValue(null,cache);
            Current=Fixture("current", "3.0.6",Id);
            string latest=Fixture("registered latest á", "3.0.5",Id),failed=Fixture("registered older", "3.0.4",Id);
            string orphan=Fixture(Path.Combine("known","orphan"),"3.0.2",Id);
            string backup=Fixture(Path.Combine("known","custom.copia-older"),"3.0.0",Id);
            string explicitOld=Fixture("unregistered previous","3.0.1",Id);
            Register("3.0.5",latest,"3.0.5",Id); Register("3.0.4",failed,"3.0.4",Id);
            Register("3.0.5-duplicate",latest.ToUpperInvariant(),"3.0.5",Id);
            Register("3.0.6",Current,"3.0.6",Id);
            string newer=Fixture(Path.Combine("known","newer"),"3.0.7",Id); Register("3.0.7",newer,"3.0.7",Id);
            string currentOther=Fixture(Path.Combine("known","same version"),"3.0.6",Id);
            string foreign=Fixture(Path.Combine("known","3.0.3"),"3.0.3","Another.Application"); Register("3.0.3",foreign,"3.0.3",Id);
            string wrongOwner=Fixture("foreign registration","3.0.2",Id); Register("foreign-owner",wrongOwner,"3.0.2","Another.Application");
            string mismatch=Fixture("mismatched registration","3.0.2",Id); Register("mismatched",mismatch,"3.0.1",Id);
            string partial=Fixture(Path.Combine("known","partial"),"3.0",Id);
            string leadingZero=Fixture(Path.Combine("known","leading zero"),"03.0.5",Id);
            string altered=Fixture(Path.Combine("known","altered uninstaller"),"3.0.5",Id); File.AppendAllText(Path.Combine(altered,"Desinstalar.exe"),"altered");
            string guessed=Path.Combine(known,"PDFModder-3.0.1"); Directory.CreateDirectory(guessed); File.WriteAllText(Path.Combine(guessed,"personal.pdf"),"keep");
            object previous=Call("DiscoverPreviousInstallations",Current,explicitOld);
            HashSet<string> locations=Locations(previous);
            Check(locations.SetEquals(new[]{latest,failed,orphan,backup,explicitOld}),"Discovery did not return exactly the five recognized older copies");
            Check((string)Call("DiscoverPrevious",Current)==latest,"Legacy discovery no longer selects highest version");
            Pass("all_registered_orphan_and_explicit_older_copies_are_discovered_and_deduplicated");
            Check(!locations.Contains(Current)&&!locations.Contains(newer)&&!locations.Contains(currentOther)&&!locations.Contains(foreign)&&!locations.Contains(wrongOwner)&&!locations.Contains(mismatch)&&!locations.Contains(partial)&&!locations.Contains(leadingZero)&&!locations.Contains(altered)&&!locations.Contains(guessed),"Unrecognized copy was selected");
            try { Call("DiscoverPreviousInstallations",Current,Current); throw new Exception("Current target accepted as previous"); }
            catch(TargetInvocationException ex) { Check(ex.InnerException is IOException,"Wrong same-target failure"); }
            Pass("current_newer_foreign_modified_and_ambiguous_copies_are_preserved");
            // Add a backup only after discovery, as happens when the destination is moved aside.
            string lateBackup=Fixture("late.copia-verified","3.0.5",Id);
            // Old registration still points at the original root now occupied by 3.0.6.
            Register("3.0.5",Current,"3.0.5",Id);
            object associationResult=NewResult();
            Check((bool)Call("RegisterPdfAssociations",Current,associationResult),"Could not create isolated PDF associations");
            Check((bool)Call("RegisterShellActions",Current,associationResult),"Could not create isolated shell actions");
            var preserved=new[]{Current,newer,currentOther,foreign,wrongOwner,mismatch,partial,leadingZero,altered,guessed};
            var allBefore=FilesUnder(preserved); var oldBefore=FilesUnder(new[]{latest,failed,orphan,backup,explicitOld,lateBackup});
            // Cached installer fixtures include valid old files plus lookalikes to preserve.
            string oldCache=Path.Combine(cache,"PDFModder-v3.0.4-Instalar.exe"), oldCache2=Path.Combine(cache,"PDFModder-v3.0.5-Instalar.exe");
            File.Copy(Path.Combine(Binaries,"Cache-old.exe"),oldCache); File.Copy(Path.Combine(Binaries,"Cache-old2.exe"),oldCache2);
            var cacheKeep=new List<string>();
            foreach(string name in new[]{"current","newer","foreign","wrongversion","wrongtitle"}) {
                string filename=name=="current"?"3.0.6":name=="newer"?"3.0.7":name=="foreign"?"3.0.3":name=="wrongversion"?"3.0.2":"3.0.1";
                string path=Path.Combine(cache,"PDFModder-v"+filename+"-Instalar.exe"); File.Copy(Path.Combine(Binaries,"Cache-"+name+".exe"),path); cacheKeep.Add(path);
            }
            foreach(string name in new[]{"PDFModder-v3.0.0-Instalar.exe","PDFModder-v03.0.0-Instalar.exe","PDFModder-v3.0.4-Instalar.exe.part"}) { string path=Path.Combine(cache,name);File.WriteAllText(path,"user file");cacheKeep.Add(path); }
            string nested=Path.Combine(cache,"nested");Directory.CreateDirectory(nested);File.Copy(Path.Combine(Binaries,"Cache-old.exe"),Path.Combine(nested,"PDFModder-v3.0.4-Instalar.exe"));cacheKeep.Add(Path.Combine(nested,"PDFModder-v3.0.4-Instalar.exe"));
            long cacheBytes=new FileInfo(oldCache).Length+new FileInfo(oldCache2).Length;
            foreach(bool[] state in new[]{new[]{false,true},new[]{true,false},new[]{false,false}}) {
                object blocked=NewResult(); Set(blocked,"backup",lateBackup); Clean(NewOptions(true),previous,blocked,state[0],state[1]);
                Check(MissingBytes(oldBefore)==0&&File.Exists(oldCache)&&File.Exists(oldCache2),"Failed registration caused cleanup");
                Check((long)Get(blocked,"reclaimed_bytes")==0 && (int)Get(blocked,"removed_installations")==0,"Blocked cleanup claimed removed copies");
            }
            object kept=NewResult();Set(kept,"backup",lateBackup);Clean(NewOptions(false),previous,kept,true,true);
            Check(MissingBytes(oldBefore)==0&&File.Exists(oldCache),"--keep-previous caused cleanup");
            Pass("cleanup_waits_for_complete_registration_and_honors_keep_previous");
            // A changed uninstaller between discovery and retirement must be skipped;
            // retirement of other installations must continue.
            File.AppendAllText(Path.Combine(failed,"Desinstalar.exe"),"changed during update");
            object result=NewResult();Set(result,"backup",lateBackup);Clean(NewOptions(true),previous,result,true,true);
            Check((int)Get(result,"removed_installations")==5,"Did not retire every other verified installation");
            var removed=(List<string>)Get(result,"removed_versions");
            Check(new HashSet<string>(removed).SetEquals(new[]{"3.0.5","3.0.2","3.0.1","3.0.0"}),"Wrong removed versions");
            Check(File.Exists(Path.Combine(failed,Marker))&&File.Exists(Path.Combine(failed,"PDFModder.exe")),"Changed uninstaller was retired");
            foreach(string root in new[]{latest,orphan,backup,explicitOld,lateBackup}) {
                Check(!File.Exists(Path.Combine(root,"PDFModder.exe"))&&!File.Exists(Path.Combine(root,"Desinstalar.exe"))&&!File.Exists(Path.Combine(root,Marker)),"Old program payload remains");
                Check(File.ReadAllText(Path.Combine(root,"settings.ini")).StartsWith("user modified"),"User modification was lost");
                Check(File.ReadAllText(Path.Combine(root,"documentos","personal.pdf")).StartsWith("personal document"),"Personal PDF was lost");
            }
            Check((bool)Get(result,"previous_removed")&&((List<string>)Get(result,"warnings")).Count>0,"Legacy result or warning missing");
            Pass("all_old_programs_are_retired_while_documents_and_modified_files_survive_one_failure");
            Check(MissingBytes(allBefore)==0,"A protected current/newer/foreign copy changed");
            Check(Exists(Uninstall+"3.0.6") && Reg(Uninstall+"3.0.6","InstallLocation")==Current,"New uninstall registration was removed");
            Check(!Exists(Uninstall+"3.0.5"),"Stale backup registration still points at the new uninstaller");
            string verb=@"Software\Classes\SystemFileAssociations\.pdf\shell\PDFModder.CombinePdf";
            Check(Reg(verb,"PDFModderInstallRoot")==Current,"New context menu was removed");
            Check(Reg(@"Software\Classes\PDFModder.Document\shell\open\command","")=="\""+Path.Combine(Current,"PDFModder.exe")+"\" \"%1\"","New PDF association was removed");
            Pass("old_uninstallers_keep_new_registration_and_same_folder_backup_registration_is_retired");
            Check((int)Get(result,"cached_installers_removed")==2&&!File.Exists(oldCache)&&!File.Exists(oldCache2),"Verified old installer cache not cleaned");
            foreach(string path in cacheKeep) Check(File.Exists(path),"Foreign/current/newer/nested/incomplete cache file deleted: "+path);
            long recovered=MissingBytes(oldBefore)+cacheBytes;
            Check((long)Get(result,"reclaimed_bytes")==recovered,"Recovered bytes do not match removed files");
            outcome["reclaimed_bytes"]=recovered; outcome["removed_installations"]=Get(result,"removed_installations");
            Pass("cache_cleanup_requires_product_title_and_matching_older_PE_versions_and_counts_actual_bytes");
            outcome["ok"]=true;
        } catch(Exception ex) { outcome["ok"]=false;outcome["error"]=ex.ToString();code=1; }
        finally {
            if(Root!=null) Root.Close();
            try { RemoveFixture(Registry.CurrentUser,keyPath); using(var remaining=Registry.CurrentUser.OpenSubKey(keyPath)) outcome["temporary_registry_removed"]=remaining==null; }
            catch(Exception ex) { outcome["temporary_registry_removed"]=false;outcome["cleanup_error"]=ex.ToString();code=1; }
            outcome["scenarios"]=Cases;
            File.WriteAllText(report,new JavaScriptSerializer().Serialize(outcome),new UTF8Encoding(false));
        }
        return code;
    }
}
'''


def _compile(work, name, sources, *, library=False, main=None):
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    output = work / (name + ('.dll' if library else '.exe'))
    command = [compiler, '/nologo', '/platform:x64', '/target:' + ('library' if library else 'exe'),
               '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
               '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
               '/reference:System.IO.Compression.FileSystem.dll', '/out:' + str(output)]
    if main:
        command.append('/main:' + main)
    result = subprocess.run([str(value) for value in (*command, *sources)], cwd=work,
                            capture_output=True, text=True, timeout=45,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def _versioned(source, version, target):
    content = source.read_text(encoding='utf-8-sig')
    template = re.search(r'const string Version = "([0-9.]+)"', content).group(1)
    target.write_text(content.replace(template, version), encoding='utf-8-sig')
    return target


def test_production_upgrade_cleanup_preserves_documents_and_current_registration(tmp_path):
    import winreg

    def snapshot(path):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            return None
        with key:
            children, values, _ = winreg.QueryInfoKey(key)
            return (tuple(sorted(winreg.EnumValue(key, index) for index in range(values))),
                    tuple((name, snapshot(path + '\\' + name)) for name in sorted(winreg.EnumKey(key, index) for index in range(children))))

    real_paths = [r'Software\Microsoft\Windows\CurrentVersion\Uninstall\PDFModder-' + version
                  for version in ('3.0.0', '3.0.1', '3.0.2', '3.0.4', '3.0.5', '3.0.6', '3.0.7')]
    real_paths.extend([r'Software\Classes\PDFModder.Document',
                       r'Software\Classes\Applications\PDFModder.exe',
                       r'Software\PDFModder\Capabilities', r'Software\RegisteredApplications'])
    real_paths.extend('Software\\Classes\\SystemFileAssociations\\' + extension
                      for extension in ('.pdf', '.doc', '.docx'))
    real_paths.extend('Software\\Classes\\CLSID\\' + value for value in
                      ('{2C75E6DF-A2CB-49C1-871F-B0D9E30CB26E}', '{F43E797E-C01B-4C4E-929A-1C6258406FC5}'))
    before = [snapshot(path) for path in real_paths]
    sources = [ROOT / 'installer' / name for name in ('PdfModderInstaller.cs', 'PdfModderUninstaller.cs')]
    generated = _versioned(sources[0], '3.0.6', tmp_path / 'Installer.cs')
    installer = _compile(tmp_path, 'Installer', [generated], library=True)
    wrapper = tmp_path / 'UninstallEntry.cs'
    wrapper.write_text(UNINSTALL_ENTRY, encoding='utf-8-sig')
    for version in ('3.0.0', '3.0.1', '3.0.2', '3.0.4', '3.0.5'):
        generated = _versioned(sources[1], version, tmp_path / ('Uninstaller-' + version + '.cs'))
        _compile(tmp_path, 'Uninstall-' + version, [generated, wrapper], main='UpgradeUninstallEntry')
    cache_fixtures = [('old', '3.0.4', 'PDF Modder', None), ('old2', '3.0.5', 'PDF Modder', None),
                      ('current', '3.0.6', 'PDF Modder', None), ('newer', '3.0.7', 'PDF Modder', None),
                      ('foreign', '3.0.3', 'Another product', None), ('wrongversion', '3.0.1', 'PDF Modder', None),
                      ('wrongtitle', '3.0.1', 'PDF Modder', 'Another title')]
    for name, version, product, title in cache_fixtures:
        fixture = tmp_path / ('Cache-' + name + '.cs')
        fixture.write_text('using System.Reflection;\n'
                           + f'[assembly: AssemblyTitle("{title or "Instalar PDF Modder " + version}")]\n'
                           + f'[assembly: AssemblyProduct("{product}")]\n'
                           + f'[assembly: AssemblyVersion("{version}.1")]\n'
                           + f'[assembly: AssemblyFileVersion("{version}.1")]\n'
                           + 'class CacheFixture { static void Main() {} }\n', encoding='utf-8-sig')
        _compile(tmp_path, 'Cache-' + name, [fixture])
    harness = tmp_path / 'Harness.cs'
    harness.write_text(HARNESS, encoding='utf-8-sig')
    executable = _compile(tmp_path, 'Harness', [harness])
    key = 'Software\\PDFModderUpgradeTests\\' + uuid.uuid4().hex
    fixtures = tmp_path / 'fixtures'
    fixtures.mkdir()
    report_path = tmp_path / 'upgrade.json'
    try:
        result = subprocess.run([str(value) for value in (executable, key, fixtures, installer, tmp_path, report_path)],
                                cwd=tmp_path, capture_output=True, text=True, timeout=180,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        report = json.loads(report_path.read_text(encoding='utf-8-sig')) if report_path.exists() else {}
        assert result.returncode == 0 and report.get('ok'), result.stdout + result.stderr + json.dumps(report, indent=2)
        assert len(report['scenarios']) == 6 and all(case['passed'] for case in report['scenarios'])
        assert report['temporary_registry_removed'] and snapshot(key) is None
        assert [snapshot(path) for path in real_paths] == before, 'Real Windows application registry was changed'
        report['source_sha256'] = {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}
        (ROOT / 'output').mkdir(exist_ok=True)
        (ROOT / 'output' / 'upgrade-cleanup-v306.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    finally:
        def remove(path):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as root:
                    names = [winreg.EnumKey(root, index) for index in range(winreg.QueryInfoKey(root)[0])]
                for name in names:
                    remove(path + '\\' + name)
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
        remove(key)
        # Workers are exact paths written by our fixture-only entry point. Do not
        # scan or remove any other uninstall worker or user's temporary files.
        for record in fixtures.glob('updates/retirada-*.json.worker-path'):
            worker = Path(record.read_text(encoding='utf-8-sig'))
            folder = worker.parent
            assert worker.name == 'Desinstalar.exe'
            assert folder.parent.resolve() == Path(tempfile.gettempdir()).resolve()
            assert re.fullmatch(r'PDFModder-uninstall-[0-9a-f]{32}', folder.name)
            assert {child.name for child in folder.iterdir()} == {'Desinstalar.exe'}
            for attempt in range(30):
                try:
                    worker.unlink()
                    folder.rmdir()
                    break
                except PermissionError:
                    time.sleep(0.1)
            else:
                pytest.fail(f'Test uninstall worker is still running: {worker}')
        assert [snapshot(path) for path in real_paths] == before, 'Real Windows application registry was changed'
