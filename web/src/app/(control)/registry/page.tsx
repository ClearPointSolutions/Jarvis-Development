import Link from "next/link";
export default function Page() {
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Control plane</p>
        <h1>Configuration registry</h1>
        <p>
          Persistent configuration, immutable revisions, and deterministic
          policies.
        </p>
      </header>
      <section className="registry-cards">
        {[
          [
            "workers",
            "Workers",
            "Capabilities, concurrency, and model binding",
          ],
          [
            "providers",
            "Providers",
            "Connections, secret status, and recorded health",
          ],
          ["models", "Models", "Capabilities, limits, and versioned pricing"],
          ["routing", "Routing", "Ordered candidates and resolution preview"],
          ["policies", "Policies", "Independent retry budgets and permissions"],
        ].map(([path, title, copy]) => (
          <Link
            className="content-card registry-link"
            href={`/${path}`}
            key={path}
          >
            <h2>{title}</h2>
            <p>{copy}</p>
            <span>Open registry</span>
          </Link>
        ))}
      </section>
    </div>
  );
}
