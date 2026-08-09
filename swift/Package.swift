// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "CorpGovAssist",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .library(name: "GovernanceTypes", targets: ["GovernanceTypes"]),
        .executable(name: "corp-gov-check", targets: ["corp-gov-check"]),
    ],
    targets: [
        .target(
            name: "GovernanceTypes",
            path: "Sources/GovernanceTypes"
        ),
        .executableTarget(
            name: "corp-gov-check",
            dependencies: ["GovernanceTypes"],
            path: "Sources/corp-gov-check"
        ),
        .testTarget(
            name: "GovernanceTypesTests",
            dependencies: ["GovernanceTypes"],
            path: "Tests/GovernanceTypesTests"
        ),
    ]
)
