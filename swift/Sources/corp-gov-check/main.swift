import Foundation
import GovernanceTypes

/// Thin typed splash: validate assist / proof JSON produced by Python, then echo it.
/// Python remains the sole writer for program.json.

@main
struct CorpGovCheck {
    static func main() {
        let args = Array(CommandLine.arguments.dropFirst())
        guard let command = args.first else {
            fputs(
                "usage: corp-gov-check <diagnose|scaffold-approval|scaffold-factory-auth|"
                    + "explain-transition|explain-stale|check-handoff|"
                    + "check-authorized-surfaces|validate-action|write-receipt> --root PATH "
                    + "[--to PHASE] [--path REL ...] [--action ACTION]\n",
                stderr
            )
            exit(2)
        }

        let isHeavyProof = command == "validate-action" || command == "write-receipt"
        if !isHeavyProof {
            guard GovAssistCommand(rawValue: command) != nil else {
                fputs("unsupported command: \(command)\n", stderr)
                exit(2)
            }
        }

        var root: String?
        var toPhase: String?
        var action: String?
        var paths: [String] = []
        var idx = 1
        while idx < args.count {
            let token = args[idx]
            if token == "--root", idx + 1 < args.count {
                root = args[idx + 1]
                idx += 2
                continue
            }
            if token == "--to", idx + 1 < args.count {
                toPhase = args[idx + 1]
                idx += 2
                continue
            }
            if token == "--path", idx + 1 < args.count {
                paths.append(args[idx + 1])
                idx += 2
                continue
            }
            if token == "--action", idx + 1 < args.count {
                action = args[idx + 1]
                idx += 2
                continue
            }
            fputs("unknown argument: \(token)\n", stderr)
            exit(2)
        }
        guard let root else {
            fputs("--root is required\n", stderr)
            exit(2)
        }
        if command == "validate-action", action == nil {
            fputs("--action is required for validate-action\n", stderr)
            exit(2)
        }

        var argv = ["python3", "-m", "corp_harness.swift_gov"]
        switch command {
        case "validate-action":
            argv.append(contentsOf: ["--validate-action", "--root", root, "--action", action!])
        case "write-receipt":
            argv.append(contentsOf: ["--write-receipt", "--root", root])
        default:
            argv.append(contentsOf: ["--assist", command, "--root", root])
            if let toPhase {
                argv.append(contentsOf: ["--to", toPhase])
            }
            for path in paths {
                argv.append(contentsOf: ["--path", path])
            }
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = argv
        let stdout = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdout
        process.standardError = stderrPipe
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            let errorCode = isHeavyProof ? "GOV_REQUIRED" : "GOV_ASSIST_UNAVAILABLE"
            let payload: [String: Any] = [
                "ok": false,
                "assist": !isHeavyProof,
                "mutation": false,
                "error": errorCode,
                "detail": "failed to launch python assist: \(error)",
                "command": command,
            ]
            emitJSON(payload)
            exit(2)
        }

        let data = stdout.fileHandleForReading.readDataToEndOfFile()
        let errData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        guard !data.isEmpty else {
            let errText = String(data: errData, encoding: .utf8) ?? ""
            let errorCode = isHeavyProof ? "GOV_REQUIRED" : "GOV_ASSIST_UNAVAILABLE"
            let payload: [String: Any] = [
                "ok": false,
                "assist": !isHeavyProof,
                "mutation": false,
                "error": errorCode,
                "detail": "python assist produced empty stdout: \(errText)",
                "command": command,
            ]
            emitJSON(payload)
            exit(2)
        }

        if isHeavyProof {
            do {
                _ = try JSONDecoder().decode(ProofEnvelope.self, from: data)
            } catch {
                // Proof envelope may include ok/assist fields; accept TrustEvent-adjacent JSON.
                // Fall through and echo bytes if envelope-only decode fails.
                if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   obj["schema"] as? String == ProofEnvelope.schemaName
                    || obj["command"] as? String == command
                {
                    // ok
                } else {
                    fputs("\(command) payload failed type check: \(error)\n", stderr)
                }
            }
        } else {
            do {
                _ = try JSONDecoder().decode(GovAssistEnvelope.self, from: data)
            } catch {
                fputs("assist payload failed GovernanceTypes decode: \(error)\n", stderr)
                if let text = String(data: data, encoding: .utf8) {
                    FileHandle.standardOutput.write(Data(text.utf8))
                }
                exit(process.terminationStatus == 0 ? 1 : Int32(process.terminationStatus))
            }
        }

        FileHandle.standardOutput.write(data)
        if data.last != UInt8(ascii: "\n") {
            FileHandle.standardOutput.write(Data("\n".utf8))
        }
        exit(process.terminationStatus)
    }

    static func emitJSON(_ payload: [String: Any]) {
        if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys, .prettyPrinted]),
           let text = String(data: data, encoding: .utf8)
        {
            print(text)
        }
    }
}
