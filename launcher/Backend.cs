using System.Diagnostics;
using System.Net.Http;
using System.Text;
using System.Text.Json;

namespace FCAnalytics;

/// <summary>Sobe e derruba o backend (uvicorn) sem janela, e confere se ele e o Ollama respondem.</summary>
public sealed class Backend
{
    public const string Url = "http://localhost:8000/";
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(2) };

    private Process? _process;
    private StreamWriter? _logFile;

    public event Action<string>? Line;

    public bool Running => _process is { HasExited: false };

    public void Start(string dataDir)
    {
        if (Running)
            return;
        Directory.CreateDirectory(Paths.Logs);
        Directory.CreateDirectory(Paths.Models);
        Directory.CreateDirectory(dataDir);
        _logFile = new StreamWriter(Path.Combine(Paths.Logs, "backend.log"), append: true, Encoding.UTF8) { AutoFlush = true };
        _logFile.WriteLine($"===== {DateTime.Now:yyyy-MM-dd HH:mm:ss} iniciando =====");

        var psi = new ProcessStartInfo(Paths.Python, "-m uvicorn app.main:app --host 127.0.0.1 --port 8000")
        {
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = Paths.Backend,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        psi.Environment["FCA_DATA_DIR"] = dataDir;
        psi.Environment["FCA_MODELS_DIR"] = Paths.Models;
        psi.Environment["FCA_WEB_DIR"] = Paths.Web;
        psi.Environment["PYTHONUNBUFFERED"] = "1";
        psi.Environment["PYTHONIOENCODING"] = "utf-8";

        _process = new Process { StartInfo = psi, EnableRaisingEvents = true };
        _process.OutputDataReceived += (_, e) => Write(e.Data);
        _process.ErrorDataReceived += (_, e) => Write(e.Data);
        _process.Exited += (_, _) => Write("O backend parou.");
        _process.Start();
        _process.BeginOutputReadLine();
        _process.BeginErrorReadLine();
    }

    private void Write(string? line)
    {
        if (line == null)
            return;
        try
        {
            _logFile?.WriteLine(line);
        }
        catch (ObjectDisposedException)
        {
        }
        Line?.Invoke(line);
    }

    public void Stop()
    {
        try
        {
            if (_process is { HasExited: false })
            {
                _process.Kill(entireProcessTree: true);
                _process.WaitForExit(5000);
            }
        }
        catch (Exception)
        {
            // Já tinha parado.
        }
        _process = null;
        _logFile?.Dispose();
        _logFile = null;
    }

    /// <summary>Versão do backend se ele responde em /health, senão null.</summary>
    public static async Task<string?> HealthAsync()
    {
        try
        {
            var json = await Http.GetStringAsync(Url + "health");
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.TryGetProperty("version", out var v) ? v.GetString() : "?";
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>Versão do Ollama se ele está aberto, senão null.</summary>
    public static async Task<string?> OllamaAsync()
    {
        try
        {
            var json = await Http.GetStringAsync("http://127.0.0.1:11434/api/version");
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.TryGetProperty("version", out var v) ? v.GetString() : "?";
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>Abre o painel no Chrome (a captura da aba funciona melhor nele) ou no navegador padrão.</summary>
    public static void OpenPanel()
    {
        var chrome = new[]
        {
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Google", "Chrome", "Application", "chrome.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Google", "Chrome", "Application", "chrome.exe"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Google", "Chrome", "Application", "chrome.exe"),
        }.FirstOrDefault(File.Exists);
        if (chrome != null)
            Process.Start(new ProcessStartInfo(chrome, Url) { UseShellExecute = false });
        else
            Shell.Open(Url);
    }

    /// <summary>Abre o Ollama se ele estiver instalado e fechado.</summary>
    public static bool TryStartOllama()
    {
        var exe = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Ollama", "ollama app.exe");
        if (!File.Exists(exe))
            return false;
        Process.Start(new ProcessStartInfo(exe) { UseShellExecute = true });
        return true;
    }
}
