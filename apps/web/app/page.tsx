import { getApiHealth } from "@/lib/api-health";

export const dynamic = "force-dynamic";

const plannedCapabilities = [
  {
    label: "KRIBU Guard",
    detail: "Identity, RBAC, ABAC, document permissions, approvals, and audit.",
  },
  {
    label: "KRIBU Brain",
    detail: "Provenance-aware ingestion, organizational memory, and authorized retrieval.",
  },
  {
    label: "KRIBU Engine",
    detail: "Durable LangGraph workflows for evidence-backed analysis and artifacts.",
  },
];

export default async function Home() {
  const apiHealth = await getApiHealth();

  return (
    <main>
      <section className="hero" aria-labelledby="page-title">
        <div className="shell hero__content">
          <p className="eyebrow">KRIBU Studio</p>
          <h1 id="page-title">Company intelligence you can verify.</h1>
          <p className="hero__summary">
            KRIBU connects organizational evidence, respects access boundaries,
            and explains every material finding with its source.
          </p>
          <div className="service-status" aria-live="polite">
            <span
              className={`status-dot status-dot--${apiHealth.status}`}
              aria-hidden="true"
            />
            <span>
              API: <strong>{apiHealth.label}</strong>
            </span>
          </div>
        </div>
      </section>

      <section className="shell section" aria-labelledby="foundation-title">
        <div className="section__heading">
          <p className="eyebrow eyebrow--dark">Iteration 1</p>
          <h2 id="foundation-title">Platform foundation</h2>
          <p>
            This scaffold proves the web, API, and database boundary before any
            agent or sensitive-data workflow is introduced.
          </p>
        </div>

        <div className="capability-grid">
          {plannedCapabilities.map((capability) => (
            <article className="capability-card" key={capability.label}>
              <div className="capability-card__mark" aria-hidden="true" />
              <h3>{capability.label}</h3>
              <p>{capability.detail}</p>
              <span>Planned</span>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

