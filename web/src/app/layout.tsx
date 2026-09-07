import type { Metadata } from "next";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { AppProviders } from "@/components/app-providers";

import "./globals.css";

export const metadata: Metadata = {
  title: "Jarvis Mission Control",
  description: "Durable control plane for Jarvis V1",
};

export default async function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  // Opt into per-request rendering so Next can apply the CSP nonce supplied by
  // `proxy.ts` to framework bootstrap scripts.
  await headers();
  return (
    <html lang="en">
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
