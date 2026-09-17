import Cocoa
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var webViewController: WebViewController!

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenu()
        setupWindow()
    }

    private func setupWindow() {
        let rect = NSRect(x: 0, y: 0, width: 1280, height: 820)
        window = NSWindow(
            contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.center()
        window.minSize = NSSize(width: 900, height: 600)
        window.title = "Ganymede Gateway"
        window.titleVisibility = .visible
        window.titlebarAppearsTransparent = false
        window.backgroundColor = NSColor(red: 0.08, green: 0.09, blue: 0.11, alpha: 1.0)

        webViewController = WebViewController()
        window.contentViewController = webViewController
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func setupMenu() {
        let mainMenu = NSMenu()

        // 1. App Menu
        let appMenuItem = NSMenuItem()
        let appMenu = NSMenu(title: "Ganymede")
        appMenu.addItem(withTitle: "About Ganymede", action: #selector(showAbout), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Hide Ganymede", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let hideOthers = NSMenuItem(title: "Hide Others", action: #selector(NSApplication.hideOtherApplications(_:)), keyEquivalent: "h")
        hideOthers.keyEquivalentModifierMask = [.command, .option]
        appMenu.addItem(hideOthers)
        appMenu.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        appMenu.addItem(NSMenuItem.separator())
        appMenu.addItem(withTitle: "Quit Ganymede", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appMenuItem.submenu = appMenu
        mainMenu.addItem(appMenuItem)

        // 2. File Menu
        let fileMenuItem = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        fileMenu.addItem(withTitle: "Reload", action: #selector(reloadDashboard), keyEquivalent: "r")
        let forceReload = NSMenuItem(title: "Force Reload", action: #selector(forceReloadDashboard), keyEquivalent: "r")
        forceReload.keyEquivalentModifierMask = [.command, .shift]
        fileMenu.addItem(forceReload)
        fileMenu.addItem(NSMenuItem.separator())
        fileMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        fileMenuItem.submenu = fileMenu
        mainMenu.addItem(fileMenuItem)

        // 3. Edit Menu (Standard macOS responder chain)
        let editMenuItem = NSMenuItem()
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Undo", action: #selector(UndoManager.undo), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Redo", action: #selector(UndoManager.redo), keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editMenuItem.submenu = editMenu
        mainMenu.addItem(editMenuItem)

        // 4. View Menu
        let viewMenuItem = NSMenuItem()
        let viewMenu = NSMenu(title: "View")
        viewMenu.addItem(withTitle: "Toggle Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        viewMenu.addItem(NSMenuItem.separator())
        viewMenu.addItem(withTitle: "Actual Size", action: #selector(zoomActual), keyEquivalent: "0")
        viewMenu.addItem(withTitle: "Zoom In", action: #selector(zoomIn), keyEquivalent: "+")
        viewMenu.addItem(withTitle: "Zoom Out", action: #selector(zoomOut), keyEquivalent: "-")
        viewMenu.addItem(NSMenuItem.separator())
        
        let inspectItem = NSMenuItem(title: "Toggle Web Inspector", action: #selector(toggleWebInspector), keyEquivalent: "i")
        inspectItem.keyEquivalentModifierMask = [.command, .option]
        viewMenu.addItem(inspectItem)
        
        viewMenuItem.submenu = viewMenu
        mainMenu.addItem(viewMenuItem)

        // 5. Gateway Menu
        let gatewayMenuItem = NSMenuItem()
        let gatewayMenu = NSMenu(title: "Gateway")
        gatewayMenu.addItem(withTitle: "Restart Gateway Daemon", action: #selector(restartGateway), keyEquivalent: "")
        gatewayMenu.addItem(withTitle: "Open in Default Browser", action: #selector(openInBrowser), keyEquivalent: "b")
        gatewayMenu.addItem(NSMenuItem.separator())
        gatewayMenu.addItem(withTitle: "View Gateway Logs", action: #selector(viewGatewayLogs), keyEquivalent: "l")
        gatewayMenuItem.submenu = gatewayMenu
        mainMenu.addItem(gatewayMenuItem)

        // 6. Window Menu
        let windowMenuItem = NSMenuItem()
        let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(NSMenuItem.separator())
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)

        NSApp.mainMenu = mainMenu
    }

    @objc func reloadDashboard() {
        webViewController?.reload()
    }

    @objc func forceReloadDashboard() {
        webViewController?.forceReload()
    }

    @objc func zoomActual() {
        webViewController?.webView.pageZoom = 1.0
    }

    @objc func zoomIn() {
        webViewController?.webView.pageZoom += 0.1
    }

    @objc func zoomOut() {
        if let current = webViewController?.webView.pageZoom, current > 0.4 {
            webViewController?.webView.pageZoom -= 0.1
        }
    }

    @objc func toggleWebInspector() {
        if #available(macOS 13.3, *) {
            if let webView = webViewController?.webView {
                let sel = Selector(("_showInspector"))
                if webView.responds(to: sel) {
                    webView.perform(sel)
                }
            }
        }
    }

    @objc func restartGateway() {
        webViewController?.showLoading(message: "Restarting Gateway daemon...")
        DaemonSupervisor.shared.restartDaemon { [weak self] success in
            if success {
                self?.webViewController?.loadDashboard()
            }
        }
    }

    @objc func openInBrowser() {
        let url = DaemonSupervisor.shared.dashboardURL
        NSWorkspace.shared.open(url)
    }

    @objc func viewGatewayLogs() {
        let logPath = NSString(string: "~/.ganymede/ganymede.log").expandingTildeInPath
        if FileManager.default.fileExists(atPath: logPath) {
            NSWorkspace.shared.open(URL(fileURLWithPath: logPath))
        } else {
            let appLog = NSString(string: "~/.ganymede/ganymede_app.log").expandingTildeInPath
            if FileManager.default.fileExists(atPath: appLog) {
                NSWorkspace.shared.open(URL(fileURLWithPath: appLog))
            }
        }
    }

    @objc func showAbout() {
        let alert = NSAlert()
        alert.messageText = "Ganymede Gateway"
        alert.informativeText = "Antigravity Gateway & Communications Control Panel\nVersion 0.1.104\nDigital Forge Studios Inc."
        alert.alertStyle = .informational
        alert.runModal()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            window?.makeKeyAndOrderFront(nil)
        }
        return true
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            if url.scheme == "ganymede" {
                webViewController?.loadDashboard()
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        // Graceful exit
    }
}
