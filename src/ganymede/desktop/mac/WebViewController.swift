import Cocoa
import WebKit

final class WebViewController: NSViewController, WKNavigationDelegate, WKUIDelegate {
    var webView: WKWebView!
    private var loadingOverlay: NSView!
    private var statusLabel: NSTextField!
    private var spinner: NSProgressIndicator!
    private var retryButton: NSButton!
    private var titleLabel: NSTextField!

    override func loadView() {
        let root = NSView(frame: NSRect(x: 0, y: 0, width: 1280, height: 800))
        root.wantsLayer = true
        root.layer?.backgroundColor = NSColor(red: 0.08, green: 0.09, blue: 0.11, alpha: 1.0).cgColor
        self.view = root

        setupWebView()
        setupLoadingOverlay()
    }

    private func setupWebView() {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        config.defaultWebpagePreferences.allowsContentJavaScript = true

        webView = WKWebView(frame: view.bounds, configuration: config)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        webView.uiDelegate = self
        
        // Standard Desktop Safari User-Agent for flawless web compatibility and OAuth
        webView.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
        
        // Enable Web Inspector on macOS 13.3+
        if #available(macOS 13.3, *) {
            webView.isInspectable = true
        }

        view.addSubview(webView)
    }

    private func setupLoadingOverlay() {
        loadingOverlay = NSView(frame: view.bounds)
        loadingOverlay.autoresizingMask = [.width, .height]
        loadingOverlay.wantsLayer = true
        loadingOverlay.layer?.backgroundColor = NSColor(red: 0.06, green: 0.07, blue: 0.09, alpha: 1.0).cgColor

        let container = NSStackView()
        container.orientation = .vertical
        container.alignment = .centerX
        container.spacing = 16
        container.translatesAutoresizingMaskIntoConstraints = false

        titleLabel = NSTextField(labelWithString: "GANYMEDE GATEWAY")
        titleLabel.font = NSFont.systemFont(ofSize: 22, weight: .bold)
        titleLabel.textColor = NSColor(red: 0.81, green: 0.66, blue: 0.37, alpha: 1.0) // Gold accent
        titleLabel.alignment = .center

        spinner = NSProgressIndicator()
        spinner.style = .spinning
        spinner.controlSize = .regular
        spinner.startAnimation(nil)

        statusLabel = NSTextField(labelWithString: "Initializing services...")
        statusLabel.font = NSFont.systemFont(ofSize: 13, weight: .medium)
        statusLabel.textColor = NSColor.secondaryLabelColor
        statusLabel.alignment = .center

        retryButton = NSButton(title: "Retry Connection", target: self, action: #selector(onRetryClicked))
        retryButton.bezelStyle = .rounded
        retryButton.isHidden = true

        container.addArrangedSubview(titleLabel)
        container.addArrangedSubview(spinner)
        container.addArrangedSubview(statusLabel)
        container.addArrangedSubview(retryButton)

        loadingOverlay.addSubview(container)
        NSLayoutConstraint.activate([
            container.centerXAnchor.constraint(equalTo: loadingOverlay.centerXAnchor),
            container.centerYAnchor.constraint(equalTo: loadingOverlay.centerYAnchor)
        ])

        view.addSubview(loadingOverlay)
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        
        DaemonSupervisor.shared.onStatusChanged = { [weak self] isRunning, message in
            DispatchQueue.main.async {
                self?.statusLabel.stringValue = message
                if !isRunning && message.contains("Error") {
                    self?.spinner.stopAnimation(nil)
                    self?.retryButton.isHidden = false
                }
            }
        }

        startDaemonAndLoad()
    }

    func showLoading(message: String) {
        statusLabel.stringValue = message
        spinner.startAnimation(nil)
        retryButton.isHidden = true
        loadingOverlay.isHidden = false
        loadingOverlay.alphaValue = 1.0
    }

    func startDaemonAndLoad() {
        showLoading(message: "Checking gateway status...")

        DaemonSupervisor.shared.startDaemonIfNeeded { [weak self] success in
            guard let self = self else { return }
            if success {
                self.loadDashboard()
            } else {
                self.spinner.stopAnimation(nil)
                self.retryButton.isHidden = false
            }
        }
    }

    func loadDashboard() {
        let url = DaemonSupervisor.shared.dashboardURL
        let request = URLRequest(url: url)
        webView.load(request)
    }

    func reload() {
        webView.reload()
    }

    func forceReload() {
        webView.reloadFromOrigin()
    }

    @objc private func onRetryClicked() {
        startDaemonAndLoad()
    }

    // MARK: - WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // Fade out overlay smoothly once dashboard is ready
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.35
            loadingOverlay.animator().alphaValue = 0.0
        } completionHandler: {
            self.loadingOverlay.isHidden = true
            self.loadingOverlay.alphaValue = 1.0
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        statusLabel.stringValue = "Connection failed: \(error.localizedDescription)"
        spinner.stopAnimation(nil)
        retryButton.isHidden = false
        loadingOverlay.isHidden = false
    }

    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.allow)
            return
        }

        // Allow in-page anchors, about:blank, or scheme-less navigations
        if url.scheme == nil || url.scheme == "about" || url.host == nil {
            decisionHandler(.allow)
            return
        }

        let host = url.host?.lowercased() ?? ""
        let isLocalhost = host == "127.0.0.1" || host == "localhost"
        
        // Allow Google OAuth & Cerberus Keycloak domains in the webview
        let isAuthHost = host.contains("google.com")
            || host.contains("gstatic.com")
            || host.contains("technocraftonline.com")
            || host.contains("dforge.ca")

        if isLocalhost || isAuthHost {
            decisionHandler(.allow)
        } else {
            // External links (e.g. Patreon, docs, GitHub) open in default system handler
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    // MARK: - WKUIDelegate

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        // Intercept target="_blank" and open internally or in browser
        if let url = navigationAction.request.url {
            let host = url.host?.lowercased() ?? ""
            let isLocal = host == "127.0.0.1"
                || host == "localhost"
                || host.isEmpty
                || host.contains("google.com")
                || host.contains("gstatic.com")
                || host.contains("technocraftonline.com")
                || host.contains("dforge.ca")
            if isLocal {
                webView.load(navigationAction.request)
            } else {
                NSWorkspace.shared.open(url)
            }
        }
        return nil
    }
}
