using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Microsoft.Win32;
using Velopack;
using Velopack.Sources;

namespace FCAnalytics;

/// <summary>
/// Janela do app de controle. Na primeira vez mostra a configuração inicial (pasta das
/// partidas e instalação do ambiente); depois, o estado das partes e os botões do dia a dia.
/// </summary>
public sealed class MainWindow : Window
{
    private const string RepoUrl = "https://github.com/carloscjm/fc-analytics";

    private static readonly Brush Green = MakeBrush("#1f7a3a");
    private static readonly Brush Amber = MakeBrush("#b7791f");
    private static readonly Brush Red = MakeBrush("#b3261e");
    private static readonly Brush Gray = MakeBrush("#9aa393");
    private static readonly Brush Accent = MakeBrush("#1f6f3a");
    private static readonly Brush Muted = MakeBrush("#5d6657");

    private readonly Settings _settings = Settings.Load();
    private readonly Backend _backend = new();
    private readonly UpdateManager? _updates = CreateUpdateManager();
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(2) };
    private readonly (string? Name, int Driver) _gpu = Installer.DetectGpu();
    private readonly string? _oldInstall = Paths.FindOldInstall();

    // Configuração inicial
    private readonly StackPanel _setup = new();
    private readonly TextBox _dataDirBox = new() { MinWidth = 380, Padding = new Thickness(4) };
    private readonly CheckBox _importCheck = new() { IsChecked = true, Margin = new Thickness(0, 10, 0, 0) };
    private readonly Button _installButton;

    // Painel do dia a dia
    private readonly StackPanel _dashboard = new();
    private readonly StatusRow _backendRow = new("Análise (backend)");
    private readonly StatusRow _ollamaRow = new("LLM local (Ollama)");
    private readonly StatusRow _gpuRow = new("Placa de vídeo");
    private readonly TextBlock _dataDirText = new() { TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center };
    private readonly Button _startButton;
    private readonly Button _stopButton;
    private readonly Button _openButton;
    private readonly Button _ollamaButton;
    private readonly Button _updateButton;
    private readonly TextBlock _updateText = new() { Foreground = Muted, Margin = new Thickness(10, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };

    // Comum
    private readonly TextBlock _stepText = new() { FontWeight = FontWeights.SemiBold, Margin = new Thickness(0, 12, 0, 4), TextWrapping = TextWrapping.Wrap };
    private readonly ProgressBar _progress = new() { Height = 8, Visibility = Visibility.Collapsed };
    private readonly TextBox _log = new()
    {
        IsReadOnly = true,
        FontFamily = new FontFamily("Consolas"),
        FontSize = 11.5,
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
        HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
        TextWrapping = TextWrapping.NoWrap,
        Background = MakeBrush("#f4f5f1"),
    };

    private bool _openWhenReady;
    private bool _busy;

    public MainWindow()
    {
        Title = "FC Analytics";
        Width = 760;
        Height = 640;
        MinWidth = 560;
        MinHeight = 480;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Background = Brushes.White;
        FontFamily = new FontFamily("Segoe UI");
        FontSize = 13.5;
        try
        {
            Icon = new BitmapImage(new Uri("pack://application:,,,/app.ico"));
        }
        catch (Exception)
        {
            // Sem ícone, tudo bem.
        }

        _installButton = MakeButton("Instalar", async (_, _) => await InstallAsync(), primary: true);
        _startButton = MakeButton("Iniciar", (_, _) => StartBackend(openPanel: true), primary: true);
        _stopButton = MakeButton("Parar", (_, _) => StopBackend());
        _openButton = MakeButton("Abrir painel", (_, _) => Backend.OpenPanel());
        _ollamaButton = MakeButton("Abrir o Ollama", async (_, _) => await OllamaActionAsync());
        _updateButton = MakeButton("Buscar atualizações", async (_, _) => await UpdateAsync(interactive: true));

        Content = BuildLayout();

        _backend.Line += line => Ui(() => AppendLog(line));
        _timer.Tick += async (_, _) => await RefreshStatusAsync();
        Loaded += async (_, _) => await OnLoadedAsync();
        Closing += OnClosing;
    }

    // ------------------------------------------------------------------ layout

    private UIElement BuildLayout()
    {
        var root = new DockPanel { Margin = new Thickness(18) };

        var header = new StackPanel { Margin = new Thickness(0, 0, 0, 12) };
        header.Children.Add(new TextBlock { Text = "FC Analytics", FontSize = 22, FontWeight = FontWeights.Bold });
        var version = _updates is { IsInstalled: true } ? $"versão {_updates.CurrentVersion}" : "versão de desenvolvimento";
        header.Children.Add(new TextBlock { Text = $"Analisador de futebol ao vivo · {version}", Foreground = Muted });
        DockPanel.SetDock(header, Dock.Top);
        root.Children.Add(header);

        BuildSetup();
        BuildDashboard();
        var top = new StackPanel();
        top.Children.Add(_setup);
        top.Children.Add(_dashboard);
        top.Children.Add(_stepText);
        top.Children.Add(_progress);
        DockPanel.SetDock(top, Dock.Top);
        root.Children.Add(top);

        var logLabel = new TextBlock { Text = "Registro", Foreground = Muted, Margin = new Thickness(0, 12, 0, 4) };
        DockPanel.SetDock(logLabel, Dock.Top);
        root.Children.Add(logLabel);
        root.Children.Add(_log); // ocupa o resto da janela
        return root;
    }

    private void BuildSetup()
    {
        _setup.Children.Add(new TextBlock
        {
            Text = "Configuração inicial",
            FontSize = 16,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 6),
        });
        _setup.Children.Add(new TextBlock
        {
            Text = "O app vai baixar o Python, o PyTorch e as bibliotecas da análise (alguns GB, na pasta do programa no disco C:). "
                 + "Escolha onde as partidas analisadas ficam gravadas.",
            TextWrapping = TextWrapping.Wrap,
            Foreground = Muted,
        });

        _setup.Children.Add(new TextBlock { Text = "Pasta das partidas", Margin = new Thickness(0, 12, 0, 4), FontWeight = FontWeights.SemiBold });
        var row = new StackPanel { Orientation = Orientation.Horizontal };
        _dataDirBox.Text = _settings.DataDir ?? Paths.DefaultDataDir();
        row.Children.Add(_dataDirBox);
        row.Children.Add(MakeButton("Escolher...", (_, _) =>
        {
            var chosen = PickFolder(_dataDirBox.Text);
            if (chosen != null)
                _dataDirBox.Text = chosen;
        }));
        _setup.Children.Add(row);

        if (_oldInstall != null)
        {
            _importCheck.Content = $"Trazer os modelos e as partidas da instalação antiga ({_oldInstall})";
            _setup.Children.Add(_importCheck);
        }

        var gpu = _gpu.Name != null
            ? $"Placa de vídeo: {_gpu.Name} (driver {_gpu.Driver}) · PyTorch com {Installer.TorchIndexFor(_gpu.Driver).ToUpperInvariant()}"
            : "Nenhuma placa NVIDIA encontrada: a análise vai rodar no processador, bem mais devagar.";
        _setup.Children.Add(new TextBlock { Text = gpu, Foreground = Muted, Margin = new Thickness(0, 10, 0, 0), TextWrapping = TextWrapping.Wrap });

        var actions = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 14, 0, 0) };
        actions.Children.Add(_installButton);
        _setup.Children.Add(actions);
    }

    private void BuildDashboard()
    {
        _dashboard.Children.Add(_backendRow.Element);
        _dashboard.Children.Add(_ollamaRow.Element);
        _dashboard.Children.Add(_gpuRow.Element);

        var buttons = new WrapPanel { Margin = new Thickness(0, 12, 0, 0) };
        buttons.Children.Add(_startButton);
        buttons.Children.Add(_stopButton);
        buttons.Children.Add(_openButton);
        buttons.Children.Add(_ollamaButton);
        _dashboard.Children.Add(buttons);

        _dashboard.Children.Add(new TextBlock { Text = "Pasta das partidas", Margin = new Thickness(0, 14, 0, 4), FontWeight = FontWeights.SemiBold });
        var data = new DockPanel();
        var dataButtons = new StackPanel { Orientation = Orientation.Horizontal };
        dataButtons.Children.Add(MakeButton("Abrir pasta", (_, _) => OpenDataDir()));
        dataButtons.Children.Add(MakeButton("Alterar...", (_, _) => ChangeDataDir()));
        DockPanel.SetDock(dataButtons, Dock.Right);
        data.Children.Add(dataButtons);
        data.Children.Add(_dataDirText);
        _dashboard.Children.Add(data);

        var updates = new DockPanel { Margin = new Thickness(0, 14, 0, 0) };
        DockPanel.SetDock(_updateButton, Dock.Left);
        updates.Children.Add(_updateButton);
        updates.Children.Add(_updateText);
        _dashboard.Children.Add(updates);
    }

    private static Button MakeButton(string text, RoutedEventHandler click, bool primary = false)
    {
        var button = new Button
        {
            Content = text,
            Padding = new Thickness(14, 6, 14, 6),
            Margin = new Thickness(0, 0, 8, 0),
            MinWidth = 90,
            Cursor = System.Windows.Input.Cursors.Hand,
        };
        if (primary)
        {
            button.Background = Accent;
            button.Foreground = Brushes.White;
            button.FontWeight = FontWeights.SemiBold;
        }
        button.Click += click;
        return button;
    }

    private static UpdateManager? CreateUpdateManager()
    {
        try
        {
            return new UpdateManager(new GithubSource(RepoUrl, null, false));
        }
        catch (Exception)
        {
            return null; // rodando fora da instalação (desenvolvimento)
        }
    }

    /// <summary>Executa na thread da janela (as saídas dos programas chegam de outras threads).</summary>
    private void Ui(Action action) => Dispatcher.BeginInvoke(action);

    private static SolidColorBrush MakeBrush(string hex)
    {
        var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(hex));
        brush.Freeze();
        return brush;
    }

    private sealed class StatusRow
    {
        private readonly System.Windows.Shapes.Ellipse _dot = new() { Width = 10, Height = 10, Margin = new Thickness(0, 0, 8, 0) };
        private readonly TextBlock _value = new() { TextWrapping = TextWrapping.Wrap };

        public StatusRow(string label)
        {
            var panel = new DockPanel { Margin = new Thickness(0, 3, 0, 3) };
            var name = new TextBlock { Text = label, Width = 170, Foreground = Muted };
            DockPanel.SetDock(_dot, Dock.Left);
            DockPanel.SetDock(name, Dock.Left);
            panel.Children.Add(_dot);
            panel.Children.Add(name);
            panel.Children.Add(_value);
            Element = panel;
            Set(Gray, "...");
        }

        public UIElement Element { get; }

        public void Set(Brush color, string text)
        {
            _dot.Fill = color;
            _value.Text = text;
        }
    }

    // ------------------------------------------------------------------ fluxo

    private async Task OnLoadedAsync()
    {
        _gpuRow.Set(_gpu.Name != null ? Green : Amber, _gpu.Name != null ? $"{_gpu.Name} (driver {_gpu.Driver})" : "sem placa NVIDIA (vai usar o processador)");
        if (!_settings.SetupDone || !File.Exists(Paths.Python))
        {
            ShowSetup(true);
            AppendLog("Primeira execução: escolha a pasta das partidas e clique em Instalar.");
            return;
        }

        ShowSetup(false);
        _timer.Start();
        await EnsureRequirementsAsync();
        StartBackend(openPanel: true);
        await UpdateAsync(interactive: false);
    }

    private void ShowSetup(bool setup)
    {
        _setup.Visibility = setup ? Visibility.Visible : Visibility.Collapsed;
        _dashboard.Visibility = setup ? Visibility.Collapsed : Visibility.Visible;
        _dataDirText.Text = _settings.DataDir ?? "";
    }

    private async Task InstallAsync()
    {
        if (_busy)
            return;
        var dataDir = _dataDirBox.Text.Trim();
        if (string.IsNullOrEmpty(dataDir))
        {
            MessageBox.Show(this, "Escolha a pasta das partidas.", "FC Analytics");
            return;
        }
        try
        {
            Directory.CreateDirectory(dataDir);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, $"Não foi possível usar essa pasta: {ex.Message}", "FC Analytics");
            return;
        }

        SetBusy(true);
        var installer = new Installer(line => Ui(() => AppendLog(line)), Step);
        try
        {
            var torch = Installer.TorchIndexFor(_gpu.Driver);
            await Task.Run(() => installer.InstallAllAsync(torch, CancellationToken.None));
            if (_oldInstall != null && _importCheck.IsChecked == true)
                await Task.Run(() => installer.ImportOld(_oldInstall, dataDir));

            _settings.DataDir = dataDir;
            _settings.TorchIndex = torch;
            _settings.RequirementsHash = Installer.RequirementsHash();
            _settings.SetupDone = true;
            _settings.Save();
            Step("Instalação concluída.");
            ShowSetup(false);
            _timer.Start();
            StartBackend(openPanel: true);
        }
        catch (Exception ex)
        {
            Step("A instalação parou: " + ex.Message);
            AppendLog(ex.ToString());
        }
        finally
        {
            SetBusy(false);
        }
    }

    /// <summary>Depois de uma atualização, instala as bibliotecas novas (se a lista mudou).</summary>
    private async Task EnsureRequirementsAsync()
    {
        string hash;
        try
        {
            hash = Installer.RequirementsHash();
        }
        catch (Exception)
        {
            return;
        }
        if (hash == _settings.RequirementsHash)
            return;
        SetBusy(true);
        var installer = new Installer(line => Ui(() => AppendLog(line)), Step);
        try
        {
            await Task.Run(() => installer.InstallRequirementsAsync(CancellationToken.None));
            _settings.RequirementsHash = hash;
            _settings.Save();
            Step("Bibliotecas atualizadas.");
        }
        catch (Exception ex)
        {
            Step("Falha ao atualizar as bibliotecas: " + ex.Message);
        }
        finally
        {
            SetBusy(false);
        }
    }

    private async void StartBackend(bool openPanel)
    {
        if (_backend.Running || _settings.DataDir == null)
            return;
        if (await Backend.HealthAsync() != null)
        {
            AppendLog("Já existe um FC Analytics rodando na porta 8000 (talvez pelo iniciar.bat antigo). "
                      + "Feche aquelas janelas pretas e clique em Iniciar.");
            Step("Outro FC Analytics já está rodando.");
            return;
        }
        if (await Backend.OllamaAsync() == null)
            Backend.TryStartOllama();
        try
        {
            _backend.Start(_settings.DataDir);
            _openWhenReady = openPanel;
            Step("Iniciando a análise... (o primeiro início pode levar até 1 minuto)");
        }
        catch (Exception ex)
        {
            Step("Não foi possível iniciar: " + ex.Message);
        }
    }

    private void StopBackend()
    {
        _backend.Stop();
        _openWhenReady = false;
        Step("Análise parada.");
    }

    private async Task RefreshStatusAsync()
    {
        var health = await Backend.HealthAsync();
        if (health != null)
        {
            _backendRow.Set(Green, $"rodando (versão {health})");
            if (_openWhenReady)
            {
                _openWhenReady = false;
                Step("Pronto. O painel abre no navegador; lá, clique em Escolher aba.");
                Backend.OpenPanel();
            }
        }
        else if (_backend.Running)
        {
            _backendRow.Set(Amber, "iniciando...");
        }
        else
        {
            _backendRow.Set(Gray, "parado");
        }

        var ollama = await Backend.OllamaAsync();
        _ollamaRow.Set(ollama != null ? Green : Amber, ollama != null ? $"aberto (versão {ollama})" : "fechado ou não instalado");
        _ollamaButton.Visibility = ollama != null ? Visibility.Collapsed : Visibility.Visible;
        _startButton.IsEnabled = !_backend.Running && !_busy;
        _stopButton.IsEnabled = _backend.Running;
        _openButton.IsEnabled = health != null;
    }

    private async Task OllamaActionAsync()
    {
        if (Backend.TryStartOllama())
        {
            Step("Abrindo o Ollama...");
            return;
        }
        var answer = MessageBox.Show(this,
            "O Ollama (que roda o LLM das análises) não está instalado. Instalar agora pelo winget?",
            "FC Analytics", MessageBoxButton.YesNo, MessageBoxImage.Question);
        if (answer != MessageBoxResult.Yes)
            return;
        SetBusy(true);
        Step("Instalando o Ollama...");
        var code = await Shell.RunAsync("winget",
            "install --exact --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements",
            null, null, line => Ui(() => AppendLog(line)));
        SetBusy(false);
        Step(code == 0 ? "Ollama instalado." : "Não foi possível instalar o Ollama. Veja o registro.");
        Backend.TryStartOllama();
    }

    private async Task UpdateAsync(bool interactive)
    {
        if (_updates is not { IsInstalled: true })
        {
            if (interactive)
                _updateText.Text = "As atualizações só funcionam na versão instalada pelo Setup.";
            return;
        }
        try
        {
            _updateText.Text = "Procurando atualizações...";
            var info = await _updates.CheckForUpdatesAsync();
            if (info == null)
            {
                _updateText.Text = $"Você está na versão mais nova ({_updates.CurrentVersion}).";
                return;
            }
            var target = info.TargetFullRelease.Version;
            if (!interactive)
            {
                _updateText.Text = $"Nova versão disponível: {target}. Clique em Buscar atualizações para instalar.";
                _updateButton.Background = Accent;
                _updateButton.Foreground = Brushes.White;
                return;
            }
            var answer = MessageBox.Show(this,
                $"A versão {target} está disponível. Instalar agora? O app fecha e abre de novo sozinho.",
                "FC Analytics", MessageBoxButton.YesNo, MessageBoxImage.Question);
            if (answer != MessageBoxResult.Yes)
                return;
            SetBusy(true);
            _progress.IsIndeterminate = false;
            _progress.Value = 0;
            Step($"Baixando a versão {target}...");
            await _updates.DownloadUpdatesAsync(info, p => Ui(() => _progress.Value = p));
            Step("Instalando a atualização...");
            _backend.Stop();
            _updates.ApplyUpdatesAndRestart(info.TargetFullRelease);
        }
        catch (Exception ex)
        {
            _updateText.Text = "Não foi possível buscar atualizações: " + ex.Message;
            SetBusy(false);
        }
    }

    private void OpenDataDir()
    {
        if (_settings.DataDir != null && Directory.Exists(_settings.DataDir))
            Shell.Open(_settings.DataDir);
    }

    private void ChangeDataDir()
    {
        var chosen = PickFolder(_settings.DataDir);
        if (chosen == null || chosen == _settings.DataDir)
            return;
        var old = _settings.DataDir;
        var move = old != null && Directory.Exists(old) && Directory.GetFiles(old).Length > 0 &&
                   MessageBox.Show(this, "Levar as partidas gravadas para a nova pasta?", "FC Analytics",
                       MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes;
        var wasRunning = _backend.Running;
        _backend.Stop();
        try
        {
            Directory.CreateDirectory(chosen);
            if (move && old != null)
            {
                foreach (var file in Directory.GetFiles(old))
                {
                    var target = Path.Combine(chosen, Path.GetFileName(file));
                    if (!File.Exists(target))
                        File.Move(file, target);
                }
            }
            _settings.DataDir = chosen;
            _settings.Save();
            _dataDirText.Text = chosen;
            Step("Pasta das partidas alterada.");
        }
        catch (Exception ex)
        {
            Step("Não foi possível trocar a pasta: " + ex.Message);
        }
        if (wasRunning)
            StartBackend(openPanel: false);
    }

    private string? PickFolder(string? initial)
    {
        var dialog = new OpenFolderDialog { Title = "Pasta das partidas" };
        if (!string.IsNullOrEmpty(initial) && Directory.Exists(initial))
            dialog.InitialDirectory = initial;
        return dialog.ShowDialog(this) == true ? dialog.FolderName : null;
    }

    private void SetBusy(bool busy)
    {
        _busy = busy;
        _installButton.IsEnabled = !busy;
        _updateButton.IsEnabled = !busy;
        _progress.IsIndeterminate = busy;
        _progress.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
    }

    private void Step(string text)
    {
        Ui(() =>
        {
            _stepText.Text = text;
            AppendLog("== " + text);
        });
    }

    private void AppendLog(string line)
    {
        _log.AppendText(line + Environment.NewLine);
        if (_log.LineCount > 600)
        {
            var text = _log.Text;
            _log.Text = text.Substring(text.Length / 2);
        }
        _log.ScrollToEnd();
    }

    private void OnClosing(object? sender, CancelEventArgs e)
    {
        if (_busy)
        {
            var answer = MessageBox.Show(this, "Uma instalação está em andamento. Fechar mesmo assim?", "FC Analytics",
                MessageBoxButton.YesNo, MessageBoxImage.Warning);
            if (answer != MessageBoxResult.Yes)
            {
                e.Cancel = true;
                return;
            }
        }
        _timer.Stop();
        _backend.Stop();
    }
}
