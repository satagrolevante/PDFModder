"""Exercise the Windows installer's real update window, bytes and silent entry point."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.name != 'nt', reason='Requires Windows WinForms and the Framework C# compiler')


HARNESS = r'''
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using PdfModderInstallation;

class InstallerProgressHarness {
    const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic;
    static void Check(bool value, string message) { if (!value) throw new Exception(message); }
    static T Control<T>(Form form, string name) where T : System.Windows.Forms.Control {
        return (T)form.Controls.Find(name, true)[0];
    }
    static int Entry(params string[] args) {
        return (int)typeof(Program).GetMethod("Main", Static).Invoke(null, new object[] { args });
    }
    static void OptionsContract() {
        var automatic = Options.Parse(new[] { "--update" });
        Check(automatic.Update && !automatic.Silent && automatic.Launch && automatic.Report != null,
            "Update must automatically show progress and launch by default");
        foreach (string[] args in new[] {
            new[] { "--silent", "--update", "--no-launch" },
            new[] { "--update", "--no-launch", "--silent" } }) {
            var silent = Options.Parse(args);
            Check(silent.Silent && silent.Update && !silent.Launch, "Explicit silent/no-launch was lost");
        }
        Check(!Options.Parse(new[] { "--update", "--no-launch" }).Launch, "Visible update ignored --no-launch");
        var manual = Options.Parse(new string[0]);
        Check(!manual.Silent && !manual.Update && !manual.Launch, "Manual installation defaults changed");
    }
    static void ExtractPayload(string directory) {
        Directory.CreateDirectory(directory);
        var observed = new List<int>();
        var result = new Result();
        string finalMessage = null;
        Action<int, string> progress = delegate(int percent, string message) {
            Check(percent >= 0 && percent < 100, "Copy claimed final completion");
            Check(observed.Count == 0 || percent >= observed[observed.Count - 1], "Measured progress moved backwards");
            observed.Add(percent); finalMessage = message;
        };
        typeof(Installer).GetMethod("Extract", Static).Invoke(null, new object[] { directory, progress, result });
        Check(result.files == 9 && observed.Count >= 2 && observed[0] == 0 && observed[observed.Count - 1] == 99,
            "Payload files or bounded byte progress missing");
        Check(finalMessage.Contains("9 de 9") && finalMessage.Contains("MiB") && finalMessage.Contains("SHA-256"),
            "Final measured-byte and verified-file details missing");
    }
    static void HashWrittenBytes(string path, string expected) {
        long count = 0; int chunks = 0;
        Action<int> measured = delegate(int bytes) { Check(bytes > 0, "Empty byte callback"); count += bytes; chunks++; };
        MethodInfo method = typeof(Installer).GetMethod("Hash", Static, null,
            new[] { typeof(string), typeof(Action<int>) }, null);
        string actual = (string)method.Invoke(null, new object[] { path, measured });
        Check(actual == expected && count == new FileInfo(path).Length && chunks > 1,
            "Disk hash or byte telemetry changed");
    }
    static void RenderProgress() {
        using (var form = new InstallerWindow(new Options { Update = true, Launch = false })) {
            var meter = Control<ProgressBar>(form, "installationProgress");
            MethodInfo show = typeof(InstallerWindow).GetMethod("ShowProgress", Instance);
            show.Invoke(form, new object[] { 40, "Measured" });
            Check(meter.Value == 40 && meter.Style == ProgressBarStyle.Continuous, "Measured mode incorrect");
            show.Invoke(form, new object[] { -1, "Waiting" });
            Check(meter.Value == 40 && meter.Style == ProgressBarStyle.Marquee && meter.MarqueeAnimationSpeed > 0,
                "Waiting phase must animate without inventing a percent");
            show.Invoke(form, new object[] { 20, "Older observation" });
            Check(meter.Value == 40, "Meter moved backwards");
            show.Invoke(form, new object[] { 100, "Report not saved yet" });
            Check(meter.Value == 99, "Non-final callback reached 100");
            Check(!Control<CheckBox>(form, "launchApplication").Checked, "Update window ignored --no-launch");
        }
    }
    static void AutomaticFailure(string directory, string report) {
        var options = Options.Parse(new[] { "--update", "--no-launch", "--dir", directory, "--report", report });
        bool shown = false, completed = false; Exception failure = null;
        using (var form = new InstallerWindow(options))
        using (var timer = new System.Windows.Forms.Timer { Interval = 25 }) {
            var close = Control<Button>(form, "closeButton");
            var meter = Control<ProgressBar>(form, "installationProgress");
            var watch = System.Diagnostics.Stopwatch.StartNew();
            form.Shown += delegate {
                try {
                    Check(form.Visible && !close.Enabled && !form.ControlBox && meter.Style == ProgressBarStyle.Marquee,
                        "Automatic progress was not visible and protected before work");
                    form.Close();
                    Check(!form.IsDisposed && form.Visible, "Early close interrupted automatic update");
                    shown = true;
                } catch (Exception ex) { failure = ex; }
                timer.Start();
            };
            timer.Tick += delegate {
                if (failure != null) {
                    if (close.Enabled) { timer.Stop(); form.Close(); }
                    return;
                }
                try {
                    Check(watch.Elapsed.TotalSeconds < 15, "Automatic update did not finish");
                    if (!close.Enabled) { form.Close(); Check(!form.IsDisposed, "Close interrupted update"); return; }
                    Check(form.ExitCode == 1 && meter.Value < 100 && meter.Style != ProgressBarStyle.Marquee,
                        "Failed update claimed success or kept animating");
                    var data = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(report, Encoding.UTF8));
                    Check(data.ContainsKey("ok") && !(bool)data["ok"] && data.ContainsKey("error"), "Final failure report missing");
                    Check(Control<TextBox>(form, "installationStatus").Text.Contains(report), "Report location not shown");
                    completed = true;
                } catch (Exception ex) { failure = ex; if (!close.Enabled) return; }
                timer.Stop(); form.Close();
            };
            Application.Run(form);
        }
        if (failure != null) throw failure;
        Check(shown && completed, "Update did not automatically run through completion");
    }
    [STAThread] static int Main(string[] args) {
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
        AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
        try {
            if (args[0] == "options") OptionsContract();
            else if (args[0] == "extract") ExtractPayload(args[1]);
            else if (args[0] == "hash") HashWrittenBytes(args[1], args[2]);
            else if (args[0] == "render") { Application.EnableVisualStyles(); RenderProgress(); }
            else if (args[0] == "gui") {
                System.Windows.Forms.Control.CheckForIllegalCrossThreadCalls = true;
                Application.EnableVisualStyles(); AutomaticFailure(args[1], args[2]);
            }
            else if (args[0] == "silent") {
                Check(Entry("--silent", "--update", "--unknown-option") == 1, "Silent parse failure exit changed");
                Check(Entry("--silent", "--update", "--no-launch", "--dir", args[1], "--report", args[2]) == 1,
                    "Silent installation failure exit changed");
                Check(File.Exists(args[2]), "Silent final report missing");
            }
            else throw new Exception("Unknown harness mode");
            return 0;
        } catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
}
'''


@pytest.fixture(scope='module')
def installer_harness(tmp_path_factory):
    work = tmp_path_factory.mktemp('installer-progress')
    source = ROOT / 'installer' / 'PdfModderInstaller.cs'
    critical_block = re.search(
        r'static readonly string\[\] Critical = \{(.*?)\};',
        source.read_text(encoding='utf-8-sig'), re.S).group(1)
    names = re.findall(r'"([^"]+)"', critical_block)
    assert len(names) == 9
    payload = {name: ((bytes(range(256)) * 4096) if index == 0 else name.encode())
               for index, name in enumerate(names)}
    archive = work / 'payload.zip'
    inventory = work / 'payload.tsv'
    rows = []
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as stream:
        for name, content in payload.items():
            member = 'PDFModder/' + name
            stream.writestr(member, content)
            rows.append(f'{hashlib.sha256(content).hexdigest()}\t{len(content)}\t{member}\n')
    inventory.write_text(''.join(rows), encoding='utf-8')
    harness = work / 'ProgressHarness.cs'
    harness.write_text(HARNESS, encoding='utf-8-sig')
    compiler = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.exists():
        pytest.skip('Windows Framework C# compiler is not installed')
    executable = work / 'InstallerProgressHarness.exe'
    command = [compiler, '/nologo', '/platform:x64', '/target:exe', '/main:InstallerProgressHarness',
               '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
               '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
               '/reference:System.IO.Compression.FileSystem.dll', '/out:' + str(executable),
               '/resource:' + str(archive) + ',PDFModderPayload.zip',
               '/resource:' + str(inventory) + ',PDFModderPayload.tsv', source, harness]
    result = subprocess.run([str(value) for value in command], cwd=work, capture_output=True,
                            text=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr
    return executable, payload


def run_harness(installer_harness, *args):
    executable, _ = installer_harness
    try:
        result = subprocess.run([str(executable), *map(str, args)], capture_output=True,
                                text=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        pytest.fail('Installer stopped responding or displayed an unexpected modal dialog')
    assert result.returncode == 0, result.stdout + result.stderr


def test_update_options_preserve_explicit_silent_and_no_launch(installer_harness):
    run_harness(installer_harness, 'options')


def test_copy_and_disk_sha256_report_actual_bytes_below_final_completion(installer_harness, tmp_path):
    destination = tmp_path / 'extracted'
    run_harness(installer_harness, 'extract', destination)
    _, payload = installer_harness
    for name, content in payload.items():
        assert (destination / name).read_bytes() == content
    data = payload['PDFModder.exe']
    run_harness(installer_harness, 'hash', destination / 'PDFModder.exe', hashlib.sha256(data).hexdigest())


def test_meter_handles_indeterminate_phases_without_fake_completion(installer_harness):
    run_harness(installer_harness, 'render')


@pytest.mark.parametrize('mode', ['gui', 'silent'])
def test_update_failure_preserves_documents_and_writes_report(installer_harness, tmp_path, mode):
    destination = tmp_path / 'unrecognized-existing-folder'
    destination.mkdir()
    document = destination / 'personal.pdf'
    document.write_bytes(b'User document must remain unchanged')
    report = tmp_path / 'failed-update.json'
    run_harness(installer_harness, mode, destination, report)
    assert document.read_bytes() == b'User document must remain unchanged'
    assert set(destination.iterdir()) == {document}
    assert not list(tmp_path.glob('.pdfmodder-stage-*'))
