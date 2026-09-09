import Link from "next/link";
export default function Page() {
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Configuration</p>
        <h1>Settings</h1>
        <p>
          Configure the resources and policies used by your agent loops.
          Published runs retain their original configuration.
        </p>
      </header>
      <section className="content-card">
        <h2>Runtime configuration</h2>
        <ul>
          <li>
            <Link href="/workers">Workers and execution capacity</Link>
          </li>
          <li>
            <Link href="/providers">Provider connections</Link>
          </li>
          <li>
            <Link href="/models">Model profiles</Link>
          </li>
          <li>
            <Link href="/routing">Model routes and spending policies</Link>
          </li>
          <li>
            <Link href="/policies">Permissions and retry policies</Link>
          </li>
          <li>
            <Link href="/workflows">Workflow versions</Link>
          </li>
        </ul>
        <p>
          Credentials and repository bindings are provisioned in the private
          server configuration. The browser only receives their public
          configuration references.
        </p>
      </section>
    </div>
  );
}
