import type { ComponentPropsWithoutRef } from "react";
import Markdown from "react-markdown";

const permittedProtocols = new Set(["http:", "https:", "mailto:"]);

export function safeMarkdownUrl(value: string): string {
  const url = value.trim();
  if (url.startsWith("/") || url.startsWith("#")) return url;
  try {
    const parsed = new URL(url, "https://jarvis.invalid");
    return permittedProtocols.has(parsed.protocol) ? url : "";
  } catch {
    return "";
  }
}

function SafeLink({ href = "", ...props }: ComponentPropsWithoutRef<"a">) {
  const safeHref = safeMarkdownUrl(href);
  const external =
    safeHref.startsWith("http://") || safeHref.startsWith("https://");
  return (
    <a
      {...props}
      href={safeHref || undefined}
      rel={external ? "noopener noreferrer" : undefined}
      target={external ? "_blank" : undefined}
    />
  );
}

export function SafeMarkdown({ children }: { children: string }) {
  return (
    <div className="markdown-content">
      <Markdown
        components={{ a: SafeLink }}
        disallowedElements={["img"]}
        skipHtml
        urlTransform={safeMarkdownUrl}
      >
        {children}
      </Markdown>
    </div>
  );
}
