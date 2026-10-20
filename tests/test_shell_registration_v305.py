"""Exercise production shell registration and a real Windows selection array."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Requires Windows shell COM, HKCU and Framework compiler')

REGISTRATION_HARNESS = r'''
using System;
using System.IO;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Web.Script.Serialization;
using Microsoft.Win32;
class ShellRegistrationHarness {
    [DllImport("advapi32.dll")] static extern int RegOverridePredefKey(IntPtr key, IntPtr replacement);
    static BindingFlags Flags = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;
    const string ConvertId="{2C75E6DF-A2CB-49C1-871F-B0D9E30CB26E}", CombineId="{F43E797E-C01B-4C4E-929A-1C6258406FC5}";
    static RegistryKey Root;
    static Type Installer, Cleaner, Result;
    static List<object> Cases=new List<object>();
    static void Check(bool value,string name) { if(!value) throw new Exception(name); }
    static void Pass(string name) { Cases.Add(new {name=name,passed=true}); }
    static void Put(string path,string name,string value) { using(var key=Root.CreateSubKey(path)) key.SetValue(name,value); }
    static string Get(string path,string name) { using(var key=Root.OpenSubKey(path)) return key==null ? null : key.GetValue(name,null) as string; }
    static bool Exists(string path) { using(var key=Root.OpenSubKey(path)) return key!=null; }
    static string Verb(string extension) { return @"Software\Classes\SystemFileAssociations\"+extension+@"\shell\"+(extension==".pdf"?"PDFModder.CombinePdf":"PDFModder.ConvertToPdf"); }
    static string Class(string clsid) { return @"Software\Classes\CLSID\"+clsid; }
    static bool Register(string path) {
        return (bool)Installer.GetMethod("RegisterShellActions",Flags).Invoke(null,new object[]{path,Activator.CreateInstance(Result,true)});
    }
    static void Remove(string path) {
        var warnings=new List<string>();
        Cleaner.GetMethod("RemoveShellActions",Flags).Invoke(null,new object[]{path,warnings});
        Check(warnings.Count==0,"Unexpected cleanup warning");
    }
    static void AssertCurrent(string root) {
        string server="\""+Path.Combine(root,"PDFModderShellActions.exe")+"\" --com-server";
        foreach(string ext in new[]{".pdf",".doc",".docx"}) {
            string verb=Verb(ext), clsid=ext==".pdf"?CombineId:ConvertId;
            Check(Get(verb,"MUIVerb")== (ext==".pdf"?"Combinar archivos PDF":"Convertir a PDF"),"Missing menu label");
            Check(Get(verb,"MultiSelectModel")=="Player","Not an all-selection action");
            Check(Get(verb,"PDFModderInstallRoot")==root,"Stale menu root");
            Check(Get(verb+@"\command","DelegateExecute")==clsid && Get(verb+@"\command","")=="","Missing delegated selection command");
            Check(!Exists(@"Software\Classes\SystemFileAssociations\"+ext+@"\shell\"+(ext==".pdf"?"PDFModder.ConvertToPdf":"PDFModder.CombinePdf")),"Unexpected action for extension");
        }
        foreach(string clsid in new[]{ConvertId,CombineId}) {
            Check(Get(Class(clsid)+@"\LocalServer32","")==server,"Stale COM server command");
            Check(Get(Class(clsid),"PDFModderInstallRoot")==root,"Stale COM ownership root");
            Check(!Exists(Class(clsid)+@"\InprocServer32"),"Managed code would load into Explorer");
        }
    }
    static int Main(string[] args) {
        string temporary=args[0], work=args[1], report=args[4];
        var outcome=new Dictionary<string,object>(); bool overridden=false; int code=0;
        Check(temporary.StartsWith(@"Software\PDFModderShellTests\",StringComparison.Ordinal),"Unsafe test key");
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
            string old=Path.Combine(work,"anterior á 3.0.4"), current=Path.Combine(work,"nueva versión 3.0.5");
            foreach(string root in new[]{old,current}) {
                Directory.CreateDirectory(root);
                File.WriteAllText(Path.Combine(root,"PDFModder.exe"),"fixture");
                File.WriteAllText(Path.Combine(root,"PDFModderShellActions.exe"),"fixture");
            }
            foreach(string ext in new[]{".pdf",".doc",".docx"}) {
                Put(@"Software\Classes\"+ext,"","OtherApplication"+ext);
                Put(@"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\"+ext+@"\UserChoice","ProgId","OtherApplication"+ext);
                Put(@"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\"+ext+@"\UserChoice","Hash","unaltered");
                Put(@"Software\Classes\SystemFileAssociations\"+ext+@"\shell\OtherAction\command","","keep-command");
            }
            Check(Register(old),"Initial registration failed"); AssertCurrent(old);
            Check(Register(current),"Update registration failed"); AssertCurrent(current);
            Pass("register_and_update_complete_selection_actions_with_spaces_and_unicode");
            Remove(old); AssertCurrent(current);
            Pass("old_uninstaller_preserves_newer_menu_and_com_server");
            string deniedPath=Verb(".docx")+@"\command";
            System.Security.AccessControl.RegistrySecurity originalAcl;
            using(var key=Root.OpenSubKey(deniedPath,RegistryKeyPermissionCheck.ReadWriteSubTree,
                  RegistryRights.ChangePermissions | RegistryRights.ReadKey)) {
                originalAcl=key.GetAccessControl();
                var denied=key.GetAccessControl();
                denied.AddAccessRule(new RegistryAccessRule(WindowsIdentity.GetCurrent().User,RegistryRights.SetValue,
                    InheritanceFlags.None,PropagationFlags.None,AccessControlType.Deny));
                key.SetAccessControl(denied);
            }
            try {
                Check(!Register(old),"Denied intermediate write reported success");
                AssertCurrent(current);
            } finally {
                using(var key=Root.OpenSubKey(deniedPath,RegistryKeyPermissionCheck.ReadWriteSubTree,
                      RegistryRights.ChangePermissions | RegistryRights.ReadKey)) key.SetAccessControl(originalAcl);
            }
            Pass("intermediate_registry_failure_restores_every_previous_verb_and_class");
            File.Delete(Path.Combine(old,"PDFModderShellActions.exe"));
            Check(!Register(old),"Missing helper reported success"); AssertCurrent(current);
            using(var closed=Root.CreateSubKey("ClosedFixture")) {
                closed.Close(); Installer.GetField("UserRegistryRoot",Flags).SetValue(null,closed);
                Check(!Register(current),"Registry failure reported success");
            }
            Installer.GetField("UserRegistryRoot",Flags).SetValue(null,Root); AssertCurrent(current);
            Pass("missing_helper_and_registry_errors_preserve_current_registration");
            Remove(current);
            foreach(string ext in new[]{".pdf",".doc",".docx"}) Check(!Exists(Verb(ext)),"Owned verb not removed");
            foreach(string clsid in new[]{ConvertId,CombineId}) Check(!Exists(Class(clsid)),"Owned COM server not removed");
            foreach(string ext in new[]{".pdf",".doc",".docx"}) {
                Check(Get(@"Software\Classes\"+ext,"")=="OtherApplication"+ext,"Default app changed");
                string choice=@"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\"+ext+@"\UserChoice";
                Check(Get(choice,"ProgId")=="OtherApplication"+ext && Get(choice,"Hash")=="unaltered","UserChoice changed");
                Check(Get(@"Software\Classes\SystemFileAssociations\"+ext+@"\shell\OtherAction\command","")=="keep-command","Other context menu removed");
            }
            Pass("uninstall_preserves_other_apps_defaults_userchoice_and_verbs");
            Put(Verb(".docx"),"PDFModderApplicationId","foreign-owner");
            Put(Verb(".docx"),"MUIVerb","Foreign label");
            Check(!Register(current),"Foreign-owned identifier overwritten");
            Check(!Exists(Verb(".doc")) && !Exists(Verb(".pdf")) && !Exists(Class(ConvertId)),"Conflict caused partial registration");
            Remove(current);
            Check(Get(Verb(".docx"),"MUIVerb")=="Foreign label","Foreign collision removed");
            Root.DeleteSubKeyTree(Verb(".docx"),false);
            Pass("foreign_owned_identifiers_are_preflighted_and_never_deleted");
            Check(Register(current),"Final registration failed");
            Put(Verb(".pdf")+@"\command","DelegateExecute","{00000000-0000-0000-0000-000000000001}");
            Put(Class(ConvertId)+@"\LocalServer32","","different-server");
            Remove(current);
            Check(Exists(Verb(".pdf")) && Exists(Class(ConvertId)),"Modified handler removed");
            Check(!Exists(Verb(".doc")) && !Exists(Verb(".docx")) && !Exists(Class(CombineId)),"Unmodified owned handler retained");
            Pass("uninstall_preserves_handlers_changed_by_another_installation");
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

SELECTION_HARNESS = r'''
using System;
using System.IO;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using PdfModderShellActions;
class ShellSelectionHarness {
    [DllImport("shell32.dll",CharSet=CharSet.Unicode)] static extern int SHParseDisplayName(string name,IntPtr bind,out IntPtr item,uint mask,out uint attributes);
    [DllImport("shell32.dll")] static extern int SHCreateShellItemArrayFromIDLists(uint count,[MarshalAs(UnmanagedType.LPArray,SizeParamIndex=0)] IntPtr[] items,out IShellItemArray selection);
    static List<object> Cases=new List<object>();
    static void Check(bool value,string name) { if(!value) throw new Exception(name); }
    static void Pass(string name) { Cases.Add(new {name=name,passed=true}); }
    static IShellItemArray Select(params string[] paths) {
        var items=new IntPtr[paths.Length];
        try {
            for(int i=0;i<paths.Length;i++) {
                uint attrs;
                Marshal.ThrowExceptionForHR(SHParseDisplayName(paths[i],IntPtr.Zero,out items[i],0,out attrs));
            }
            IShellItemArray selected;
            Marshal.ThrowExceptionForHR(SHCreateShellItemArrayFromIDLists((uint)items.Length,items,out selected));
            return selected;
        } finally { foreach(IntPtr item in items) if(item!=IntPtr.Zero) Marshal.FreeCoTaskMem(item); }
    }
    static void Release(IShellItemArray selection) { if(selection!=null && Marshal.IsComObject(selection)) Marshal.ReleaseComObject(selection); }
    [STAThread] static int Main(string[] args) {
        string work=args[0], report=args[1];
        var outcome=new Dictionary<string,object>(); int code=0;
        try {
            Application.OleRequired();
            string documents=Path.Combine(work,"documentos con á y espacios");
            Directory.CreateDirectory(documents);
            string first=Path.Combine(documents,"primero á.pdf"), second=Path.Combine(documents,"segundo & (final).PDF");
            string doc=Path.Combine(documents,"antiguo.doc"), docx=Path.Combine(documents,"actual.docx");
            foreach(string path in new[]{first,second,doc,docx}) File.WriteAllText(path,"fixture-original");
            SelectionRequest.RequestRoot=Path.Combine(work,"request-owner","shell-requests");
            string[] selected;
            var pdfs=Select(first,second);
            try {
                selected=SelectionRequest.Paths(pdfs,"combine");
                Check(selected.Length==2 && selected[0]==first && selected[1]==second,"Not every selected PDF was retained in order");
                var command=new ShellCommand("combine"); command.SetNoShowUI(true);
                Check(command.SetSelection(pdfs)==0 && command.Execute()==0,"Delegated command failed");
            } finally { Release(pdfs); }
            string log=Path.Combine(work,"invocations.txt");
            var timeout=DateTime.UtcNow.AddSeconds(10);
            while(!File.Exists(log) && DateTime.UtcNow<timeout) Thread.Sleep(25);
            Check(File.Exists(log),"Application was not launched");
            // The stub writes atomically, so a visible log is complete.
            string[] invocations=File.ReadAllLines(log,Encoding.UTF8);
            Check(invocations.Length==1,"The application was invoked more than once for one selection");
            Check(Directory.GetFiles(Path.Combine(work,"invocation-count")).Length==1,"More than one application process was launched");
            string request=invocations[0];
            Check(Directory.GetFiles(SelectionRequest.RequestRoot,"*.request.json").Length==1,"More than one request was created");
            Check(Path.GetFileName(request).Length==45 && Path.GetFileName(request).EndsWith(".request.json"),"Unexpected request filename");
            byte[] bytes=File.ReadAllBytes(request);
            Check(bytes.Length<3 || !(bytes[0]==239 && bytes[1]==187 && bytes[2]==191),"Unexpected UTF8 BOM");
            var data=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(bytes));
            Check((int)data["schema"]==1 && (string)data["action"]=="combine","Wrong request protocol");
            var paths=(System.Collections.IList)data["paths"];
            Check(paths.Count==2 && (string)paths[0]==first && (string)paths[1]==second,"Request lost selected paths");
            Pass("native_shell_array_launches_one_request_containing_every_selected_pdf");
            var rules=new DirectoryInfo(SelectionRequest.RequestRoot).GetAccessControl();
            Check(rules.AreAccessRulesProtected,"Request directory inherited broad permissions");
            var sid=WindowsIdentity.GetCurrent().User;
            foreach(FileSystemAccessRule rule in rules.GetAccessRules(true,true,typeof(SecurityIdentifier)))
                Check(rule.IdentityReference.Equals(sid) && rule.AccessControlType==AccessControlType.Allow,"Request readable by another principal");
            Pass("request_is_utf8_without_bom_in_a_current_user_only_directory");
            var words=Select(doc,docx);
            try {
                string[] wordPaths=SelectionRequest.Paths(words,"convert");
                Check(wordPaths.Length==2 && wordPaths[0]==doc && wordPaths[1]==docx,"DOC and DOCX selection failed");
            } finally { Release(words); }
            Pass("native_word_selection_accepts_both_doc_and_docx");
            var mixed=Select(first,docx);
            bool blocked=false;
            try { SelectionRequest.Paths(mixed,"combine"); } catch(IOException) { blocked=true; } finally { Release(mixed); }
            Check(blocked && Directory.GetFiles(SelectionRequest.RequestRoot,"*.request.json").Length==1,"Mixed selection was partially accepted");
            foreach(string path in new[]{first,second,doc,docx}) Check(File.ReadAllText(path)=="fixture-original","Input file was modified");
            Pass("incompatible_selection_is_rejected_as_a_whole_and_inputs_are_untouched");
            outcome["ok"]=true;
        } catch(Exception ex) { outcome["ok"]=false; outcome["error"]=ex.ToString(); code=1; }
        finally {
            outcome["scenarios"]=Cases;
            File.WriteAllText(report,new JavaScriptSerializer().Serialize(outcome));
        }
        return code;
    }
}
'''

LAUNCH_STUB = r'''
using System;
using System.IO;
using System.Reflection;
using System.Text;
class ApplicationStub {
    static int Main(string[] args) {
        if(args.Length!=2 || args[0]!="--shell-request" || !File.Exists(args[1])) return 1;
        string log=Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location),"invocations.txt");
        string calls=Path.Combine(Path.GetDirectoryName(log),"invocation-count");
        Directory.CreateDirectory(calls);
        File.WriteAllText(Path.Combine(calls,Guid.NewGuid().ToString("N")),"called");
        string temporary=log+".tmp";
        File.WriteAllText(temporary,args[1]+Environment.NewLine,new UTF8Encoding(false));
        File.Move(temporary,log);
        return 0;
    }
}
'''


ACTIVATION_HARNESS = r'''
using System;
using System.IO;
using System.Diagnostics;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;
using PdfModderShellActions;
class ShellActivationHarness {
    [DllImport("ole32.dll")] static extern int CoCreateInstance(ref Guid clsid,IntPtr outer,uint context,ref Guid iid,out IntPtr instance);
    [DllImport("shell32.dll",CharSet=CharSet.Unicode)] static extern int SHParseDisplayName(string name,IntPtr bind,out IntPtr item,uint mask,out uint attributes);
    [DllImport("shell32.dll")] static extern int SHCreateShellItemArrayFromIDLists(uint count,[MarshalAs(UnmanagedType.LPArray,SizeParamIndex=0)] IntPtr[] items,out IShellItemArray selection);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SetSelectionCall(IntPtr self,[MarshalAs(UnmanagedType.Interface)] IShellItemArray selection);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetSelectionCall(IntPtr self,ref Guid iid,out IntPtr selection);
    static void Check(bool value,string name) { if(!value) throw new Exception(name); }
    static object Call(IntPtr instance,int slot,Type signature) {
        return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(instance),slot*IntPtr.Size),signature);
    }
    static IntPtr Query(IntPtr instance,string value) {
        Guid iid=new Guid(value); IntPtr result;
        Marshal.ThrowExceptionForHR(Marshal.QueryInterface(instance,ref iid,out result));
        return result;
    }
    static IShellItemArray Select(string first,string second) {
        var pidls=new IntPtr[2];
        try {
            uint attributes;
            Marshal.ThrowExceptionForHR(SHParseDisplayName(first,IntPtr.Zero,out pidls[0],0,out attributes));
            Marshal.ThrowExceptionForHR(SHParseDisplayName(second,IntPtr.Zero,out pidls[1],0,out attributes));
            IShellItemArray selected;
            Marshal.ThrowExceptionForHR(SHCreateShellItemArrayFromIDLists(2,pidls,out selected)); return selected;
        } finally { foreach(IntPtr pidl in pidls) if(pidl!=IntPtr.Zero) Marshal.FreeCoTaskMem(pidl); }
    }
    static void Register(string id,string executable,string owner) {
        string path=@"Software\Classes\CLSID\"+id;
        using(var existing=Registry.CurrentUser.OpenSubKey(path)) Check(existing==null,"Temporary CLSID already exists");
        using(var key=Registry.CurrentUser.CreateSubKey(path)) {
            key.SetValue("","PDF Modder isolated native COM test"); key.SetValue("PDFModderTestOwner",owner);
        }
        using(var key=Registry.CurrentUser.CreateSubKey(path+@"\LocalServer32")) key.SetValue("","\""+executable+"\" --com-server");
    }
    static void Remove(string id,string owner) {
        string path=@"Software\Classes\CLSID\"+id; bool own=false;
        using(var key=Registry.CurrentUser.OpenSubKey(path)) own=key!=null && (string)key.GetValue("PDFModderTestOwner",null)==owner;
        if(own) Registry.CurrentUser.DeleteSubKeyTree(path,false);
    }
    [STAThread] static int Main(string[] args) {
        string work=args[0], executable=args[1], convert=args[2], combine=args[3], report=args[4];
        var outcome=new Dictionary<string,object>(); var cases=new List<object>(); int code=0;
        IntPtr command=IntPtr.Zero, selectionInterface=IntPtr.Zero, initialize=IntPtr.Zero, returned=IntPtr.Zero;
        IShellItemArray original=null, roundtrip=null;
        try {
            Application.OleRequired();
            Register(convert,executable,work); Register(combine,executable,work);
            Guid id=new Guid(combine), iid=new Guid("7F9185B0-CB92-43C5-80A9-92277A4F7B54");
            Marshal.ThrowExceptionForHR(CoCreateInstance(ref id,IntPtr.Zero,4,ref iid,out command));
            selectionInterface=Query(command,"1C9CD5BB-98E9-4491-A60F-31AACC72B83C");
            initialize=Query(command,"85075ACF-231F-40EA-9610-D26B7B58F638");
            bool separate=false;
            foreach(Process process in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(executable))) {
                using(process) if(process.Id!=Process.GetCurrentProcess().Id && process.MainModule.FileName.Equals(executable,StringComparison.OrdinalIgnoreCase)) separate=true;
            }
            Check(separate,"COM did not launch the separate registered server");
            cases.Add(new {name="localserver32_activates_production_factory_and_all_delegate_interfaces",passed=true});
            string first=Path.Combine(work,"RPC primero á.pdf"), second=Path.Combine(work,"RPC segundo.pdf");
            File.WriteAllText(first,"first"); File.WriteAllText(second,"second"); original=Select(first,second);
            var set=(SetSelectionCall)Call(selectionInterface,3,typeof(SetSelectionCall));
            var get=(GetSelectionCall)Call(selectionInterface,4,typeof(GetSelectionCall));
            Marshal.ThrowExceptionForHR(set(selectionInterface,original));
            Guid arrayId=typeof(IShellItemArray).GUID;
            Marshal.ThrowExceptionForHR(get(selectionInterface,ref arrayId,out returned));
            roundtrip=(IShellItemArray)Marshal.GetObjectForIUnknown(returned);
            string[] paths=SelectionRequest.Paths(roundtrip,"combine");
            Check(paths.Length==2 && paths[0]==first && paths[1]==second,"RPC selection lost files");
            cases.Add(new {name="selection_roundtrips_over_real_out_of_process_com_rpc",passed=true});
            Marshal.Release(command); command=IntPtr.Zero;
            id=new Guid(convert);
            Marshal.ThrowExceptionForHR(CoCreateInstance(ref id,IntPtr.Zero,4,ref iid,out command));
            cases.Add(new {name="conversion_class_is_available_in_the_same_local_server",passed=true});
            outcome["ok"]=true;
        } catch(Exception ex) { outcome["ok"]=false; outcome["error"]=ex.ToString(); code=1; }
        finally {
            if(roundtrip!=null && Marshal.IsComObject(roundtrip)) Marshal.ReleaseComObject(roundtrip);
            if(returned!=IntPtr.Zero) Marshal.Release(returned);
            if(original!=null && Marshal.IsComObject(original)) Marshal.ReleaseComObject(original);
            foreach(IntPtr value in new[]{initialize,selectionInterface,command}) if(value!=IntPtr.Zero) Marshal.Release(value);
            Remove(convert,work); Remove(combine,work);
            // Clean up only the unique fixture executable if a failed client left a COM reference.
            foreach(Process process in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(executable))) {
                using(process) {
                    try { if(process.MainModule.FileName.Equals(executable,StringComparison.OrdinalIgnoreCase) && !process.WaitForExit(7000)) process.Kill(); }
                    catch(InvalidOperationException) { }
                }
            }
            outcome["scenarios"]=cases;
            File.WriteAllText(report,new JavaScriptSerializer().Serialize(outcome));
        }
        return code;
    }
}
'''


def _compile(work, name, sources, *, main=None, library=False):
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    output = work / (name + ('.dll' if library else '.exe'))
    args = [compiler, '/nologo', '/platform:x64', '/target:' + ('library' if library else 'exe'),
            '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
            '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
            '/reference:System.IO.Compression.FileSystem.dll', '/out:' + str(output)]
    if main:
        args.append('/main:' + main)
    _run([*args, *sources], work)
    return output


def _run(args, work):
    result = subprocess.run([str(a) for a in args], cwd=work, capture_output=True, text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def _report(name, report_path, sources):
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    assert report['ok'] and all(case['passed'] for case in report['scenarios']), report
    report['source_sha256'] = {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}
    (ROOT / 'output').mkdir(exist_ok=True)
    (ROOT / 'output' / name).write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def test_production_shell_registration_in_isolated_registry(tmp_path):
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

    paths = ['Software\\Classes\\CLSID\\' + clsid for clsid in
             ('{2C75E6DF-A2CB-49C1-871F-B0D9E30CB26E}', '{F43E797E-C01B-4C4E-929A-1C6258406FC5}')]
    for ext in ('.pdf', '.doc', '.docx'):
        paths.extend(('Software\\Classes\\' + ext, 'Software\\Classes\\SystemFileAssociations\\' + ext,
                      'Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\' + ext + r'\UserChoice'))
    before = [snapshot(path) for path in paths]
    sources = [ROOT / 'installer' / name for name in ('PdfModderInstaller.cs', 'PdfModderUninstaller.cs')]
    libraries = [_compile(tmp_path, 'library-' + str(index), [source], library=True) for index, source in enumerate(sources)]
    harness = tmp_path / 'RegistryHarness.cs'
    harness.write_text(REGISTRATION_HARNESS, encoding='utf-8-sig')
    executable = _compile(tmp_path, 'RegistryHarness', [harness])
    key = 'Software\\PDFModderShellTests\\' + uuid.uuid4().hex
    report = tmp_path / 'registry.json'
    try:
        _run([executable, key, tmp_path, *libraries, report], tmp_path)
        result = _report('shell-registration-v305.json', report, sources)
        assert len(result['scenarios']) == 7 and result['temporary_registry_removed']
        assert [snapshot(path) for path in paths] == before, 'Real shell registration was changed'
        assert snapshot(key) is None
    finally:
        def remove_tree(path):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as root:
                    names = [winreg.EnumKey(root, i) for i in range(winreg.QueryInfoKey(root)[0])]
                for name in names:
                    remove_tree(path + '\\' + name)
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
        remove_tree(key)


def test_native_shell_selection_preserves_all_files_in_one_launch(tmp_path):
    source = ROOT / 'installer/PdfModderShellActions.cs'
    harness = tmp_path / 'SelectionHarness.cs'
    harness.write_text(SELECTION_HARNESS, encoding='utf-8-sig')
    executable = _compile(tmp_path, 'SelectionHarness', [source, harness], main='ShellSelectionHarness')
    stub = tmp_path / 'ApplicationStub.cs'
    stub.write_text(LAUNCH_STUB, encoding='utf-8-sig')
    _compile(tmp_path, 'PDFModder', [stub])
    report = tmp_path / 'selection.json'
    _run([executable, tmp_path, report], tmp_path)
    result = _report('shell-selection-v305.json', report, [source])
    assert len(result['scenarios']) == 4


def test_native_com_local_server_activation_and_selection_rpc(tmp_path):
    import winreg

    source = ROOT / 'installer/PdfModderShellActions.cs'
    clsids = ['{' + str(uuid.uuid4()).upper() + '}' for _ in range(2)]
    generated = tmp_path / 'IsolatedShellServer.cs'
    text = source.read_text(encoding='utf-8-sig')
    for original, replacement in zip(('{2C75E6DF-A2CB-49C1-871F-B0D9E30CB26E}',
                                      '{F43E797E-C01B-4C4E-929A-1C6258406FC5}'), clsids):
        text = text.replace(original, replacement)
    generated.write_text(text, encoding='utf-8-sig')
    server = _compile(tmp_path, 'PdfModderShellTest-' + uuid.uuid4().hex, [generated])
    harness = tmp_path / 'ActivationHarness.cs'
    harness.write_text(ACTIVATION_HARNESS, encoding='utf-8-sig')
    executable = _compile(tmp_path, 'ActivationHarness', [generated, harness], main='ShellActivationHarness')
    report = tmp_path / 'activation.json'
    try:
        _run([executable, tmp_path, server, *clsids, report], tmp_path)
        result = _report('shell-activation-v305.json', report, [source])
        assert len(result['scenarios']) == 3
        for clsid in clsids:
            with pytest.raises(FileNotFoundError):
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Software\\Classes\\CLSID\\' + clsid)
    finally:
        # These unpredictable CLSIDs are this fixture's only real HKCU writes.
        for clsid in clsids:
            path = 'Software\\Classes\\CLSID\\' + clsid
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                    owner = winreg.QueryValueEx(key, 'PDFModderTestOwner')[0]
                if owner == str(tmp_path):
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path + '\\LocalServer32')
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except FileNotFoundError:
                pass
        # Also handles a crashed/timed-out harness; the name is unique per test.
        subprocess.run(['taskkill', '/F', '/T', '/IM', server.name], capture_output=True, timeout=20,
                       creationflags=subprocess.CREATE_NO_WINDOW)
