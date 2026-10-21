using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Security.Cryptography;

namespace FCAnalytics;

/// <summary>
/// Prepara o ambiente Python com o uv (que vem junto com o app): baixa o Python 3.12,
/// cria o ambiente, instala o PyTorch com CUDA (ou para CPU) e as bibliotecas do backend.
/// </summary>
public sealed class Installer
{
    private readonly Action<string> _log;
    private readonly Action<string> _step;

    public Installer(Action<string> log, Action<string> step)
    {
        _log = log;
        _step = step;
    }

    private static Dictionary<string, string> UvEnv => new()
    {
        ["UV_PYTHON_INSTALL_DIR"] = Paths.PythonInstalls,
        ["UV_CACHE_DIR"] = Paths.UvCache,
        ["UV_PYTHON_PREFERENCE"] = "only-managed",
        ["UV_LINK_MODE"] = "copy",
        ["UV_NO_PROGRESS"] = "1",
    };

    /// <summary>Nome da placa NVIDIA e versão principal do driver (0 se não houver).</summary>
    public static (string? Name, int Driver) DetectGpu()
    {
        var output = Shell.RunQuick("nvidia-smi", "--query-gpu=name,driver_version --format=csv,noheader");
        if (string.IsNullOrWhiteSpace(output))
            return (null, 0);
        var parts = output.Split('\n')[0].Split(',');
        var name = parts[0].Trim();
        var driver = 0;
        if (parts.Length > 1)
            int.TryParse(parts[1].Trim().Split('.')[0], out driver);
        return (name, driver);
    }

    /// <summary>CUDA 13 pede driver 580 ou mais novo; com driver antigo, CUDA 12.6; sem NVIDIA, CPU.</summary>
    public static string TorchIndexFor(int driver) => driver >= 580 ? "cu130" : driver > 0 ? "cu126" : "cpu";

    public static string RequirementsHash()
    {
        using var sha = SHA256.Create();
        using var stream = File.OpenRead(Paths.Requirements);
        return Convert.ToHexString(sha.ComputeHash(stream));
    }

    private async Task Uv(string arguments, string title, CancellationToken cancel, bool ignoreErrors = false)
    {
        _step(title);
        _log($"> uv {arguments}");
        var code = await Shell.RunAsync(Paths.Uv, arguments, Paths.Runtime, UvEnv, _log, cancel);
        if (code != 0 && !ignoreErrors)
            throw new InvalidOperationException($"Falhou: {title} (código {code}). Veja o registro abaixo.");
    }

    public async Task InstallAllAsync(string torchIndex, CancellationToken cancel)
    {
        Directory.CreateDirectory(Paths.Runtime);
        if (!File.Exists(Paths.Uv))
            throw new FileNotFoundException("O instalador do Python (uv.exe) não veio junto com o app.", Paths.Uv);

        await Uv("python install 3.12", "1/5 · Baixando o Python 3.12", cancel);
        if (!File.Exists(Paths.Python))
            await Uv($"venv \"{Paths.Venv}\" --python 3.12", "2/5 · Criando o ambiente Python", cancel);

        var torch = torchIndex == "cpu"
            ? "torch torchvision"
            : $"torch torchvision --index-url https://download.pytorch.org/whl/{torchIndex}";
        await Uv($"pip install --python \"{Paths.Python}\" {torch}",
            "3/5 · Baixando o PyTorch (alguns GB; pode levar vários minutos)", cancel);

        await InstallRequirementsAsync(cancel, "4/5");
        await Uv("cache clean", "5/5 · Apagando os arquivos temporários da instalação", cancel, ignoreErrors: true);
    }

    public async Task InstallRequirementsAsync(CancellationToken cancel, string prefix = "")
    {
        var label = string.IsNullOrEmpty(prefix) ? "" : prefix + " · ";
        await Uv($"pip install --python \"{Paths.Python}\" -r \"{Paths.Requirements}\"",
            $"{label}Instalando as bibliotecas do FC Analytics", cancel);
        // O leitor do placar vai sem dependências: ele pediria um segundo OpenCV, que briga com o primeiro.
        await Uv($"pip install --python \"{Paths.Python}\" --no-deps rapidocr==3.9.2",
            $"{label}Instalando o leitor do placar", cancel);
    }

    /// <summary>Traz da instalação antiga os modelos baixados e as partidas gravadas (sem sobrescrever nada).</summary>
    public void ImportOld(string oldDir, string dataDir)
    {
        _step("Trazendo modelos e partidas da instalação antiga");
        var oldModels = Path.Combine(oldDir, "backend", "models");
        var oldData = Path.Combine(oldDir, "backend", "data");
        CopyFiles(oldModels, Paths.Models);
        CopyFiles(oldData, dataDir);
    }

    private void CopyFiles(string from, string to)
    {
        if (!Directory.Exists(from))
            return;
        Directory.CreateDirectory(to);
        foreach (var file in Directory.GetFiles(from))
        {
            var target = Path.Combine(to, Path.GetFileName(file));
            if (File.Exists(target))
                continue;
            File.Copy(file, target);
            _log($"Copiado: {Path.GetFileName(file)}");
        }
    }
}
