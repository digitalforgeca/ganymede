import Cocoa
import WebKit

final class MainWindow: NSWindow {
    override func performMiniaturize(_ sender: Any?) {
        if let delegate = self.delegate as? AppDelegate {
            delegate.shrinkToTray()
        } else {
            super.performMiniaturize(sender)
        }
    }

    override func miniaturize(_ sender: Any?) {
        if let delegate = self.delegate as? AppDelegate {
            delegate.shrinkToTray()
        } else {
            super.miniaturize(sender)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuDelegate {
    var window: NSWindow!
    var webViewController: WebViewController!
    private var statusItem: NSStatusItem!

    func applicationDidFinishLaunching(_ notification: Notification) {
        setupMenu()
        setupWindow()
        setupTray()
        setupDaemonObserver()
    }

    private func setupWindow() {
        let rect = NSRect(x: 0, y: 0, width: 1280, height: 820)
        window = MainWindow(
            contentRect: rect,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.delegate = self
        window.center()
        window.minSize = NSSize(width: 900, height: 600)
        window.title = "Ganymede Gateway"
        window.titleVisibility = .visible
        window.titlebarAppearsTransparent = false
        window.backgroundColor = NSColor(red: 0.08, green: 0.09, blue: 0.11, alpha: 1.0)
        window.animationBehavior = .none

        if let minButton = window.standardWindowButton(.miniaturizeButton) {
            minButton.target = self
            minButton.action = #selector(shrinkToTray)
        }

        savedFrame = window.frame
        webViewController = WebViewController()
        window.contentViewController = webViewController
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: - Tray (Menu Bar Status Item)

    private func setupTray() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = createTrayImage()
            button.toolTip = "Ganymede Gateway\n(Click to Show/Hide, Right-Click for Menu)"
            button.target = self
            button.action = #selector(statusItemClicked(_:))
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
    }

    private func createTrayImage() -> NSImage {
        if let imagePath = Bundle.main.path(forResource: "AppLogo", ofType: "png"),
           let img = NSImage(contentsOfFile: imagePath) {
            img.size = NSSize(width: 18, height: 18)
            img.isTemplate = true
            return img
        }
        if let img = NSImage(named: "AppLogo") {
            img.size = NSSize(width: 18, height: 18)
            img.isTemplate = true
            return img
        }
        if #available(macOS 11.0, *), let symbol = NSImage(systemSymbolName: "orbit", accessibilityDescription: "Ganymede") {
            symbol.size = NSSize(width: 18, height: 18)
            symbol.isTemplate = true
            return symbol
        }
        return NSImage(size: NSSize(width: 18, height: 18))
    }

    @objc private func statusItemClicked(_ sender: NSStatusBarButton) {
        guard let event = NSApp.currentEvent else {
            toggleWindow()
            return
        }

        if event.type == .rightMouseUp || event.modifierFlags.contains(.control) || event.modifierFlags.contains(.option) {
            let menu = buildTrayMenu()
            menu.delegate = self
            menu.popUp(positioning: nil, at: NSPoint(x: 0, y: 0), in: sender)
        } else {
            toggleWindow()
        }
    }

    private func buildTrayMenu() -> NSMenu {
        let menu = NSMenu(title: "Ganymede Tray")

        let isVisible = window != nil && window.isVisible && !window.isMiniaturized && window.alphaValue > 0.5
        let toggleTitle = isVisible ? "Shrink to Tray" : "Show Ganymede"
        let toggleItem = NSMenuItem(title: toggleTitle, action: isVisible ? #selector(shrinkToTray) : #selector(showWindow), keyEquivalent: "")
        toggleItem.target = self
        let font = NSFont.boldSystemFont(ofSize: NSFont.systemFontSize)
        toggleItem.attributedTitle = NSAttributedString(string: toggleTitle, attributes: [.font: font])
        menu.addItem(toggleItem)

        menu.addItem(NSMenuItem.separator())

        let isRunning = DaemonSupervisor.shared.isDaemonRunning
        let port = DaemonSupervisor.shared.activePort
        let statusText = isRunning ? "● Gateway: Online (Port \(port))" : "○ Gateway: Offline"
        let statusItem = NSMenuItem(title: statusText, action: nil, keyEquivalent: "")
        statusItem.isEnabled = false
        menu.addItem(statusItem)

        menu.addItem(NSMenuItem.separator())

        let reloadItem = NSMenuItem(title: "Reload Dashboard", action: #selector(reloadDashboard), keyEquivalent: "r")
        reloadItem.target = self
        menu.addItem(reloadItem)

        let browserItem = NSMenuItem(title: "Open in Browser", action: #selector(openInBrowser), keyEquivalent: "b")
        browserItem.target = self
        menu.addItem(browserItem)

        let logsItem = NSMenuItem(title: "View Gateway Logs", action: #selector(viewGatewayLogs), keyEquivalent: "l")
        logsItem.target = self
        menu.addItem(logsItem)

        menu.addItem(NSMenuItem.separator())

        let restartItem = NSMenuItem(title: "Restart Gateway Daemon", action: #selector(restartGateway), keyEquivalent: "")
        restartItem.target = self
        menu.addItem(restartItem)

        menu.addItem(NSMenuItem.separator())

        let quitItem = NSMenuItem(title: "Quit Ganymede", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quitItem)

        return menu
    }

    private func setupDaemonObserver() {
        DaemonSupervisor.shared.onStatusChanged = { [weak self] isRunning, message in
            DispatchQueue.main.async {
                let port = DaemonSupervisor.shared.activePort
                let status = isRunning ? "Online (Port \(port))" : "Offline"
                self?.statusItem?.button?.toolTip = "Ganymede Gateway: \(status)\n(Click to Show/Hide, Right-Click for Menu)"
            }
        }
    }

    // MARK: - Window Visibility & Animated Shrink to Tray

    private var isTransitioning = false
    private var savedFrame: NSRect?

    private func trayOffset(for w: NSWindow) -> (dx: CGFloat, dy: CGFloat) {
        var dx: CGFloat = 0
        if let button = statusItem?.button,
           let buttonWindow = button.window {
            let buttonScreenRect = buttonWindow.convertToScreen(button.convert(button.bounds, to: nil))
            let trayCenterX = buttonScreenRect.midX
            let winCenterX = w.frame.midX
            let diffX = trayCenterX - winCenterX
            if abs(diffX) > 40 {
                dx = diffX > 0 ? 18 : -18
            }
        }
        return (dx: dx, dy: 24)
    }

    @objc func showWindow() {
        if window == nil {
            setupWindow()
            return
        }
        guard let w = window else { return }
        if isTransitioning { return }

        if w.isMiniaturized {
            w.deminiaturize(nil)
        }

        let targetFrame = savedFrame ?? w.frame
        let offset = trayOffset(for: w)
        let startFrame = NSRect(
            x: targetFrame.origin.x + offset.dx,
            y: targetFrame.origin.y + offset.dy,
            width: targetFrame.size.width,
            height: targetFrame.size.height
        )

        isTransitioning = true
        w.setFrame(startFrame, display: false)
        w.alphaValue = 0.0
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.20
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            w.animator().alphaValue = 1.0
            w.animator().setFrame(targetFrame, display: false)
        }, completionHandler: { [weak self] in
            guard let self = self else { return }
            self.savedFrame = w.frame
            self.isTransitioning = false
        })
    }

    @objc func shrinkToTray() {
        guard let w = window, w.isVisible, !isTransitioning else { return }
        isTransitioning = true
        savedFrame = w.frame

        let currentFrame = w.frame
        let offset = trayOffset(for: w)
        let targetFrame = NSRect(
            x: currentFrame.origin.x + offset.dx,
            y: currentFrame.origin.y + offset.dy,
            width: currentFrame.size.width,
            height: currentFrame.size.height
        )

        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.18
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            w.animator().alphaValue = 0.0
            w.animator().setFrame(targetFrame, display: false)
        }, completionHandler: { [weak self] in
            guard let self = self else { return }
            w.orderOut(nil)
            w.alphaValue = 1.0
            if let orig = self.savedFrame {
                w.setFrame(orig, display: false)
            }
            self.isTransitioning = false
        })
    }

    @objc func toggleWindow() {
        if isTransitioning { return }
        if let w = window, w.isVisible && !w.isMiniaturized && NSApp.isActive && w.alphaValue > 0.5 {
            shrinkToTray()
        } else {
            showWindow()
        }
    }

    // MARK: - NSWindowDelegate

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        shrinkToTray()
        return false
    }

    func windowWillMiniaturize(_ notification: Notification) {
        shrinkToTray()
    }

    func windowDidMove(_ notification: Notification) {
        if !isTransitioning, let w = window, w.isVisible {
            savedFrame = w.frame
        }
    }

    func windowDidResize(_ notification: Notification) {
        if !isTransitioning, let w = window, w.isVisible {
            savedFrame = w.frame
        }
    }

    // MARK: - Application Menus

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
        windowMenu.addItem(withTitle: "Shrink to Tray", action: #selector(shrinkToTray), keyEquivalent: "")
        windowMenu.addItem(withTitle: "Minimize to Tray", action: #selector(shrinkToTray), keyEquivalent: "m")
        windowMenu.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        windowMenu.addItem(NSMenuItem.separator())
        windowMenu.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        windowMenuItem.submenu = windowMenu
        mainMenu.addItem(windowMenuItem)

        NSApp.mainMenu = mainMenu
    }

    // MARK: - Actions

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
        alert.informativeText = "Antigravity Gateway & Communications Control Panel\nVersion 0.1.105\nDigital Forge Studios Inc."
        alert.alertStyle = .informational
        alert.runModal()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        showWindow()
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
        if let item = statusItem {
            NSStatusBar.system.removeStatusItem(item)
        }
    }
}
