import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "sans_schema playground",
  description: "Query a database you've never seen, in your own words.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
