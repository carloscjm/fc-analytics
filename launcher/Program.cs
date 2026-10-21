using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using Velopack;

namespace FCAnalytics;

public static class Program
{
    [STAThread]
    public static void Main(string[] args)
    {
        // Precisa ser a primeira coisa: trata instalação, desinstalação e atualização do Velopack.
        VelopackApp.Build().Run();

        var app = new Application { ShutdownMode = ShutdownMode.OnMainWindowClose };
        app.DispatcherUnhandledException += (_, e) =>
        {
            MessageBox.Show(e.Exception.Message, "FC Analytics", MessageBoxButton.OK, MessageBoxImage.Error);
            e.Handled = true;
        };
        app.Run(new MainWindow());
    }
}
