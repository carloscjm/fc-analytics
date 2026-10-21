using System.Text.Json;

namespace FCAnalytics;

/// <summary>Configurações do app, guardadas em runtime\settings.json.</summary>
public sealed class Settings
{
    public string? DataDir { get; set; }
    public string? TorchIndex { get; set; }
    public string? RequirementsHash { get; set; }
    public bool SetupDone { get; set; }

    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true };

    public static Settings Load()
    {
        try
        {
            if (File.Exists(Paths.SettingsFile))
                return JsonSerializer.Deserialize<Settings>(File.ReadAllText(Paths.SettingsFile)) ?? new Settings();
        }
        catch (Exception)
        {
            // Arquivo corrompido: começa de novo com o padrão.
        }
        return new Settings();
    }

    public void Save()
    {
        Directory.CreateDirectory(Paths.Runtime);
        File.WriteAllText(Paths.SettingsFile, JsonSerializer.Serialize(this, Options));
    }
}
