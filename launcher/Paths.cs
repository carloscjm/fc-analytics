namespace FCAnalytics;

/// <summary>
/// Onde fica cada coisa.
///
/// O programa (este app, o código do backend e a página) fica na pasta que o instalador
/// troca a cada atualização. O ambiente Python, os modelos baixados, as configurações e os
/// registros ficam em %LocalAppData%\FCAnalytics\runtime, que as atualizações não apagam.
/// As partidas gravadas ficam na pasta que a pessoa escolhe.
/// </summary>
public static class Paths
{
    public static string AppDir => AppContext.BaseDirectory;
    public static string Backend => Path.Combine(AppDir, "app", "backend");
    public static string Web => Path.Combine(AppDir, "app", "web");
    public static string Uv => Path.Combine(AppDir, "tools", "uv.exe");
    public static string Requirements => Path.Combine(Backend, "requirements.txt");

    public static string Runtime { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FCAnalytics", "runtime");

    public static string Venv => Path.Combine(Runtime, "venv");
    public static string Python => Path.Combine(Venv, "Scripts", "python.exe");
    public static string PythonInstalls => Path.Combine(Runtime, "python");
    public static string UvCache => Path.Combine(Runtime, "uv-cache");
    public static string Models => Path.Combine(Runtime, "models");
    public static string Logs => Path.Combine(Runtime, "logs");
    public static string SettingsFile => Path.Combine(Runtime, "settings.json");

    /// <summary>Pasta sugerida para as partidas: no disco E: se existir, senão em Documentos.</summary>
    public static string DefaultDataDir()
    {
        if (Directory.Exists(@"E:\"))
            return @"E:\FC Analytics\partidas";
        return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "FC Analytics", "partidas");
    }

    /// <summary>Instalação antiga (pelos arquivos .bat), de onde dá para trazer modelos e partidas.</summary>
    public static string? FindOldInstall()
    {
        var candidates = new[]
        {
            @"E:\fc-analytics",
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "fc-analytics"),
        };
        return candidates.FirstOrDefault(d => Directory.Exists(Path.Combine(d, "backend")));
    }
}
