import Foundation

// MARK: - TR-11 ADTs

public enum ProgramPhase: String, Codable, Sendable, CaseIterable {
    case design = "DESIGN"
    case corporateAcceptance = "CORPORATE_ACCEPTANCE"
    case siteDelivery = "SITE_DELIVERY"
    case corporateReview = "CORPORATE_REVIEW"
    case awaitingUserApproval = "AWAITING_USER_APPROVAL"
    case approved = "APPROVED"
    case rework = "REWORK"
}

public enum ExecutionLayer: String, Codable, Sendable, CaseIterable {
    case light
    case heavy
}

public enum ProofKind: String, Codable, Sendable, CaseIterable {
    case assistEnvelope = "assist_envelope"
    case validationVerdict = "validation_verdict"
    case govSeal = "gov_seal"
    case trustEvent = "trust_event"
}

public enum HarnessAction: String, Codable, Sendable, CaseIterable {
    case recordArtifactGates = "record_artifact:gates"
    case recordArtifactKpis = "record_artifact:kpis"
    case recordArtifactCorporateHandoff = "record_artifact:corporate_handoff"
    case recordArtifactFactoryAuthorization = "record_artifact:factory_authorization"
    case recordArtifactUserApproval = "record_artifact:user_approval"
    case mintGovReceipt = "mint_gov_receipt"
    case heavyValidate = "heavy_validate"
    case recordArtifactOther = "record_artifact:other"
    case nextAdvance = "next_advance"
    case checkApply = "check_apply"
}

public enum TrustEventKind: String, Codable, Sendable, CaseIterable {
    case strictSuccess = "strict_success"
    case validationFailure = "validation_failure"
    case deceptiveTheater = "deceptive_theater"
}

public enum TheaterSignalId: String, Codable, Sendable, CaseIterable {
    case vacuousGatePass = "vacuous_gate_pass"
    case unboundKpi = "unbound_kpi"
    case sealBypassAttempt = "seal_bypass_attempt"
    case outOfBandMutation = "out_of_band_mutation"
    case unauthorizedActor = "unauthorized_actor"
    case staleFactoryAuthorization = "stale_factory_authorization"
    case wrongRootOperation = "wrong_root_operation"
}

public enum ValidationVerdict: String, Codable, Sendable, CaseIterable {
    case accept
    case reject
    case requiresHeavy = "requires_heavy"
    case govRequired = "GOV_REQUIRED"
    case govAssistUnavailable = "GOV_ASSIST_UNAVAILABLE"
}

/// Quantized trust score in [0.0, 1.0] with 2 decimal places (half-up).
public struct TrustScore: Codable, Sendable, Equatable, Hashable {
    public var value: Decimal

    public static let lightThreshold = Decimal(string: "0.70")!
    public static let justBelowLight = Decimal(string: "0.69")!

    public init(_ raw: Decimal) {
        self.value = TrustScore.quantize(raw)
    }

    public init(double: Double) {
        self.init(Decimal(double))
    }

    public var executionLayer: ExecutionLayer {
        value >= Self.lightThreshold ? .light : .heavy
    }

    public static func quantize(_ raw: Decimal) -> Decimal {
        let value = min(max(raw, 0), 1)
        var rounded = Decimal()
        var mutable = value
        NSDecimalRound(&rounded, &mutable, 2, .plain)
        return rounded
    }

    public func applying(_ kind: TrustEventKind) -> TrustScore {
        switch kind {
        case .strictSuccess:
            return TrustScore(value + Decimal(string: "0.05")!)
        case .validationFailure:
            return TrustScore(min(value, Self.justBelowLight))
        case .deceptiveTheater:
            return TrustScore(0)
        }
    }
}

public struct TrustEvent: Codable, Sendable, Equatable {
    public var schema: String
    public var eventId: String
    public var kind: TrustEventKind
    public var programDigest: String
    public var emitter: String
    public var theaterSignalId: TheaterSignalId?
    public var reasons: [String]
    public var scoreBefore: Decimal
    public var scoreAfter: Decimal

    public enum CodingKeys: String, CodingKey {
        case schema
        case eventId = "event_id"
        case kind
        case programDigest = "program_digest"
        case emitter
        case theaterSignalId = "theater_signal_id"
        case reasons
        case scoreBefore = "score_before"
        case scoreAfter = "score_after"
    }

    public static let schemaName = "corporate-site-trust-event/v1"
    public static let soleEmitter = "python_runtime_engine"

    public init(
        eventId: String,
        kind: TrustEventKind,
        programDigest: String,
        emitter: String = TrustEvent.soleEmitter,
        theaterSignalId: TheaterSignalId? = nil,
        reasons: [String] = [],
        scoreBefore: Decimal,
        scoreAfter: Decimal
    ) {
        self.schema = Self.schemaName
        self.eventId = eventId
        self.kind = kind
        self.programDigest = programDigest
        self.emitter = emitter
        self.theaterSignalId = theaterSignalId
        self.reasons = reasons
        self.scoreBefore = scoreBefore
        self.scoreAfter = scoreAfter
    }

    public static func validatePreconditions(
        kind: TrustEventKind,
        theaterSignalId: TheaterSignalId?,
        reasons: [String]
    ) -> String? {
        if kind == .deceptiveTheater {
            guard theaterSignalId != nil else {
                return "deceptive_theater requires theater_signal_id"
            }
            if reasons.isEmpty {
                return "deceptive_theater requires reasons"
            }
        }
        if kind == .validationFailure && reasons.isEmpty {
            return "validation_failure requires reasons"
        }
        return nil
    }
}

public struct ProofEnvelope: Codable, Sendable, Equatable {
    public var schema: String
    public var kind: ProofKind
    public var programDigest: String
    public var action: String
    public var layer: ExecutionLayer
    public var verdict: ValidationVerdict
    public var detail: String?

    public enum CodingKeys: String, CodingKey {
        case schema
        case kind
        case programDigest = "program_digest"
        case action
        case layer
        case verdict
        case detail
    }

    public static let schemaName = "corporate-site-proof-envelope/v1"

    public init(
        kind: ProofKind,
        programDigest: String,
        action: String,
        layer: ExecutionLayer,
        verdict: ValidationVerdict,
        detail: String? = nil
    ) {
        self.schema = Self.schemaName
        self.kind = kind
        self.programDigest = programDigest
        self.action = action
        self.layer = layer
        self.verdict = verdict
        self.detail = detail
    }
}

// MARK: - Protocols

public protocol Validatable {
    func validate() throws
}

public protocol Provable {
    func proofEnvelope(programDigest: String, layer: ExecutionLayer) -> ProofEnvelope
}

public protocol TrustAdjusting {
    func apply(to score: TrustScore) -> TrustScore
}

public protocol LayerRouting {
    func actionRoutedLayer(score: TrustScore, action: HarnessAction) -> ExecutionLayer
}

public protocol HeavyValidating {
    func validateAction(
        action: HarnessAction,
        programDigest: String,
        score: TrustScore
    ) -> ProofEnvelope
}

public struct TrustRouter: LayerRouting, Sendable {
    public static let alwaysForceHeavy: Set<HarnessAction> = [
        .recordArtifactGates,
        .recordArtifactKpis,
        .recordArtifactCorporateHandoff,
        .recordArtifactFactoryAuthorization,
        .recordArtifactUserApproval,
        .mintGovReceipt,
    ]

    public init() {}

    public func actionRoutedLayer(score: TrustScore, action: HarnessAction) -> ExecutionLayer {
        if score.executionLayer == .heavy { return .heavy }
        if Self.alwaysForceHeavy.contains(action) { return .heavy }
        if action == .heavyValidate { return .heavy }
        return .light
    }
}

extension TrustEvent: TrustAdjusting {
    public func apply(to score: TrustScore) -> TrustScore {
        score.applying(kind)
    }
}

extension TrustEvent: Validatable {
    public func validate() throws {
        if kind == .deceptiveTheater || kind == .validationFailure {
            if let err = TrustEvent.validatePreconditions(
                kind: kind,
                theaterSignalId: theaterSignalId,
                reasons: reasons
            ) {
                throw TrustRuntimeError.precondition(err)
            }
        }
        if emitter != TrustEvent.soleEmitter && emitter != "swift_propose_only" {
            throw TrustRuntimeError.precondition("unknown emitter")
        }
    }
}

public enum TrustRuntimeError: Error, CustomStringConvertible {
    case precondition(String)
    public var description: String {
        switch self {
        case .precondition(let message): return message
        }
    }
}
