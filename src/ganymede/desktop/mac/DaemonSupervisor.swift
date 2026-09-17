import Foundation
import AppKit

final class DaemonSupervisor: NSObject {
    static let shared = DaemonSupervisor()

    private(set) var isDaemonRunning = false
    private(set) var daemonProcess: Process?
    private var healthCheckTimer: Timer?
    
    let defaultPort: Int = 8180
    var dashboardURL: URL {
        return URL(string: "http://127.0.0.1:\(defaultPort)")!
    }
    
    var statusURL: URL {
        return URL(string: "http://127.0.0.1:\(defaultPort)/api/status")!
    }

    var onStatusChanged: ((Bool, String) -> Void)?

    func checkDaemonHealth(completion: @escaping (Bool) -> Void) {
        var request = URLRequest(url: statusURL)
        request.timeoutInterval = 1.5
        request.httpMethod = "GET"

        let task = URLSession.shared.dataTask(with: request) { _, response, error in
            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                DispatchQueue.main.async {
                    self.isDaemonRunning = true
                    completion(true)
                }
            } else {
                DispatchQueue.main.async {
                    self.isDaemonRunning = false
                    completion(false)
                }
            }
        }
        task.resume()
    }

    func findGanymedeExecutable() -> String? {
        let fileManager = FileManager.default
        let searchPaths = [
            "/opt/homebrew/bin/ganymede",
            "/usr/local/bin/ganymede",
            NSString(string: "~/.local/bin/ganymede").expandingTildeInPath,
            NSString(string: "~/dev/ganymede/bin/ganymede").expandingTildeInPath
        ]
        for path in searchPaths {
            if fileManager.isExecutableFile(atPath: path) {
                return path
            }
        }
        
        // Also check PATH via which
        let whichProcess = Process()
        let pipe = Pipe()
        whichProcess.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        whichProcess.arguments = ["ganymede"]
        whichProcess.standardOutput = pipe
        try? whichProcess.run()
        whichProcess.waitUntilExit()
        
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        if let out = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines), !out.isEmpty {
            if fileManager.isExecutableFile(atPath: out) {
                return out
            }
        }
        
        return nil
    }

    func startDaemonIfNeeded(completion: @escaping (Bool) -> Void) {
        checkDaemonHealth { alreadyRunning in
            if alreadyRunning {
                self.onStatusChanged?(true, "Connected to running Ganymede daemon")
                completion(true)
                return
            }

            self.onStatusChanged?(false, "Starting Ganymede gateway service...")
            guard let execPath = self.findGanymedeExecutable() else {
                self.onStatusChanged?(false, "Error: 'ganymede' binary not found. Please verify Homebrew installation.")
                completion(false)
                return
            }

            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: execPath)
            proc.arguments = ["run"]
            
            // Set up environment with Homebrew PATH
            var env = ProcessInfo.processInfo.environment
            let existingPath = env["PATH"] ?? ""
            env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:\(existingPath)"
            proc.environment = env

            // Standard output and error redirect to log file
            let logDir = NSString(string: "~/.ganymede").expandingTildeInPath
            try? FileManager.default.createDirectory(atPath: logDir, withIntermediateDirectories: true)
            let logPath = (logDir as NSString).appendingPathComponent("ganymede_app.log")
            
            FileManager.default.createFile(atPath: logPath, contents: nil)
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                proc.standardOutput = fileHandle
                proc.standardError = fileHandle
            }

            do {
                try proc.run()
                self.daemonProcess = proc
            } catch {
                self.onStatusChanged?(false, "Failed to launch process: \(error.localizedDescription)")
                completion(false)
                return
            }

            // Poll for readiness
            var attempts = 0
            let maxAttempts = 50 // 50 * 0.3s = 15 seconds
            
            Timer.scheduledTimer(withTimeInterval: 0.3, repeats: true) { timer in
                attempts += 1
                self.checkDaemonHealth { isUp in
                    if isUp {
                        timer.invalidate()
                        self.onStatusChanged?(true, "Ganymede is online")
                        completion(true)
                    } else if attempts >= maxAttempts {
                        timer.invalidate()
                        self.onStatusChanged?(false, "Timed out waiting for Ganymede to boot. Check ~/.ganymede/ganymede_app.log")
                        completion(false)
                    }
                }
            }
        }
    }

    func restartDaemon(completion: @escaping (Bool) -> Void) {
        onStatusChanged?(false, "Restarting Ganymede daemon...")
        
        // If we spawned it, terminate it
        if let proc = daemonProcess, proc.isRunning {
            proc.terminate()
        }
        
        // Also send CLI restart / stop to be thorough
        if let exec = findGanymedeExecutable() {
            let stopProc = Process()
            stopProc.executableURL = URL(fileURLWithPath: exec)
            stopProc.arguments = ["stop"]
            try? stopProc.run()
            stopProc.waitUntilExit()
        }
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.startDaemonIfNeeded(completion: completion)
        }
    }

    func stopDaemonIfSpawned() {
        if let proc = daemonProcess, proc.isRunning {
            proc.terminate()
        }
    }
}
