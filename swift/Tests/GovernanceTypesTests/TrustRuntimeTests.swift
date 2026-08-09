import XCTest
@testable import GovernanceTypes

final class TrustRuntimeTests: XCTestCase {
    func testD1ThresholdBoundary() {
        XCTAssertEqual(TrustScore(double: 0.70).executionLayer, .light)
        XCTAssertEqual(TrustScore(double: 0.69).executionLayer, .heavy)
    }

    func testD1SuccessDeltaClamp() {
        let high = TrustScore(double: 0.98).applying(.strictSuccess)
        XCTAssertEqual(high.value, Decimal(string: "1.00")!)
        let mid = TrustScore(double: 0.70).applying(.strictSuccess)
        XCTAssertEqual(mid.value, Decimal(string: "0.75")!)
    }

    func testD1FailureDropsBelowThreshold() {
        let dropped = TrustScore(double: 0.95).applying(.validationFailure)
        XCTAssertEqual(dropped.value, Decimal(string: "0.69")!)
        XCTAssertEqual(dropped.executionLayer, .heavy)
    }

    func testD1TheaterZero() {
        let zero = TrustScore(double: 0.80).applying(.deceptiveTheater)
        XCTAssertEqual(zero.value, 0)
        XCTAssertEqual(zero.executionLayer, .heavy)
    }

    func testD9ClosedKinds() {
        let kinds = Set(TrustEventKind.allCases.map(\.rawValue))
        XCTAssertEqual(kinds, ["strict_success", "validation_failure", "deceptive_theater"])
    }

    func testD9TheaterPreconditions() {
        XCTAssertNotNil(
            TrustEvent.validatePreconditions(
                kind: .deceptiveTheater,
                theaterSignalId: nil,
                reasons: ["x"]
            )
        )
        XCTAssertNil(
            TrustEvent.validatePreconditions(
                kind: .deceptiveTheater,
                theaterSignalId: .vacuousGatePass,
                reasons: ["vacuous"]
            )
        )
        XCTAssertEqual(
            TheaterSignalId.allCases.count,
            7,
            "TheaterSignalId must mirror full D5 set (TRR-01 / PLAT-TR-05)"
        )
        let expectedRaw = Set([
            "vacuous_gate_pass",
            "unbound_kpi",
            "seal_bypass_attempt",
            "out_of_band_mutation",
            "unauthorized_actor",
            "stale_factory_authorization",
            "wrong_root_operation",
        ])
        XCTAssertEqual(Set(TheaterSignalId.allCases.map(\.rawValue)), expectedRaw)
        for signal in TheaterSignalId.allCases {
            XCTAssertNil(
                TrustEvent.validatePreconditions(
                    kind: .deceptiveTheater,
                    theaterSignalId: signal,
                    reasons: ["reason"]
                )
            )
        }
    }

    func testD9AmnestyForbiddenAsKind() {
        let raw = Set(TrustEventKind.allCases.map(\.rawValue))
        XCTAssertFalse(raw.contains("digest_amnesty"))
        XCTAssertFalse(raw.contains("amnesty"))
    }

    func testD10AlwaysForceAtScoreOne() {
        let router = TrustRouter()
        let score = TrustScore(double: 1.0)
        XCTAssertEqual(score.executionLayer, .light)
        for action in TrustRouter.alwaysForceHeavy {
            XCTAssertEqual(router.actionRoutedLayer(score: score, action: action), .heavy)
        }
        XCTAssertEqual(router.actionRoutedLayer(score: score, action: .heavyValidate), .heavy)
        XCTAssertEqual(router.actionRoutedLayer(score: score, action: .recordArtifactOther), .light)
    }

    func testFourteenStrictSuccessRecoversLight() {
        var score = TrustScore(0)
        for _ in 0..<13 {
            score = score.applying(.strictSuccess)
        }
        XCTAssertEqual(score.value, Decimal(string: "0.65")!)
        XCTAssertEqual(score.executionLayer, .heavy)
        score = score.applying(.strictSuccess)
        XCTAssertEqual(score.value, Decimal(string: "0.70")!)
        XCTAssertEqual(score.executionLayer, .light)
    }

    func testQuantizeHalfUp() {
        XCTAssertEqual(TrustScore.quantize(Decimal(string: "0.705")!), Decimal(string: "0.71")!)
        XCTAssertEqual(TrustScore.quantize(Decimal(string: "0.704")!), Decimal(string: "0.70")!)
    }
}
