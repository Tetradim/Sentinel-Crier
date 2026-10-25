import Foundation
import SwiftUI

struct PracticeGuide: Decodable {
    struct Step: Decodable { let title: String; let body: String }
    struct Journey: Decodable, Identifiable { let id: String; let title: String; let steps: [Step] }
    let version: Int; let notice: String; let privacy: String; let journeys: [Journey]
    enum Invalid: Error { case content }
    static let supportURL = URL(string: "https://github.com/Tetradim/Sentinel-Crier/issues")!
    static func load() throws -> Self {
        guard let url = Bundle.main.url(forResource: "customer-practice", withExtension: "json") else { throw Invalid.content }
        return try parse(Data(contentsOf: url))
    }
    static func parse(_ data: Data) throws -> Self {
        func keys(_ object: [String: Any], _ expected: Set<String>) throws {
            guard Set(object.keys) == expected else { throw Invalid.content }
        }
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let journeys = object["journeys"] as? [[String: Any]], journeys.count == 3 else { throw Invalid.content }
        try keys(object, ["version", "notice", "privacy", "journeys"])
        for journey in journeys {
            try keys(journey, ["id", "title", "steps"])
            guard let steps = journey["steps"] as? [[String: Any]], (3...8).contains(steps.count) else { throw Invalid.content }
            for step in steps { try keys(step, ["title", "body"]) }
        }
        let guide = try JSONDecoder().decode(Self.self, from: data)
        guard guide.version == 1, Set(guide.journeys.map(\.id)) == ["alerts", "trade", "follow"] else { throw Invalid.content }
        func text(_ value: String, _ limit: Int) throws {
            guard !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, value.count <= limit,
                  !value.unicodeScalars.contains(where: { $0.value < 32 }) else { throw Invalid.content }
        }
        try text(guide.notice, 1200); try text(guide.privacy, 1200)
        for journey in guide.journeys {
            try text(journey.title, 100)
            for step in journey.steps { try text(step.title, 100); try text(step.body, 1200) }
        }
        return guide
    }
}

struct PracticeGuideView: View {
    private let guide = try? PracticeGuide.load()
    var body: some View {
        Form {
            if let guide {
                Section("Optional practice") { Text(guide.notice) }
                Section("Choose your guide") {
                    ForEach(guide.journeys) { journey in
                        NavigationLink(journey.title) { PracticeJourneyView(guide: guide, journey: journey) }
                            .accessibilityIdentifier("practice-\(journey.id)")
                    }
                }
                Section("Support") {
                    Text(guide.privacy)
                    Link("Open support (GitHub Issues)", destination: PracticeGuide.supportURL)
                }
            } else {
                Text("Practice guide unavailable. Existing account controls remain available; see the project README.")
            }
        }.navigationTitle("Paper practice")
    }
}

private struct PracticeJourneyView: View {
    let guide: PracticeGuide; let journey: PracticeGuide.Journey
    var body: some View {
        Form {
            Section { Text(guide.notice) }
            ForEach(Array(journey.steps.enumerated()), id: \.offset) { index, step in
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("\(index + 1). \(step.title)").font(.headline).accessibilityAddTraits(.isHeader)
                        Text(step.body)
                    }.accessibilityElement(children: .combine)
                        .accessibilityIdentifier("practice-step-\(journey.id)-\(index)")
                }
            }
            Section("Support") {
                Text(guide.privacy)
                Link("Open support (GitHub Issues)", destination: PracticeGuide.supportURL)
            }
        }.navigationTitle(journey.title)
    }
}
