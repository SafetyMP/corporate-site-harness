import Foundation

/// Typed assist envelopes for corp-gov-check (splash only; no write authority).
public struct GovAssistEnvelope: Codable, Sendable {
    public var schema: String
    public var ok: Bool
    public var assist: Bool
    public var mutation: Bool
    public var command: String
    public var programId: String?
    public var phase: String?
    public var revision: Int?
    public var programDigest: String?
    public var programDigestAfter: String?
    public var phaseUnchanged: Bool?
    public var error: String?
    public var detail: String?

    public enum CodingKeys: String, CodingKey {
        case schema
        case ok
        case assist
        case mutation
        case command
        case programId = "program_id"
        case phase
        case revision
        case programDigest = "program_digest"
        case programDigestAfter = "program_digest_after"
        case phaseUnchanged = "phase_unchanged"
        case error
        case detail
    }
}

public struct CorporateAcceptanceAssist: Codable, Sendable {
    public var present: Bool
    public var status: String?
    public var current: Bool
    public var currentnessMode: String
    public var reviewOnlyPassNotCurrent: Bool
    public var reasons: [String]

    public enum CodingKeys: String, CodingKey {
        case present
        case status
        case current
        case currentnessMode = "currentness_mode"
        case reviewOnlyPassNotCurrent = "review_only_pass_not_current"
        case reasons
    }
}

public enum GovAssistCommand: String, Codable, CaseIterable, Sendable {
    case diagnose
    case scaffoldApproval = "scaffold-approval"
    case scaffoldFactoryAuth = "scaffold-factory-auth"
    case explainTransition = "explain-transition"
    case explainStale = "explain-stale"
    case checkHandoff = "check-handoff"
    case checkAuthorizedSurfaces = "check-authorized-surfaces"
}
