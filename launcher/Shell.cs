using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Text;

namespace FCAnalytics;

/// <summary>Roda programas sem janela preta, repassando cada linha de saída.</summary>
public static class Shell
{
    public static async Task<int> RunAsync(
        string file,
        string arguments,
        string? workDir,
        IDictionary<string, string>? env,
        Action<string> onLine,
        CancellationToken cancel = default)
    {
        var psi = new ProcessStartInfo(file, arguments)
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = workDir ?? Paths.AppDir,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        if (env != null)
        {
            foreach (var pair in env)
                psi.Environment[pair.Key] = pair.Value;
        }

        using var process = new Process { StartInfo = psi };
        process.OutputDataReceived += (_, e) => { if (e.Data != null) onLine(e.Data); };
        process.ErrorDataReceived += (_, e) => { if (e.Data != null) onLine(e.Data); };
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        await process.WaitForExitAsync(cancel);
        return process.ExitCode;
    }

    /// <summary>Roda um comando curto e devolve a saída (ou null se não deu certo).</summary>
    public static string? RunQuick(string file, string arguments, int timeoutMs = 5000)
    {
        try
        {
            var psi = new ProcessStartInfo(file, arguments)
            {
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            };
            using var process = Process.Start(psi);
            if (process == null)
                return null;
            var output = process.StandardOutput.ReadToEnd();
            if (!process.WaitForExit(timeoutMs))
            {
                process.Kill(true);
                return null;
            }
            return process.ExitCode == 0 ? output : null;
        }
        catch (Exception)
        {
            return null;
        }
    }

    public static void Open(string target)
    {
        Process.Start(new ProcessStartInfo(target) { UseShellExecute = true });
    }
}
