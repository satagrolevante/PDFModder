// PDF Modder Explorer selection bridge. SPDX-License-Identifier: AGPL-3.0-only
// Out-of-process COM: no CLR is loaded into Explorer and no administrator is needed.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("PDF Modder: acciones del Explorador")]
[assembly: AssemblyProduct("PDF Modder")]
[assembly: AssemblyVersion("1.7.0.0")]
[assembly: AssemblyFileVersion("1.7.0.0")]
[assembly: ComVisible(false)]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = ".NET Framework 4.8")]

namespace PdfModderShellActions
{
    internal static class SelectionRequest
    {
        internal const string ConvertClsid = "{2C75E6DF-A2CB-49C1-871F-B0D9E30CB26E}";
        internal const string CombineClsid = "{F43E797E-C01B-4C4E-929A-1C6258406FC5}";
        internal const int MaximumItems = 2000;
        internal const int MaximumBytes = 4 * 1024 * 1024;
        // Replaceable only by the compiled isolated harness, never a CLI option.
        internal static string RequestRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PDFModder", "shell-requests");

        internal static string[] Paths(IShellItemArray selection, string action)
        {
            if (selection == null) throw new IOException("Windows no proporcionó los archivos seleccionados.");
            uint count;
            Marshal.ThrowExceptionForHR(selection.GetCount(out count));
            if (count == 0 || count > MaximumItems)
                throw new IOException("Seleccione entre 1 y 2000 archivos.");
            var paths = new List<string>();
            var unique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (uint index = 0; index < count; index++)
            {
                IShellItem item = null;
                IntPtr name = IntPtr.Zero;
                try
                {
                    Marshal.ThrowExceptionForHR(selection.GetItemAt(index, out item));
                    Marshal.ThrowExceptionForHR(item.GetDisplayName(0x80058000, out name)); // SIGDN_FILESYSPATH
                    string path = Marshal.PtrToStringUni(name);
                    if (String.IsNullOrWhiteSpace(path) || !Path.IsPathRooted(path))
                        throw new IOException("La selección contiene un elemento sin ruta de archivo.");
                    path = Path.GetFullPath(path);
                    string extension = Path.GetExtension(path);
                    bool word = extension.Equals(".doc", StringComparison.OrdinalIgnoreCase) ||
                                extension.Equals(".docx", StringComparison.OrdinalIgnoreCase);
                    bool pdf = extension.Equals(".pdf", StringComparison.OrdinalIgnoreCase);
                    if (!(action == "convert" ? word : action == "combine" && pdf) || !File.Exists(path))
                        throw new IOException("La selección contiene un archivo inexistente o incompatible: " + Path.GetFileName(path));
                    if (unique.Add(path)) paths.Add(path);
                }
                finally
                {
                    if (name != IntPtr.Zero) Marshal.FreeCoTaskMem(name);
                    if (item != null && Marshal.IsComObject(item)) Marshal.ReleaseComObject(item);
                }
            }
            return paths.ToArray();
        }

        internal static string Write(string action, string[] paths)
        {
            if ((action != "convert" && action != "combine") || paths == null ||
                paths.Length == 0 || paths.Length > MaximumItems)
                throw new IOException("La solicitud del Explorador no es válida.");
            string directory = RequestRoot;
            Directory.CreateDirectory(directory);
            string parent = Path.GetDirectoryName(directory);
            if ((File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0 ||
                (File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("La carpeta de solicitudes no puede ser un enlace.");
            var security = new DirectorySecurity();
            security.SetAccessRuleProtection(true, false);
            security.AddAccessRule(new FileSystemAccessRule(WindowsIdentity.GetCurrent().User,
                FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                PropagationFlags.None, AccessControlType.Allow));
            new DirectoryInfo(directory).SetAccessControl(security);
            var serializer = new JavaScriptSerializer { MaxJsonLength = MaximumBytes };
            byte[] content = new UTF8Encoding(false).GetBytes(serializer.Serialize(new {
                schema = 1, action = action, paths = paths
            }));
            if (content.Length > MaximumBytes) throw new IOException("La selección supera el tamaño permitido.");
            string request = Path.Combine(directory, Guid.NewGuid().ToString("N") + ".request.json");
            string pending = request + ".pending";
            try
            {
                using (var file = new FileStream(pending, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    file.Write(content, 0, content.Length);
                    file.Flush(true);
                }
                File.Move(pending, request); // Atomic publication, never overwrite an existing request.
            }
            catch { try { File.Delete(pending); } catch (IOException) { } throw; }
            return request;
        }

        internal static void Launch(string action, IShellItemArray selection)
        {
            string[] paths = Paths(selection, action);
            string executable = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "PDFModder.exe");
            if (!File.Exists(executable)) throw new IOException("No se encuentra el ejecutable de PDF Modder.");
            string request = Write(action, paths);
            try
            {
                // The only argument is our own request path. Selected filenames
                // never become shell code or compete for the command-line limit.
                Process.Start(new ProcessStartInfo(executable, "--shell-request \"" + request + "\"") {
                    UseShellExecute = false, WorkingDirectory = Path.GetDirectoryName(executable)
                });
            }
            catch
            {
                try { File.Delete(request); } catch (IOException) { }
                throw;
            }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct NativePoint { public int X, Y; }

    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItem
    {
        [PreserveSig] int BindToHandler(IntPtr bind, ref Guid handler, ref Guid iid, out IntPtr result);
        [PreserveSig] int GetParent(out IShellItem parent);
        [PreserveSig] int GetDisplayName(uint kind, out IntPtr name);
        [PreserveSig] int GetAttributes(uint mask, out uint attributes);
        [PreserveSig] int Compare(IShellItem other, uint hint, out int order);
    }

    [ComImport, Guid("B63EA76D-1F85-456F-A19C-48159EFA858B"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IShellItemArray
    {
        [PreserveSig] int BindToHandler(IntPtr bind, ref Guid handler, ref Guid iid, out IntPtr result);
        [PreserveSig] int GetPropertyStore(uint flags, ref Guid iid, out IntPtr store);
        [PreserveSig] int GetPropertyDescriptionList(IntPtr key, ref Guid iid, out IntPtr result);
        [PreserveSig] int GetAttributes(uint flags, uint mask, out uint attributes);
        [PreserveSig] int GetCount(out uint count);
        [PreserveSig] int GetItemAt(uint index, out IShellItem item);
        [PreserveSig] int EnumItems(out IntPtr enumerator);
    }

    [ComVisible(true), Guid("7F9185B0-CB92-43C5-80A9-92277A4F7B54"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IExecuteCommand
    {
        [PreserveSig] int SetKeyState(uint state);
        [PreserveSig] int SetParameters([MarshalAs(UnmanagedType.LPWStr)] string parameters);
        [PreserveSig] int SetPosition(NativePoint position);
        [PreserveSig] int SetShowWindow(int show);
        [PreserveSig] int SetNoShowUI([MarshalAs(UnmanagedType.Bool)] bool value);
        [PreserveSig] int SetDirectory([MarshalAs(UnmanagedType.LPWStr)] string directory);
        [PreserveSig] int Execute();
    }

    [ComVisible(true), Guid("1C9CD5BB-98E9-4491-A60F-31AACC72B83C"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IObjectWithSelection
    {
        [PreserveSig] int SetSelection([MarshalAs(UnmanagedType.Interface)] IShellItemArray selection);
        [PreserveSig] int GetSelection(ref Guid iid, out IntPtr selection);
    }

    [ComVisible(true), Guid("85075ACF-231F-40EA-9610-D26B7B58F638"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IInitializeCommand
    {
        [PreserveSig] int Initialize([MarshalAs(UnmanagedType.LPWStr)] string commandName, IntPtr propertyBag);
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public sealed class ShellCommand : IExecuteCommand, IObjectWithSelection, IInitializeCommand
    {
        readonly string action;
        IShellItemArray selection;
        bool noShow;
        internal static int Objects;
        public ShellCommand(string value) { action = value; Interlocked.Increment(ref Objects); Server.Touch(); }
        ~ShellCommand() { Interlocked.Decrement(ref Objects); }
        public int SetKeyState(uint state) { Server.Touch(); return 0; }
        public int SetParameters(string parameters) { Server.Touch(); return 0; }
        public int SetPosition(NativePoint position) { Server.Touch(); return 0; }
        public int SetShowWindow(int show) { Server.Touch(); return 0; }
        public int SetNoShowUI(bool value) { noShow = value; Server.Touch(); return 0; }
        public int SetDirectory(string directory) { Server.Touch(); return 0; }
        public int Initialize(string name, IntPtr bag) { Server.Touch(); return 0; }
        public int SetSelection(IShellItemArray value) { selection = value; Server.Touch(); return 0; }
        public int GetSelection(ref Guid iid, out IntPtr result)
        {
            Server.Touch(); result = IntPtr.Zero;
            if (selection == null) return unchecked((int)0x80004005);
            IntPtr pointer = Marshal.GetIUnknownForObject(selection);
            try { return Marshal.QueryInterface(pointer, ref iid, out result); }
            finally { Marshal.Release(pointer); }
        }
        public int Execute()
        {
            Server.Touch();
            try { SelectionRequest.Launch(action, selection); return 0; }
            catch (Exception exception)
            {
                if (!noShow) MessageBox.Show(exception.Message, "PDF Modder", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return Marshal.GetHRForException(exception);
            }
            finally { selection = null; Server.Touch(); }
        }
    }

    [ComVisible(true), Guid("00000001-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IClassFactory
    {
        [PreserveSig] int CreateInstance(IntPtr outer, ref Guid iid, out IntPtr result);
        [PreserveSig] int LockServer([MarshalAs(UnmanagedType.Bool)] bool value);
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public sealed class CommandFactory : IClassFactory
    {
        readonly string action;
        public CommandFactory(string value) { action = value; }
        public int CreateInstance(IntPtr outer, ref Guid iid, out IntPtr result)
        {
            result = IntPtr.Zero; Server.Touch();
            if (outer != IntPtr.Zero) return unchecked((int)0x80040110); // CLASS_E_NOAGGREGATION
            IntPtr unknown = IntPtr.Zero;
            try
            {
                unknown = Marshal.GetIUnknownForObject(new ShellCommand(action));
                return Marshal.QueryInterface(unknown, ref iid, out result);
            }
            catch (Exception exception) { return Marshal.GetHRForException(exception); }
            finally { if (unknown != IntPtr.Zero) Marshal.Release(unknown); }
        }
        public int LockServer(bool value)
        {
            if (value) Interlocked.Increment(ref Server.Locks);
            else Interlocked.Decrement(ref Server.Locks);
            Server.Touch(); return 0;
        }
    }

    internal static class Server
    {
        [DllImport("ole32.dll")] static extern int CoRegisterClassObject(ref Guid clsid,
            [MarshalAs(UnmanagedType.Interface)] IClassFactory factory, uint context, uint flags, out uint cookie);
        [DllImport("ole32.dll")] static extern int CoRevokeClassObject(uint cookie);
        internal static int Locks;
        static long lastActivity = DateTime.UtcNow.Ticks;
        internal static void Touch() { Interlocked.Exchange(ref lastActivity, DateTime.UtcNow.Ticks); }

        [STAThread]
        static int Main(string[] arguments)
        {
            uint convert = 0, combine = 0;
            System.Windows.Forms.Timer timer = null;
            var factories = new List<IClassFactory>();
            try
            {
                bool server = false;
                foreach (string argument in arguments)
                {
                    if (argument.Equals("--com-server", StringComparison.OrdinalIgnoreCase)) server = true;
                    else if (!argument.Equals("-Embedding", StringComparison.OrdinalIgnoreCase) &&
                             !argument.Equals("/Embedding", StringComparison.OrdinalIgnoreCase))
                        throw new ArgumentException("Este componente se inicia desde el menú contextual de Windows.");
                }
                if (!server) throw new ArgumentException("Este componente se inicia desde el menú contextual de Windows.");
                Application.OleRequired();
                Guid convertId = new Guid(SelectionRequest.ConvertClsid), combineId = new Guid(SelectionRequest.CombineClsid);
                factories.Add(new CommandFactory("convert")); factories.Add(new CommandFactory("combine"));
                Marshal.ThrowExceptionForHR(CoRegisterClassObject(ref convertId, factories[0], 4, 1, out convert));
                Marshal.ThrowExceptionForHR(CoRegisterClassObject(ref combineId, factories[1], 4, 1, out combine));
                timer = new System.Windows.Forms.Timer { Interval = 2000 };
                timer.Tick += delegate {
                    // A CCW with references held by Explorer remains alive. Once
                    // clients release their commands, the small server can exit.
                    // Keep pumping the STA while RCWs are finalized; waiting
                    // synchronously here can stall their apartment releases.
                    GC.Collect();
                    if (ShellCommand.Objects == 0 && Locks <= 0 &&
                        DateTime.UtcNow.Ticks - Interlocked.Read(ref lastActivity) > TimeSpan.FromSeconds(2).Ticks)
                        Application.ExitThread();
                };
                timer.Start(); Application.Run(); return 0;
            }
            catch (Exception exception)
            {
                MessageBox.Show(exception.Message, "PDF Modder", MessageBoxButtons.OK, MessageBoxIcon.Warning); return 1;
            }
            finally
            {
                if (timer != null) timer.Dispose();
                if (convert != 0) CoRevokeClassObject(convert);
                if (combine != 0) CoRevokeClassObject(combine);
                GC.KeepAlive(factories);
            }
        }
    }
}
